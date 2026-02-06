#keyboard_sidebar_widget.py

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QPaintEvent, QFont
from PySide6.QtCore import Qt, Slot, QSize, QRect

class KeyboardSidebarWidget(QWidget):
    def __init__(self, key_height_pixels=20, parent=None):
        super().__init__(parent)
        self.key_height_pixels = key_height_pixels
        self.scroll_y_offset = 0  
        self.setFixedWidth(50) 
        
        # フォント設定
        self.label_font = QFont("Segoe UI", 7)
        self.label_font.setBold(True)

    def sizeHint(self) -> QSize:
        return QSize(50, 600)

    @Slot(int)
    def set_vertical_offset(self, offset_pixels: int):
        self.scroll_y_offset = offset_pixels
        self.update()

    @Slot(float)
    def set_key_height_pixels(self, height: float):
        self.key_height_pixels = height
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        # RenderHint を指定
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 背景
        painter.fillRect(self.rect(), QColor(30, 30, 30))

        # --- レイヤー1: 白鍵 ---
        for note_number in range(128):
            pitch_class = note_number % 12
            is_black_key = pitch_class in [1, 3, 6, 8, 10]
            
            if is_black_key:
                continue

            y_pos = (127 - note_number) * self.key_height_pixels - self.scroll_y_offset
            
            if y_pos + self.key_height_pixels < 0 or y_pos > self.height():
                continue

            rect = QRect(0, int(y_pos), self.width(), int(self.key_height_pixels))
            
            painter.setBrush(QBrush(QColor(245, 245, 245)))
            painter.setPen(QPen(QColor(180, 180, 180), 1))
            painter.drawRect(rect)
            
            if pitch_class == 0:
                octave = (note_number // 12) - 1
                painter.setFont(self.label_font)
                painter.setPen(QColor(120, 120, 120))
                text_rect = rect.adjusted(0, 0, -5, 0)
                # AlignmentFlag を使用
                align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                painter.drawText(text_rect, align, f"C{octave}")

        # --- レイヤー2: 黒鍵 ---
        black_key_width = int(self.width() * 0.65)
        for note_number in range(128):
            pitch_class = note_number % 12
            if pitch_class not in [1, 3, 6, 8, 10]:
                continue

            y_pos = (127 - note_number) * self.key_height_pixels - self.scroll_y_offset
            
            if y_pos + self.key_height_pixels < 0 or y_pos > self.height():
                continue

            black_rect = QRect(0, int(y_pos), black_key_width, int(self.key_height_pixels))
            
            painter.setBrush(QBrush(QColor(40, 40, 40)))
            # Qt.black -> Qt.GlobalColor.black
            painter.setPen(QPen(Qt.GlobalColor.black, 1))
            painter.drawRect(black_rect)
            
            # ハイライト
            painter.setPen(QPen(QColor(80, 80, 80), 1))
            painter.drawLine(1, int(y_pos)+1, black_key_width-1, int(y_pos)+1)

        # 右側の境界影
        painter.setPen(QPen(QColor(20, 20, 20, 150), 2))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
