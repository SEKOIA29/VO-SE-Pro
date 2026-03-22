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
        
        # 探索パスの設定（代表の環境に合わせて優先順位を整理）
        search_paths = [
            os.path.join(os.getcwd(), "bin", lib_name),
            os.path.join(os.path.dirname(__file__), "..", "bin", lib_name),
        ]
        
        for path in search_paths:
            if os.path.exists(path):
                try:
                    self.lib = ctypes.CDLL(path)
                    self._setup_prototypes()
                    print(f"✅ VOSE Core Engine Loaded: {path}")
                    return
                except Exception as e:
                    print(f"❌ Load Error: {e}")
        
        print("⚠️ Warning: VOSE Core DLL not found. Engine is offline.")

    def _setup_prototypes(self):
        """DLL内の関数型定義を一括管理"""
        if not self.lib:
            return

        # 1. レンダリング (旧 connector)
        self.lib.execute_render.argtypes = [
            ctypes.POINTER(CNoteEvent),
            ctypes.c_int,
            ctypes.c_char_p
        ]

        # 2. 内蔵音源の初期化・合成 (旧 bridge)
        if hasattr(self.lib, "init_official_engine"):
            self.lib.init_official_engine.restype = None
            self.lib.synthesize_by_name.argtypes = [ctypes.c_char_p, ctypes.c_float]
            self.lib.synthesize_by_name.restype = ctypes.POINTER(ctypes.c_float)

    def get_lib(self):
        """エンジン本体を取得"""
        return self.lib

# インスタンスをエクスポート
vose_manager = VoseCoreManager()
