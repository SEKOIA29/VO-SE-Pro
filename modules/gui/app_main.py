#app_main.py

import sys
import os
import ctypes
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

# PyInstallerのスプラッシュスクリーン制御
try:
    import pyi_splash
except ImportError:
    pyi_splash = None

# 自作モジュールのインポート
from GUI.main_window import MainWindow
from engine.vo_se_engine import VO_SE_Engine
from engine.ai_manager import AIManager

def main():
    # 1. 高DPI対応（GUIを表示する前に必須）
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    
    app = QApplication(sys.argv)

    # --- 2. スタイルシートの一括適用 ---
    app.setStyleSheet("""
        QMainWindow { background-color: #2e2e2e; color: #eeeeee; }
        QPushButton { background-color: #007acc; border: none; color: white; padding: 6px 12px; border-radius: 4px; }
        QPushButton:hover { background-color: #005f99; }
        QLabel { color: #eeeeee; }
        QLineEdit, QComboBox { background-color: #3e3e3e; border: 1px solid #555555; color: #eeeeee; padding: 4px; }
        QScrollBar:vertical { background: #333333; width: 12px; }
        QScrollBar::handle:vertical { background: #007acc; min-height: 20px; }
        QSplitter::handle { background-color: #555; }
    """)

    # --- 3. アプリの初期化（スプラッシュ表示中に実行） ---
    if pyi_splash:
        pyi_splash.update_text("エンジンを初期化中...")

    # C言語エンジンのロード
    engine = VO_SE_Engine() 

    if pyi_splash:
        pyi_splash.update_text("AIモデルを準備中...")

    # AIマネージャーの初期化
    ai = AIManager()
    ai.init_model()

    # メインウィンドウの作成
    window = MainWindow(engine=engine, ai=ai)

    # --- 4. セットアップ完了、表示 ---
    if pyi_splash:
        pyi_splash.close()

    window.show()
    sys.exit(app.exec())

# Windowsのタスクバーアイコン個別認識用
if os.name == 'nt':
    try:
        myappid = 'mycompany.vo-se.pro.1.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception as e:
        print(f"Windows AppID Setting Error: {e}")

if __name__ == "__main__":
    main()
