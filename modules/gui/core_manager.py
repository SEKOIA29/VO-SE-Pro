import ctypes
import os
import platform
from typing import Optional

from modules.ffi import CNoteEvent, validate_note_event_layout


class VoseCoreManager:
    """DLLロードと C 関数シグネチャ管理を行うシングルトン。"""

    _instance: Optional["VoseCoreManager"] = None
    lib: Optional[ctypes.CDLL] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VoseCoreManager, cls).__new__(cls)
            cls._instance._initialized = False
            cls._instance._disabled_reason = None
        return cls._instance

    def _candidate_paths(self) -> list[str]:
        system = platform.system()
        lib_name = "vose_core.dll" if system == "Windows" else "libvose_core.dylib"

        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        return [
            os.path.join(repo_root, "bin", lib_name),
            os.path.join(os.path.dirname(__file__), "..", "bin", lib_name),
            os.path.join(os.getcwd(), "bin", lib_name),
        ]

    def _init_engine(self):
                if self._initialized:
            return

        disable_native = os.getenv("VOSE_DISABLE_NATIVE_CORE", "").lower() in {"1", "true", "yes", "on"}
        if disable_native:
            self._disabled_reason = "VOSE_DISABLE_NATIVE_CORE is enabled"
            self._initialized = True
            self.lib = None
            print(f"⚠️ VOSE Core disabled: {self._disabled_reason}")
            return
        for path in self._candidate_paths():
            if not os.path.exists(path):
                continue

            try:
                self.lib = ctypes.CDLL(path)
                self._setup_prototypes()
                print(f"[OK] VOSE Core Engine Loaded: {path}")
                self._initialized = True
                return
            except Exception as e:
                print(f"[Error] Load Error: {path} ({e})")

        print("[Warning] VOSE Core DLL not found. Engine is offline.")
        self.lib = None
        self._initialized = True

    def _setup_prototypes(self) -> None:
        if not self.lib:
            return

        validate_note_event_layout()

        self.lib.execute_render.argtypes = [
            ctypes.POINTER(CNoteEvent),
            ctypes.c_int,
            ctypes.c_char_p,
        ]
        self.lib.execute_render.restype = None

        if hasattr(self.lib, "init_official_engine"):
            self.lib.init_official_engine.argtypes = []
            self.lib.init_official_engine.restype = None

        if hasattr(self.lib, "synthesize_by_name"):
            self.lib.synthesize_by_name.argtypes = [ctypes.c_char_p, ctypes.c_float]
            self.lib.synthesize_by_name.restype = ctypes.POINTER(ctypes.c_float)

    def get_lib(self) -> Optional[ctypes.CDLL]:
        if not self._initialized:
            self._init_engine()
        return self.lib


vose_manager = VoseCoreManager()

__all__ = ["VoseCoreManager", "vose_manager", "CNoteEvent"]
