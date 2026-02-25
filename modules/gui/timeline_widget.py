import json
import os
import ctypes
import wave
import numpy as np
from datetime import datetime
from typing import List, Dict, Any, Optional, Protocol, runtime_checkable

from PySide6.QtWidgets import (QWidget, QApplication, QInputDialog, QLineEdit, 
                               QMainWindow, QMenu)
from PySide6.QtCore import Qt, QRect, QRectF, Signal, Slot, QPoint, QPointF, QSize
from PySide6.QtGui import (QPainter, QPen, QBrush, QColor, QFont, QAction, QContextMenuEvent,
                            QLinearGradient, QPaintEvent, QMouseEvent, QKeyEvent, QWheelEvent)


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
    ズーム機能 & コンテキストメニュー搭載版
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

    def add_note_from_midi(self, pitch: int, start_beat: float, duration_beat: float) -> None:
        start_time = self.beats_to_seconds(start_beat)
        duration = self.beats_to_seconds(duration_beat)
        new_note = NoteEventClass(start_time, duration, pitch, "la")
        new_note.phoneme = "la"
        self.notes_list.append(new_note)
        self.notes_changed_signal.emit()
        self.update()

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
        top = self.window()
        audio_path = str(getattr(top, 'current_audio_path', ''))
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

        # 1. グリッド
        for i in range(2000):
            x = i * self.pixels_per_beat - self.scroll_x_offset
            if x < -self.pixels_per_beat: continue
            if x > self.width(): break
            color = QColor(58, 58, 60) if i % 4 == 0 else QColor(36, 36, 36)
            p.setPen(QPen(color, 1))
            p.drawLine(int(x), 0, int(x), self.height())

        # 2. オーディオ波形
        self._draw_audio_waveform(p)

        # 3. audio_level グロー
        if self.audio_level > 0.001:
            cx = int(self.seconds_to_beats(self._current_playback_time)
                     * self.pixels_per_beat - self.scroll_x_offset)
            gw = int(self.audio_level * 150)
            grad = QLinearGradient(float(cx - gw), 0.0, float(cx + gw), 0.0)
            grad.setColorAt(0, QColor(255, 45, 85, 0))
            grad.setColorAt(0.5, QColor(255, 45, 85, int(self.audio_level * 150)))
            grad.setColorAt(1, QColor(255, 45, 85, 0))
            p.fillRect(self.rect(), QBrush(grad))

        # 4. パラメータ
        for name, data in self.parameters.items():
            if name != self.current_param_layer:
                self._draw_curve(p, data, self._PARAM_COLORS.get(name, QColor(200, 200, 200)), 60, 1)
        
        active_color = self._PARAM_COLORS.get(self.current_param_layer, QColor(255, 255, 255))
        self._draw_curve(p, self.parameters.get(self.current_param_layer, {}), active_color, 255, 2)

        # 5. ノート
        for n in self.notes_list:
            rect = self.get_note_rect(n)
            if rect.right() < 0 or rect.left() > self.width(): continue
            
            is_selected = bool(getattr(n, 'is_selected', False))
            base_color = QColor(255, 159, 10) if is_selected else QColor(10, 132, 255)
            
            p.setBrush(QBrush(base_color))
            p.setPen(QPen(base_color.lighter(130), 1))
            p.drawRoundedRect(rect, 4, 4)

            if rect.width() > 15:
                p.setPen(Qt.GlobalColor.white)
                p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                p.drawText(rect.adjusted(5, 0, -2, 0),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           n.lyrics)
                
                p.setPen(QColor(255, 255, 255, 180))
                p.setFont(QFont("Consolas", 7))
                phoneme_text = n.phoneme or self.analyze_lyric_to_phoneme(n.lyrics)
                p.drawText(rect.adjusted(5, self.key_height_pixels * 0.6, 0, 0),
                           Qt.AlignmentFlag.AlignLeft, phoneme_text)

        # 6. 選択枠
        if self.edit_mode == "select_box":
            p.setPen(QPen(Qt.GlobalColor.white, 1, Qt.PenStyle.DashLine))
            p.setBrush(QBrush(QColor(255, 255, 255, 40)))
            p.drawRect(self.selection_rect)

        # 7. 再生カーソル
        cx = int(self.seconds_to_beats(self._current_playback_time)
                 * self.pixels_per_beat - self.scroll_x_offset)
        p.setPen(QPen(QColor(255, 45, 85), 2))
        p.drawLine(cx, 0, cx, self.height())

        p.end()

    def _draw_curve(self, p: QPainter, data: Dict[float, float],
                    color: QColor, alpha: int, width: int) -> None:
        if not data: return
        c = QColor(color)
        c.setAlpha(alpha)
        p.setPen(QPen(c, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        
        prev: Optional[QPoint] = None
        for t in sorted(data):
            x = int(self.seconds_to_beats(t) * self.pixels_per_beat - self.scroll_x_offset)
            y = int(self.height() - (data[t] * self.height() * 0.4) - 20)
            curr = QPoint(x, y)
            if prev:
                if abs(curr.x() - prev.x()) < 500:
                    p.drawLine(prev, curr)
            prev = curr

    # ============================================================
    # マウス・ホイールイベント
    # ============================================================

    def wheelEvent(self, event: QWheelEvent) -> None:
        """ズーム（Ctrl + ホイール）とスクロール"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # ズームロジック
            delta = event.angleDelta().y()
            zoom_factor = 1.1 if delta > 0 else 0.9
            
            # マウス位置のビート数を保持（ここを中心にズームする）
            mouse_x = event.position().x()
            beat_at_mouse = (mouse_x + self.scroll_x_offset) / self.pixels_per_beat
            
            # ズーム実行
            new_pixels_per_beat = self.pixels_per_beat * zoom_factor
            self.pixels_per_beat = max(10.0, min(1000.0, new_pixels_per_beat))
            
            # オフセット再計算
            self.scroll_x_offset = (beat_at_mouse * self.pixels_per_beat) - mouse_x
            self.update()
        else:
            # 通常のスクロール（横）
            delta = event.angleDelta().y()
            self.scroll_x_offset = max(0.0, self.scroll_x_offset - delta)
            self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event is None: return
        pos_f = event.position()
        self.drag_start_pos = QPoint(int(pos_f.x()), int(pos_f.y()))

        if event.button() == Qt.MouseButton.RightButton:
            return # コンテキストメニューは contextMenuEvent で処理

        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self.edit_mode = "draw_parameter"
            self._add_param_pt(pos_f)
            return

        for n in reversed(self.notes_list):
            r = self.get_note_rect(n)
            if QRectF(r.right() - 12, r.top(), 12, r.height()).contains(pos_f):
                self.edit_mode = "resize"
                self._resizing_note = n
                self.deselect_all()
                n.is_selected = True
                return
            if r.contains(pos_f):
                if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    if not n.is_selected: self.deselect_all()
                n.is_selected = True
                self.edit_mode = "move"
                self.update()
                return

        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.deselect_all()
        self.edit_mode = "select_box"
        self.selection_rect = QRect(self.drag_start_pos, QSize(0, 0))
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event is None or self.drag_start_pos is None: return
        pos_f = event.position()
        curr_pos = QPoint(int(pos_f.x()), int(pos_f.y()))

        if self.edit_mode == "draw_parameter":
            self._add_param_pt(pos_f)
        elif self.edit_mode == "move":
            dx_beats = (curr_pos.x() - self.drag_start_pos.x()) / self.pixels_per_beat
            dy_notes = -int(round((curr_pos.y() - self.drag_start_pos.y()) / self.key_height_pixels))
            dt = self.beats_to_seconds(dx_beats)
            if abs(dt) > 0.0001 or dy_notes != 0:
                for n in self.notes_list:
                    if getattr(n, 'is_selected', False):
                        n.start_time = max(0.0, n.start_time + dt)
                        n.note_number = max(0, min(127, n.note_number + dy_notes))
                self.drag_start_pos = curr_pos
        elif self.edit_mode == "resize" and self._resizing_note is not None:
            note_start_px = (self.seconds_to_beats(self._resizing_note.start_time) * self.pixels_per_beat)
            new_w_beats = (curr_pos.x() + self.scroll_x_offset - note_start_px) / self.pixels_per_beat
            self._resizing_note.duration = self.beats_to_seconds(max(self.quantize_resolution, new_w_beats))
        elif self.edit_mode == "select_box":
            self.selection_rect = QRect(self.drag_start_pos, curr_pos).normalized()
            for n in self.notes_list:
                n.is_selected = self.selection_rect.intersects(self.get_note_rect(n).toRect())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self.edit_mode == "draw_parameter":
            self._smooth_param()
        elif self.edit_mode in ("move", "resize"):
            for n in self.notes_list:
                if getattr(n, 'is_selected', False) or n == self._resizing_note:
                    n.start_time = self.beats_to_seconds(self.quantize(self.seconds_to_beats(n.start_time)))
                    n.duration = self.beats_to_seconds(max(self.quantize_resolution, self.quantize(self.seconds_to_beats(n.duration))))
            self.notes_changed_signal.emit()
        self.edit_mode = None
        self._resizing_note = None
        self.drag_start_pos = None
        self.update()

    def contextMenuEvent(self, event: Any) -> None:
        """右クリックメニューの実装"""
        menu = QMenu(self)
        
        # 選択されたノートがあるかチェック
        selected_notes = [n for n in self.notes_list if n.is_selected]
        
        if selected_notes:
            act_clear_param = QAction(f"選択したノートの {self.current_param_layer} をリセット", self)
            act_clear_param.triggered.connect(self._clear_selected_params)
            menu.addAction(act_clear_param)
            
            act_reset_lyrics = QAction("歌詞を 'la' にリセット", self)
            act_reset_lyrics.triggered.connect(self._reset_selected_lyrics)
            menu.addAction(act_reset_lyrics)
            
            menu.addSeparator()
            
        act_export = QAction("JSONエクスポート (Ctrl+S)", self)
        act_export.triggered.connect(self.export_all_data)
        menu.addAction(act_export)
        
        menu.exec(event.globalPos())

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event is None: return
        pos_f = event.position()
        for n in self.notes_list:
            if self.get_note_rect(n).contains(pos_f):
                text, ok = QInputDialog.getText(self, "歌詞入力", "ノートの歌詞:", QLineEdit.EchoMode.Normal, n.lyrics)
                if ok and text:
                    n.lyrics = text
                    n.phoneme = self.analyze_lyric_to_phoneme(text)
                    tokens = self.tokenizer.tokenize(text)
                    chars = [str(getattr(t, 'surface', '')) for t in tokens]
                    if len(chars) > 1: self._split_note(n, chars)
                    self.notes_changed_signal.emit()
                    self.update()
                return

    # ============================================================
    # 編集ロジック
    # ============================================================

    def _clear_selected_params(self) -> None:
        """選択中のノートの範囲にあるパラメータを削除"""
        selected_notes = [n for n in self.notes_list if n.is_selected]
        if not selected_notes: return
        
        layer = self.current_param_layer
        for n in selected_notes:
            start, end = n.start_time, n.start_time + n.duration
            # 範囲内のキーを特定して削除
            keys_to_del = [t for t in self.parameters[layer] if start <= t <= end]
            for k in keys_to_del: del self.parameters[layer][k]
        self.update()

    def _reset_selected_lyrics(self) -> None:
        for n in self.notes_list:
            if n.is_selected:
                n.lyrics = "la"
                n.phoneme = "la"
        self.update()

    def change_layer(self, name: str) -> None:
        self.current_param_layer = name
        if isinstance(self.window(), QMainWindow):  # ← Doc10 にあった処理
            sb = self.window().statusBar()
            if sb:
                sb.showMessage(f"Active Layer: {name}", 2000)
        self.update()

    def _add_param_pt(self, pos: QPointF) -> None:
        t = self.beats_to_seconds((pos.x() + self.scroll_x_offset) / self.pixels_per_beat)
        val = max(0.0, min(1.0, (self.height() - 20 - pos.y()) / (self.height() * 0.4)))
        self.parameters[self.current_param_layer][float(t)] = float(val)
        self.update()

    def _smooth_param(self) -> None:
        layer = self.current_param_layer
        data = self.parameters[layer]
        if len(data) < 3: return
        keys = sorted(data.keys())
        smoothed = {}
        for i, t in enumerate(keys):
            window = [data[keys[j]] for j in range(max(0, i-1), min(len(keys), i+2))]
            smoothed[t] = sum(window) / len(window)
        self.parameters[layer] = smoothed
        self.notes_changed_signal.emit()

    def _split_note(self, n: Any, chars: List[str]) -> None:
        if n not in self.notes_list: return
        total_duration = n.duration
        single_dur = total_duration / len(chars)
        start_t = n.start_time
        pitch = n.note_number
        self.notes_list.remove(n)
        for i, char in enumerate(chars):
            new_n = NoteEventClass(start_t + (i * single_dur), single_dur, pitch, char)
            new_n.phoneme = self.analyze_lyric_to_phoneme(char)
            self.notes_list.append(new_n)

    def _copy_notes(self) -> None:
        sel = [n for n in self.notes_list if getattr(n, 'is_selected', False)]
        if not sel: return
        base_t = min(n.start_time for n in sel)
        payload = [{"l": n.lyrics, "n": n.note_number, "o": n.start_time - base_t, "d": n.duration} for n in sel]
        QApplication.clipboard().setText(json.dumps(payload))

    def _paste_notes(self) -> None:
        try:
            data = json.loads(QApplication.clipboard().text())
            self.deselect_all()
            for d in data:
                nn = NoteEventClass(self._current_playback_time + d["o"], d["d"], d["n"], d["l"])
                nn.is_selected = True
                nn.phoneme = self.analyze_lyric_to_phoneme(d["l"])
                self.notes_list.append(nn)
            self.notes_changed_signal.emit()
            self.update()
        except Exception: pass

    def _duplicate_notes(self) -> None:
        sel = [n for n in self.notes_list if getattr(n, 'is_selected', False)]
        if not sel: return
        offset = max(n.start_time + n.duration for n in sel) - min(n.start_time for n in sel)
        self.deselect_all()
        for n in sel:
            clone = NoteEventClass(n.start_time + offset, n.duration, n.note_number, n.lyrics)
            clone.is_selected = True
            clone.phoneme = n.phoneme
            self.notes_list.append(clone)
        self.notes_changed_signal.emit()
        self.update()

    def select_all(self) -> None:
        for n in self.notes_list: n.is_selected = True
        self.update()

    def deselect_all(self) -> None:
        for n in self.notes_list: n.is_selected = False
        self.update()

    def delete_selected(self) -> None:
        self.notes_list = [n for n in self.notes_list if not getattr(n, 'is_selected', False)]
        self.notes_changed_signal.emit()
        self.update()

    # ============================================================
    # キーボード操作
    # ============================================================

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event is None: return
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        key = event.key()
        layer_map = {Qt.Key.Key_1: "Dynamics", Qt.Key.Key_2: "Pitch", Qt.Key.Key_3: "Vibrato", Qt.Key.Key_4: "Formant"}
        if key in layer_map: self.change_layer(layer_map[key])
        elif ctrl:
            if key == Qt.Key.Key_S: self.export_all_data()
            elif key == Qt.Key.Key_C: self._copy_notes()
            elif key == Qt.Key.Key_V: self._paste_notes()
            elif key == Qt.Key.Key_D: self._duplicate_notes()
            elif key == Qt.Key.Key_A: self.select_all()
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace): self.delete_selected()
        self.update()

    # ============================================================
    # スロット
    # ============================================================

    @Slot(float)
    def update_audio_level(self, level: float) -> None:
        self.audio_level = level
        self.update()

    @Slot(float)
    def set_playback_time(self, t: float) -> None:
        self._current_playback_time = t
        self.update()

    @Slot(int)
    def set_vertical_offset(self, val: int) -> None:
        self.scroll_y_offset = float(val)
        self.update()

    @Slot(int)
    def set_horizontal_offset(self, val: int) -> None:
        self.scroll_x_offset = float(val)
        self.update()
