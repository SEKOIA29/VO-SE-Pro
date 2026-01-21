#keyboard_sidebar_widget.py

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QPaintEvent, QFont
from PySide6.QtCore import Qt, Slot, QSize, QRect

class KeyboardSidebarWidget(QWidget):
    def __init__(self, key_height_pixels=20, parent=None):
        super().__init__(parent)
        self.key_height_pixels = key_height_pixels
        self.scroll_y_offset = 0
        self.setFixedWidth(50) # 少しスリムに
        
        # フォント設定
        self.label_font = QFont("Segoe UI", 7)
        self.label_font.setBold(True)

    def set_vertical_offset(self, offset):
        """メインウィンドウのスクロールバーから値を受け取る"""
        self.vertical_offset = offset
        self.update() # 再描画して位置をずらす

    def sizeHint(self) -> QSize:
        return QSize(50, 600)

    @Slot(int)
    def set_scroll_y_offset(self, offset_pixels: int):
        """タイムラインのスクロールと同期させるスロット"""
        self.scroll_y_offset = offset_pixels
        self.update()

    @Slot(float)
    def set_key_height_pixels(self, height: float):
        self.key_height_pixels = height
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 背景色（ダークテーマ）
        painter.fillRect(self.rect(), QColor(45, 45, 45))

        # 表示範囲の計算（カリング: 見えている範囲だけ描画する）
        # 0が一番上、127が一番下というMIDI規格に合わせるか、
        # ピアノロールに合わせて「上が高く、下が低い」にするかを整理
        # ここでは「上が高く（127）、下が低い（0）」のDAW標準に合わせます
        
        for note_number in range(128):
            pitch_class = note_number % 12
            is_black_key = pitch_class in [1, 3, 6, 8, 10]
            
            # 座標計算: ノート127がy=0付近に来るように配置
            # (127 - note_number) で上下を反転
            y_pos = (127 - note_number) * self.key_height_pixels - self.scroll_y_offset
            
            # 画面外なら描画スキップ
            if y_pos + self.key_height_pixels < 0 or y_pos > self.height():
                continue

            rect = QRect(0, int(y_pos), self.width(), int(self.key_height_pixels))

            if not is_black_key:
                # 白鍵の描画
                painter.setBrush(QBrush(QColor(240, 240, 240)))
                painter.setPen(QPen(QColor(180, 180, 180), 1))
                painter.drawRect(rect)
                
                # C音（ド）にだけオクターブを表示してスッキリさせる
                if pitch_class == 0:
                    octave = (note_number // 12) - 1
                    painter.setFont(self.label_font)
                    painter.setPen(QColor(100, 100, 100))
                    # 右端にマージンを持たせて描画
                    text_rect = rect.adjusted(0, 0, -5, 0)
                    painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, f"C{octave}")
            else:
                # 黒鍵の描画（白鍵の上に後で描画するため、ここでは位置だけ計算しても良いが
                # ループを分けるのが面倒な場合はそのまま描画）
                # 黒鍵は横幅を短く、色は少し浮かせる
                black_key_width = int(self.width() * 0.6)
                black_key_rect = QRect(0, int(y_pos), black_key_width, int(self.key_height_pixels))
                
                painter.setBrush(QBrush(QColor(30, 30, 30)))
                painter.setPen(QPen(Qt.black, 1))
                painter.drawRect(black_key_rect)
                
                # 黒鍵のハイライト（少し立体感を出す）
                painter.setPen(QPen(QColor(60, 60, 60), 1))
                painter.drawLine(0, int(y_pos), black_key_width, int(y_pos))

        # 右側の境界線
        painter.setPen(QPen(QColor(30, 30, 30), 2))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
