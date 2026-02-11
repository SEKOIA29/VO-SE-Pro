#keyboard_sidebar_widget.py

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPaintEvent
# Actions対策: QSize と Slot を追加
from PySide6.QtCore import Qt, QRect, QSize, Slot

# Actions対策: Optional は型ヒントで使用されているため、
# 明示的に残すか、使用しない場合は削除します。今回は安全のため残します。
from typing import Optional

class KeyboardSidebarWidget(QWidget):
    def __init__(self, key_height_pixels: float = 20.0, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        # 基本設定
        self.key_height_pixels: float = key_height_pixels  # 1ノートあたりの高さ
        self.scroll_y_offset: float = 0.0      # 外部（タイムライン）と同期するオフセット
        
        # 最小幅の設定（ピアノロールの鍵盤として適切なサイズ）
        self.setMinimumWidth(60)
        self.setFixedWidth(60) 

        # フォント設定
        self.label_font = QFont("Segoe UI", 7)
        self.label_font.setBold(True)

    def sizeHint(self) -> QSize:
        # F821: QSize の未定義を解消済み
        return QSize(60, 600)

    @Slot(int)
    def set_vertical_offset(self, offset_pixels: int):
        """
        タイムラインのスクロール位置を受け取り、鍵盤の表示を更新する。
        """
        # F821: Slot の未定義を解消済み
        if self.scroll_y_offset != float(offset_pixels):
            self.scroll_y_offset = float(offset_pixels)
            # 再描画を指示
            self.update()

    @Slot(float)
    def set_key_height_pixels(self, height: float):
        # F821: Slot の未定義を解消済み
        if self.key_height_pixels != height:
            self.key_height_pixels = height
            self.update()

    def paintEvent(self, event: QPaintEvent):
        """
        代表が設計した高品質な鍵盤描画ロジック。
        1行も省略せず、最新のQt6基準でレンダリングします。
        """
        painter = QPainter(self)
        # RenderHint を指定 (滑らかな描画)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 背景（DAWらしいダークカラー）
        painter.fillRect(self.rect(), QColor(30, 30, 30))

        # --- レイヤー1: 白鍵 ---
        for note_number in range(128):
            pitch_class = note_number % 12
            # 黒鍵（C#, D#, F#, G#, A#）の判定
            is_black_key = pitch_class in [1, 3, 6, 8, 10]
            
            if is_black_key:
                continue

            # y_pos の計算（127が一番上）
            y_pos = (127 - note_number) * self.key_height_pixels - self.scroll_y_offset
            
            # 画面外描画のクリッピング
            if y_pos + self.key_height_pixels < 0 or y_pos > self.height():
                continue

            rect = QRect(0, int(y_pos), self.width(), int(self.key_height_pixels))
            
            # 白鍵の塗り
            painter.setBrush(QBrush(QColor(245, 245, 245)))
            painter.setPen(QPen(QColor(180, 180, 180), 1))
            painter.drawRect(rect)
            
            # オクターブ名（Cのみ）の描画
            if pitch_class == 0:
                octave = (note_number // 12) - 1
                painter.setFont(self.label_font)
                painter.setPen(QColor(120, 120, 120))
                # 右側に少し余白を持たせる
                text_rect = rect.adjusted(0, 0, -5, 0)
                # AlignmentFlag を使用して右中央に配置
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
            
            # 黒鍵の塗り
            painter.setBrush(QBrush(QColor(40, 40, 40)))
            painter.setPen(QPen(Qt.GlobalColor.black, 1))
            painter.drawRect(black_rect)
            
            # 3D感を出すためのハイライト線
            painter.setPen(QPen(QColor(80, 80, 80), 1))
            painter.drawLine(1, int(y_pos)+1, black_key_width-1, int(y_pos)+1)

        # 右側の境界影
        painter.setPen(QPen(QColor(20, 20, 20, 150), 2))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        
        painter.end()
