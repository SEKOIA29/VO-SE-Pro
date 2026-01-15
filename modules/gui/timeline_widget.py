#timeline_widget.py
import json, os, time, threading
from PySide6.QtWidgets import QWidget, QApplication, QInputDialog, QLineEdit
from PySide6.QtCore import Qt, QRect, Signal, Slot
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QMouseEvent, QPaintEvent, QKeyEvent, QWheelEvent, QClipboard
from data_models import NoteEvent
from janome.tokenizer import Tokenizer

class TimelineWidget(QWidget):
    # シグナル定義
    zoom_changed_signal = Signal()
    vertical_zoom_changed_signal = Signal()
    notes_changed_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 200)
        self.setFocusPolicy(Qt.StrongFocus)
        
        # --- 基本設定 ---
        self.notes_list: list[NoteEvent] = []
        self.tempo = 120
        self.pixels_per_beat = 40.0
        self.key_height_pixels = 12.0
        self.lowest_note_display = 24  # C1付近
        self.scroll_x_offset = 0
        self.scroll_y_offset = 0
        self._current_playback_time = 0.0
        self.quantize_resolution = 0.25  # 16分音符
        
        # --- 編集・ドラッグ状態 ---
        self.edit_mode = None  # 'move', 'resize', 'select_box', 'ONSET'
        self.target_note = None
        self.selection_start_pos = None
        self.selection_end_pos = None
        self.is_additive_selection_mode = False
        
        # --- 外部ツール ---
        self.tokenizer = Tokenizer()
        # 必要に応じてエンジンを初期化（wrapperがある場合）
        # self.engine = VoSeEngineWrapper() 

    # --- ヘルパー関数 ---
    def seconds_to_beats(self, seconds: float) -> float:
        return seconds / (60.0 / self.tempo)

    def beats_to_seconds(self, beats: float) -> float:
        return beats * (60.0 / self.tempo)

    def quantize_value(self, value, resolution):
        return round(value / resolution) * resolution if resolution > 0 else value

    # --- 描画ロジック ---
    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(event.rect(), QColor(30, 30, 30)) # ダーク背景

        # 1. グリッド描画
        self._draw_grid(painter)

        # 2. ノートと解析線の描画
        for note in self.notes_list:
            # 座標計算
            start_beat = self.seconds_to_beats(note.start_time)
            duration_beat = self.seconds_to_beats(note.duration)
            
            x = int(start_beat * self.pixels_per_beat - self.scroll_x_offset)
            y = int((self.lowest_note_display + 60 - note.note_number) * self.key_height_pixels - self.scroll_y_offset)
            w = int(duration_beat * self.pixels_per_beat)
            h = int(self.key_height_pixels)

            # ノート本体
            rect = QRect(x, y, w, h)
            color = QColor(0, 150, 255)
            if note.is_selected: color = QColor(255, 200, 0)
            elif note.is_playing: color = QColor(255, 100, 100)
            
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(Qt.black, 1))
            painter.drawRect(rect)
            
            if note.lyrics:
                painter.setPen(Qt.white)
                painter.drawText(rect, Qt.AlignCenter, note.lyrics)

            # --- AI解析線（Onset）の描画 ---
            if hasattr(note, 'has_analysis') and note.has_analysis:
                onset_beat = self.seconds_to_beats(note.start_time + note.onset)
                onset_x = int(onset_beat * self.pixels_per_beat - self.scroll_x_offset)
                
                # 赤い縦線（ドラッグ可能）
                painter.setPen(QPen(QColor(255, 50, 50), 2))
                painter.drawLine(onset_x, y, onset_x, y + h)

        # 3. 再生カーソル
        cursor_x = self.seconds_to_beats(self._current_playback_time) * self.pixels_per_beat - self.scroll_x_offset
        painter.setPen(QPen(QColor(255, 50, 50), 2))
        painter.drawLine(int(cursor_x), 0, int(cursor_x), self.height())

    def _draw_grid(self, painter):
        # 垂直線（拍・小節）
        painter.setPen(QPen(QColor(60, 60, 60), 1))
        for i in range(100): # 簡易的に100拍分
            x = i * self.pixels_per_beat - self.scroll_x_offset
            if i % 4 == 0: painter.setPen(QPen(QColor(100, 100, 100), 2))
            else: painter.setPen(QPen(QColor(60, 60, 60), 1))
            painter.drawLine(int(x), 0, int(x), self.height())

    # --- マウスイベント (統合版) ---
    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position()
        self.drag_start_pos = pos
        
        # Onset線の判定を優先
        for note in self.notes_list:
            if not getattr(note, 'has_analysis', False): continue
            onset_x = self.seconds_to_beats(note.start_time + note.onset) * self.pixels_per_beat - self.scroll_x_offset
            if abs(pos.x() - onset_x) < 7:
                self.target_note = note
                self.edit_mode = "ONSET"
                return

        # 通常のノート判定
        clicked_note = None
        for note in self.notes_list:
            # 矩形判定ロジック（簡略化して記述）
            if self._get_note_rect(note).contains(pos.toPoint()):
                clicked_note = note
                break
        
        if clicked_note:
            self.target_note = clicked_note
            self.edit_mode = "move"
            clicked_note.is_selected = True
        else:
            self.edit_mode = "select_box"
        self.update()

    def _get_note_rect(self, note):
        x = int(self.seconds_to_beats(note.start_time) * self.pixels_per_beat - self.scroll_x_offset)
        y = int((self.lowest_note_display + 60 - note.note_number) * self.key_height_pixels - self.scroll_y_offset)
        w = int(self.seconds_to_beats(note.duration) * self.pixels_per_beat)
        return QRect(x, y, w, int(self.key_height_pixels))

    @Slot(float)
    def set_current_time(self, time_in_seconds: float):
        self._current_playback_time = time_in_seconds
        self.update()
