#app_main.py

import sys
import os
import ctypes
import logging

from PySide6.QtWidgets import QApplication


# --- 自作モジュールのインポート ---
# フォルダ構成に合わせてパスを調整（絶対インポートを推奨）
from modules.gui.main_window import MainWindow
from modules.audio.vo_se_engine import VO_SE_Engine
from modules.ai.ai_manager import AIManager
from modules.audio.audio_output import AudioOutput

# PyInstallerのスプラッシュスクリーン制御
try:
    import pyi_splash
except ImportError:
    pyi_splash = None

def main():
    # 1. 環境設定
    # Windows/Macでの高DPIスケーリングを有効化
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_AUTOSCREEN_SCALE_FACTOR"] = "1"
    
    # ロギング設定
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    app = QApplication(sys.argv)
    app.setApplicationName("VO-SE Pro")
    app.setOrganizationName("VO-SE Project")

    # --- 2. スタイルシート（ダークモード・モダンUI） ---
    app.setStyleSheet("""
        QMainWindow { background-color: #1e1e1e; color: #d4d4d4; }
        QWidget { font-family: 'Segoe UI', 'Hiragino Kaku Gothic ProN', sans-serif; }
        
        /* タイムライン・ピアノロール周辺 */
        QScrollArea { border: none; background-color: #252526; }
        
        /* ボタン */
        QPushButton { 
            background-color: #007acc; border: none; color: white; 
            padding: 8px 16px; border-radius: 4px; font-weight: bold;
        }
        QPushButton:hover { background-color: #0062a3; }
        QPushButton:pressed { background-color: #004d80; }
        QPushButton:disabled { background-color: #3e3e3e; color: #888888; }

        /* 入力系 */
        QLineEdit, QComboBox { 
            background-color: #3c3c3c; border: 1px solid #555555; 
            color: #eeeeee; padding: 4px; selection-background-color: #264f78;
        }
        
        /* スプリッター（境界線） */
        QSplitter::handle { background-color: #333333; }
        QSplitter::handle:horizontal { width: 4px; }
        QSplitter::handle:vertical { height: 4px; }

        /* スクロールバー */
        QScrollBar:vertical { background: #1e1e1e; width: 10px; margin: 0; }
        QScrollBar::handle:vertical { background: #424242; min-height: 20px; border-radius: 5px; }
        QScrollBar::handle:vertical:hover { background: #4f4f4f; }
    """)

    # --- 3. バックエンドの初期化（スプラッシュ表示中に実行） ---
    try:
        if pyi_splash:
            pyi_splash.update_text("音声エンジンをロード中...")
        
        # 低遅延オーディオ出力の初期化
        audio_device = AudioOutput(sample_rate=44100, block_size=256)
        
        # C言語エンジンのロード
        engine = VO_SE_Engine() 

        if pyi_splash:
            pyi_splash.update_text("AI推論モデルを最適化中...")

        # AIマネージャーの初期化
        ai = AIManager()
        ai.init_model()

        # 4. メインウィンドウの作成と依存注入(Dependency Injection)
        if pyi_splash:
            pyi_splash.update_text("UIを構築中...")
            
        window = MainWindow(engine=engine, ai=ai, audio=audio_device)

        # --- 5. セットアップ完了、表示 ---
        if pyi_splash:
            pyi_splash.close()

        window.show()
        
    except Exception as e:
        logging.critical(f"アプリケーションの起動に失敗しました: {e}")
        if pyi_splash:
            pyi_splash.close()
        return

    sys.exit(app.exec())

# Windowsのタスクバーアイコン個別認識用（PyInstallerで必須）
if platform_system := os.name == 'nt':
    try:
        myappid = 'vose.pro.editor.v1'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

if __name__ == "__main__":
    main()
