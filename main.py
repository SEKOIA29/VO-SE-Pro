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
        
        # 1. 基本的なリソースパス（get_resource_pathを使用）
        dll_path = get_resource_path(os.path.join("bin", lib_name))
        
        # 2. Mac特有のフォールバック処理
        if self.os_name == "Darwin":
            if not os.path.exists(dll_path):
                # sys._MEIPASS を直接参照せず getattr で取得（型チェック対策）
                meipass = getattr(sys, '_MEIPASS', None)
                if meipass:
                    # Contents/MacOS から見た Contents/Frameworks の位置を探す
                    bundle_dir = os.path.dirname(os.path.dirname(meipass))
                    alt_path = os.path.join(bundle_dir, "Frameworks", "bin", lib_name)
                    if os.path.exists(alt_path):
                        dll_path = alt_path
                        print(f"[Info] Mac Frameworks path used: {dll_path}")

        # 3. 最終的なロード実行
        if os.path.exists(dll_path):
            try:
                # Macでは絶対パス指定が必須
                abs_dll_path = os.path.abspath(dll_path)
                
                if self.os_name == "Windows":
                    self.c_engine = ctypes.CDLL(abs_dll_path)
                else:
                    # Macでのロード。mode=10 (RTLD_GLOBAL)
                    self.c_engine = ctypes.CDLL(abs_dll_path, mode=10)
                
                # --- [追加] C関数の型定義 (安全性の向上) ---
                # process_voice(float* data, int length) と仮定
                if hasattr(self.c_engine, 'process_voice'):
                    self.c_engine.process_voice.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.c_int]
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
        """
        【読み上げ用】pyopenjtalkを使用した音韻解析
        """
        print(f"\n--- 読み上げ解析実行: '{text}' ---")
        try:
            labels = pyopenjtalk.extract_fullcontext(text)
            return labels
        except Exception as e:
            return [f"Analysis failed: {str(e)}"]

    def process_with_c(self, data_array):
        """
        【読み上げ・歌唱共通】C++製エンジンによる音声波形処理
        歌唱データなどの長い配列でも、メモリの連続性を保証して処理します。
        """
        if not self.c_engine:
            print("[Warning] C-Engine is not loaded. Skipping process.")
            return data_array
            
        try:
            # メモリが連続していることを保証 (歌唱データの音飛び防止)
            data_float = np.ascontiguousarray(data_array, dtype=np.float32)
            
            # C言語側のポインタを取得
            ptr = data_float.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            length = len(data_float)
            
            # C++エンジンの呼び出し（ピッチ補正やフォルマント処理を想定）
            self.c_engine.process_voice(ptr, length)
            
            return data_float
        except Exception as e:
            print(f"C-Process error: {e}")
            return data_array

    def analyze_musical_score(self, score_data):
        """
        【歌唱用】将来的な拡張：楽譜データの解析メソッド
        現在はスタブ（枠組み）として定義
        """
        print("--- 歌唱データ解析中 ---")
        # ここにMusicXML等の解析ロジックを統合予定
        pass

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
