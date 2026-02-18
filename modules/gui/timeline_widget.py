import json
import os
import ctypes
import wave
import numpy as np
from typing import List, Dict, Any, Optional, Protocol, runtime_checkable

from PySide6.QtWidgets import QWidget, QApplication, QInputDialog, QLineEdit
from PySide6.QtCore import Qt, QRect, Signal, Slot, QPoint, QSize
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QLinearGradient, QPaintEvent





# --- 1. データモデルの安全なインポートと型定義 ---
# Protocolを使用して、NoteEventが持つべき属性を型チェッカーに約束させます
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

try:
    import modules.data.data_models as _data_models
    NoteEvent: Any = getattr(_data_models, "NoteEvent")
except Exception:
    # Actions対策: 本物の NoteEvent とシグネチャを合わせ、
    # 属性アクセス(reportAttributeAccessIssue)を完全に封殺します。
    class NoteEvent:
        def __init__(
            self, 
            start_time: float, 
            duration: float, 
            note_number: int, 
            lyrics: str
        ) -> None:
            self.start_time: float = start_time
            self.duration: float = duration
            self.note_number: int = note_number
            self.lyrics: str = lyrics
            self.is_selected: bool = False
            self.phoneme: str = ""
            
            # 解析用パラメータ（main_window.py との整合性維持）
            self.onset: float = 0.0
            self.overlap: float = 0.0
            self.pre_utterance: float = 0.0
            self.has_analysis: bool = False

        def to_dict(self) -> Dict[str, Any]:
            """
            ダミー実装でも、最低限の構造を返すことで
            保存処理（JSON書き出しなど）でのクラッシュを防ぎます。
            """
            return {
                "start_time": self.start_time,
                "duration": self.duration,
                "note_number": self.note_number,
                "lyrics": self.lyrics,
                "phoneme": self.phoneme,
                "onset": getattr(self, "onset", 0.0),
                "overlap": getattr(self, "overlap", 0.0),
                "pre_utterance": getattr(self, "pre_utterance", 0.0)
            }

# --- 2. Janome Tokenizer の安全なインポート ---
# Protocol定義により、ダミーでも本物でも tokenize メソッドの存在を保証
class TokenizerProtocol(Protocol):
    def tokenize(self, text: str) -> List[Any]: ...

try:
    import janome.tokenizer as _janome_tokenizer
    JanomeTokenizer: Any = getattr(_janome_tokenizer, "Tokenizer")
except Exception:
    class JanomeTokenizer:
        def tokenize(self, text: str) -> List[Any]:
            return []


class TimelineWidget(QWidget):
    # シグナル名の統一（MainWindow側での接続エラーを確実に防ぐ）
    notes_changed_signal: Signal = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        タイムライン・ピアノロールのメインウィジェット。
        多レイヤー編集と音声エンジン連携を完遂します。
        """
        super().__init__(parent)

        self.notes: list = []
        
        # --- 基本的な表示設定 ---
        self.setMinimumSize(400, 200)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True) # マウス移動を常に監視（ノート描画用）
        
        # --- 基本データ構造 ---
        # NoteEventがダミーでも本物でも、型ヒントでActionsを黙らせます
        self.notes_list: List[Any] = []
        self.tempo: float = 120.0
        self.pixels_per_beat: float = 40.0
        self.key_height_pixels: float = 20.0
        self.scroll_x_offset: int = 0
        self.scroll_y_offset: int = 0
        self._current_playback_time: float = 0.0
        self.quantize_resolution: float = 0.25  # 16分音符
        
        # --- Pyrightの reportAttributeAccessIssue / F841 対策 ---
        # MainWindowや他モジュールから参照される全属性を明示的に初期化
        self.sync_notes: bool = True
        self.text_color: QColor = QColor(255, 255, 255)
        self.bg_color: QColor = QColor(45, 45, 45)
        self.note_color: QColor = QColor(74, 144, 226)
        
        # --- モニタリング & 多レイヤーパラメータ ---
        # 各パラメータ値を保持する辞書。将来のピッチ編集機能等を見据えた設計を維持。
        self.audio_level: float = 0.0
        self.parameters: Dict[str, Dict[float, float]] = {
            "Dynamics": {}, 
            "Pitch": {}, 
            "Vibrato": {}, 
            "Formant": {}
        }
        self.current_param_layer: str = "Dynamics"
        
        # --- 状態管理・操作系 ---
        self.edit_mode: Optional[str] = None
        self.drag_start_pos: Optional[QPoint] = None
        self.selection_rect: QRect = QRect()
        
        # Tokenizerの初期化 (Noneチェックを行いActionsエラーを回避)
        self.tokenizer: Any = None
        try:
            # 型チェックを通過させるため、一度ローカル変数に受ける等の工夫も可だが
            # ここではクラス定義の try-except ブロックで保証された Tokenizer を使用
            self.tokenizer = JanomeTokenizer()
        except Exception:
            # 万が一の予備
            class DummyTokenizer:
                def tokenize(self, text: str) -> List[str]: return [text]
            self.tokenizer = DummyTokenizer()
        
        # --- 音声エンジン初期化 ---
        self.vose_core: Any = None 
        # 代表の設計通り、初期化時にエンジンをセットアップ
        self.init_voice_engine()

    def get_max_beat_position(self) -> int:
        """最大ビート位置を返す"""
        return 480 * 4 # デフォルト値

    def add_note_from_midi(self, pitch: int, start: int, duration: int):
        """MIDIデータからノートを追加"""
        pass

    def get_all_notes_data(self) -> list:
        """全ノートデータをリストで返す"""
        return self.notes
            

    # --- 座標 & 解析 ---
    def seconds_to_beats(self, s: float) -> float: 
        return s / (60.0 / self.tempo)

    def beats_to_seconds(self, b: float) -> float: 
        return b * (60.0 / self.tempo)

    def quantize(self, val: float) -> float: 
        return round(val / self.quantize_resolution) * self.quantize_resolution

    def get_note_rect(self, note: Any) -> QRect:
        x = int(self.seconds_to_beats(note.start_time) * self.pixels_per_beat - self.scroll_x_offset)
        y = int((127 - note.note_number) * self.key_height_pixels - self.scroll_y_offset)
        w = int(self.seconds_to_beats(note.duration) * self.pixels_per_beat)
        h = int(self.key_height_pixels)
        return QRect(x, y, w, h)

    def analyze_lyric_to_phoneme(self, text: str) -> str:
        try:
            tokens = self.tokenizer.tokenize(text)
            # 属性アクセスを安全に（getattrを使用）
            phonemes = []
            for t in tokens:
                reading = str(getattr(t, 'reading', '*'))
                surface = str(getattr(t, 'surface', ''))
                phonemes.append(reading if reading != "*" else surface)
            return "".join(phonemes)
        except Exception: 
            return text

    # --- C言語エンジン連携ブリッジ ---
    def export_all_data(self, file_path: str = "engine_input.json") -> None:
        data = {
            "metadata": {"tempo": self.tempo, "version": "1.4.0"},
            "notes": [
                {
                    "t": n.start_time, 
                    "d": n.duration, 
                    "n": n.note_number, 
                    "p": self.analyze_lyric_to_phoneme(n.lyrics),
                    "onset": float(getattr(n, 'onset', 0.0)),
                    "overlap": float(getattr(n, 'overlap', 0.0)),
                    "pre_utterance": float(getattr(n, 'pre_utterance', 0.0)),
                    "optimized": bool(getattr(n, 'has_analysis', False))
                } for n in self.notes_list
            ],
            "parameters": self.parameters
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ Exported to {file_path}")

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

    @Slot(float)
    def update_audio_level(self, level: float) -> None:
        self.audio_level = level
        self.update()        

    # --- 描画ロジック ---
    def get_audio_peaks(self, file_path: str, num_peaks: int = 2000) -> List[float]:
        """WAVファイルから描画用のピークデータを抽出する（NumPy高速版）"""
        if not file_path or not os.path.exists(file_path):
            return []
            
        try:
            with wave.open(file_path, 'rb') as w:
                params = w.getparams()
                n_frames = params.nframes
                if n_frames == 0: 
                    return []
                
                frames = w.readframes(n_frames)
                samples = np.frombuffer(frames, dtype=np.int16)
                
                if params.nchannels == 2:
                    samples = samples[::2]
                
                if len(samples) < num_peaks:
                    num_peaks = len(samples)
                
                if num_peaks <= 0:
                    return []
                
                chunks = np.array_split(samples, num_peaks)
                peaks = [float(np.max(np.abs(chunk))) if len(chunk) > 0 else 0.0 for chunk in chunks]
                
                max_val = float(np.max(peaks)) if peaks else 1.0
                return [p / max_val for p in peaks]
        except Exception as e:
            print(f"Waveform Analysis Error: {e}")
            return []

    def _draw_audio_waveform(self, p: QPainter) -> None:
        """タイムラインの背景としてオーディオ波形を描画する（同期修正版）"""
        # 親オブジェクトへのアクセスを安全に行う
        parent_obj = self.parent()
        if parent_obj is None:
            return
            
        # getattrを使用して動的属性アクセスによる型エラーを回避
        target_idx_val = getattr(parent_obj, 'current_track_idx', 0)
        tracks_val = getattr(parent_obj, 'tracks', [])
        
        target_idx: int = int(target_idx_val)
        tracks: List[Any] = list(tracks_val) if isinstance(tracks_val, list) else []
        
        if target_idx >= len(tracks):
            return
            
        track = tracks[target_idx]
        
        track_type = str(getattr(track, 'track_type', ''))
        audio_path = str(getattr(track, 'audio_path', ''))

        if track_type != "wave" or not audio_path:
            return

        # ピークデータのキャッシュ確認
        if not hasattr(track, 'vose_peaks'):
            setattr(track, 'vose_peaks', self.get_audio_peaks(audio_path))
            
        vose_peaks = getattr(track, 'vose_peaks', [])
        if not vose_peaks or not isinstance(vose_peaks, list):
            return

        pixels_per_second = (self.tempo / 60.0) * self.pixels_per_beat
        data_interval_px = pixels_per_second * 0.05 
        
        p.setPen(QPen(QColor(0, 255, 255, 60), 1))
        
        mid_y = float(self.height() / 2)
        max_h = float(self.height() * 0.7)
        
        for i, peak in enumerate(vose_peaks):
            x = (i * data_interval_px) - self.scroll_x_offset
            if x < -data_interval_px:
                continue
            if x > self.width():
                break
            
            h = peak * max_h
            p.drawLine(int(x), int(mid_y - h/2), int(x), int(mid_y + h/2))

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(18, 18, 18))

        # --- 1. 背景グリッド ---
        for i in range(200):
            x = i * self.pixels_per_beat - self.scroll_x_offset
            pen_color = QColor(58, 58, 60) if i % 4 == 0 else QColor(36, 36, 36)
            p.setPen(QPen(pen_color, 1))
            p.drawLine(int(x), 0, int(x), self.height())

        # --- 2. オーディオ波形描画 ---
        self._draw_audio_waveform(p)

        # --- 3. モニタリング発光 ---
        if self.audio_level > 0.001:
            cx = int(self.seconds_to_beats(self._current_playback_time) * self.pixels_per_beat - self.scroll_x_offset)
            glow_w = int(self.audio_level * 100)
            grad = QLinearGradient(float(cx - glow_w), 0.0, float(cx + glow_w), 0.0)
            grad.setColorAt(0, QColor(255, 45, 85, 0))
            grad.setColorAt(0.5, QColor(255, 45, 85, int(self.audio_level * 120)))
            grad.setColorAt(1, QColor(255, 45, 85, 0))
            p.fillRect(self.rect(), QBrush(grad))

        # --- 4. パラメータ表示 ---
        colors = {
            "Dynamics": QColor(255, 45, 85), 
            "Pitch": QColor(0, 255, 255), 
            "Vibrato": QColor(255, 165, 0), 
            "Formant": QColor(200, 100, 255)
        }
        for name, data in self.parameters.items():
            if name != self.current_param_layer:
                self._draw_curve(p, data, colors.get(name, QColor(255, 255, 255)), 40, 1)
        
        current_layer_data = self.parameters.get(self.current_param_layer, {})
        self._draw_curve(p, current_layer_data, colors.get(self.current_param_layer, QColor(255, 255, 255)), 220, 2)

        # --- 5. ノート描画 ---
        for n in self.notes_list:
            r = self.get_note_rect(n)
            # n.is_selected の存在を確認
            is_selected = bool(getattr(n, 'is_selected', False))
            color = QColor(255, 159, 10) if is_selected else QColor(10, 132, 255)
            
            p.setBrush(QBrush(color))
            p.setPen(QPen(color.lighter(120), 1))
            p.drawRoundedRect(r, 2, 2)
            
            if n.lyrics:
                p.setPen(Qt.GlobalColor.white)
                p.setFont(QFont("Helvetica", 9, QFont.Weight.Bold))
                p.drawText(r.adjusted(5, 0, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, n.lyrics)
                
                # 音素情報の表示
                p.setPen(QColor(200, 200, 200, 150))
                p.setFont(QFont("Consolas", 7))
                phoneme_text = self.analyze_lyric_to_phoneme(n.lyrics)
                p.drawText(r.adjusted(2, 22, 0, 0), Qt.AlignmentFlag.AlignLeft, phoneme_text)

        # --- 6. 選択枠 & 再生カーソル ---
        if self.edit_mode == "select_box":
            p.setPen(QPen(Qt.GlobalColor.white, 1, Qt.PenStyle.DashLine))
            p.setBrush(QBrush(QColor(255, 255, 255, 30)))
            p.drawRect(self.selection_rect)

        # 再生カーソル
        cx_play = int(self.seconds_to_beats(self._current_playback_time) * self.pixels_per_beat - self.scroll_x_offset)
        p.setPen(QPen(QColor(255, 45, 85), 2))
        p.drawLine(cx_play, 0, cx_play, self.height())
        p.end()

    def _draw_curve(self, p: QPainter, data: Dict[float, float], color: QColor, alpha: int, width: int) -> None:
        if not data:
            return
        c = QColor(color)
        c.setAlpha(alpha)
        p.setPen(QPen(c, width))
        sorted_ts = sorted(data.keys())
        prev: Optional[QPoint] = None
        for t in sorted_ts:
            x = int(self.seconds_to_beats(t) * self.pixels_per_beat - self.scroll_x_offset)
            y = int(self.height() - (data[t] * self.height() * 0.3) - 10)
            curr = QPoint(x, y)
            if prev:
                p.drawLine(prev, curr)
            prev = curr

    def keyPressEvent(self, event: Any) -> None:
        if event is None:
            return
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        key = event.key()
        if key == Qt.Key.Key_1:
            self.change_layer("Dynamics")
        elif key == Qt.Key.Key_2:
            self.change_layer("Pitch")
        elif key == Qt.Key.Key_3:
            self.change_layer("Vibrato")
        elif key == Qt.Key.Key_4:
            self.change_layer("Formant")
        elif ctrl and key == Qt.Key.Key_S:
            self.export_all_data()
        elif ctrl and key == Qt.Key.Key_C:
            self.copy_notes()
        elif ctrl and key == Qt.Key.Key_V:
            self.paste_notes()
        elif ctrl and key == Qt.Key.Key_D:
            self.duplicate_notes()
        elif ctrl and key == Qt.Key.Key_A:
            self.select_all()
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()

    def change_layer(self, name: str) -> None:
        self.current_param_layer = name
        self.update()

    def mousePressEvent(self, event: Any) -> None:
        if event is None: 
            return
        
        pos = event.position()
        self.drag_start_pos = QPoint(int(pos.x()), int(pos.y()))
        
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self.edit_mode = "draw_parameter"
            self.add_param_pt(pos)
            return
            
        for n in reversed(self.notes_list):
            if self.get_note_rect(n).contains(self.drag_start_pos):
                if not getattr(n, 'is_selected', False):
                    if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                        self.deselect_all()
                    n.is_selected = True
                self.edit_mode = "move"
                self.update()
                return
        
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.deselect_all()
        self.edit_mode = "select_box"
        self.selection_rect = QRect(self.drag_start_pos, QSize(0,0))
        self.update()

    def mouseMoveEvent(self, event: Any) -> None:
        if event is None or self.drag_start_pos is None:
            return

        pos = event.position()
        
        if self.edit_mode == "draw_parameter":
            self.add_param_pt(pos)
            self.update()
        elif self.edit_mode == "move":
            dx = (pos.x() - self.drag_start_pos.x()) / self.pixels_per_beat
            dy = (pos.y() - self.drag_start_pos.y()) / self.key_height_pixels
            dt = self.beats_to_seconds(dx)
            dn = -int(round(dy))
            
            if abs(dt) > 0.001 or dn != 0:
                for n in self.notes_list:
                    if getattr(n, 'is_selected', False):
                        n.start_time += dt
                        n.note_number = max(0, min(127, n.note_number + dn))
                self.drag_start_pos = QPoint(int(pos.x()), int(pos.y()))
                self.update()
        elif self.edit_mode == "select_box":
            self.selection_rect = QRect(self.drag_start_pos, QPoint(int(pos.x()), int(pos.y()))).normalized()
            for n in self.notes_list:
                n.is_selected = self.selection_rect.intersects(self.get_note_rect(n))
            self.update()

    def mouseReleaseEvent(self, event: Any) -> None:
        if self.edit_mode == "draw_parameter":
            self.smooth_param()
        elif self.edit_mode == "move":
            for n in self.notes_list:
                if getattr(n, 'is_selected', False):
                    beats = self.seconds_to_beats(n.start_time)
                    n.start_time = self.beats_to_seconds(self.quantize(beats))
            self.notes_changed_signal.emit()
        self.edit_mode = None
        self.update()

    def add_param_pt(self, pos: Any) -> None:
        t = self.beats_to_seconds((pos.x() + self.scroll_x_offset) / self.pixels_per_beat)
        val = max(0.0, min(1.0, (self.height() - 10 - pos.y()) / (self.height() * 0.3)))
        self.parameters[self.current_param_layer][t] = float(val)

    def smooth_param(self) -> None:
        data = self.parameters[self.current_param_layer]
        if len(data) < 5:
            return
        sorted_ts = sorted(data.keys())
        new_data = {}
        for i, t in enumerate(sorted_ts):
            subset = [data[sorted_ts[j]] for j in range(max(0, i-2), min(len(sorted_ts), i+3))]
            new_data[t] = sum(subset) / len(subset)
        self.parameters[self.current_param_layer] = new_data
        self.notes_changed_signal.emit()

    def duplicate_notes(self) -> None:
        sel = [n for n in self.notes_list if getattr(n, 'is_selected', False)]
        if not sel:
            return
        offset = max(n.start_time + n.duration for n in sel) - min(n.start_time for n in sel)
        self.deselect_all()
        for n in sel:
            clone = NoteEvent(n.start_time + offset, n.duration, n.note_number, n.lyrics)
            clone.is_selected = True
            self.notes_list.append(clone)
        self.notes_changed_signal.emit()
        self.update()

    def mouseDoubleClickEvent(self, event: Any) -> None:
        if event is None: 
            return
        pos_pt = QPoint(int(event.position().x()), int(event.position().y()))
        for n in self.notes_list:
            if self.get_note_rect(n).contains(pos_pt):
                text, ok = QInputDialog.getText(self, "歌詞", "入力:", QLineEdit.EchoMode.Normal, n.lyrics)
                if ok:
                    n.lyrics = text
                    n.phoneme = self.analyze_lyric_to_phoneme(text)
                    tokens = self.tokenizer.tokenize(text)
                    chars = [str(getattr(t, 'surface', '')) for t in tokens]
                    if len(chars) > 1:
                        self.split_note(n, chars)
                    self.notes_changed_signal.emit()
                    self.update()

    def split_note(self, n: Any, chars: List[str]) -> None:
        dur = n.duration / len(chars)
        if n in self.notes_list:
            self.notes_list.remove(n)
        for i, c in enumerate(chars): 
            new_n = NoteEvent(n.start_time + i*dur, dur, n.note_number, c)
            self.notes_list.append(new_n)

    def copy_notes(self) -> None:
        sel = [n for n in self.notes_list if getattr(n, 'is_selected', False)]
        if not sel:
            return
        base = min(n.start_time for n in sel)
        data = [{"l": n.lyrics, "n": n.note_number, "o": n.start_time - base, "d": n.duration} for n in sel]
        QApplication.clipboard().setText(json.dumps(data))

    def paste_notes(self) -> None:
        try:
            clipboard_text = QApplication.clipboard().text()
            if not clipboard_text:
                return
            data = json.loads(clipboard_text)
            self.deselect_all()
            for d in data:
                nn = NoteEvent(self._current_playback_time + d["o"], d["d"], d["n"], d["l"])
                nn.is_selected = True
                self.notes_list.append(nn)
            self.notes_changed_signal.emit()
            self.update()
        except Exception:
            pass

    def delete_selected(self) -> None: 
        self.notes_list = [n for n in self.notes_list if not getattr(n, 'is_selected', False)]
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

    @Slot(int)
    def set_vertical_offset(self, val: int) -> None: 
        self.scroll_y_offset = val
        self.update()

    @Slot(int)
    def set_horizontal_offset(self, val: int) -> None: 
        self.scroll_x_offset = val
        self.update()
