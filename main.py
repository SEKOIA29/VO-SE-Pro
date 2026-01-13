import sys
import os

# 自作モジュールのインポート
from modules.utils.initializer import AppInitializer
from modules.utils.config_handler import ConfigHandler
from modules.utils.zip_handler import ZipHandler
from modules.gui.main_window import MainWindow
from modules.engine.wrapper import EngineWrapper
from modules.talk.talk_manager import TalkManager

from PySide6.QtWidgets import QApplication, QMessageBox

class VoseProApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        
        # 1. 起動前環境チェック
        success, message = AppInitializer.check_environment()
        if not success:
            QMessageBox.critical(None, "環境エラー", message)
            sys.exit(1)

        # 2. 設定の読み込み
        self.config_manager = ConfigHandler()
        self.config = self.config_manager.load_config()

        # 3. 各エンジンの初期化
        self.engine = EngineWrapper()
        self.talk_engine = TalkManager()

        # 4. メインウィンドウの立ち上げ
        self.window = MainWindow()
        
        # UIのイベントとバックエンドロジックの接続（コネクト）
        self.connect_signals()

    def connect_signals(self):
        """UIでの操作と実際の処理を紐付ける"""
        # ZIPドロップ時の処理をZipHandlerに橋渡し
        self.window.import_requested.connect(self.handle_zip_import)
        
        # 保存(エクスポート)時の処理
        self.window.export_requested.connect(self.handle_export)

    def handle_zip_import(self, zip_path):
        success, result = ZipHandler.extract_voice_bank(zip_path)
        if success:
            QMessageBox.information(self.window, "完了", f"音源 '{result}' を導入しました。")
            self.window.refresh_ui() # UI側のリスト表示などを更新
        else:
            QMessageBox.warning(self.window, "失敗", f"インポートエラー: {result}")

    def handle_export(self, file_path):
        # 現在のモード（歌唱 or トーク）に応じてエンジンを使い分け
        if self.window.current_mode == "SING":
            # 歌唱合成(Cエンジン)実行
            self.engine.render([], file_path) 
        else:
            # トーク(Open JTalk)実行
            text = self.window.get_talk_text()
            self.talk_engine.synthesize(text, file_path)
            
        # 最後に保存したフォルダを記憶
        self.config["last_save_dir"] = os.path.dirname(file_path)
        self.config_manager.save_config(self.config)

    def run(self):
        self.window.show()
        return self.app.exec()

if __name__ == "__main__":
    vose_app = VoseProApp()
    sys.exit(vose_app.run())
