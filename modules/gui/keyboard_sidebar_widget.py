#keyboard_sidebar_widget.py

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPaintEvent, QLinearGradient, QPixmap, QMouseEvent
from PySide6.QtCore import Qt, QRect, QSize, Slot, Signal
from typing import Optional

class KeyboardSidebarWidget(QWidget):
    """
    [VO-SE Pro: Keyboard Sidebar Widget]
    High DPI対応、オフスクリーン・レンダリング、グリッサンド演奏を統合した
    サイドバー・ウィジェットの決定版。
    """
    # 外部の音源モジュールへ通知するための信号
    note_pressed = Signal(int)
    note_released = Signal(int)

    def __init__(self, key_height_pixels: float = 20.0, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        # 基本パラメータ
        self.key_height_pixels: float = key_height_pixels
        self.scroll_y_offset: float = 0.0
        self._last_rendered_height: float = -1.0
        
        # キャッシュ（VRAM/RAM上への事前描画）
        self._cache_pixmap: Optional[QPixmap] = None
        
        # 🍎 Apple基準の固定幅（少し広げて操作性を向上）
        self.setMinimumWidth(72)
        self.setFixedWidth(72) 

        # フォント設定（視認性の高いSegoe UI / San Francisco系）
        self.label_font = QFont("Segoe UI", 8)
        self.label_font.setBold(True)
        
        self.setMouseTracking(True)
        self._current_pressed_note: Optional[int] = None

    def sizeHint(self) -> QSize:
        return QSize(72, 600)

    @staticmethod
    def is_black_key(note_number: int) -> bool:
        """MIDIノート番号が黒鍵かどうかを高速に判定"""
        return (note_number % 12) in [1, 3, 6, 8, 10]

    def resizeEvent(self, event):
        """リサイズ時にキャッシュを破棄し、次回の描画で再生成させる"""
        self._cache_pixmap = None
        super().resizeEvent(event)

    def _update_cache(self):
        """
        [最速の描画ロジック]
        128音すべての鍵盤を、デバイスの解像度（DPI）に合わせて
        巨大な一枚の画像としてメモリに焼き付けます。
        """
        # 高精細ディスプレイ（Retina/4K）のスケールを取得
        dpr = self.devicePixelRatioF()
        total_height = int(self.key_height_pixels * 128)
        
        # 解像度に合わせてピクセル数を倍増させたPixmapを生成
        self._cache_pixmap = QPixmap(int(self.width() * dpr), int(total_height * dpr))
        self._cache_pixmap.setDevicePixelRatio(dpr)
        self._cache_pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(self._cache_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # --- レイヤー1: 全白鍵の描画 ---
        for n in range(128):
            if self.is_black_key(n): continue
            
            y = (127 - n) * self.key_height_pixels
            rect = QRect(0, int(y), self.width(), int(self.key_height_pixels))
            
            # わずかなグラデーションで「触りたくなる質感」を演出
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0, QColor(255, 255, 255))
            grad.setColorAt(0.9, QColor(245, 245, 245))
            grad.setColorAt(1, QColor(225, 225, 225))
            
            painter.setBrush(grad)
            painter.setPen(QPen(QColor(180, 180, 180), 1))
            painter.drawRect(rect)
            
            # C音のラベル描画
            if n % 12 == 0:
                octave = (n // 12) - 1
                painter.setFont(self.label_font)
                painter.setPen(QColor(120, 120, 120))
                # ラベルを右端に配置
                painter.drawText(rect.adjusted(0, 0, -8, 0), 
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, 
                                 f"C{octave}")

        # --- レイヤー2: 全黒鍵の描画 ---
        black_w = int(self.width() * 0.62)
        for n in range(128):
            if not self.is_black_key(n): continue
            
            y = (127 - n) * self.key_height_pixels
            rect = QRect(0, int(y), black_w, int(self.key_height_pixels))
            
            # 黒鍵の高級感を出す深みのあるグラデーション
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0, QColor(60, 60, 60))
            grad.setColorAt(1, QColor(10, 10, 10))
            
            painter.setBrush(grad)
            painter.setPen(QPen(Qt.GlobalColor.black, 1))
            painter.drawRect(rect)
            
            # 上端に立体感を出すハイライト線を追加
            painter.setPen(QPen(QColor(90, 90, 90, 150), 1))
            painter.drawLine(rect.left() + 1, rect.top() + 1, rect.right() - 1, rect.top() + 1)

        painter.end()
        self._last_rendered_height = self.key_height_pixels

    @Slot(int)
    def set_vertical_offset(self, offset_pixels: int):
        if self.scroll_y_offset != float(offset_pixels):
            self.scroll_y_offset = float(offset_pixels)
            self.update()

    @Slot(float)
    def set_key_height_pixels(self, height: float):
        if self.key_height_pixels != height:
            self.key_height_pixels = height
            self._cache_pixmap = None # キャッシュ破棄
            self.update()

    def _y_to_note(self, y: float) -> int:
        """Y座標からノート番号への高速変換"""
        absolute_y = y + self.scroll_y_offset
        note = 127 - int(absolute_y / self.key_height_pixels)
        return max(0, min(127, note))

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:  
            note = self._y_to_note(event.position().y())
            self._current_pressed_note = note
            self.note_pressed.emit(note)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        # 左ボタンが押されている場合のみグリッサンドを処理
        if event.buttons() & Qt.MouseButton.LeftButton:
            new_note = self._y_to_note(event.position().y())
            if new_note != self._current_pressed_note:
                if self._current_pressed_note is not None:
                    self.note_released.emit(self._current_pressed_note)
                self._current_pressed_note = new_note
                self.note_pressed.emit(new_note)
                self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._current_pressed_note is not None:
            self.note_released.emit(self._current_pressed_note)
            self._current_pressed_note = None
            self.update()

    def paintEvent(self, event: QPaintEvent):
        # キャッシュの整合性チェック
        if self._cache_pixmap is None or self.key_height_pixels != self._last_rendered_height:
            self._update_cache()

        painter = QPainter(self)
        
        # 1. キャッシュされた全鍵盤を「一撃」で転送（超低負荷）
        # スクロールオフセットにDPIを掛けて転送元を調整
        dpr = self.devicePixelRatioF()
        painter.drawPixmap(0, 0, self._cache_pixmap, 
                           0, int(self.scroll_y_offset), 
                           int(self.width() * dpr), int(self.height() * dpr))

        # 2. 押下状態のネオン・ハイライト（リアルタイム描画）
        if self._current_pressed_note is not None:
            y = (127 - self._current_pressed_note) * self.key_height_pixels - self.scroll_y_offset
            
            # Apple風ネオングリーン。不透明度を調整して「発光感」を出す
            painter.fillRect(QRect(0, int(y), self.width(), int(self.key_height_pixels)), 
                             QColor(0, 255, 127, 70))
            
            # 左端に4pxのアクセントバーを描画してプロ感を演出
            painter.fillRect(QRect(0, int(y), 4, int(self.key_height_pixels)), 
                             QColor(0, 255, 127, 200))

        # 3. タイムラインとの境界線（非常に薄いシャドウ）
        painter.setPen(QPen(QColor(0, 0, 0, 50), 1))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        
        painter.end()
