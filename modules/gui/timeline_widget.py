import json
import os
import ctypes
import wave
import numpy as np
from datetime import datetime
from typing import List, Dict, Any, Optional, Protocol, runtime_checkable

from PySide6.QtWidgets import QWidget, QApplication, QInputDialog, QLineEdit, QMainWindow
from PySide6.QtCore import Qt, QRect, QRectF, Signal, Slot, QPoint, QSize
from PySide6.QtGui import (QPainter, QPen, QBrush, QColor, QFont,
                            QLinearGradient, QPaintEvent, QMouseEvent)


# ============================================================
# 1. データモデル
# ============================================================

@runtime_checkable
class NoteEventProtocol(Protocol):
    start_time: float
    duration: float
    note_number: int
    lyrics: str
    is_selected: bool
    phoneme: str
    onset: float
    overlap: float
    pre_utterance: float
    has_analysis: bool
    def to_dict(self) -> Dict[str, Any]: ...


class _FallbackNoteEvent:
    """modules.data.data_models が存在しない場合のフォールバック実装"""
    def __init__(self, start_time: float, duration: float,
                 note_number: int, lyrics: str = "la") -> None:
        self.start_time: float = start_time
        self.duration: float = duration
        self.note_number: int = note_number
        self.lyrics: str = lyrics
        self.is_selected: bool = False
        self.phoneme: str = ""
        self.onset: float = 0.0
        self.overlap: float = 0.0
        self.pre_utterance: float = 0.0
        self.has_analysis: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_time": self.start_time,
            "duration": self.duration,
            "note_number": self.note_number,
            "lyrics": self.lyrics,
            "phoneme": self.phoneme,
            "onset": self.onset,
            "overlap": self.overlap,
            "pre_utterance": self.pre_utterance,
        }


try:
    import modules.data.data_models as _data_models
    NoteEventClass: Any = getattr(_data_models, "NoteEvent", _FallbackNoteEvent)
except Exception:
    NoteEventClass = _FallbackNoteEvent


# ============================================================
# 2. Janome Tokenizer（安全なロード）
# ============================================================

class _FallbackTokenizer:
    def tokenize(self, text: str) -> List[Any]:
        return []


try:
    from janome.tokenizer import Tokenizer as _JanomeTokenizer
    _TOKENIZER_CLASS: Any = _JanomeTokenizer
except Exception:
    _TOKENIZER_CLASS = _FallbackTokenizer


# ============================================================
# 3. TimelineWidget
# ============================================================

class TimelineWidget(QWidget):
    """
    VO-SE Pro: メインタイムライン（ピアノロール）

    統合ポイント:
    - QRectF で get_note_rect を返し、アンチエイリアス品質を向上 (Doc8)
    - Protocol + FallbackClass でモジュール未存在時も安全動作 (Doc9)
    - ノートリサイズ操作を搭載 (Doc8)
    - パラメータ描画を _draw_curve に統一し全レイヤーを色分け表示 (Doc9)
    - audio_level によるグロー演出 (Doc9)
    - コピー / ペースト / 複製 / 全選択 / 削除 の完全なキーバインド (Doc9)
    - smooth_param によるパラメータ平滑化 (Doc9)
    - 歌詞ダブルクリック編集＋ノート分割 (Doc9)
    """

    notes_changed_signal = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # --- 表示パラメータ ---
        self.tempo: float = 120.0
        self.pixels_per_beat: float = 80.0
        self.key_height_pixels: float = 20.0
        self.quantize_resolution: float = 0.25   # 16分音符

        # --- スクロール ---
        self.scroll_x_offset: float = 0.0
        self.scroll_y_offset: float = 0.0
        self._current_playback_time: float = 0.0

        # --- データ ---
        self.notes_list: List[Any] = []
        self.parameters: Dict[str, Dict[float, float]] = {
            "Dynamics": {}, "Pitch": {}, "Vibrato": {}, "Formant": {}
        }
        self.current_param_layer: str = "Dynamics"
        self.audio_level: float = 0.0

        # --- 編集状態 ---
        self.edit_mode: Optional[str] = None
        self.drag_start_pos: Optional[QPoint] = None
        self.selection_rect: QRect = QRect()
        self._resizing_note: Optional[Any] = None

        # --- 音声波形キャッシュ ---
        self._wave_cache: List[float] = []
        self._wave_cache_path: str = ""

        # --- Tokenizer ---
        try:
            self.tokenizer: Any = _TOKENIZER_CLASS()
        except Exception:
            self.tokenizer = _FallbackTokenizer()

        # --- 音声エンジン ---
        self.vose_core: Any = None
        self.init_voice_engine()

        # --- ウィジェット設定 ---
        self.setMinimumSize(400, 200)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    # ============================================================
    # 座標変換
    # ============================================================

    def seconds_to_beats(self, s: float) -> float:
        return s / (60.0 / self.tempo)

    def beats_to_seconds(self, b: float) -> float:
        return b * (60.0 / self.tempo)

    def quantize(self, val: float) -> float:
        return round(val / self.quantize_resolution) * self.quantize_resolution

    def get_note_rect(self, note: Any) -> QRectF:
        """QRectF を返してアンチエイリアス品質を確保"""
        x = self.seconds_to_beats(note.start_time) * self.pixels_per_beat - self.scroll_x_offset
        y = (127 - note.note_number) * self.key_height_pixels - self.scroll_y_offset
        w = self.seconds_to_beats(note.duration) * self.pixels_per_beat
        h = self.key_height_pixels
        return QRectF(x, y, w, h)

    # ============================================================
    # 歌詞 → 音素解析
    # ============================================================

    def analyze_lyric_to_phoneme(self, text: str) -> str:
        try:
            tokens = self.tokenizer.tokenize(text)
            phonemes = []
            for t in tokens:
                reading = str(getattr(t, 'reading', '*'))
                surface = str(getattr(t, 'surface', ''))
                phonemes.append(reading if reading != "*" else surface)
            return "".join(phonemes) if phonemes else text
        except Exception:
            return text

    # ============================================================
    # 音声エンジン
    # ============================================================

    def init_voice_engine(self) -> None:
        voice_db_path = "assets/voice_db/"
        if not os.path.exists(voice_db_path):
            return
        for file in os.listdir(voice_db_path):
            if file.endswith(".wav"):
                phoneme = file.replace(".wav", "")
                try:
                    with wave.open(os.path.join(voice_db_path, file), 'rb') as wr:
                        frames = wr.readframes(wr.getnframes())
                        data = np.frombuffer(frames, dtype=np.int16)
                        if self.vose_core:
                            self.vose_core.load_embedded_resource(
                                phoneme.encode('utf-8'),
                                data.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
                                len(data)
                            )
                except Exception as e:
                    print(f"Voice load error: {e}")

    # ============================================================
    # データ入出力
    # ============================================================

    def export_all_data(self, file_path: str = "engine_input.json") -> None:
        top = self.window()
        char_name = getattr(top, 'current_voice', "Default_Standard")
        char_id = getattr(top, 'current_voice_id', "__INTERNAL__:standard")
        active_device = getattr(top, 'active_device', "CPU")

        data = {
            "metadata": {
                "tempo": self.tempo,
                "version": "1.4.0",
                "project": "VO-SE_Project",
                "character_name": char_name,
                "character_id": char_id,
                "render_device": active_device,
                "timestamp": datetime.now().isoformat(),
            },
            "notes": [
                {
                    "t": n.start_time,
                    "d": n.duration,
                    "n": n.note_number,
                    "p": self.analyze_lyric_to_phoneme(n.lyrics),
                    "lyric": n.lyrics,
                    "onset": float(getattr(n, 'onset', 0.0)),
                    "overlap": float(getattr(n, 'overlap', 0.0)),
                    "pre_utterance": float(getattr(n, 'pre_utterance', 0.0)),
                    "optimized": bool(getattr(n, 'has_analysis', False)),
                }
                for n in self.notes_list
            ],
            "parameters": {
                "pitch": self.parameters.get("Pitch", {}),
                "gender": self.parameters.get("Gender", {}),
                "tension": self.parameters.get("Tension", {}),
                "breath": self.parameters.get("Breath", {}),
            },
        }

        try:
            abs_path = os.path.abspath(file_path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"✅ Exported (Voice: {char_name}) → {abs_path}")
            if isinstance(top, QMainWindow):
                sb = top.statusBar()
                if sb:
                    sb.showMessage(f"Export Complete: {char_name}", 5000)
        except Exception as e:
            print(f"❌ Export failed: {e}")

    def get_all_notes_data(self) -> list:
        return self.notes_list

    def add_note_from_midi(self, pitch: int, start: int, duration: int) -> None:
        pass

    # ============================================================
    # 音声波形
    # ============================================================

    def get_audio_peaks(self, file_path: str, num_peaks: int = 2000) -> List[float]:
        if not file_path or not os.path.exists(file_path):
            return []
        try:
            with wave.open(file_path, 'rb') as w:
                params = w.getparams()
                if params.nframes == 0:
                    return []
                samples = np.frombuffer(w.readframes(params.nframes), dtype=np.int16)
                if params.nchannels == 2:
                    samples = samples[::2]
                num_peaks = min(num_peaks, max(1, len(samples)))
                chunks = np.array_split(samples, num_peaks)
                peaks = [float(np.max(np.abs(c))) if len(c) > 0 else 0.0 for c in chunks]
                max_val = float(np.max(peaks)) if peaks else 1.0
                return [p / max_val for p in peaks] if max_val > 0 else peaks
        except Exception as e:
            print(f"Waveform Analysis Error: {e}")
            return []

    def _draw_audio_waveform(self, p: QPainter) -> None:
        audio_path = str(getattr(self.window(), 'current_audio_path', ''))
        if not audio_path or not os.path.exists(audio_path):
            return
        if self._wave_cache_path != audio_path:
            self._wave_cache = self.get_audio_peaks(audio_path)
            self._wave_cache_path = audio_path
        if not self._wave_cache:
            return

        p.setPen(QPen(QColor(0, 255, 255, 50), 1))
        mid_y = self.height() / 2.0
        max_h = self.height() * 0.7
        px_per_sec = (self.tempo / 60.0) * self.pixels_per_beat
        interval_px = px_per_sec * 0.05

        for i, peak in enumerate(self._wave_cache):
            x = i * interval_px - self.scroll_x_offset
            if x < -interval_px:
                continue
            if x > self.width():
                break
            h = peak * max_h
            p.drawLine(int(x), int(mid_y - h / 2), int(x), int(mid_y + h / 2))

    # ============================================================
    # 描画
    # ============================================================

    _PARAM_COLORS: Dict[str, QColor] = {
        "Dynamics": QColor(255, 45, 85),
        "Pitch":    QColor(0, 255, 255),
        "Vibrato":  QColor(255, 165, 0),
        "Formant":  QColor(200, 100, 255),
    }

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(18, 18, 18))

        # 1. グリッド（小節線・拍線）
        for i in range(500):
            x = i * self.pixels_per_beat - self.scroll_x_offset
            if x < 0:
                continue
            if x > self.width():
                break
            color = QColor(58, 58, 60) if i % 4 == 0 else QColor(36, 36, 36)
            p.setPen(QPen(color, 1))
            p.drawLine(int(x), 0, int(x), self.height())

        # 2. オーディオ波形
        self._draw_audio_waveform(p)

        # 3. audio_level によるグロー演出
        if self.audio_level > 0.001:
            cx = int(self.seconds_to_beats(self._current_playback_time)
                     * self.pixels_per_beat - self.scroll_x_offset)
            gw = int(self.audio_level * 100)
            grad = QLinearGradient(float(cx - gw), 0.0, float(cx + gw), 0.0)
            grad.setColorAt(0, QColor(255, 45, 85, 0))
            grad.setColorAt(0.5, QColor(255, 45, 85, int(self.audio_level * 120)))
            grad.setColorAt(1, QColor(255, 45, 85, 0))
            p.fillRect(self.rect(), QBrush(grad))

        # 4. パラメータ曲線（非アクティブ層は薄く、アクティブ層は強調）
        for name, data in self.parameters.items():
            if name != self.current_param_layer:
                self._draw_curve(p, data, self._PARAM_COLORS.get(name, QColor(200, 200, 200)), 40, 1)
        self._draw_curve(p,
                         self.parameters.get(self.current_param_layer, {}),
                         self._PARAM_COLORS.get(self.current_param_layer, QColor(255, 255, 255)),
                         220, 2)

        # 5. ノート
        for n in self.notes_list:
            rect = self.get_note_rect(n)
            if rect.right() < 0 or rect.left() > self.width():
                continue
            is_selected = bool(getattr(n, 'is_selected', False))
            color = QColor(255, 159, 10) if is_selected else QColor(10, 132, 255)
            p.setBrush(QBrush(color))
            p.setPen(QPen(color.lighter(120), 1))
            p.drawRoundedRect(rect, 3, 3)

            if rect.width() > 20:
                p.setPen(Qt.GlobalColor.white)
                p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                p.drawText(rect.adjusted(5, 0, 0, 0),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           n.lyrics)
                p.setPen(QColor(255, 255, 255, 150))
                p.setFont(QFont("Consolas", 7))
                p.drawText(rect.adjusted(5, 22, 0, 0),
                           Qt.AlignmentFlag.AlignLeft,
                           n.phoneme or self.analyze_lyric_to_phoneme(n.lyrics))

        # 6. 選択枠
        if self.edit_mode == "select_box":
            p.setPen(QPen(Qt.GlobalColor.white, 1, Qt.PenStyle.DashLine))
            p.setBrush(QBrush(QColor(255, 255, 255, 30)))
            p.drawRect(self.selection_rect)

        # 7. 再生カーソル
        cx = int(self.seconds_to_beats(self._current_playback_time)
                 * self.pixels_per_beat - self.scroll_x_offset)
        p.setPen(QPen(QColor(255, 45, 85), 2))
        p.drawLine(cx, 0, cx, self.height())

        p.end()

    def _draw_curve(self, p: QPainter, data: Dict[float, float],
                    color: QColor, alpha: int, width: int) -> None:
        if not data:
            return
        c = QColor(color)
        c.setAlpha(alpha)
        p.setPen(QPen(c, width))
        prev: Optional[QPoint] = None
        for t in sorted(data):
            x = int(self.seconds_to_beats(t) * self.pixels_per_beat - self.scroll_x_offset)
            y = int(self.height() - data[t] * self.height() * 0.3 - 10)
            curr = QPoint(x, y)
            if prev:
                p.drawLine(prev, curr)
            prev = curr

    # ============================================================
    # マウスイベント
    # ============================================================

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event is None:
            return
        pos = event.position()
        self.drag_start_pos = QPoint(int(pos.x()), int(pos.y()))

        # Alt + クリック → パラメータ描画
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self.edit_mode = "draw_parameter"
            self._add_param_pt(pos)
            return

        # ノートのリサイズ判定（右端10px）
        for n in reversed(self.notes_list):
            r = self.get_note_rect(n)
            resize_zone = QRectF(r.right() - 10, r.top(), 10, r.height())
            if resize_zone.contains(pos):
                self.edit_mode = "resize"
                self._resizing_note = n
                return
            if r.contains(pos):
                if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    self.deselect_all()
                n.is_selected = True
                self.edit_mode = "move"
                self.update()
                return

        # 範囲選択
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.deselect_all()
        self.edit_mode = "select_box"
        self.selection_rect = QRect(self.drag_start_pos, QSize(0, 0))
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event is None or self.drag_start_pos is None:
            return
        pos = event.position()

        if self.edit_mode == "draw_parameter":
            self._add_param_pt(pos)

        elif self.edit_mode == "move":
            dx_beats = (pos.x() - self.drag_start_pos.x()) / self.pixels_per_beat
            dy_notes = -int(round((pos.y() - self.drag_start_pos.y()) / self.key_height_pixels))
            dt = self.beats_to_seconds(dx_beats)
            if abs(dt) > 0.001 or dy_notes != 0:
                for n in self.notes_list:
                    if getattr(n, 'is_selected', False):
                        n.start_time = max(0.0, n.start_time + dt)
                        n.note_number = max(0, min(127, n.note_number + dy_notes))
                self.drag_start_pos = QPoint(int(pos.x()), int(pos.y()))

        elif self.edit_mode == "resize" and self._resizing_note is not None:
            note_start_px = (self.seconds_to_beats(self._resizing_note.start_time)
                             * self.pixels_per_beat)
            new_w_beats = (pos.x() + self.scroll_x_offset - note_start_px) / self.pixels_per_beat
            self._resizing_note.duration = self.beats_to_seconds(max(self.quantize_resolution, new_w_beats))

        elif self.edit_mode == "select_box":
            self.selection_rect = QRect(
                self.drag_start_pos, QPoint(int(pos.x()), int(pos.y()))
            ).normalized()
            for n in self.notes_list:
                n.is_selected = self.selection_rect.intersects(self.get_note_rect(n).toRect())

        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self.edit_mode == "draw_parameter":
            self._smooth_param()
        elif self.edit_mode in ("move", "resize"):
            # クオンタイズを適用して整列
            for n in self.notes_list:
                if getattr(n, 'is_selected', False) or n == self._resizing_note:
                    n.start_time = self.beats_to_seconds(
                        self.quantize(self.seconds_to_beats(n.start_time)))
                    n.duration = self.beats_to_seconds(
                        max(self.quantize_resolution,
                            self.quantize(self.seconds_to_beats(n.duration))))
            self.notes_changed_signal.emit()

        self.edit_mode = None
        self._resizing_note = None
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event is None:
            return
        pos_pt = QPoint(int(event.position().x()), int(event.position().y()))
        for n in self.notes_list:
            if self.get_note_rect(n).toRect().contains(pos_pt):
                text, ok = QInputDialog.getText(
                    self, "歌詞", "入力:", QLineEdit.EchoMode.Normal, n.lyrics)
                if ok:
                    n.lyrics = text
                    n.phoneme = self.analyze_lyric_to_phoneme(text)
                    chars = [str(getattr(t, 'surface', ''))
                             for t in self.tokenizer.tokenize(text)]
                    if len(chars) > 1:
                        self._split_note(n, chars)
                    self.notes_changed_signal.emit()
                    self.update()
                return

    # ============================================================
    # キーボード操作
    # ============================================================

    def keyPressEvent(self, event: Any) -> None:
        if event is None:
            return
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        key = event.key()
        layer_map = {
            Qt.Key.Key_1: "Dynamics",
            Qt.Key.Key_2: "Pitch",
            Qt.Key.Key_3: "Vibrato",
            Qt.Key.Key_4: "Formant",
        }
        if key in layer_map:
            self.change_layer(layer_map[key])
        elif ctrl and key == Qt.Key.Key_S:
            self.export_all_data()
        elif ctrl and key == Qt.Key.Key_C:
            self._copy_notes()
        elif ctrl and key == Qt.Key.Key_V:
            self._paste_notes()
        elif ctrl and key == Qt.Key.Key_D:
            self._duplicate_notes()
        elif ctrl and key == Qt.Key.Key_A:
            self.select_all()
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()

    # ============================================================
    # 編集操作
    # ============================================================

    def change_layer(self, name: str) -> None:
        self.current_param_layer = name
        self.update()

    def _add_param_pt(self, pos: Any) -> None:
        t = self.beats_to_seconds(
            (pos.x() + self.scroll_x_offset) / self.pixels_per_beat)
        val = max(0.0, min(1.0, (self.height() - 10 - pos.y()) / (self.height() * 0.3)))
        self.parameters[self.current_param_layer][t] = float(val)
        self.update()

    def _smooth_param(self) -> None:
        data = self.parameters[self.current_param_layer]
        if len(data) < 5:
            return
        keys = sorted(data)
        smoothed = {}
        for i, t in enumerate(keys):
            subset = [data[keys[j]] for j in range(max(0, i - 2), min(len(keys), i + 3))]
            smoothed[t] = sum(subset) / len(subset)
        self.parameters[self.current_param_layer] = smoothed
        self.notes_changed_signal.emit()

    def _split_note(self, n: Any, chars: List[str]) -> None:
        dur = n.duration / len(chars)
        if n in self.notes_list:
            self.notes_list.remove(n)
        for i, c in enumerate(chars):
            self.notes_list.append(
                NoteEventClass(n.start_time + i * dur, dur, n.note_number, c))

    def _copy_notes(self) -> None:
        sel = [n for n in self.notes_list if getattr(n, 'is_selected', False)]
        if not sel:
            return
        base = min(n.start_time for n in sel)
        payload = [{"l": n.lyrics, "n": n.note_number,
                    "o": n.start_time - base, "d": n.duration} for n in sel]
        QApplication.clipboard().setText(json.dumps(payload))

    def _paste_notes(self) -> None:
        try:
            data = json.loads(QApplication.clipboard().text())
            self.deselect_all()
            for d in data:
                nn = NoteEventClass(
                    self._current_playback_time + d["o"], d["d"], d["n"], d["l"])
                nn.is_selected = True
                self.notes_list.append(nn)
            self.notes_changed_signal.emit()
            self.update()
        except Exception:
            pass

    def _duplicate_notes(self) -> None:
        sel = [n for n in self.notes_list if getattr(n, 'is_selected', False)]
        if not sel:
            return
        offset = (max(n.start_time + n.duration for n in sel)
                  - min(n.start_time for n in sel))
        self.deselect_all()
        for n in sel:
            clone = NoteEventClass(n.start_time + offset, n.duration,
                                   n.note_number, n.lyrics)
            clone.is_selected = True
            self.notes_list.append(clone)
        self.notes_changed_signal.emit()
        self.update()

    def select_all(self) -> None:
        for n in self.notes_list:
            n.is_selected = True
        self.update()

    def deselect_all(self) -> None:
        for n in self.notes_list:
            n.is_selected = False
        self.update()

    def delete_selected(self) -> None:
        self.notes_list = [n for n in self.notes_list
                           if not getattr(n, 'is_selected', False)]
        self.notes_changed_signal.emit()
        self.update()

    # ============================================================
    # 外部スロット
    # ============================================================

    @Slot(float)
    def update_audio_level(self, level: float) -> None:
        self.audio_level = level
        self.update()

    @Slot(int)
    def set_vertical_offset(self, val: int) -> None:
        self.scroll_y_offset = float(val)
        self.update()

    @Slot(int)
    def set_horizontal_offset(self, val: int) -> None:
        self.scroll_x_offset = float(val)
        self.update()
