#dynamics_engine.py

import ctypes
import numpy as np
import _ctypes
import platform
import os



try:
    from .audio_types import SynthesisRequest, CNoteEvent  # type: ignore
except Exception:
    class CNoteEvent(ctypes.Structure):
        _fields_ = [
            ("note_number", ctypes.c_int),
            ("start_time", ctypes.c_double),
            ("duration", ctypes.c_double),
            ("velocity", ctypes.c_int),
        ]

    class SynthesisRequest(ctypes.Structure):
        _fields_ = [
            ("notes", ctypes.POINTER(CNoteEvent)),
            ("note_count", ctypes.c_int),
            ("sample_rate", ctypes.c_int),
        ]

class DynamicsEngine:
    def __init__(self, dll_path, _model_path):
        # OSに応じたライブラリ名の自動判別
        system = platform.system()
        # GitHub Actionsのパス構造に合わせて、ファイル名だけを抽出、または補完する
        if system == "Darwin":  # Mac
            lib_name = "libvose_core.dylib"
        else:                   # Windows
            lib_name = "vose_core.dll"

        # dll_path がディレクトリを指しているかファイル指しているかにかかわらず
        # 適切なパスを構築する（ここで os を使用）
        if os.path.isdir(dll_path):
            full_path = os.path.join(dll_path, lib_name)
        else:
            full_path = dll_path

        # 1. DLLのロード
        self.lib = ctypes.CDLL(full_path) # <--- self はメソッド内で使う (Error 2)
        self._setup_ctypes()
        
        print(f"Dynamics Engine: System Initialized for {system}")

    def _setup_ctypes(self):
        """C言語関数の入出力型を定義（メモリ安全のため）"""
        self.lib.init_engine.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        self.lib.init_engine.restype = ctypes.c_int

        self.lib.request_synthesis_full.argtypes = [SynthesisRequest, ctypes.POINTER(ctypes.c_int)]
        self.lib.request_synthesis_full.restype = ctypes.POINTER(ctypes.c_float)

        self.lib.vse_free_buffer.argtypes = [ctypes.POINTER(ctypes.c_float)]
        self.lib.vse_free_buffer.restype = None

    def run_full_synthesis(self, raw_notes):
        """
        AI推論 -> C言語合成 -> メモリ解放 までを一括で行うメイン関数
        """
        # --- STEP 2: C言語用リクエストの作成 ---
        req = self._build_request(raw_notes)
        out_count = ctypes.c_int(0)

        # --- STEP 3: C言語による高速合成 ---
        audio_ptr = self.lib.request_synthesis_full(req, ctypes.byref(out_count))
        
        if not audio_ptr:
            print("Error: Synthesis failed.")
            return None

        try:
            # --- STEP 4: 安全なデータ取得 ---
            count = out_count.value
            float_array = np.ctypeslib.as_array(audio_ptr, shape=(count,))
            audio_result = float_array.copy() # M3のメモリ上に完全複製
            
            return audio_result
            
        finally:
            # --- STEP 5: 【最重要】C側のメモリを即座に解放 ---
            self.lib.vse_free_buffer(audio_ptr)

    def _build_request(self, raw_notes):
        """PythonのデータをC言語の構造体にパッキングする"""
        note_count = len(raw_notes)
        c_notes = (CNoteEvent * note_count)()

        for i, n in enumerate(raw_notes):
            c_notes[i].note_number = n['note']
            c_notes[i].start_time = n['start']
            c_notes[i].duration = n['duration']
            c_notes[i].velocity = 100
            
        req = SynthesisRequest()
        req.notes = ctypes.cast(c_notes, ctypes.POINTER(CNoteEvent))
        req.note_count = note_count
        req.sample_rate = 44100
        return req

    def unload(self):
        """DLLをメモリから完全に解除する（OS別の低層処理）"""
        if not hasattr(self, 'lib') or self.lib is None:
            return

        handle = self.lib._handle
        system = platform.system()

        try:
            if system == "Windows":
                # Windows: kernel32.dllのFreeLibraryを使用
                from _ctypes import FreeLibrary
                FreeLibrary(handle)
            else:
                # Mac / Linux: libdl.dylib(又はlibc)のdlcloseを使用
                # pythonapiを経由することで、OS標準の動的ライブラリ操作を直接叩く
                import ctypes
                libdl = ctypes.CDLL(None) # Noneを指定すると標準Cライブラリをロード
                dlclose = libdl.dlclose
                dlclose.argtypes = [ctypes.c_void_p]
                dlclose(handle)
            
            self.lib = None
            print(f"Engine: DLL Unloaded successfully on {system}.")
            
        except Exception as e:
            # 強制解放はリスクを伴うため、失敗してもクラッシュさせない
            print(f"Engine: Unload warning - {e}")
