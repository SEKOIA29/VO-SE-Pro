import os
import sys

class AppInitializer:
    @staticmethod
    def check_environment():
        """必要なファイルが揃っているかチェックし、足りなければエラーを返す"""
        # 実行環境(exe化後か)に応じたベースパスの取得
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            base_path = os.path.join(base_path, "../../")

        # チェック対象リスト
        required_files = [
            os.path.join(base_path, "bin", "libvo_se.dll" if sys.platform == "win32" else "libvo_se.dylib"),
            os.path.join(base_path, "models", "onset_detector.onnx"),
            os.path.join(base_path, "bin", "open_jtalk", "open_jtalk.exe" if sys.platform == "win32" else "open_jtalk")
        ]

        missing = []
        for f in required_files:
            if not os.path.exists(f):
                missing.append(os.path.basename(f))

        if missing:
            return False, "以下の必須ファイルが見つかりません:\n" + "\n".join(missing)
        
        return True, "All clear"
