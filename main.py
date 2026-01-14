import sys
import os
import platform
import ctypes
import pyopenjtalk
import numpy as np

def get_resource_path(relative_path):
    """
    実行環境（開発時 or PyInstaller実行時）に応じて正しいファイルパスを返します。
    """
    if getattr(sys, 'frozen', False):
        # PyInstallerで固められた実行ファイル内の一時フォルダ
        base_path = sys._MEIPASS
    else:
        # 通常の開発環境
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class VoSeEngine:
    def __init__(self):
        self.os_name = platform.system()
        self.c_engine = None
        self._load_c_engine()

    def _load_c_engine(self):
        """OSに応じてC言語で書かれたエンジン(DLL)をロードします"""
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
        else:
            print(f"[Info] Running on {self.os_name}. C-Engine (DLL) skip.")

    def analyze_intonation(self, text):
        """Open JTalkを使用して日本語のイントネーション（フルコンテキストラベル）を解析します"""
        print(f"\n--- 解析実行: '{text}' ---")
        try:
            # pyopenjtalkによる解析
            labels = pyopenjtalk.extract_fullcontext(text)
            return labels
        except Exception as e:
            return [f"Analysis failed: {str(e)}"]

    def process_with_c(self, data_array):
        """解析結果をCエンジン(DLL)に渡して高速処理します(Windowsのみ)"""
        if not self.c_engine:
            return data_array
        
        # 例: float配列をC言語側に渡す処理
        data_float = np.array(data_array, dtype=np.float32)
        ptr = data_float.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        
        # C側の関数 process_voice(float* buffer, int length) を呼び出す想定
        try:
            self.c_engine.process_voice(ptr, len(data_float))
            return data_float
        except AttributeError:
            print("[Error] Function 'process_voice' not found in DLL.")
            return data_array

def main():
    print("==============================")
    print("   VO-SE Pro - Main System    ")
    print("==============================")
    
    engine = VoSeEngine()
    
    # ユーザー入力のシミュレーション
    test_text = "こんにちは、音声合成テストを開始します。"
    
    # 1. イントネーション解析
    labels = engine.analyze_intonation(test_text)
    
    print(f"抽出されたラベル数: {len(labels)}")
    for i, label in enumerate(labels[:5]): # 最初の5つだけ表示
        print(f"  [{i}] {label}")
    
    # 2. Cエンジンによる処理（ダミーデータでのテスト）
    if engine.c_engine:
        test_data = [1.0, 0.5, -0.5, 0.0]
        result = engine.process_with_c(test_data)
        print(f"Cエンジン処理結果: {result}")

    print("\nVO-SEシステムは正常に動作しています。")

if __name__ == "__main__":
    main()
