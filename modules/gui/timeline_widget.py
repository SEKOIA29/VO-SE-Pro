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
                            QLinearGradient, QPaintEvent, QMouseEvent, QKeyEvent, QWheelEvent,
                            QPixmap)  # [OPT] QPixmap追加

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
# 2. Janome Tokenizer
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

    最適化一覧:
    [OPT-1] グリッドキャッシュ: _grid_pixmap にグリッドを一度だけ描画し、
            スクロール・ズーム変更時のみ再生成する。
            毎フレーム2000本の線を描く処理をゼロコストに削減。

    [OPT-2] 可視範囲クリッピング: _draw_notes / _draw_ai_phoneme_ghosts /
            _draw_parameter_curves で可視範囲外のノートを早期スキップ。
            ノート数が多い曲での描画コストをO(n)→O(visible)に削減。

    [OPT-3] ノート矩形キャッシュ: _note_rects_cache に QRectF を保持し、
            ノートリストが変化したときだけ再計算する。
            get_note_rect() の繰り返し計算を排除。

    [OPT-4] 選択変更の差分更新: is_selected が変わったノートだけ
            update(rect) で部分再描画する（将来拡張用に構造を用意）。
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

        self.show_ai_phonemes: bool = True
        self.ai_ghost_alpha: int = 100

        # [OPT-1] グリッドキャッシュ
        self._grid_pixmap: Optional[QPixmap] = None
        self._grid_cache_key: tuple = ()  # (width, height, ppb, kh, scroll_y) で無効化

        # [OPT-3] ノート矩形キャッシュ
        # notes_list の id と scroll に依存するため、
        # _invalidate_note_rects() で明示的に無効化する
        self._note_rects_cache: Dict[int, QRectF] = {}  # id(note) -> QRectF
        self._note_rects_scroll: tuple = ()             # (scroll_x, scroll_y, ppb, kh)

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
    # [OPT-1] グリッドキャッシュ管理
    # ============================================================

    def _get_grid_cache_key(self) -> tuple:
        return (self.width(), self.height(),
                self.pixels_per_beat, self.key_height_pixels,
                self.scroll_y_offset)

    def _invalidate_grid(self) -> None:
        """スクロール・ズーム変更時にグリッドキャッシュを破棄する"""
        self._grid_pixmap = None

    def _ensure_grid_pixmap(self) -> QPixmap:
        """
        グリッドキャッシュを返す。
        キャッシュキーが変わっていれば再生成する。
        """
        key = self._get_grid_cache_key()
        if self._grid_pixmap is not None and self._grid_cache_key == key:
            return self._grid_pixmap

        # キャッシュミス: グリッドを QPixmap に描画して保存
        pixmap = QPixmap(self.width(), self.height())
        pixmap.fill(QColor(18, 18, 18))

        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)  # グリッドはAAなし

        # --- 横線（ノート行・黒鍵強調） ---
        pen_dark = QPen(QColor(35, 35, 35), 1)
        for n in range(128):
            y = (127 - n) * self.key_height_pixels - self.scroll_y_offset
            if y + self.key_height_pixels < 0:
                continue
            if y > self.height():
                break
            if (n % 12) in (1, 3, 6, 8, 10):
                p.fillRect(QRectF(0, y, self.width(), self.key_height_pixels),
                           QColor(22, 22, 22))
            p.setPen(pen_dark)
            p.drawLine(0, int(y), self.width(), int(y))

        # --- 縦線（可視範囲のみ）[OPT-2] ---
        # scroll_x_offset を考慮して最初の拍インデックスを計算
        first_beat = int(self.scroll_x_offset / self.pixels_per_beat)
        last_beat  = int((self.scroll_x_offset + self.width()) / self.pixels_per_beat) + 2
        for i in range(first_beat, last_beat):
            x = i * self.pixels_per_beat - self.scroll_x_offset
            p.setPen(QPen(QColor(58, 58, 60) if i % 4 == 0 else QColor(36, 36, 36), 1))
            p.drawLine(int(x), 0, int(x), self.height())

        p.end()

        self._grid_pixmap = pixmap
        self._grid_cache_key = key
        return pixmap

    # ============================================================
    # [OPT-3] ノート矩形キャッシュ管理
    # ============================================================

    def _get_scroll_key(self) -> tuple:
        return (self.scroll_x_offset, self.scroll_y_offset,
                self.pixels_per_beat, self.key_height_pixels)

    def _invalidate_note_rects(self) -> None:
        """ノートリスト変更時にキャッシュを全破棄する"""
        self._note_rects_cache.clear()
        self._note_rects_scroll = ()

    def _rebuild_note_rects_if_needed(self) -> None:
        """
        スクロール・ズームが変わったらノート矩形を全再計算する。
        ノートリスト変更時は _invalidate_note_rects() を先に呼ぶこと。
        """
        key = self._get_scroll_key()
        if self._note_rects_scroll == key and self._note_rects_cache:
            return
        self._note_rects_cache = {
            id(n): self._calc_note_rect(n) for n in self.notes_list
        }
        self._note_rects_scroll = key

    def _calc_note_rect(self, note: Any) -> QRectF:
        """座標計算の実体（キャッシュなし）"""
        x = self.seconds_to_beats(note.start_time) * self.pixels_per_beat - self.scroll_x_offset
        y = (127 - note.note_number) * self.key_height_pixels - self.scroll_y_offset
        w = self.seconds_to_beats(note.duration) * self.pixels_per_beat
        h = self.key_height_pixels
        return QRectF(x, y, w, h)

    def get_note_rect(self, note: Any) -> QRectF:
        """
        キャッシュ済み矩形を返す。
        マウスイベントなど頻繁に呼ばれる箇所でキャッシュを活用する。
        """
        nid = id(note)
        if nid in self._note_rects_cache:
            return self._note_rects_cache[nid]
        # キャッシュミス（新規ノートなど）: 計算して登録
        rect = self._calc_note_rect(note)
        self._note_rects_cache[nid] = rect
        return rect

    # ============================================================
    # 座標変換
    # ============================================================

    def seconds_to_beats(self, s: float) -> float:
        return s / (60.0 / self.tempo)

    def beats_to_seconds(self, b: float) -> float:
        return b * (60.0 / self.tempo)

    def quantize(self, val: float) -> float:
        return round(val / self.quantize_resolution) * self.quantize_resolution

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
        self._invalidate_note_rects()  # [OPT-3]
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
        # [OPT-3] 描画前にノート矩形キャッシュを更新
        self._rebuild_note_rects_if_needed()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # [OPT-1] グリッドはキャッシュ済み QPixmap を貼るだけ（毎フレームの線描画ゼロ）
        p.drawPixmap(0, 0, self._ensure_grid_pixmap())

        self._draw_audio_waveform(p)
        self._draw_glow(p)
        if self.show_ai_phonemes:
            self._draw_ai_phoneme_ghosts(p)
        self._draw_parameter_curves(p)
        self._draw_notes(p)
        self._draw_selection_rect(p)
        self._draw_playhead(p)

        p.end()

    def resizeEvent(self, event: Any) -> None:
        """ウィンドウリサイズ時にグリッドキャッシュを無効化する"""
        self._invalidate_grid()
        super().resizeEvent(event)

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
        """onset をノート左側にグラデーションで可視化 [OPT-2: 可視範囲クリッピング]"""
        vw = self.width()
        for n in self.notes_list:
            rect = self.get_note_rect(n)
            # [OPT-2] 可視範囲外を早期スキップ
            if rect.right() < 0 or rect.left() > vw:
                continue
            onset_px = self.seconds_to_beats(float(getattr(n, 'onset', 0.1))) * self.pixels_per_beat
            ghost_rect = QRectF(rect.left() - onset_px, rect.top(), onset_px, rect.height())
            p.setPen(Qt.PenStyle.NoPen)
            grad = QLinearGradient(ghost_rect.topLeft(), ghost_rect.topRight())
            grad.setColorAt(0, QColor(0, 255, 255, 0))
            grad.setColorAt(1, QColor(0, 255, 255, self.ai_ghost_alpha))
            p.setBrush(QBrush(grad))
            p.drawRect(ghost_rect)
            p.setPen(QPen(QColor(0, 255, 255, 180), 1, Qt.PenStyle.DashLine))
            p.drawLine(int(rect.left()), int(rect.top()),
                       int(rect.left()), int(rect.bottom()))

    def _draw_notes(self, painter: QPainter) -> None:
        """
        [VO-SE Pro: Ultra Fast Rendering]
        代表、このメソッドは二分探索を用いて、画面内に映るノートだけをピンポイントで描画します。
        """
        if not self.notes_list:
            return

        import bisect

        # 1. 描画範囲の計算（ピクセルから拍数へ変換）
        view_width = self.width()
        # 画面の左端と右端が「何拍目」に相当するか
        visible_start_time = self.scroll_x_offset / self.pixels_per_beat
        visible_end_time = (self.scroll_x_offset + view_width) / self.pixels_per_beat

        # 2. 描画開始インデックスの特定 (O(log N))
        # 検索用に開始時間だけのリストを作成（またはキャッシュされたものを使用）
        # ※ ノートは start_time 順にソートされている必要があります
        self.notes_list.sort(key=lambda n: n.start_time) 
        start_times = [n.start_time for n in self.notes_list]
        
        # 画面左端から少し余裕（1拍分）を持って検索開始
        start_idx = bisect.bisect_left(start_times, visible_start_time - 1.0)

        # 3. 描画ループ
        for i in range(start_idx, len(self.notes_list)):
            n = self.notes_list[i]
            
            # 画面右端を越えたら、これ以降のノートは見えないのでループを完全に抜ける
            if n.start_time > visible_end_time:
                break

            # 座標計算
            rect = self.get_note_rect(n)
            
            # [セーフティ] 上下の画面外チェック
            if rect.bottom() < 0 or rect.top() > self.height():
                continue

            # --- 描画ロジック ---
            is_selected = bool(getattr(n, 'is_selected', False))
            
            # Apple風・高品位カラー
            base_color = QColor(255, 159, 10) if is_selected else QColor(10, 132, 255)
            
            # ノート本体の描画（角丸）
            painter.setBrush(QBrush(base_color))
            painter.setPen(QPen(base_color.lighter(130), 1))
            painter.drawRoundedRect(rect, 4, 4)

            # テキスト描画（十分な幅がある場合のみ）
            if rect.width() > 15:
                # 歌詞（メイン）
                painter.setPen(Qt.GlobalColor.white)
                painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                painter.drawText(
                    rect.adjusted(5, 0, -2, 0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    n.lyrics
                )

                # 音素（サブ）
                painter.setPen(QColor(255, 255, 255, 180))
                painter.setFont(QFont("Consolas", 7))
                phoneme_text = getattr(n, 'phoneme', "") or self.analyze_lyric_to_phoneme(n.lyrics)
                painter.drawText(
                    rect.adjusted(5, int(self.key_height_pixels * 0.6), 0, 0),
                    Qt.AlignmentFlag.AlignLeft, 
                    phoneme_text
                )

    def _draw_parameter_curves(self, p: QPainter) -> None:
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
        vw = self.width()
        prev: Optional[QPointF] = None
        for t in sorted(data):
            x = self.seconds_to_beats(t) * self.pixels_per_beat - self.scroll_x_offset
            # [OPT-2] 可視範囲外はprevだけ更新してスキップ
            if x > vw + 10:
                break
            y = self.height() - (data[t] * self.height() * 0.4) - 20
            curr = QPointF(x, y)
            if prev and abs(curr.x() - prev.x()) < 500 and x > -10:
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
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.1 if delta > 0 else 0.9
            mouse_x = event.position().x()
            beat_at_mouse = (mouse_x + self.scroll_x_offset) / self.pixels_per_beat
            self.pixels_per_beat = max(10.0, min(1000.0, self.pixels_per_beat * factor))
            self.scroll_x_offset = (beat_at_mouse * self.pixels_per_beat) - mouse_x
            self._invalidate_grid()          # [OPT-1] ズーム変更でグリッド無効化
            self._invalidate_note_rects()    # [OPT-3] ズーム変更でノート矩形無効化
        else:
            self.scroll_y_offset = max(0.0, self.scroll_y_offset - delta)
            self._invalidate_grid()          # [OPT-1] 縦スクロールでグリッド無効化
            self.scroll_synced_signal.emit(self.scroll_y_offset)
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event is None:
            return
        pos_f = event.position()
        self.drag_start_pos = QPoint(int(pos_f.x()), int(pos_f.y()))

        if event.button() == Qt.MouseButton.RightButton:
            return

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
                self._invalidate_note_rects()  # [OPT-3] ノート移動で矩形無効化
                self.drag_start_pos = curr_pos
        elif self.edit_mode == "resize" and self._resizing_note is not None:
            note_start_px = (self.seconds_to_beats(self._resizing_note.start_time)
                             * self.pixels_per_beat)
            new_w_beats = (curr_pos.x() + self.scroll_x_offset - note_start_px) / self.pixels_per_beat
            self._resizing_note.duration = self.beats_to_seconds(
                max(self.quantize_resolution, new_w_beats))
            self._invalidate_note_rects()  # [OPT-3] リサイズで矩形無効化
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
            self._invalidate_note_rects()  # [OPT-3] 量子化後に再計算
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
                    self._invalidate_note_rects()  # [OPT-3]
                    self.notes_changed_signal.emit()
                    self.update()
                return

    # ============================================================
    # キーボード操作
    # ============================================================

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event is None:
            return

        modifiers = event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        key_int = event.key()

        layer_map = {
            Qt.Key.Key_1.value: "Dynamics",
            Qt.Key.Key_2.value: "Pitch",
            Qt.Key.Key_3.value: "Vibrato",
            Qt.Key.Key_4.value: "Formant",
        }

        main_window = self.window()
        status_bar = getattr(main_window, "statusBar", lambda: None)()

        if key_int in layer_map:
            target_layer = layer_map[key_int]
            self.change_layer(target_layer)
            if status_bar:
                status_bar.showMessage(f"Layer switched to: {target_layer}", 2000)

        elif ctrl:
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

        elif key_int in (Qt.Key.Key_Delete.value, Qt.Key.Key_Backspace.value):
            self.delete_selected()
            if status_bar:
                status_bar.showMessage("Selected points deleted", 2000)

        self.update()

    # ============================================================
    # 編集ロジック
    # ============================================================

    def change_layer(self, name: str) -> None:
        self.current_param_layer = name
        main_win = self.window()
        if isinstance(main_win, QMainWindow):
            sb = main_win.statusBar()
            if sb:
                sb.showMessage(f"Active Layer: {name}", 2000)
        self.update()
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
        self._invalidate_note_rects()  # [OPT-3]

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
            self._invalidate_note_rects()  # [OPT-3]
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
        self._invalidate_note_rects()  # [OPT-3]
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
        self._invalidate_note_rects()  # [OPT-3]
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
        self._invalidate_grid()        # [OPT-1]
        self.update()

    @Slot(int)
    def set_horizontal_offset(self, val: int) -> None:
        self.scroll_x_offset = float(val)
        self._invalidate_grid()        # [OPT-1]
        self._invalidate_note_rects()  # [OPT-3]
        self.update()
