import ctypes
import numpy as np
import os
import _ctypes
import platform
from audio_types import SynthesisRequest, CNoteEvent, CPitchEvent # 前に定義した構造体

class DynamicsEngine:
    def __init__(self, dll_path, model_path):
        # 1. DLLのロード
        self.lib = ctypes.CDLL(dll_path)
        self._setup_ctypes()
        
        # 2. AIモデルのロード (onnxruntime等を想定)
        # self.ai_model = self._load_ai_model(model_path)
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
        # --- STEP 1: AIによる歌唱予測 ---
        # ここでAIが「音素の長さ」や「ピッチの揺れ」を計算したと仮定
        # durations = self.ai_model.predict_duration(raw_notes)
        # pitches = self.ai_model.predict_pitch(raw_notes)
        
        # --- STEP 2: C言語用リクエストの作成 ---
        req = self._build_request(raw_notes)
        out_count = ctypes.c_int(0)

        # --- STEP 3: C言語による高速合成 ---
        # C側で malloc が発生する
        audio_ptr = self.lib.request_synthesis_full(req, ctypes.byref(out_count))
        
        if not audio_ptr:
            print("Error: Synthesis failed.")
            return None

        try:
            # --- STEP 4: 安全なデータ取得 ---
            # ポインタが指す先のデータを、Pythonが安全に扱える numpy 配列にコピー
            count = out_count.value
            float_array = np.ctypeslib.as_array(audio_ptr, shape=(count,))
            audio_result = float_array.copy() # ここで完全な複製を作る
            
            return audio_result
            
        finally:
            # --- STEP 5: 【最重要】C側のメモリを即座に解放 ---
            self.lib.vse_free_buffer(audio_ptr)
            # print("Memory Cleaned: C-buffer released.")

    def _build_request(self, raw_notes):
        """PythonのデータをC言語の構造体にパッキングする"""
        note_count = len(raw_notes)
        c_notes = (CNoteEvent * note_count)()

        for i, n in enumerate(raw_notes):
            c_notes[i].note_number = n['note']
            c_notes[i].start_time = n['start']
            c_notes[i].duration = n['duration']
            c_notes[i].velocity = 100
            # 音素パス等のコピー (ctypes用の文字列変換が必要)
            # c_notes[i].lyrics = n['lyric'].encode('utf-8')
            
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
