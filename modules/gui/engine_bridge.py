import ctypes
import os

class VoseEngine:
    def __init__(self, dll_path="../../bin/vose_core.dll"):
        # DLLの絶対パスを取得
        abs_path = os.path.abspath(dll_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"DLLが見つかりません: {abs_path}")
            
        # DLLを読み込む
        self.lib = ctypes.CDLL(abs_path)
        
        # C++関数の戻り値と引数の型を定義（型安全のため）
        self.lib.init_official_engine.restype = None
        self.lib.synthesize_by_name.argtypes = [ctypes.c_char_p, ctypes.c_float]
        self.lib.synthesize_by_name.restype = ctypes.POINTER(ctypes.c_float)

    def initialize(self):
        """内蔵音源をメモリに展開する"""
        print("🎙️ Initializing VO-SE Official Engine...")
        self.lib.init_official_engine()
        print("✅ Ready to Sing!")

    def play_voice(self, entry_name, pitch=440.0):
        """
        名前を指定して音を出す
        例: engine.play_voice("kanase_あ")
        """
        # Pythonの文字列をC言語の文字列(char*)に変換
        name_bytes = entry_name.encode('utf-8')
        
        print(f"📣 Synthesizing: {entry_name} at {pitch}Hz")
        # C++側の合成関数を呼び出す
        self.lib.synthesize_by_name(name_bytes, pitch)

# --- テスト実行用 ---
if __name__ == "__main__":
    try:
        engine = VoseEngine()
        engine.initialize()
        
        # 奏瀬（kanase）の「あ」を鳴らしてみる
        #engine.play_voice("kanase_あ")
        
    except Exception:
        pass
       # print(f"❌ Error: {e}")
