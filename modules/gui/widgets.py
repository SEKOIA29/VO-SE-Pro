#GUI/widgets.py

import os
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QPixmap

class VoiceCardWidget(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, name, icon_path, color="#007AFF"):
        super().__init__()
        self.name = name
        self.color = color
        self._selected = False # 選択状態を内部で保持
        self.setFixedSize(120, 160)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("VoiceCard")
        
        # レイアウト・UI構築（提供されたコードを継承）
        layout = QVBoxLayout(self)
        self.icon_label = QLabel()
        pix = QPixmap(icon_path if os.path.exists(icon_path) else "assets/default_icon.png")
        self.icon_label.setPixmap(pix.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.name_label = QLabel(self.name)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setStyleSheet("font-weight: bold; color: white; font-size: 11px;")
        
        layout.addWidget(self.icon_label)
        layout.addWidget(self.name_label)
        
        self.update_style(False)

    def set_selected(self, state: bool):
        """外部から選択状態を切り替えるメソッド"""
        self._selected = state
        self.update_style(selected=state)

    def update_style(self, selected=False):
        # 2026年式：ネオンボーダーとブラー風の背景
        border_color = self.color if selected else "rgba(255, 255, 255, 30)"
        bg_alpha = "60" if selected else "15"
        glow = f"border: 2px solid {border_color};" if selected else f"border: 1px solid {border_color};"
        
        self.setStyleSheet(f"""
            #VoiceCard {{
                background-color: rgba(255, 255, 255, {bg_alpha});
                {glow}
                border-radius: 18px;
            }}
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.name)
