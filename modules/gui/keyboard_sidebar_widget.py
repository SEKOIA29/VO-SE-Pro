#keyboard_sidebar_widget.py

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPaintEvent, QLinearGradient, QPixmap, QMouseEvent
from PySide6.QtCore import Qt, QRect, QSize, Slot, Signal
from typing import Optional

class KeyboardSidebarWidget(QWidget):
    # 代表、鍵盤がクリックされたことを外部（音源エンジンなど）に知らせる信号です
    note_pressed = Signal(int)
    note_released = Signal(int)

    def __init__(self, key_height_pixels: float = 20.0, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self.key_height_pixels: float = key_height_pixels
        self.scroll_y_offset: float = 0.0
        self._last_rendered_height: float = -1.0
        
        # --- 高解像度キャッシュ ---
        self._cache_pixmap: Optional[QPixmap] = None
        
        self.setMinimumWidth(70)
        self.setFixedWidth(70) 

        self.label_font = QFont("Segoe UI", 8)
        self.label_font.setBold(True)
        
        # マウスイベントの有効化
        self.setMouseTracking(True)
        self._current_pressed_note: Optional[int] = None

    def sizeHint(self) -> QSize:
        return QSize(70, 600)

    def resizeEvent(self, event):
        self._cache_pixmap = None  # キャッシュを無効化（次のpaintEventで再生成）
        super().resizeEvent(event)

    def _update_cache(self):
        """
        [最速の秘訣] 128音すべての鍵盤を一枚の画像としてメモリに焼き付けます。
        これを一度行えば、スクロール中の paintEvent 負荷はほぼ「ゼロ」になります。
        """
        total_height = int(self.key_height_pixels * 128)
        self._cache_pixmap = QPixmap(self.width(), total_height)
        self._cache_pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(self._cache_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # --- レイヤー1: 全白鍵の一括描画 ---
        for n in range(128):
            pitch_class = n % 12
            if pitch_class in [1, 3, 6, 8, 10]: continue
            
            y = (127 - n) * self.key_height_pixels
            rect = QRect(0, int(y), self.width(), int(self.key_height_pixels))
            
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0, QColor(252, 252, 252))
            grad.setColorAt(1, QColor(235, 235, 235))
            
            painter.setBrush(grad)
            painter.setPen(QPen(QColor(170, 170, 170), 1))
            painter.drawRect(rect)
            
            if pitch_class == 0:
                octave = (n // 12) - 1
                painter.setFont(self.label_font)
                painter.setPen(QColor(130, 130, 130))
                painter.drawText(rect.adjusted(0, 0, -8, 0), 
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, 
                                 f"C{octave}")

        # --- レイヤー2: 全黒鍵の一括描画 ---
        black_w = int(self.width() * 0.65)
        for n in range(128):
            pitch_class = n % 12
            if pitch_class not in [1, 3, 6, 8, 10]: continue
            
            y = (127 - n) * self.key_height_pixels
            rect = QRect(0, int(y), black_w, int(self.key_height_pixels))
            
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0, QColor(70, 70, 70))
            grad.setColorAt(1, QColor(20, 20, 20))
            
            painter.setBrush(grad)
            painter.setPen(QPen(Qt.GlobalColor.black, 1))
            painter.drawRect(rect)
            
            # ハイライトエッジ
            painter.setPen(QPen(QColor(100, 100, 100), 1))
            painter.drawLine(rect.left()+1, rect.top()+1, rect.right()-1, rect.top()+1)

        painter.end()
        self._last_rendered_height = self.key_height_pixels

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._current_pressed_note is not None:
            new_note = self._y_to_note(event.position().y())
            if new_note != self._current_pressed_note:
                self.note_released.emit(self._current_pressed_note)
                self._current_pressed_note = new_note
                self.note_pressed.emit(new_note)
                self.update()


    @Slot(int)
    def set_vertical_offset(self, offset_pixels: int):
        if self.scroll_y_offset != float(offset_pixels):
            self.scroll_y_offset = float(offset_pixels)
            self.update()

    @Slot(float)
    def set_key_height_pixels(self, height: float):
        if self.key_height_pixels != height:
            self.key_height_pixels = height
            self._update_cache() # 高さが変わった時だけキャッシュを再生成
            self.update()

    def _y_to_note(self, y: float) -> int:
        """座標からノート番号を算出する高速ロジック"""
        absolute_y = y + self.scroll_y_offset
        note = 127 - int(absolute_y / self.key_height_pixels)
        return max(0, min(127, note))

    def mousePressEvent(self, event: QMouseEvent):
        note = self._y_to_note(event.position().y())
        self._current_pressed_note = note
        self.note_pressed.emit(note)
        self.update() # 押下状態を描画するために更新

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._current_pressed_note is not None:
            self.note_released.emit(self._current_pressed_note)
            self._current_pressed_note = None
            self.update()

    def paintEvent(self, event: QPaintEvent):
        # キャッシュが未作成、または解像度が変わっていたら更新
        if self._cache_pixmap is None or self.key_height_pixels != self._last_rendered_height:
            self._update_cache()

        painter = QPainter(self)
        
        # --- [超高速描画] ---
        # メモリ上の巨大な鍵盤画像から、現在のスクロール位置に対応する部分を「一瞬」で転送
        painter.drawPixmap(0, 0, self._cache_pixmap, 
                           0, int(self.scroll_y_offset), 
                           self.width(), self.height())

        # --- レイヤー3: 押下中の鍵盤の強調（リアルタイム描画） ---
        if self._current_pressed_note is not None:
            y = (127 - self._current_pressed_note) * self.key_height_pixels - self.scroll_y_offset
            # Apple風の「押している感」を出す半透明のオーバーレイ
            painter.fillRect(QRect(0, int(y), self.width(), int(self.key_height_pixels)), 
                             QColor(0, 255, 127, 80))

        # 右端の立体的な境界線
        painter.setPen(QPen(QColor(0, 0, 0, 80), 1))
        painter.drawLine(self.width()-1, 0, self.width()-1, self.height())
        
        painter.end() 
