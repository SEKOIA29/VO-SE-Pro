from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QPaintEvent
from PySide6.QtCore import Qt, Slot, QSize, QRect

class KeyboardSidebarWidget(QWidget):
    def __init__(self, key_height_pixels, lowest_note_display, parent=None):
        super().__init__(parent)
        self.key_height_pixels = key_height_pixels
        self.lowest_note_display = lowest_note_display
        self.scroll_y_offset = 0
        self.setFixedWidth(60)

    def sizeHint(self) -> QSize:
        return QSize(60, 200)

    @Slot(int)
    def set_scroll_y_offset(self, offset_pixels: int):
        self.scroll_y_offset = offset_pixels
        self.update()

    @Slot(float)
    def set_key_height_pixels(self, height: float):
        self.key_height_pixels = height
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(event.rect())

        # まず白鍵を描画する
        for note_number in range(128):
            pitch_class = note_number % 12
            is_black_key = pitch_class in [1, 3, 6, 8, 10]
            if is_black_key: continue

            y_pos = (self.lowest_note_display + 1 - note_number) * self.key_height_pixels - self.scroll_y_offset
            key_rect = QRect(0, int(y_pos), self.width(), int(self.key_height_pixels))
            
            # 白鍵の色はデフォルトのままでOK
            painter.setBrush(QBrush(Qt.white))
            painter.setPen(QPen(Qt.gray))
            painter.drawRect(key_rect)
            
            # 音名を描画
            painter.setPen(QColor(50, 50, 50))
            note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
            octave = (note_number // 12) - 1
            name = f"{note_names[pitch_class]}{octave}"
            painter.drawText(key_rect, Qt.AlignRight | Qt.AlignVCenter, name)

        # 次に黒鍵を描画する（白鍵の上に重なるように）
        for note_number in range(128):
            pitch_class = note_number % 12
            is_black_key = pitch_class in [1, 3, 6, 8, 10]
            if not is_black_key: continue
            
            y_pos = (self.lowest_note_display + 1 - note_number) * self.key_height_pixels - self.scroll_y_offset
            key_rect = QRect(0, int(y_pos), int(self.width() * 0.65), int(self.key_height_pixels))

            # 黒鍵の色はデフォルトのままでOK
            painter.setBrush(QBrush(Qt.black))
            painter.setPen(QPen(Qt.black))
            painter.drawRect(key_rect)

