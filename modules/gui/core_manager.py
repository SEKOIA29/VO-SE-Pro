# core_manager.py 
import ctypes
import os
import platform
from typing import Optional

# 構造体名を CNoteEvent に統一
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
        
        # 実行パスの探索（代表の環境に合わせる）
        base_dir = os.path.dirname(os.path.abspath(__file__))
        search_paths = [
            os.path.join(os.getcwd(), "bin", lib_name),
            os.path.join(base_dir, "..", "bin", lib_name),
            os.path.join(base_dir, "bin", lib_name),
        ]
        
        for path in search_paths:
            if os.path.exists(path):
                try:
                    self.lib = ctypes.CDLL(path)
                    self._setup_prototypes() # 型定義を別メソッドに分離
                    print(f"✅ Vose Core Loaded: {path}")
                    return
                except Exception as e:
                    print(f"❌ Load Error: {e}")
        
        print("⚠️ Warning: DLL not found. Engine is offline.")

    def _setup_prototypes(self):
        """DLL内の関数型を定義（旧bridge/connectorの内容をここに集約）"""
        if not self.lib: return

        # 1. レンダリング用 (旧 engine_connector)
        self.lib.execute_render.argtypes = [
            ctypes.POINTER(CNoteEvent),
            ctypes.c_int,
            ctypes.c_char_p
        ]

        # 2. 内蔵音源・公式エンジン用 (旧 engine_bridge)
        if hasattr(self.lib, "init_official_engine"):
            self.lib.init_official_engine.restype = None
            self.lib.synthesize_by_name.argtypes = [ctypes.c_char_p, ctypes.c_float]
            self.lib.synthesize_by_name.restype = ctypes.POINTER(ctypes.c_float)

    def get_lib(self):
        return self.lib

vose_manager = VoseCoreManager()
