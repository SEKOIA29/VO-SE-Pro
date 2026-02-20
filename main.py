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
        型チェックエラー（_MEIPASS）を回避し、Mac実機構造に対応した完全版です。
        """
        lib_name = "libvo_se.dll" if self.os_name == "Windows" else "libvo_se.dylib"
        
        # 1. 基本的なリソースパス
        dll_path = get_resource_path(os.path.join("bin", lib_name))
        
        # 2. Mac特有のフォールバック処理
        if self.os_name == "Darwin":
            if not os.path.exists(dll_path):
                meipass = getattr(sys, '_MEIPASS', None)
                if meipass:
                    bundle_dir = os.path.dirname(os.path.dirname(meipass))
                    alt_path = os.path.join(bundle_dir, "Frameworks", "bin", lib_name)
                    if os.path.exists(alt_path):
                        dll_path = alt_path
                        print(f"[Info] Mac Frameworks path used: {dll_path}")

        # 3. 最終的なロード実行
        if os.path.exists(dll_path):
            try:
                abs_dll_path = os.path.abspath(dll_path)
                
                if self.os_name == "Windows":
                    self.c_engine = ctypes.CDLL(abs_dll_path)
                else:
                    self.c_engine = ctypes.CDLL(abs_dll_path, mode=10) # RTLD_GLOBAL
                
                # --- C関数の型定義 (歌唱・読み上げの両方に対応) ---
                if hasattr(self.c_engine, 'process_voice'):
                    # process_voice(float* wav_data, int length, float* f0_data) 
                    # 歌唱用にピッチ配列(f0)も渡せるように定義を拡張
                    self.c_engine.process_voice.argtypes = [
                        ctypes.POINTER(ctypes.c_float), 
                        ctypes.c_int,
                        ctypes.POINTER(ctypes.c_float)
                    ]
                    self.c_engine.process_voice.restype = None
                
                print(f"[Success] C-Engine loaded: {abs_dll_path}")
            except Exception as e:
                print(f"[Error] Failed to load C-Engine: {e}")
                if hasattr(sys, 'stderr'):
                    import traceback
                    traceback.print_exc()
        else:
            print(f"[Warning] C-Engine file not found at: {dll_path}")

    def analyze_intonation(self, text):
        """【読み上げ用】音韻解析"""
        print(f"\n--- 読み上げ解析実行: '{text}' ---")
        try:
            labels = pyopenjtalk.extract_fullcontext(text)
            return labels
        except Exception as e:
            return [f"Analysis failed: {str(e)}"]

    def analyze_singing_pitch(self, notes):
        """
        【歌唱用】ノート情報（音符）からピッチ（F0）配列を生成します。
        notes: [{'pitch': 60, 'duration': 1.0}, ...] のようなリストを想定
        """
        print("--- 歌唱ピッチ解析実行 ---")
        # サンプリングレートやフレーム数に基づいたピッチカーブの生成ロジック
        # ここで生成した配列を process_with_c に渡します
        f0_curve = np.full(1000, 440.0, dtype=np.float32) # テスト用の固定ピッチ
        return f0_curve

    def process_with_c(self, data_array, f0_array=None):
        """
        【共通処理】波形データとピッチデータをC++エンジンに送り込みます。
        """
        if not self.c_engine:
            return data_array
            
        try:
            # 波形データの準備
            wav_float = np.ascontiguousarray(data_array, dtype=np.float32)
            wav_ptr = wav_float.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            length = len(wav_float)

            # ピッチデータ（F0）の準備（歌唱モード時のみ使用）
            f0_ptr = None
            if f0_array is not None:
                f0_float = np.ascontiguousarray(f0_array, dtype=np.float32)
                f0_ptr = f0_float.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            
            # C++エンジンの呼び出し
            # 第3引数にピッチ情報を渡すことで、歌声の高さが制御されます
            self.c_engine.process_voice(wav_ptr, length, f0_ptr)
            
            return wav_float
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
