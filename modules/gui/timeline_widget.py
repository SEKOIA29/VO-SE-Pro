#timeline_widget.py

import json
from PySide6.QtWidgets import QWidget, QApplication, QInputDialog, QLineEdit
from PySide6.QtCore import Qt, QRect, Signal, Slot, QPoint, QSize
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QMouseEvent, QPaintEvent, QKeyEvent, QFont
from .data_models import NoteEvent
from janome.tokenizer import Tokenizer

class TimelineWidget(QWidget):
    # シグナル
    notes_changed_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 200)
        self.setFocusPolicy(Qt.StrongFocus)
        
        # --- 基本データ ---
        self.notes_list: list[NoteEvent] = []
        self.tempo = 120
        self.pixels_per_beat = 40.0
        self.key_height_pixels = 20.0
        self.scroll_x_offset = 0
        self.scroll_y_offset = 0
        self._current_playback_time = 0.0
        self.quantize_resolution = 0.25 # 16分音符
        
        # --- 編集状態 ---
        self.edit_mode = None # 'move', 'select_box'
        self.target_note = None
        self.drag_start_pos = None
        self.selection_rect = QRect()
        
        # --- 外部ツール ---
        self.tokenizer = Tokenizer()

    # --- 座標変換ユーティリティ ---
    def seconds_to_beats(self, s): return s / (60.0 / self.tempo)
    def beats_to_seconds(self, b): return b * (60.0 / self.tempo)
    def quantize(self, val): return round(val / self.quantize_resolution) * self.quantize_resolution

    def get_note_rect(self, note):
        x = int(self.seconds_to_beats(note.start_time) * self.pixels_per_beat - self.scroll_x_offset)
        y = int((127 - note.note_number) * self.key_height_pixels - self.scroll_y_offset)
        w = int(self.seconds_to_beats(note.duration) * self.pixels_per_beat)
        return QRect(x, y, w, int(self.key_height_pixels))

    # --- 描画ロジック ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 1. 背景を漆黒に
        painter.fillRect(self.rect(), QColor(18, 18, 18))
        
        # 2. グリッド線
        for i in range(200):
            x = i * self.pixels_per_beat - self.scroll_x_offset
            # 1小節(4拍)ごとに線の色を濃くする
            painter.setPen(QPen(QColor(58, 58, 60) if i % 4 == 0 else QColor(36, 36, 36), 1))
            painter.drawLine(int(x), 0, int(x), self.height())

        # 3. ノートの描画
        for note in self.notes_list:
            r = self.get_note_rect(note)
            # 選択中はAppleオレンジ、通常はAppleブルー
            base_color = QColor(255, 159, 10) if note.is_selected else QColor(10, 132, 255)
            
            painter.setBrush(QBrush(base_color))
            painter.setPen(QPen(base_color.lighter(120), 1)) # 枠線を少し明るく
            painter.drawRoundedRect(r, 2, 2) # 少し角を丸く
            
            if note.lyrics:
                painter.setPen(Qt.white)
                font = QFont("Helvetica", 9)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(r.adjusted(5, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, note.lyrics)

        # 4. 選択枠
        if self.edit_mode == "select_box":
            painter.setPen(QPen(Qt.white, 1, Qt.DashLine))
            painter.setBrush(QBrush(QColor(255, 255, 255, 30)))
            painter.drawRect(self.selection_rect)

        # 5. 再生カーソル (ネオンレッド)
        cx = int(self.seconds_to_beats(self._current_playback_time) * self.pixels_per_beat - self.scroll_x_offset)
        painter.setPen(QPen(QColor(255, 45, 85), 2))
        painter.drawLine(cx, 0, cx, self.height())

    # --- マウス操作 ---
    def mousePressEvent(self, event):
        self.drag_start_pos = event.position()
        
        for note in reversed(self.notes_list):
            if self.get_note_rect(note).contains(event.position().toPoint()):
                if not note.is_selected:
                    if not (event.modifiers() & Qt.ControlModifier): self.deselect_all()
                    note.is_selected = True
                self.edit_mode = "move"
                self.update()
                return

        if not (event.modifiers() & Qt.ControlModifier): self.deselect_all()
        self.edit_mode = "select_box"
        self.selection_rect = QRect(event.position().toPoint(), QSize(0, 0))
        self.update()

    def mouseMoveEvent(self, event):
        if self.edit_mode == "move":
            dx = (event.position().x() - self.drag_start_pos.x()) / self.pixels_per_beat
            dy = (event.position().y() - self.drag_start_pos.y()) / self.key_height_pixels
            dt, dn = self.beats_to_seconds(dx), -int(round(dy))

            if abs(dt) > 0.001 or dn != 0:
                for n in self.notes_list:
                    if n.is_selected:
                        n.start_time += dt
                        n.note_number = max(0, min(127, n.note_number + dn))
                self.drag_start_pos = event.position()
                self.update()

        elif self.edit_mode == "select_box":
            self.selection_rect = QRect(self.drag_start_pos.toPoint(), event.position().toPoint()).normalized()
            for n in self.notes_list:
                n.is_selected = self.selection_rect.intersects(self.get_note_rect(n))
            self.update()

    def mouseReleaseEvent(self, event):
        if self.edit_mode == "move":
            for n in self.notes_list:
                if n.is_selected:
                    # クオンタイズ（グリッド吸着）を適用
                    n.start_time = self.beats_to_seconds(self.quantize(self.seconds_to_beats(n.start_time)))
            self.notes_changed_signal.emit()
        self.edit_mode = None
        self.update()

    # --- 複製ロジック (Ctrl+D) ---
    def duplicate_notes(self):
        sel = [n for n in self.notes_list if n.is_selected]
        if not sel: return
        
        # 選択範囲の幅を計算して、その直後に配置
        start_t = min(n.start_time for n in sel)
        end_t = max(n.start_time + n.duration for n in sel)
        offset = end_t - start_t
        
        new_clones = []
        self.deselect_all()
        for n in sel:
            clone = NoteEvent(n.start_time + offset, n.duration, n.note_number, n.lyrics)
            clone.is_selected = True
            new_clones.append(clone)
        
        self.notes_list.extend(new_clones)
        self.notes_changed_signal.emit()
        self.update()

    def mouseDoubleClickEvent(self, event):
        for n in self.notes_list:
            if self.get_note_rect(n).contains(event.position().toPoint()):
                text, ok = QInputDialog.getText(self, "歌詞入力", "歌詞を入力:", QLineEdit.Normal, n.lyrics)
                if ok:
                    chars = [t.surface for t in self.tokenizer.tokenize(text)]
                    char_list = []
                    for c in chars: char_list.extend(list(c))
                    if len(char_list) > 1: self.split_note(n, char_list)
                    else: n.lyrics = text
                    self.notes_changed_signal.emit()
                    self.update()
                return

    def split_note(self, note, char_list):
        new_dur = note.duration / len(char_list)
        start, num = note.start_time, note.note_number
        if note in self.notes_list: self.notes_list.remove(note)
        for i, c in enumerate(char_list):
            self.notes_list.append(NoteEvent(start + (i * new_dur), new_dur, num, c))

    def keyPressEvent(self, event):
        ctrl = event.modifiers() & Qt.ControlModifier
        if ctrl and event.key() == Qt.Key_C: self.copy_notes()
        elif ctrl and event.key() == Qt.Key_V: self.paste_notes()
        elif ctrl and event.key() == Qt.Key_D: self.duplicate_notes()
        elif ctrl and event.key() == Qt.Key_A: self.select_all()
        elif event.key() in (Qt.Key_Delete, Qt.Key_BackSpace): self.delete_selected()

    def copy_notes(self):
        sel = [n for n in self.notes_list if n.is_selected]
        if not sel: return
        base = min(n.start_time for n in sel)
        data = [{"l": n.lyrics, "n": n.note_number, "o": n.start_time - base, "d": n.duration} for n in sel]
        QApplication.clipboard().setText(json.dumps(data))

    def paste_notes(self):
        try:
            data = json.loads(QApplication.clipboard().text())
            self.deselect_all()
            for d in data:
                new_n = NoteEvent(self._current_playback_time + d["o"], d["d"], d["n"], d["l"])
                new_n.is_selected = True
                self.notes_list.append(new_n)
            self.notes_changed_signal.emit(); self.update()
        except: pass

    def delete_selected(self):
        self.notes_list = [n for n in self.notes_list if not n.is_selected]
        self.notes_changed_signal.emit(); self.update()

    def select_all(self):
        for n in self.notes_list: n.is_selected = True
        self.update()

    def deselect_all(self):
        for n in self.notes_list: n.is_selected = False
        self.update()

    @Slot(int)
    def set_vertical_offset(self, val): self.scroll_y_offset = val; self.update()
    @Slot(int)
    def set_horizontal_offset(self, val): self.scroll_x_offset = val; self.update()
