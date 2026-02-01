import sys
import os
import platform
import ctypes
import pyopenjtalk
import numpy as np
import json

# GUIライブラリをPySide6に統一しつつ、QMessageBoxなどは維持
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon

from modules.GUI.main_window import MainWindow

# --- [1] リソースパス解決関数 (PyInstaller対応) ---
def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- [2] 設定管理クラス (ConfigHandler) ---
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

# --- [3] エンジンクラス (VoSeEngine) ---
class VoSeEngine:
    def __init__(self):
        self.os_name = platform.system()
        self.c_engine = None
        self._load_c_engine()

    def _load_c_engine(self):
        # 以前のコードの命名規則「libvo_se.dll」を維持
        lib_name = "libvo_se.dll" if self.os_name == "Windows" else "libvo_se.dylib"
        dll_path = get_resource_path(os.path.join("bin", lib_name))
        
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
            # pyopenjtalkの解析処理（元のロジックを維持）
            labels = pyopenjtalk.extract_fullcontext(text)
            return labels
        except Exception as e:
            return [f"Analysis failed: {str(e)}"]

    def process_with_c(self, data_array):
        if not self.c_engine: return data_array
        data_float = np.array(data_array, dtype=np.float32)
        ptr = data_float.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        try:
            # 元の関数名 process_voice を維持
            self.c_engine.process_voice(ptr, len(data_float))
            return data_float
        except Exception as e:
            print(f"C-Process error: {e}")
            return data_array

# --- [4] メイン実行処理 ---
def main():
    app = QApplication(sys.argv)
    
    # 【追加】アイコン設定（ここだけ新機能として融合）
    icon_path = get_resource_path(os.path.join("assets", "icon.png"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # 【維持】環境チェックと警告表示
    lib_name = "libvo_se.dll" if platform.system() == "Windows" else "libvo_se.dylib"
    dll_path = get_resource_path(os.path.join("bin", lib_name))
    if not os.path.exists(dll_path):
        QMessageBox.warning(None, "準備不足", f"DLLが見つかりません。一部機能が制限されます。\n場所: {dll_path}")

    # 【維持】設定とエンジンの準備
    config_handler = ConfigHandler()
    config = config_handler.load_config()
    engine = VoSeEngine()

    # 【維持】GUIの起動とデータの注入
    window = MainWindow()
    window.vo_se_engine = engine # エンジンを注入
    window.config = config       # 設定を注入
    
    window.show()
    
    # 【維持】終了時に設定を保存
    result = app.exec()
    config_handler.save_config(config)
    sys.exit(result)

if __name__ == "__main__":
    main()
