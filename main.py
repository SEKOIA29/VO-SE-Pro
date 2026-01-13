import sys
import os
import traceback
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt

# 自作モジュールのインポート（フォルダ構成に合わせて適宜調整）
# 構成例: modules/gui/main_window.py に MainWindow がある場合
try:
    from modules.gui.main_window import MainWindow
except ImportError:
    # 開発中のパス通し用（必要に応じて）
    sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))
    from gui.main_window import MainWindow

class AppInitializer:
    """アプリケーションの整合性をチェックし、不足があれば補完するクラス"""
    
    REQUIRED_DIRS = ["bin", "models", "voice_banks", "output", "temp"]
    
    @classmethod
    def run_checks(cls):
        # 1. 必要なディレクトリの生成
        for d in cls.REQUIRED_DIRS:
            if not os.path.exists(d):
                try:
                    os.makedirs(d)
                    print(f"[INFO] 作成されました: {d}")
                except Exception as e:
                    cls._show_error(f"フォルダ '{d}' の作成に失敗しました:\n{e}")
                    return False

        # 2. 必須バイナリ/モデルの存在確認
        ext = ".dll" if sys.platform == "win32" else ".so"
        engine_path = os.path.join("bin", f"libvo_se{ext}")
        model_path = os.path.join("models", "onset_detector.onnx")
        
        missing = []
        if not os.path.exists(engine_path):
            missing.append(f"音声合成エンジン: {engine_path}")
        if not os.path.exists(model_path):
            missing.append(f"AI解析モデル: {model_path}")
            
        if missing:
            msg = "以下の必須ファイルが見つかりません。配置を確認してください:\n\n" + "\n".join(missing)
            cls._show_error(msg)
            return False
            
        return True

    @staticmethod
    def _show_error(message):
        # QApplicationがまだ無い場合でもメッセージを出せるようにする
        temp_app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "VO-SE Pro 起動エラー", message)

def main():
    # 高解像度ディスプレイ(4K等)への対応設定
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    # 1. システム整合性チェック
    if not AppInitializer.run_checks():
        sys.exit(1)

    # 2. アプリケーション本体の起動
    app = QApplication(sys.argv)
    app.setApplicationName("VO-SE Pro - Next Gen Vocal Synthesizer")
    app.setApplicationVersion("1.0.0")

    try:
        # メインウィンドウの構築
        # MainWindow内部で vo_se_engine や ai_manager が初期化されます
        window = MainWindow()
        window.showMaximized() # 最大化で表示
        
        print("[INFO] VO-SE Pro が正常に起動しました。")
        sys.exit(app.exec())

    except Exception as e:
        # 実行中の予期せぬクラッシュをキャッチ
        error_msg = f"致命的なエラーが発生しました:\n{str(e)}\n\n{traceback.format_exc()}"
        print(error_msg)
        
        # ユーザーへの通知
        error_dialog = QMessageBox()
        error_dialog.setIcon(QMessageBox.Critical)
        error_dialog.setWindowTitle("Fatal Error")
        error_dialog.setText("アプリケーションが異常終了しました。")
        error_dialog.setInformativeText(error_msg)
        error_dialog.exec()
        sys.exit(1)

if __name__ == "__main__":
    main()
