#keyboard_sidebar_widget.py

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import (QPainter, QColor, QPen, QFont, QPaintEvent,
                            QLinearGradient, QPixmap, QMouseEvent)
from PySide6.QtCore import Qt, QRect, QSize, Slot, Signal
from typing import Optional


class KeyboardSidebarWidget(QWidget):
    """
    高性能ピアノロール鍵盤サイドバー。

    最適化ポイント:
    - QPixmap キャッシュで 128 鍵を一枚絵に焼き付け、スクロール描画コストをほぼゼロ化
    - High DPI (4K / Retina) 対応: devicePixelRatioF() でキャッシュを物理解像度で生成
    - グリッサンド: ドラッグ中のノート切り替えを mouseMoveEvent で正確に処理
    """

    note_pressed = Signal(int)
    note_released = Signal(int)

    def __init__(self, key_height_pixels: float = 20.0, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.key_height_pixels: float = key_height_pixels
        self.scroll_y_offset: float = 0.0

        self._cache_pixmap: Optional[QPixmap] = None

        self.setMinimumWidth(70)
        self.setFixedWidth(70)

        self.label_font = QFont("Segoe UI", 8)
        self.label_font.setBold(True)

        self.setMouseTracking(True)
        self._current_pressed_note: Optional[int] = None

    def sizeHint(self) -> QSize:
        return QSize(70, 600)

    # ------------------------------------------------------------------ #
    #  ユーティリティ                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def is_black_key(note_number: int) -> bool:
        """MIDI ノート番号から黒鍵かどうかを判定"""
        return (note_number % 12) in (1, 3, 6, 8, 10)

    def _y_to_note(self, y: float) -> int:
        """画面 Y 座標 → MIDI ノート番号（0–127）"""
        absolute_y = y + self.scroll_y_offset
        note = 127 - int(absolute_y / self.key_height_pixels)
        return max(0, min(127, note))

    # ------------------------------------------------------------------ #
    #  キャッシュ管理                                                       #
    # ------------------------------------------------------------------ #

    def _invalidate_cache(self):
        """キャッシュを無効化（次の paintEvent で自動再生成）"""
        self._cache_pixmap = None

    def _update_cache(self):
        """
        128 鍵盤を一枚の QPixmap に描画してキャッシュする。
        High DPI 対応: devicePixelRatioF() で物理ピクセル密度に合わせて生成。
        """
        dpr = self.devicePixelRatioF()
        total_height = int(self.key_height_pixels * 128)

        pixmap = QPixmap(int(self.width() * dpr), int(total_height * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # --- レイヤー 1: 白鍵 ---
        for n in range(128):
            if self.is_black_key(n):
                continue

            y = (127 - n) * self.key_height_pixels
            rect = QRect(0, int(y), self.width(), int(self.key_height_pixels))

            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0, QColor(252, 252, 252))
            grad.setColorAt(0.9, QColor(240, 240, 240))
            grad.setColorAt(1, QColor(220, 220, 220))

            painter.setBrush(grad)
            painter.setPen(QPen(QColor(180, 180, 180), 1))
            painter.drawRect(rect)

            # C 音のオクターブ表示
            if n % 12 == 0:
                octave = (n // 12) - 1
                painter.setFont(self.label_font)
                painter.setPen(QColor(120, 120, 120))
                painter.drawText(
                    rect.adjusted(0, 0, -8, 0),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    f"C{octave}",
                )

        # --- レイヤー 2: 黒鍵 ---
        black_w = int(self.width() * 0.65)
        for n in range(128):
            if not self.is_black_key(n):
                continue

            y = (127 - n) * self.key_height_pixels
            rect = QRect(0, int(y), black_w, int(self.key_height_pixels))

            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0, QColor(65, 65, 65))
            grad.setColorAt(1, QColor(15, 15, 15))

            painter.setBrush(grad)
            painter.setPen(QPen(Qt.GlobalColor.black, 1))
            painter.drawRect(rect)

            # エッジのハイライト（立体感）
            painter.setPen(QPen(QColor(90, 90, 90, 150), 1))
            painter.drawLine(rect.left() + 1, rect.top() + 1,
                             rect.right() - 1, rect.top() + 1)

        painter.end()
        self._cache_pixmap = pixmap

    # ------------------------------------------------------------------ #
    #  イベントハンドラ                                                     #
    # ------------------------------------------------------------------ #

    def resizeEvent(self, event):
        """リサイズ時にキャッシュを無効化"""
        self._invalidate_cache()
        super().resizeEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            note = self._y_to_note(event.position().y())
            self._current_pressed_note = note
            self.note_pressed.emit(note)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        """グリッサンド: ドラッグ中にノートが変わったら release → press"""
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
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

    # ------------------------------------------------------------------ #
    #  外部スロット                                                         #
    # ------------------------------------------------------------------ #

    @Slot(int)
    def set_vertical_offset(self, offset_pixels: int):
        """タイムラインのスクロール位置と同期"""
        new_offset = float(offset_pixels)
        if self.scroll_y_offset != new_offset:
            self.scroll_y_offset = new_offset
            self.update()

    @Slot(float)
    def set_key_height_pixels(self, height: float):
        """ズーム変更時に鍵盤の高さを更新"""
        if self.key_height_pixels != height:
            self.key_height_pixels = height
            self._invalidate_cache()  # 次の paintEvent で自動再生成
            self.update()

    # ------------------------------------------------------------------ #
    #  描画                                                                #
    # ------------------------------------------------------------------ #

    def paintEvent(self, event: QPaintEvent):
        if self._cache_pixmap is None:
            self._update_cache()

        painter = QPainter(self)

        # 1. キャッシュ転送（超高速・論理ピクセルで指定、DPR は Qt が内部処理）
        painter.drawPixmap(
            0, 0,
            self._cache_pixmap,
            0, int(self.scroll_y_offset),
            self.width(), self.height(),
        )

        # 2. 押下オーバーレイ（リアルタイム描画）
        if self._current_pressed_note is not None:
            y = ((127 - self._current_pressed_note) * self.key_height_pixels
                 - self.scroll_y_offset)
            key_rect = QRect(0, int(y), self.width(), int(self.key_height_pixels))
            # 半透明のネオングリーン塗り
            painter.fillRect(key_rect, QColor(0, 255, 127, 60))
            # 左端のアクセントライン（視認性向上）
            painter.fillRect(QRect(0, int(y), 4, int(self.key_height_pixels)),
                             QColor(0, 255, 127, 200))

        # 3. 右端の境界線
        painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())

        painter.end() 
