#GUI/widgets.py

import os
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QGraphicsDropShadowEffect
from PyQt6.QtCore import pyqtSignal, Qt, QSize
from PyQt6.QtGui import QPixmap, QColor, QIcon

class VoiceCardWidget(QFrame):
    clicked = pyqtSignal(str)  # クリック時にキャラ名を通知

    def __init__(self, name, icon_path, color="#007AFF"):
        super().__init__()
        self.name = name
        self.color = color
        self.setFixedSize(120, 160)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 2026年式デザイン：Apple風のアクリル・ダークモード
        self.setObjectName("VoiceCard")
        self.update_style(selected=False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 15, 10, 15)
        layout.setSpacing(10)

        # アイコン：M3の処理能力を活かした滑らかな描画
        self.icon_label = QLabel()
        if not os.path.exists(icon_path):
            icon_path = "assets/default_icon.png" # 予備のアイコン
        
        pix = QPixmap(icon_path)
        self.icon_label.setPixmap(pix.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)

        # テキスト：名前を中央に配置
        self.name_label = QLabel(self.name)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setStyleSheet("font-weight: bold; color: white; font-size: 11px;")
        layout.addWidget(self.name_label)

    def update_style(self, selected=False):
        """選択状態に応じたスタイル更新"""
        border_color = self.color if selected else "rgba(255, 255, 255, 30)"
        bg_alpha = "40" if selected else "15"
        
        self.setStyleSheet(f"""
            #VoiceCard {{
                background-color: rgba(255, 255, 255, {bg_alpha});
                border: 2px solid {border_color};
                border-radius: 18px;
            }}
            #VoiceCard:hover {{
                background-color: rgba(255, 255, 255, 45);
                border: 2px solid {self.color};
            }}
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.name)
