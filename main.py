import sys
import os
import platform
import ctypes
import pyopenjtalk
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
from main_window import MainWindow # 1,200行のファイル

# --- あなたが書いた get_resource_path と VoSeEngine をそのまま使う ---

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

    def analyze_intonation(self, text):
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

# --- ここからがGUIを起動するための処理 ---

def main():
    print("==============================")
    print("   VO-SE Pro - GUI Launch     ")
    print("==============================")
    
    app = QApplication(sys.argv)
    
    # 1. エンジンをインスタンス化
    engine = VoSeEngine()
    
    # 2. 1,200行のGUIウィンドウを作成し、エンジンを渡す
    # (MainWindow側が engine を受け取れるように init を少し直す必要があります)
    window = MainWindow()
    window.vo_se_engine = engine # ウィンドウにエンジンを登録
    
    window.show()
    
    print("\nVO-SE GUIシステム 起動完了")
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
    if engine.c_engine:
        test_data = [1.0, 0.5, -0.5, 0.0]
        result = engine.process_with_c(test_data)
        print(f"Cエンジン処理結果: {result}")

    print("\nVO-SEシステムは正常に動作しています。")

if __name__ == "__main__":
    main()
