# timeline_widget.py

import json
import os
import ctypes
import wave
import numpy as np
from PySide6.QtWidgets import QWidget, QApplication, QInputDialog, QLineEdit
from PySide6.QtCore import Qt, QRect, Signal, Slot, QPoint, QSize
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QLinearGradient
from .data_models import NoteEvent
from janome.tokenizer import Tokenizer

class TimelineWidget(QWidget):
    notes_changed_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 200)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        # --- 基本データ ---
        self.notes_list: list[NoteEvent] = []
        self.tempo = 120
        self.pixels_per_beat = 40.0
        self.key_height_pixels = 20.0
        self.scroll_x_offset = 0
        self.scroll_y_offset = 0
        self._current_playback_time = 0.0
        self.quantize_resolution = 0.25
        
        # --- モニタリング & 多レイヤー ---
        self.audio_level = 0.0
        self.parameters = {"Dynamics": {}, "Pitch": {}, "Vibrato": {}, "Formant": {}}
        self.current_param_layer = "Dynamics"
        
        # --- 状態管理 ---
        self.edit_mode = None
        self.drag_start_pos = None
        self.selection_rect = QRect()
        self.tokenizer = Tokenizer()
        
        # エンジン初期化（属性エラー回避のため最後に呼ぶ）
        self.vose_core = None 
        self.init_voice_engine()

    # --- 座標 & 解析 ---
    def seconds_to_beats(self, s): 
        return s / (60.0 / self.tempo)

    def beats_to_seconds(self, b): 
        return b * (60.0 / self.tempo)

    def quantize(self, val): 
        return round(val / self.quantize_resolution) * self.quantize_resolution

    def get_note_rect(self, note):
        x = int(self.seconds_to_beats(note.start_time) * self.pixels_per_beat - self.scroll_x_offset)
        y = int((127 - note.note_number) * self.key_height_pixels - self.scroll_y_offset)
        w = int(self.seconds_to_beats(note.duration) * self.pixels_per_beat)
        h = int(self.key_height_pixels)
        return QRect(x, y, w, h)

    def analyze_lyric_to_phoneme(self, text):
        try:
            tokens = self.tokenizer.tokenize(text)
            # Pyrightのエラーを回避するため、属性の存在を確認
            return "".join([getattr(t, 'reading', '*') if getattr(t, 'reading', '*') != "*" else getattr(t, 'surface', '') for t in tokens])
        except Exception: 
            return text

    # --- C言語エンジン連携ブリッジ ---
    def export_all_data(self, file_path="engine_input.json"):
        data = {
            "metadata": {"tempo": self.tempo, "version": "1.4.0"},
            "notes": [
                {
                    "t": n.start_time, 
                    "d": n.duration, 
                    "n": n.note_number, 
                    "p": self.analyze_lyric_to_phoneme(n.lyrics),
                    "onset": getattr(n, 'onset', 0.0),
                    "overlap": getattr(n, 'overlap', 0.0),
                    "pre_utterance": getattr(n, 'pre_utterance', 0.0),
                    "optimized": getattr(n, 'has_analysis', False)
                } for n in self.notes_list
            ],
            "parameters": self.parameters
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ Exported to {file_path}")

    def init_voice_engine(self):
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
    def update_audio_level(self, level):
        self.audio_level = level
        self.update()        

    # --- 描画ロジック ---
    def get_audio_peaks(self, file_path, num_peaks=2000):
        """WAVファイルから描画用のピークデータ（音の形）を抽出する（NumPy高速版）"""
        if not file_path or not os.path.exists(file_path):
            return []
            
        try:
            with wave.open(file_path, 'rb') as w:
                params = w.getparams()
                n_frames = params.nframes
                if n_frames == 0: 
                    return []
                
                # データを読み込んでnumpy配列化
                frames = w.readframes(n_frames)
                samples = np.frombuffer(frames, dtype=np.int16)
                
                # ステレオならモノラル化（左チャンネルのみ抽出）
                if params.nchannels == 2:
                    samples = samples[::2]
                
                # 描画解像度に合わせて分割
                if len(samples) < num_peaks:
                    num_peaks = len(samples)
                
                # 配列を分割して各区間の最大絶対値をとる
                chunks = np.array_split(samples, num_peaks)
                peaks = [np.max(np.abs(chunk)) if len(chunk) > 0 else 0 for chunk in chunks]
                
                # 0.0 ~ 1.0 に正規化
                max_val = np.max(peaks) if peaks else 1
                return [p / max_val for p in peaks]
        except Exception as e:
            print(f"Waveform Analysis Error: {e}")
            return []

    def _draw_audio_waveform(self, p):
        """タイムラインの背景としてオーディオ波形を描画する（同期修正版）"""
        # 親ウィンドウから現在のトラック情報を取得
        parent_obj = self.parent()
        if parent_obj is None or not hasattr(parent_obj, 'tracks'):
            return
            
        target_idx = getattr(parent_obj, 'current_track_idx', 0)
        tracks = getattr(parent_obj, 'tracks', [])
        
        if target_idx >= len(tracks):
            return
            
        track = tracks[target_idx]
        
        # Audioトラックでない、またはファイルがない場合は何もしない
        if track.track_type != "wave" or not track.audio_path:
            return

        # 解析データのキャッシュ（vose_peaksとして保存）
        if not hasattr(track, 'vose_peaks'):
            track.vose_peaks = self.get_audio_peaks(track.audio_path)
            
        if not track.vose_peaks:
            return

        # --- 同期計算 ---
        # 1拍あたりのピクセル数とテンポから、1秒あたりのピクセル幅を算出
        pixels_per_second = (self.tempo / 60.0) * self.pixels_per_beat
        
        # 【重要】Actionの警告対応：計算した pixels_per_second を描画間隔に反映
        # 0.05秒間隔でピークを取得していると仮定した場合の計算例：
        data_interval_px = pixels_per_second * 0.05 
        
        # 描画設定
        p.setPen(QPen(QColor(0, 255, 255, 60), 1)) # 背景に馴染む薄いシアン
        
        mid_y = self.height() / 2
        max_h = self.height() * 0.7
        
        for i, peak in enumerate(track.vose_peaks):
            # スクロールを考慮したX座標
            x = (i * data_interval_px) - self.scroll_x_offset
            
            # 画面外なら描画スキップ（負荷対策）
            if x < -data_interval_px:
                continue
            if x > self.width():
                break
            
            h = peak * max_h
            p.drawLine(int(x), int(mid_y - h/2), int(x), int(mid_y + h/2))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(18, 18, 18))

        # --- 1. 背景グリッド ---
        for i in range(200):
            x = i * self.pixels_per_beat - self.scroll_x_offset
            pen_color = QColor(58, 58, 60) if i % 4 == 0 else QColor(36, 36, 36)
            p.setPen(QPen(pen_color, 1))
            p.drawLine(int(x), 0, int(x), self.height())

        # --- 2. オーディオ波形描画（最背面） ---
        # parent()が対象の属性を持っているか安全に確認
        self._draw_audio_waveform(p)

        # --- 3. モニタリング発光 ---
        if self.audio_level > 0.001:
            cx = int(self.seconds_to_beats(self._current_playback_time) * self.pixels_per_beat - self.scroll_x_offset)
            glow_w = int(self.audio_level * 100)
            grad = QLinearGradient(cx - glow_w, 0, cx + glow_w, 0)
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
                self._draw_curve(p, data, colors[name], 40, 1)
        
        # 現在選択中のレイヤーを強調描画
        current_layer_data = self.parameters.get(self.current_param_layer, {})
        self._draw_curve(p, current_layer_data, colors[self.current_param_layer], 220, 2)

        # --- 5. ノート描画 ---
        for n in self.notes_list:
            r = self.get_note_rect(n)
            color = QColor(255, 159, 10) if n.is_selected else QColor(10, 132, 255)
            
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

    def _draw_curve(self, p, data, color, alpha, width):
        if not data:
            return
        c = QColor(color)
        c.setAlpha(alpha)
        p.setPen(QPen(c, width))
        sorted_ts = sorted(data.keys())
        prev = None
        for t in sorted_ts:
            x = int(self.seconds_to_beats(t) * self.pixels_per_beat - self.scroll_x_offset)
            y = int(self.height() - (data[t] * self.height() * 0.3) - 10)
            curr = QPoint(x, y)
            if prev:
                p.drawLine(prev, curr)
            prev = curr

    def keyPressEvent(self, event):
        ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if event.key() == Qt.Key.Key_1:
            self.change_layer("Dynamics")
        elif event.key() == Qt.Key.Key_2:
            self.change_layer("Pitch")
        elif event.key() == Qt.Key.Key_3:
            self.change_layer("Vibrato")
        elif event.key() == Qt.Key.Key_4:
            self.change_layer("Formant")
        elif ctrl and event.key() == Qt.Key.Key_S:
            self.export_all_data()
        elif ctrl and event.key() == Qt.Key.Key_C:
            self.copy_notes()
        elif ctrl and event.key() == Qt.Key.Key_V:
            self.paste_notes()
        elif ctrl and event.key() == Qt.Key.Key_D:
            self.duplicate_notes()
        elif ctrl and event.key() == Qt.Key.Key_A:
            self.select_all()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
 

    def change_layer(self, name):
        self.current_param_layer = name
        self.update()

    def mousePressEvent(self, event):
        if event is None: 
            return
        
        pos = event.position()
        self.drag_start_pos = pos
        
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self.edit_mode = "draw_parameter"
            self.add_param_pt(pos)
            return
            
        for n in reversed(self.notes_list):
            if self.get_note_rect(n).contains(pos.toPoint()):
                if not n.is_selected:
                    if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                        self.deselect_all()
                    n.is_selected = True
                self.edit_mode = "move"
                self.update()
                return
        
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.deselect_all()
        self.edit_mode = "select_box"
        self.selection_rect = QRect(pos.toPoint(), QSize(0,0))
        self.update()

    def mouseMoveEvent(self, event):
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
                    if n.is_selected:
                        n.start_time += dt
                        n.note_number = max(0, min(127, n.note_number + dn))
                self.drag_start_pos = pos
                self.update()
        elif self.edit_mode == "select_box":
            self.selection_rect = QRect(self.drag_start_pos.toPoint(), pos.toPoint()).normalized()
            for n in self.notes_list:
                n.is_selected = self.selection_rect.intersects(self.get_note_rect(n))
            self.update()

    def mouseReleaseEvent(self, event):
        if self.edit_mode == "draw_parameter":
            self.smooth_param()
        elif self.edit_mode == "move":
            for n in self.notes_list:
                if n.is_selected:
                    beats = self.seconds_to_beats(n.start_time)
                    n.start_time = self.beats_to_seconds(self.quantize(beats))
            self.notes_changed_signal.emit()
        self.edit_mode = None
        self.update()

    def add_param_pt(self, pos):
        t = self.beats_to_seconds((pos.x() + self.scroll_x_offset) / self.pixels_per_beat)
        val = max(0.0, min(1.0, (self.height() - 10 - pos.y()) / (self.height() * 0.3)))
        self.parameters[self.current_param_layer][t] = val

    def smooth_param(self):
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

    def duplicate_notes(self):
        sel = [n for n in self.notes_list if n.is_selected]
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

    def mouseDoubleClickEvent(self, event):
        for n in self.notes_list:
            if self.get_note_rect(n).contains(event.position().toPoint()):
                text, ok = QInputDialog.getText(self, "歌詞", "入力:", QLineEdit.EchoMode.Normal, n.lyrics)
                if ok:
                    n.lyrics = text
                    n.phoneme = self.analyze_lyric_to_phoneme(text)
                    tokens = self.tokenizer.tokenize(text)
                    chars = [getattr(t, 'surface', '') for t in tokens]
                    if len(chars) > 1:
                        self.split_note(n, chars)
                    self.notes_changed_signal.emit()
                    self.update()

    def split_note(self, n, chars):
        dur = n.duration / len(chars)
        if n in self.notes_list:
            self.notes_list.remove(n)
        for i, c in enumerate(chars): 
            new_n = NoteEvent(n.start_time + i*dur, dur, n.note_number, c)
            self.notes_list.append(new_n)

    def copy_notes(self):
        sel = [n for n in self.notes_list if n.is_selected]
        if not sel:
            return
        base = min(n.start_time for n in sel)
        data = [{"l": n.lyrics, "n": n.note_number, "o": n.start_time - base, "d": n.duration} for n in sel]
        QApplication.clipboard().setText(json.dumps(data))

    def paste_notes(self):
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

    def delete_selected(self): 
        self.notes_list = [n for n in self.notes_list if not n.is_selected]
        self.notes_changed_signal.emit()
        self.update()

    def select_all(self):
        for n in self.notes_list:
            n.is_selected = True
        self.update()

    def deselect_all(self):
        for n in self.notes_list:
            n.is_selected = False
        self.update()

    @Slot(int)
    def set_vertical_offset(self, val): 
        self.scroll_y_offset = val
        self.update()

    @Slot(int)
    def set_horizontal_offset(self, val): 
        self.scroll_x_offset = val
        self.update()
