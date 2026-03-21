# modules/core_manager.py
import ctypes
import os
import platform
from typing import Optional

# --- 構造体定義の一元化 ---
class CNoteEvent(ctypes.Structure):
    _fields_ = [
        ("wav_path", ctypes.c_char_p),
        ("pitch_curve", ctypes.POINTER(ctypes.c_float)),
        ("pitch_length", ctypes.c_int),
        ("preutterance", ctypes.c_double),
        ("overlap", ctypes.c_double),
        ("constant", ctypes.c_double),
        ("blank", ctypes.c_double),
    ]

class VoseCoreManager:
    """DLLロードと構造体管理を行うシングルトンクラス"""
    _instance: Optional['VoseCoreManager'] = None
    lib: Optional[ctypes.CDLL] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VoseCoreManager, cls).__new__(cls)
            cls._instance._init_engine()
        return cls._instance

    def _init_engine(self):
        system = platform.system()
        lib_name = "vose_core.dll" if system == "Windows" else "libvose_core.dylib"
        
        # 実行環境に合わせてパスを探索
        search_paths = [
            os.path.join(os.getcwd(), "bin", lib_name),
            os.path.join(os.path.dirname(__file__), "..", "bin", lib_name),
        ]
        
        for path in search_paths:
            if os.path.exists(path):
                try:
                    self.lib = ctypes.CDLL(path)
                    # 関数のプロトタイプ宣言
                    self.lib.execute_render.argtypes = [
                        ctypes.POINTER(CNoteEvent),
                        ctypes.c_int,
                        ctypes.c_char_p
                    ]
                    print(f"✅ VOSE Core Engine Loaded: {path}")
                    break
                except Exception as e:
                    print(f"❌ Load Error: {e}")
        
        if not self.lib:
            print("⚠️ Warning: VOSE Core DLL not found. Offline mode.")

# インスタンスをエクスポート
vose_manager = VoseCoreManager()
