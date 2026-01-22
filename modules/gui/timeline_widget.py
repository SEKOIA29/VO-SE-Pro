#timeline_widget.py

import json, os, time
from PySide6.QtWidgets import QWidget, QApplication, QInputDialog, QLineEdit
from PySide6.QtCore import Qt, QRect, Signal, Slot, QPoint
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QMouseEvent, QPaintEvent, QKeyEvent
from .data_models import NoteEvent
from janome.tokenizer import Tokenizer

class TimelineWidget(QWidget):
    notes_changed_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 200)
        self.setFocusPolicy(Qt.StrongFocus)
        
        # --- 基本設定 ---
        self.notes_list: list[NoteEvent] = []
        self.tempo = 120
        self.pixels_per_beat = 40.0
        self.key_height_pixels = 20.0 # 少し大きくして操作性向上
        self.lowest_note_display = 36 # C2
        self.scroll_x_offset = 0
        self.scroll_y_offset = 0
        self._current_playback_time = 0.0
        self.quantize_resolution = 0.25 # 16分音符
        
        # --- 編集・ドラッグ状態 ---
        self.edit_mode = None 
        self.target_note = None
        self.drag_start_pos = None
        self.selection_rect = QRect()
        self.tokenizer = Tokenizer()

    # --- 座標変換・ユーティリティ ---
    def seconds_to_beats(self, s): return s / (60.0 / self.tempo)
    def beats_to_seconds(self, b): return b * (60.0 / self.tempo)
    def quantize(self, val): return round(val / self.quantize_resolution) * self.quantize_resolution

    def get_note_rect(self, note):
        x = int(self.seconds_to_beats(note.start_time) * self.pixels_per_beat - self.scroll_x_offset)
        y = int((127 - note.note_number) * self.key_height_pixels - self.scroll_y_offset)
        w = int(self.seconds_to_beats(note.duration) * self.pixels_per_beat)
        return QRect(x, y, w, int(self.key_height_pixels))

    # --- 描画 ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(35, 35, 35))
        
        # 1. グリッド
        painter.setPen(QPen(QColor(60, 60, 60), 1))
        for i in range(200):
            x = i * self.pixels_per_beat - self.scroll_x_offset
            if i % 4 == 0: painter.setPen(QPen(QColor(90, 90, 90), 2))
            else: painter.setPen(QPen(QColor(55, 55, 55), 1))
            painter.drawLine(int(x), 0, int(x), self.height())

        # 2. ノート描画
        for note in self.notes_list:
            r = self.get_note_rect(note)
            if not self.rect().intersects(r): continue # カリング
            
            color = QColor(60, 160, 255)
            if note.is_selected: color = QColor(255, 180, 0)
            
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor(20, 20, 20), 1))
            painter.drawRect(r)
            if note.lyrics:
                painter.setPen(Qt.white)
                painter.drawText(r.adjusted(5,0,0,0), Qt.AlignLeft | Qt.AlignVCenter, note.lyrics)

        # 3. 矩形選択枠
        if self.edit_mode == "select_box":
            painter.setPen(QPen(Qt.white, 1, Qt.DashLine))
            painter.setBrush(QBrush(QColor(255, 255, 255, 30)))
            painter.drawRect(self.selection_rect)

        # 4. 再生ライン
        cx = int(self.seconds_to_beats(self._current_playback_time) * self.pixels_per_beat - self.scroll_x_offset)
        painter.setPen(QPen(Qt.red, 2))
        painter.drawLine(cx, 0, cx, self.height())

    # --- マウス操作 ---
    def mousePressEvent(self, event):
        self.drag_start_pos = event.position()
        self.target_note = None
        
        # クリックしたノートを探す
        for note in reversed(self.notes_list):
            if self.get_note_rect(note).contains(event.position().toPoint()):
                self.target_note = note
                if not note.is_selected:
                    if not (event.modifiers() & Qt.ControlModifier):
                        self.deselect_all()
                    note.is_selected = True
                self.edit_mode = "move"
                self.update()
                return

        # 何もないところをクリック
        if not (event.modifiers() & Qt.ControlModifier):
            self.deselect_all()
        self.edit_mode = "select_box"
        self.selection_rect = QRect(event.position().toPoint(), QSize(0,0))
        self.update()

    def mouseMoveEvent(self, event):
        if self.edit_mode == "move" and self.target_note:
            dx = (event.position().x() - self.drag_start_pos.x()) / self.pixels_per_beat
            dy = (event.position().y() - self.drag_start_pos.y()) / self.key_height_pixels
            dt = self.beats_to_seconds(dx)
            dn = -int(round(dy))

            if abs(dt) > 0.01 or dn != 0:
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
                if n.is_selected: # 量子化
                    n.start_time = self.beats_to_seconds(self.quantize(self.seconds_to_beats(n.start_time)))
            self.notes_changed_signal.emit()
        self.edit_mode = None
        self.update()

    def mouseDoubleClickEvent(self, event):
        for n in self.notes_list:
            if self.get_note_rect(n).contains(event.position().toPoint()):
                text, ok = QInputDialog.getText(self, "歌詞入力", "歌詞:", QLineEdit.Normal, n.lyrics)
                if ok:
                    n.lyrics = text
                    self.notes_changed_signal.emit()
                    self.update()
                return

    # --- キー操作 ---
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self.notes_list = [n for n in self.notes_list if not n.is_selected]
            self.notes_changed_signal.emit()
            self.update()
        elif event.key() == Qt.Key_A and event.modifiers() & Qt.ControlModifier:
            for n in self.notes_list: n.is_selected = True
            self.update()

    def deselect_all(self):
        for n in self.notes_list: n.is_selected = False
