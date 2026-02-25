import json
import logging
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

logger = logging.getLogger(__name__)


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
    - AIゴーストレイヤー: onset/overlap をグラデーションで可視化 (Doc13)
    - 横線グリッド: 黒鍵行を暗い背景で強調し視認性向上 (Doc13)
    - scroll_synced_signal: 縦スクロール位置を外部に発信 (Doc13)
    - 縦スクロール: wheelEvent の通常スクロールを縦方向に修正 (Doc13)
    - 描画を専用メソッドに分割し保守性を向上 (Doc13)
    - 音声エンジン / 波形描画 / エクスポート (Doc12)
    - コピー / ペースト / 複製 / 削除 / 右クリックメニュー (Doc12)
    - パラメータ全レイヤー同時描画 (Doc12)
    """

    notes_changed_signal = Signal()
    scroll_synced_signal = Signal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.tempo: float = 120.0
        self.pixels_per_beat: float = 80.0
        self.key_height_pixels: float = 20.0
        self.quantize_resolution: float = 0.25

        self.scroll_x_offset: float = 0.0
        self.scroll_y_offset: float = 0.0
        self._current_playback_time: float = 0.0

        self.notes_list: List[Any] = []
        self.parameters: Dict[str, Dict[float, float]] = {
            "Dynamics": {}, "Pitch": {}, "Vibrato": {}, "Formant": {}
        }
        self.current_param_layer: str = "Dynamics"
        self.audio_level: float = 0.0

        self.edit_mode: Optional[str] = None
        self.drag_start_pos: Optional[QPoint] = None
        self.selection_rect: QRect = QRect()
        self._resizing_note: Optional[Any] = None

        self._wave_cache: List[float] = []
        self._wave_cache_path: str = ""

        # AIゴーストレイヤー設定
        self.show_ai_phonemes: bool = True
        self.ai_ghost_alpha: int = 100

        try:
            self.tokenizer: Any = _TOKENIZER_CLASS()
        except Exception:
            self.tokenizer = _FallbackTokenizer()

        self.vose_core: Any = None
        self.init_voice_engine()

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
                    logger.error(f"Voice load error: {e}")

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
                    "t": n.start_time, "d": n.duration, "n": n.note_number,
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
            logger.info(f"Exported (Voice: {char_name}) -> {abs_path}")
            if isinstance(top, QMainWindow):
                sb = top.statusBar()
                if sb:
                    sb.showMessage(f"Export Complete: {char_name}", 5000)
        except Exception as e:
            logger.error(f"Export failed: {e}")

    def get_all_notes_data(self) -> list:
        return self.notes_list

    def add_note_from_midi(self, pitch: int, start_beat: float, duration_beat: float) -> None:
        new_note = NoteEventClass(
            self.beats_to_seconds(start_beat), self.beats_to_seconds(duration_beat), pitch, "la")
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
            logger.error(f"Waveform Analysis Error: {e}")
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
        interval_px = (self.tempo / 60.0) * self.pixels_per_beat * 0.05
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

        self._draw_grid(p)
        self._draw_audio_waveform(p)
        self._draw_glow(p)
        if self.show_ai_phonemes:
            self._draw_ai_phoneme_ghosts(p)
        self._draw_parameter_curves(p)
        self._draw_notes(p)
        self._draw_selection_rect(p)
        self._draw_playhead(p)

        p.end()

    def _draw_grid(self, p: QPainter) -> None:
        """横線（ノート行・黒鍵強調）＋縦線（小節・拍）"""
        # 横線
        p.setPen(QPen(QColor(35, 35, 35), 1))
        for n in range(128):
            y = (127 - n) * self.key_height_pixels - self.scroll_y_offset
            if y + self.key_height_pixels < 0 or y > self.height():
                continue
            if (n % 12) in (1, 3, 6, 8, 10):
                p.fillRect(QRectF(0, y, self.width(), self.key_height_pixels),
                           QColor(22, 22, 22))
            p.drawLine(0, int(y), self.width(), int(y))

        # 縦線
        for i in range(2000):
            x = i * self.pixels_per_beat - self.scroll_x_offset
            if x < -self.pixels_per_beat:
                continue
            if x > self.width():
                break
            p.setPen(QPen(QColor(58, 58, 60) if i % 4 == 0 else QColor(36, 36, 36), 1))
            p.drawLine(int(x), 0, int(x), self.height())

    def _draw_glow(self, p: QPainter) -> None:
        if self.audio_level <= 0.001:
            return
        cx = int(self.seconds_to_beats(self._current_playback_time)
                 * self.pixels_per_beat - self.scroll_x_offset)
        gw = int(self.audio_level * 150)
        grad = QLinearGradient(float(cx - gw), 0.0, float(cx + gw), 0.0)
        grad.setColorAt(0, QColor(255, 45, 85, 0))
        grad.setColorAt(0.5, QColor(255, 45, 85, int(self.audio_level * 150)))
        grad.setColorAt(1, QColor(255, 45, 85, 0))
        p.fillRect(self.rect(), QBrush(grad))

    def _draw_ai_phoneme_ghosts(self, p: QPainter) -> None:
        """onset（子音区間）をノート左側にグラデーションで可視化"""
        for n in self.notes_list:
            rect = self.get_note_rect(n)
            if rect.right() < 0 or rect.left() > self.width():
                continue
            onset_px = self.seconds_to_beats(float(getattr(n, 'onset', 0.1))) * self.pixels_per_beat
            ghost_rect = QRectF(rect.left() - onset_px, rect.top(), onset_px, rect.height())
            p.setPen(Qt.PenStyle.NoPen)
            grad = QLinearGradient(ghost_rect.topLeft(), ghost_rect.topRight())
            grad.setColorAt(0, QColor(0, 255, 255, 0))
            grad.setColorAt(1, QColor(0, 255, 255, self.ai_ghost_alpha))
            p.setBrush(QBrush(grad))
            p.drawRect(ghost_rect)
            # 母音開始ライン
            p.setPen(QPen(QColor(0, 255, 255, 180), 1, Qt.PenStyle.DashLine))
            p.drawLine(int(rect.left()), int(rect.top()),
                       int(rect.left()), int(rect.bottom()))

    def _draw_notes(self, p: QPainter) -> None:
        for n in self.notes_list:
            rect = self.get_note_rect(n)
            if rect.right() < 0 or rect.left() > self.width():
                continue
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

    def _draw_parameter_curves(self, p: QPainter) -> None:
        """非アクティブ層は薄く、アクティブ層は強調して全レイヤー描画"""
        for name, data in self.parameters.items():
            if name != self.current_param_layer:
                self._draw_curve(p, data,
                                 self._PARAM_COLORS.get(name, QColor(200, 200, 200)), 60, 1)
        self._draw_curve(p,
                         self.parameters.get(self.current_param_layer, {}),
                         self._PARAM_COLORS.get(self.current_param_layer, QColor(255, 255, 255)),
                         255, 2)

    def _draw_curve(self, p: QPainter, data: Dict[float, float],
                    color: QColor, alpha: int, width: int) -> None:
        if not data:
            return
        c = QColor(color)
        c.setAlpha(alpha)
        p.setPen(QPen(c, width, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        prev: Optional[QPointF] = None
        for t in sorted(data):
            x = self.seconds_to_beats(t) * self.pixels_per_beat - self.scroll_x_offset
            y = self.height() - (data[t] * self.height() * 0.4) - 20
            curr = QPointF(x, y)
            if prev and abs(curr.x() - prev.x()) < 500:
                p.drawLine(prev, curr)
            prev = curr

    def _draw_selection_rect(self, p: QPainter) -> None:
        if self.edit_mode == "select_box":
            p.setPen(QPen(Qt.GlobalColor.white, 1, Qt.PenStyle.DashLine))
            p.setBrush(QBrush(QColor(255, 255, 255, 40)))
            p.drawRect(self.selection_rect)

    def _draw_playhead(self, p: QPainter) -> None:
        cx = int(self.seconds_to_beats(self._current_playback_time)
                 * self.pixels_per_beat - self.scroll_x_offset)
        p.setPen(QPen(QColor(255, 45, 85), 2))
        p.drawLine(cx, 0, cx, self.height())

    # ============================================================
    # マウス・ホイールイベント
    # ============================================================

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Ctrl+ホイール: 横ズーム / 通常: 縦スクロール + scroll_synced_signal"""
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.1 if delta > 0 else 0.9
            mouse_x = event.position().x()
            beat_at_mouse = (mouse_x + self.scroll_x_offset) / self.pixels_per_beat
            self.pixels_per_beat = max(10.0, min(1000.0, self.pixels_per_beat * factor))
            self.scroll_x_offset = (beat_at_mouse * self.pixels_per_beat) - mouse_x
        else:
            self.scroll_y_offset = max(0.0, self.scroll_y_offset - delta)
            self.scroll_synced_signal.emit(self.scroll_y_offset)
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event is None:
            return
        pos_f = event.position()
        self.drag_start_pos = QPoint(int(pos_f.x()), int(pos_f.y()))

        if event.button() == Qt.MouseButton.RightButton:
            return  # contextMenuEvent に委譲

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
                    if not n.is_selected:
                        self.deselect_all()
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
        if event is None or self.drag_start_pos is None:
            return
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
            note_start_px = (self.seconds_to_beats(self._resizing_note.start_time)
                             * self.pixels_per_beat)
            new_w_beats = (curr_pos.x() + self.scroll_x_offset - note_start_px) / self.pixels_per_beat
            self._resizing_note.duration = self.beats_to_seconds(
                max(self.quantize_resolution, new_w_beats))
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
                    n.start_time = self.beats_to_seconds(
                        self.quantize(self.seconds_to_beats(n.start_time)))
                    n.duration = self.beats_to_seconds(
                        max(self.quantize_resolution,
                            self.quantize(self.seconds_to_beats(n.duration))))
            self.notes_changed_signal.emit()
        self.edit_mode = None
        self._resizing_note = None
        self.drag_start_pos = None
        self.update()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        selected_notes = [n for n in self.notes_list if getattr(n, 'is_selected', False)]

        if selected_notes:
            act_clear = QAction(f"選択したノートの {self.current_param_layer} をリセット", self)
            act_clear.triggered.connect(self._clear_selected_params)
            menu.addAction(act_clear)

            act_reset = QAction("歌詞を 'la' にリセット", self)
            act_reset.triggered.connect(self._reset_selected_lyrics)
            menu.addAction(act_reset)

            act_ghost = QAction(
                "AIゴーストを非表示" if self.show_ai_phonemes else "AIゴーストを表示", self)
            act_ghost.triggered.connect(self._toggle_ai_ghost)
            menu.addAction(act_ghost)

            menu.addSeparator()

        act_export = QAction("JSONエクスポート (Ctrl+S)", self)
        act_export.triggered.connect(self.export_all_data)
        menu.addAction(act_export)

        menu.exec(event.globalPos())

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event is None:
            return
        pos_f = event.position()
        for n in self.notes_list:
            if self.get_note_rect(n).contains(pos_f):
                text, ok = QInputDialog.getText(
                    self, "歌詞入力", "ノートの歌詞:",
                    QLineEdit.EchoMode.Normal, n.lyrics)
                if ok and text:
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

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """
        [VO-SE Pro: ショートカット・エンジン]
        - 1~4: レイヤー切り替え (Dynamics, Pitch, Vibrato, Formant)
        - Ctrl+S/C/V/D/A: 標準的な編集コマンド
        - Del/Backspace: 選択要素の削除
        """
        if event is None:
            return

        # 修飾キーとキーコードの取得
        # Pyright対応: event.modifiers() の結果を明示的に処理
        modifiers = event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        key_int = event.key()

        # レイヤー切り替えの定義
        # Pyright対応: キーコード(int)とQt.Key型の不一致を防ぐため、比較を安定させる
        layer_map = {
            Qt.Key.Key_1.value: "Dynamics",
            Qt.Key.Key_2.value: "Pitch",
            Qt.Key.Key_3.value: "Vibrato",
            Qt.Key.Key_4.value: "Formant",
        }

        # ステータスバー通知用の準備
        main_window = self.window()
        status_bar = getattr(main_window, "statusBar", lambda: None)()

        # 1. レイヤー切り替えの処理
        if key_int in layer_map:
            target_layer = layer_map[key_int]
            self.change_layer(target_layer)
            if status_bar:
                status_bar.showMessage(f"Layer switched to: {target_layer}", 2000)

        # 2. Ctrl系ショートカット
        elif ctrl:
            # Ruff E701対応: すべての処理を改行して記述
            if key_int == Qt.Key.Key_S.value:
                self.export_all_data()
            
            elif key_int == Qt.Key.Key_C.value:
                self._copy_notes()
            
            elif key_int == Qt.Key.Key_V.value:
                self._paste_notes()
            
            elif key_int == Qt.Key.Key_D.value:
                self._duplicate_notes()
            
            elif key_int == Qt.Key.Key_A.value:
                self.select_all()

        # 3. 削除系
        elif key_int in (Qt.Key.Key_Delete.value, Qt.Key.Key_Backspace.value):
            self.delete_selected()
            if status_bar:
                status_bar.showMessage("Selected points deleted", 2000)

        # 最後にUIを更新
        self.update()

    # ============================================================
    # 編集ロジック
    # ============================================================

    def change_layer(self, name: str) -> None:
        """
        [VO-SE Pro: レイヤー切り替えエンジン]
        編集対象のパラメータ（Dynamics, Pitch等）を変更し、UIとステータスバーを同期します。
        """
        # 1. 内部状態の更新
        self.current_param_layer = name
        
        # 2. メインウィンドウのステータスバーへの通知
        # Pyright対策: self.window() の戻り値を一度変数に受け、型を確定させる
        main_win = self.window()
        
        # QMainWindow であることを確認してから statusBar() にアクセス
        if isinstance(main_win, QMainWindow):
            sb = main_win.statusBar()
            
            # Ruff E701対応: if文の中身は必ず改行
            if sb:
                sb.showMessage(f"Active Layer: {name}", 2000)
        
        # 3. 描画の更新（レイヤーによって曲線や色が変わるため必須）
        self.update()
        
        # デバッグログの出力（開発中のトレーサビリティ確保）
        logger.info(f"Graph Editor: Layer changed to '{name}'")

    def _toggle_ai_ghost(self) -> None:
        self.show_ai_phonemes = not self.show_ai_phonemes
        self.update()

    def _add_param_pt(self, pos: QPointF) -> None:
        t = self.beats_to_seconds((pos.x() + self.scroll_x_offset) / self.pixels_per_beat)
        val = max(0.0, min(1.0, (self.height() - 20 - pos.y()) / (self.height() * 0.4)))
        self.parameters[self.current_param_layer][float(t)] = float(val)
        self.update()

    def _smooth_param(self) -> None:
        layer = self.current_param_layer
        data = self.parameters[layer]
        if len(data) < 3:
            return
        keys = sorted(data.keys())
        smoothed = {}
        for i, t in enumerate(keys):
            window = [data[keys[j]] for j in range(max(0, i - 1), min(len(keys), i + 2))]
            smoothed[t] = sum(window) / len(window)
        self.parameters[layer] = smoothed
        self.notes_changed_signal.emit()

    def _clear_selected_params(self) -> None:
        layer = self.current_param_layer
        for n in self.notes_list:
            if not getattr(n, 'is_selected', False):
                continue
            keys_to_del = [t for t in self.parameters[layer]
                           if n.start_time <= t <= n.start_time + n.duration]
            for k in keys_to_del:
                del self.parameters[layer][k]
        self.update()

    def _reset_selected_lyrics(self) -> None:
        for n in self.notes_list:
            if getattr(n, 'is_selected', False):
                n.lyrics = "la"
                n.phoneme = "la"
        self.update()

    def _split_note(self, n: Any, chars: List[str]) -> None:
        if n not in self.notes_list:
            return
        single_dur = n.duration / len(chars)
        start_t, pitch = n.start_time, n.note_number
        self.notes_list.remove(n)
        for i, char in enumerate(chars):
            new_n = NoteEventClass(start_t + i * single_dur, single_dur, pitch, char)
            new_n.phoneme = self.analyze_lyric_to_phoneme(char)
            self.notes_list.append(new_n)

    def _copy_notes(self) -> None:
        sel = [n for n in self.notes_list if getattr(n, 'is_selected', False)]
        if not sel:
            return
        base_t = min(n.start_time for n in sel)
        payload = [{"l": n.lyrics, "n": n.note_number,
                    "o": n.start_time - base_t, "d": n.duration} for n in sel]
        QApplication.clipboard().setText(json.dumps(payload))

    def _paste_notes(self) -> None:
        try:
            data = json.loads(QApplication.clipboard().text())
            self.deselect_all()
            for d in data:
                nn = NoteEventClass(
                    self._current_playback_time + d["o"], d["d"], d["n"], d["l"])
                nn.is_selected = True
                nn.phoneme = self.analyze_lyric_to_phoneme(d["l"])
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
            clone.phoneme = n.phoneme
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
