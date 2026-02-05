#timeline_widget.py


import json
import os
import ctypes
from PySide6.QtWidgets import QWidget, QApplication, QInputDialog, QLineEdit
from PySide6.QtCore import Qt, QRect, Signal, Slot, QPoint, QSize
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QMouseEvent, QPaintEvent, QKeyEvent, QFont, QLinearGradient
from .data_models import NoteEvent
from janome.tokenizer import Tokenizer

class TimelineWidget(QWidget):
    notes_changed_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 200)
        self.setFocusPolicy(Qt.StrongFocus)
        self.init_voice_engine()
        
        # --- 基本データ ---
        self.notes_list: list[NoteEvent] = []
        self.tempo, self.pixels_per_beat = 120, 40.0
        self.key_height_pixels, self.scroll_x_offset, self.scroll_y_offset = 20.0, 0, 0
        self._current_playback_time = 0.0
        self.quantize_resolution = 0.25
        
        # --- 1.4.0 機能：モニタリング & 多レイヤー ---
        self.audio_level = 0.0
        self.parameters = {"Dynamics": {}, "Pitch": {}, "Vibrato": {}, "Formant": {}}
        self.current_param_layer = "Dynamics"
        
        # --- 状態管理 ---
        self.edit_mode, self.drag_start_pos, self.selection_rect = None, None, QRect()
        self.tokenizer = Tokenizer()

    # --- 座標 & 解析 ---
    def seconds_to_beats(self, s): return s / (60.0 / self.tempo)
    def beats_to_seconds(self, b): return b * (60.0 / self.tempo)
    def quantize(self, val): return round(val / self.quantize_resolution) * self.quantize_resolution
    def get_note_rect(self, note):
        x = int(self.seconds_to_beats(note.start_time) * self.pixels_per_beat - self.scroll_x_offset)
        y = int((127 - note.note_number) * self.key_height_pixels - self.scroll_y_offset)
        return QRect(x, y, int(self.seconds_to_beats(note.duration) * self.pixels_per_beat), int(self.key_height_pixels))

    def analyze_lyric_to_phoneme(self, text):
        try:
            tokens = self.tokenizer.tokenize(text)
            return "".join([t.reading if t.reading != "*" else t.surface for t in tokens])
        except: return text

    # --- C言語エンジン連携ブリッジ ---
    def export_all_data(self, file_path="engine_input.json"):
        """
        全データをC言語エンジンが読みやすい形式で保存。
        Pro Audio Performance による解析結果(onset等)もここに含めます。
        """
        data = {
            "metadata": {"tempo": self.tempo, "version": "1.4.0"},
            "notes": [
                {
                    "t": n.start_time, 
                    "d": n.duration, 
                    "n": n.note_number, 
                    "p": self.analyze_lyric_to_phoneme(n.lyrics),
                    # --- ここに解析データを追加 ---
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
        print(f"✅ Exported to {file_path} with Pro Audio parameters")

    def init_voice_engine(self):
        """音源をメモリにパッキングしてC++エンジンを初期化"""
        import wave
        import numpy as np
        
        # 例：assets内のWAVをすべて読み込んでC側に送る
        voice_db_path = "assets/voice_db/"
        for file in os.listdir(voice_db_path):
            if file.endswith(".wav"):
                phoneme = file.replace(".wav", "")
                with wave.open(voice_db_path + file, 'rb') as wr:
                    data = np.frombuffer(wr.readframes(wr.getnframes()), dtype=np.int16)
                    # C++のメモリ空間へ直接転送
                    self.vose_core.load_embedded_resource(
                        phoneme.encode('utf-8'), 
                        data.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)), 
                        len(data)
                    )
        print("内蔵音源のパッキングが完了しました。")

    @Slot(float)
    def update_audio_level(self, level):
        """C言語側からの音量通知を受けて発光演出"""
        self.audio_level = level
        self.update()        

    # --- 描画ロジック ---
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(18, 18, 18))
        
        # 背景グリッド
        for i in range(200):
            x = i * self.pixels_per_beat - self.scroll_x_offset
            p.setPen(QPen(QColor(58, 58, 60) if i % 4 == 0 else QColor(36, 36, 36), 1))
            p.drawLine(int(x), 0, int(x), self.height())

        # モニタリング発光
        if self.audio_level > 0.001:
            cx = int(self.seconds_to_beats(self._current_playback_time) * self.pixels_per_beat - self.scroll_x_offset)
            glow_w = int(self.audio_level * 100)
            grad = QLinearGradient(cx - glow_w, 0, cx + glow_w, 0)
            grad.setColorAt(0, QColor(255, 45, 85, 0))
            grad.setColorAt(0.5, QColor(255, 45, 85, int(self.audio_level * 120)))
            grad.setColorAt(1, QColor(255, 45, 85, 0))
            p.fillRect(self.rect(), QBrush(grad))

        # パラメータ表示 (ゴースト対応)
        colors = {"Dynamics": QColor(255, 45, 85), "Pitch": QColor(0, 255, 255), "Vibrato": QColor(255, 165, 0), "Formant": QColor(200, 100, 255)}
        for name, data in self.parameters.items():
            if name != self.current_param_layer: self._draw_curve(p, data, colors[name], 40, 1)
        self._draw_curve(p, self.parameters[self.current_param_layer], colors[self.current_param_layer], 220, 2)

        # ノート & 音素
        for n in self.notes_list:
            r = self.get_note_rect(n)
            
            # [蹂躙ポイント] 解析済みノートは少し光らせる、または色を変えて「プロ仕様」を演出
            base_color = QColor(255, 159, 10) if n.is_selected else QColor(10, 132, 255)
            if getattr(n, 'has_analysis', False):
                # 解析済みは少し明るい青（シアン寄り）にするなどの差別化
                color = base_color.lighter(110)
            else:
                color = base_color

            p.setBrush(QBrush(color))
            p.setPen(QPen(color.lighter(120), 1))
            p.drawRoundedRect(r, 2, 2)
            
            # 解析結果(Onset)をガイド線として表示する場合（オプション）
            if getattr(n, 'has_analysis', False):
                # 先行発音(Pre-Utterance)の位置を細い線で表示
                # これにより海外ニキが「お、正確に解析されてるな」と視認できる
                line_x = r.left() - int(self.seconds_to_beats(n.pre_utterance) * self.pixels_per_beat)
                p.setPen(QPen(QColor(255, 255, 255, 100), 1, Qt.DotLine))
                p.drawLine(line_x, r.top(), line_x, r.bottom())

        # ノート & 音素
        for n in self.notes_list:
            r = self.get_note_rect(n); color = QColor(255, 159, 10) if n.is_selected else QColor(10, 132, 255)
            p.setBrush(QBrush(color)); p.setPen(QPen(color.lighter(120), 1)); p.drawRoundedRect(r, 2, 2)
            if n.lyrics:
                p.setPen(Qt.white); p.setFont(QFont("Helvetica", 9, QFont.Bold)); p.drawText(r.adjusted(5, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, n.lyrics)
                p.setPen(QColor(200, 200, 200, 150)); p.setFont(QFont("Consolas", 7)); p.drawText(r.adjusted(2, 22, 0, 0), Qt.AlignLeft, self.analyze_lyric_to_phoneme(n.lyrics))

        if self.edit_mode == "select_box":
            p.setPen(QPen(Qt.white, 1, Qt.DashLine)); p.setBrush(QBrush(QColor(255, 255, 255, 30))); p.drawRect(self.selection_rect)

        # カーソル
        cx = int(self.seconds_to_beats(self._current_playback_time) * self.pixels_per_beat - self.scroll_x_offset)
        p.setPen(QPen(QColor(255, 45, 85), 2)); p.drawLine(cx, 0, cx, self.height())

    def _draw_curve(self, p, data, color, alpha, width):
        if not data: return
        c = QColor(color); c.setAlpha(alpha); p.setPen(QPen(c, width))
        sorted_ts = sorted(data.keys()); prev = None
        for t in sorted_ts:
            curr = QPoint(int(self.seconds_to_beats(t)*self.pixels_per_beat - self.scroll_x_offset), int(self.height()-(data[t]*self.height()*0.3)-10))
            if prev: p.drawLine(prev, curr)
            prev = curr

    # --- インタラクション (1〜4キー切替 & Ctrl+S エクスポート) ---
    def keyPressEvent(self, event):
        ctrl = event.modifiers() & Qt.ControlModifier
        if event.key() == Qt.Key_1:
            self.change_layer("Dynamics")
        elif event.key() == Qt.Key_2:
            self.change_layer("Pitch")
        elif event.key() == Qt.Key_3: self.change_layer("Vibrato")
        elif event.key() == Qt.Key_4: self.change_layer("Formant")
        elif ctrl and event.key() == Qt.Key_S: self.export_all_data() # Ctrl+SでC向けに出力
        elif ctrl and event.key() == Qt.Key_C: self.copy_notes()
        elif ctrl and event.key() == Qt.Key_V: self.paste_notes()
        elif ctrl and event.key() == Qt.Key_D: self.duplicate_notes()
        elif ctrl and event.key() == Qt.Key_A: self.select_all()
        elif event.key() in (Qt.Key_Delete, Qt.Key_BackSpace): self.delete_selected()

    def change_layer(self, name): self.current_param_layer = name; self.update()

    # --- マウス操作 (描き込み & スムージング) ---
    def mousePressEvent(self, event):
        self.drag_start_pos = event.position()
        if event.modifiers() & Qt.AltModifier:
            self.edit_mode = "draw_parameter"
            self.add_param_pt(event.position())
            return
        for n in reversed(self.notes_list):
            if self.get_note_rect(n).contains(event.position().toPoint()):
                if not n.is_selected:
                    if not (event.modifiers() & Qt.ControlModifier): self.deselect_all()
                    n.is_selected = True
                self.edit_mode = "move"; self.update(); return
        if not (event.modifiers() & Qt.ControlModifier): self.deselect_all()
        self.edit_mode = "select_box"; self.selection_rect = QRect(event.position().toPoint(), QSize(0,0)); self.update()

    def mouseMoveEvent(self, event):
        if self.edit_mode == "draw_parameter": self.add_param_pt(event.position()); self.update()
        elif self.edit_mode == "move":
            dx, dy = (event.position().x()-self.drag_start_pos.x())/self.pixels_per_beat, (event.position().y()-self.drag_start_pos.y())/self.key_height_pixels
            dt, dn = self.beats_to_seconds(dx), -int(round(dy))
            if abs(dt) > 0.001 or dn != 0:
                for n in self.notes_list:
                    if n.is_selected:
                        n.start_time += dt
                        n.note_number = max(0, min(127, n.note_number + dn))
                self.drag_start_pos = event.position(); self.update()
        elif self.edit_mode == "select_box":
            self.selection_rect = QRect(self.drag_start_pos.toPoint(), event.position().toPoint()).normalized()
            for n in self.notes_list: n.is_selected = self.selection_rect.intersects(self.get_note_rect(n))
            self.update()

    def mouseReleaseEvent(self, event):
        if self.edit_mode == "draw_parameter": self.smooth_param()
        elif self.edit_mode == "move":
            for n in self.notes_list:
                if n.is_selected: n.start_time = self.beats_to_seconds(self.quantize(self.seconds_to_beats(n.start_time)))
            self.notes_changed_signal.emit()
        self.edit_mode = None; self.update()

    def add_param_pt(self, pos):
        t = self.beats_to_seconds((pos.x()+self.scroll_x_offset)/self.pixels_per_beat)
        val = max(0.0, min(1.0, (self.height()-10-pos.y())/(self.height()*0.3)))
        self.parameters[self.current_param_layer][t] = val

    def smooth_param(self):
        data = self.parameters[self.current_param_layer]
        if len(data) < 5:
            return
        sorted_ts = sorted(data.keys())
        new_data = {}
        for i, t in enumerate(sorted_ts):
            subset = [data[sorted_ts[j]] for j in range(max(0, i-2), min(len(sorted_ts), i+3))]
            new_data[t] = sum(subset)/len(subset)
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
                text, ok = QInputDialog.getText(self, "歌詞", "入力:", QLineEdit.Normal, n.lyrics)
                if ok:
                    # 入力した瞬間に解析して、読み(phoneme)を保存しておく
                    n.lyrics = text
                    n.phoneme = self.analyze_lyric_to_phoneme(text)
                    
                    # 1文字ずつ分割するロジック
                    chars = [t.surface for t in self.tokenizer.tokenize(text)]
                    if len(chars) > 1:
                        self.split_note(n, chars)
                    
                    self.notes_changed_signal.emit()
                    self.update()

    def split_note(self, n, chars):
        dur = n.duration / len(chars)
        if n in self.notes_list:
            self.notes_list.remove(n)
        for i, c in enumerate(chars): 
            self.notes_list.append(NoteEvent(n.start_time + i*dur, dur, n.note_number, c))

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
        except (json.JSONDecodeError, KeyError):
            # クリップボードが不正な形式の場合は何もしない
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
        self.update())
