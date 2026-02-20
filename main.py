import sys
import os
import platform
import ctypes
import pyopenjtalk
import numpy as np
import json

# GUIライブラリをPySide6に統一
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon

from modules.gui.main_window import MainWindow

# --- [1] リソースパス解決関数 (PyInstaller対応) ---
def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
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
        except Exception:  # E722 修正: bare except を Exception に変更
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
        """
        OSに応じたライブラリ（DLL/dylib）を最適なパスからロードします。
        Mac実機での構造（App Bundle）特有のパス解決にも対応しています。
        """
        lib_name = "libvo_se.dll" if self.os_name == "Windows" else "libvo_se.dylib"
        
        # 1. 基本的なリソースパス（PyInstallerのデフォルト）
        dll_path = get_resource_path(os.path.join("bin", lib_name))
        
        # 2. Mac特有のフォールバック処理
        # .app/Contents/Frameworks/bin に配置された場合にも対応
        if self.os_name == "Darwin":
            if not os.path.exists(dll_path):
                if getattr(sys, 'frozen', False):
                    # PyInstallerでビルドされたMacアプリ内の相対構造を考慮
                    # Contents/MacOS から見た Contents/Frameworks の位置を探す
                    bundle_dir = os.path.dirname(os.path.dirname(sys._MEIPASS))
                    alt_path = os.path.join(bundle_dir, "Frameworks", "bin", lib_name)
                    if os.path.exists(alt_path):
                        dll_path = alt_path
                        print(f"[Info] Mac Frameworks path used: {dll_path}")

        # 3. 最終的なロード実行
        if os.path.exists(dll_path):
            try:
                # Macでは相対パス指定によるエラーを防ぐため絶対パスに変換
                abs_dll_path = os.path.abspath(dll_path)
                
                # Windowsでの読み込み（通常通り）
                if self.os_name == "Windows":
                    self.c_engine = ctypes.CDLL(abs_dll_path)
                # Macでの読み込み（ハンドルを確実に確保）
                else:
                    self.c_engine = ctypes.CDLL(abs_dll_path, mode=ctypes.RTLD_GLOBAL)
                
                print(f"[Success] C-Engine loaded: {abs_dll_path}")
            except Exception as e:
                print(f"[Error] Failed to load C-Engine: {e}")
                # ロード失敗時の詳細情報をコンソールに出力
                if hasattr(sys, 'stderr'):
                    import traceback
                    traceback.print_exc()
        else:
            print(f"[Warning] C-Engine file not found at: {dll_path}")

    def analyze_intonation(self, text):
        """pyopenjtalkを使用した音韻解析"""
        print(f"\n--- 解析実行: '{text}' ---")
        try:
            labels = pyopenjtalk.extract_fullcontext(text)
            return labels
        except Exception as e:
            return [f"Analysis failed: {str(e)}"]

    def process_with_c(self, data_array):
        """C++製エンジンによる音声波形処理"""
        if not self.c_engine:
            return data_array
            
        # numpy配列をC言語互換のfloatポインタに変換
        data_float = np.array(data_array, dtype=np.float32)
        ptr = data_float.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        
        try:
            # C++側の関数 process_voice(float* data, int length) を呼び出し
            self.c_engine.process_voice(ptr, len(data_float))
            return data_float
        except Exception as e:
            print(f"C-Process error: {e}")
            return data_array

# --- [4] メイン実行処理 ---
def main():
    app = QApplication(sys.argv)
    
    icon_path = get_resource_path(os.path.join("assets", "icon.png"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    lib_name = "libvo_se.dll" if platform.system() == "Windows" else "libvo_se.dylib"
    dll_path = get_resource_path(os.path.join("bin", lib_name))
    if not os.path.exists(dll_path):
        QMessageBox.warning(None, "準備不足", f"DLLが見つかりません。一部機能が制限されます。\n場所: {dll_path}")

    config_handler = ConfigHandler()
    config = config_handler.load_config()
    engine = VoSeEngine()

    window = MainWindow()
    window.vo_se_engine = engine
    window.config = config
    
    window.show()
    
    result = app.exec()
    config_handler.save_config(config)
    sys.exit(result)

if __name__ == "__main__":
    main()
