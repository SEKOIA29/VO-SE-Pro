import sys
import os
import platform
import ctypes
import pyopenjtalk
import numpy as np
import json
from PyQt6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


from main_window import MainWindow 

# --- [1] 設定管理クラス (ConfigHandler) ---
class ConfigHandler:
    def __init__(self, config_path="temp/config.json"):
        self.config_path = config_path
        self.default_config = {
            "last_save_dir": os.path.expanduser("~"),
            "default_voice": "mei_normal",
            "volume": 0.8
        }

    def load_config(self):
        if not os.path.exists(self.config_path):
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            self.save_config(self.default_config)
            return self.default_config
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return self.default_config

    def save_config(self, config_dict):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config_dict, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Config save error: {e}")

# --- [2] あなたの元のエンジン (VoSeEngine) ---
def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class VoSeEngine:
    def __init__(self):
        self.os_name = platform.system()
        self.c_engine = None
        self._load_c_engine()

    def _load_c_engine(self):
        if self.os_name == "Windows":
            dll_path = get_resource_path(os.path.join("bin", "libvo_se.dll"))
            if os.path.exists(dll_path):
                try:
                    self.c_engine = ctypes.CDLL(dll_path)
                    print(f"[Success] C-Engine loaded: {dll_path}")
                except Exception as e:
                    print(f"[Error] Failed to load C-Engine: {e}")
            else:
                print(f"[Warning] C-Engine not found at {dll_path}")

    def analyze_intonation(self, text):
        print(f"\n--- 解析実行: '{text}' ---")
        try:
            labels = pyopenjtalk.extract_fullcontext(text)
            return labels
        except Exception as e:
            return [f"Analysis failed: {str(e)}"]

    def process_with_c(self, data_array):
        if not self.c_engine: return data_array
        data_float = np.array(data_array, dtype=np.float32)
        ptr = data_float.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        try:
            self.c_engine.process_voice(ptr, len(data_float))
            return data_float
        except:
            return data_array

# --- [3] メイン実行処理 ---
def main():
    app = QApplication(sys.argv)
    
    # 環境チェック
    dll_path = get_resource_path(os.path.join("bin", "libvo_se.dll"))
    if not os.path.exists(dll_path):
        QMessageBox.warning(None, "準備不足", f"DLLが見つかりません。一部機能が制限されます。\n場所: {dll_path}")

    # 設定とエンジンの準備
    config_handler = ConfigHandler()
    config = config_handler.load_config()
    engine = VoSeEngine()

    # GUIの起動
    # あなたのMainWindowに、読み込んだエンジンと設定を注入
    window = MainWindow()
    window.vo_se_engine = engine
    window.config = config
    
    window.show()
    
    # 終了時に設定を保存する（例として音量0.8を保存）
    result = app.exec()
    config_handler.save_config(config)
    sys.exit(result)

if __name__ == "__main__":
    main()
