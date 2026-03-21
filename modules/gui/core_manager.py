# core_manager.py
import ctypes
import os
import platform
from typing import Optional

# 構造体の定義をここに集約（各ファイルでの重複定義を排除）
class CNoteEvent(ctypes.Structure):
    _fields_ = [
        ("wav_path", ctypes.c_char_p),
        ("pitch_curve", ctypes.POINTER(ctypes.c_float)),
        ("pitch_length", ctypes.c_int),
        ("preutterance", ctypes.c_double),
        ("overlap", ctypes.c_double),
        # 代表の C++ 側の構造体定義に合わせて適宜追加
    ]

class VoseCoreManager:
    _instance: Optional['VoseCoreManager'] = None
    lib: Optional[ctypes.CDLL] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VoseCoreManager, cls).__new__(cls)
            cls._instance._initialize_lib()
        return cls._instance

    def _initialize_lib(self):
        # OSに合わせたライブラリ名の判定
        system = platform.system()
        lib_name = "vose_core.dll" if system == "Windows" else "libvose_core.dylib"
        
        # dllの場所を特定（プロジェクトルートのbinフォルダを想定）
        base_path = os.path.dirname(os.path.abspath(__file__))
        dll_path = os.path.join(base_path, "..", "..", "bin", lib_name)
        
        if not os.path.exists(dll_path):
            print(f"[Warning] DLL not found at: {dll_path}")
            return

        try:
            self.lib = ctypes.CDLL(dll_path)
            # 関数の引数と戻り値を定義（型安全の徹底）
            self.lib.execute_render.argtypes = [
                ctypes.POINTER(CNoteEvent),
                ctypes.c_int,
                ctypes.c_char_p
            ]
            print(f"✅ Vose Core Engine Loaded Successfully ({system})")
        except Exception as e:
            print(f"❌ Failed to load DLL: {e}")

    def get_lib(self):
        return self.lib

# シングルトンインスタンスをエクスポート
vose_core_manager = VoseCoreManager()
