import ctypes
import numpy as np
import _ctypes
import platform
# F401 修正: 使っていない CPitchEvent を削除
from audio_types import SynthesisRequest, CNoteEvent 

class DynamicsEngine:
    def __init__(self, dll_path, _model_path): # 未使用引数に _ を付与
        # 1. DLLのロード
        self.lib = ctypes.CDLL(dll_path)
        self._setup_ctypes()
        
        # 2. AIモデルのロード (onnxruntime等を想定)
        # 今後M3のNeural Engineを活用する場合はここに初期化を書く
        print("Dynamics Engine: System Initialized.")

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
        """DLLをメモリから完全に解除する"""
        handle = self.lib._handle
        if platform.system() == "Windows":
            _ctypes.FreeLibrary(handle)
        else:
            _ctypes.dlclose(handle)
        print("Engine: DLL Unloaded.")
