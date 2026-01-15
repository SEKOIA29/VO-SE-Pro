# vo_se_engine.py


import ctypes
import platform
import os
import sys
import numpy as np
import sounddevice as sd
from typing import List

# データ構造をインポート
from .data_models import NoteEvent

# --- C言語側の構造体に対応するクラス定義 ---

class CNoteEvent(ctypes.Structure):
    """C言語エンジン側とメモリレイアウトを統一した構造体"""
    _fields_ = [
        ("note_number", ctypes.c_int),
        ("start_time", ctypes.c_float),
        ("duration", ctypes.c_float),
        ("velocity", ctypes.c_int),
        ("pre_utterance", ctypes.c_float),
        ("overlap", ctypes.c_float),
        # 最大8音素まで固定長配列で渡す（ポインタ管理を簡略化）
        ("phonemes", ctypes.c_char_p * 8),
        ("phoneme_count", ctypes.c_int)
    ]

class SynthesisRequest(ctypes.Structure):
    """合成リクエスト全体を包む構造体"""
    _fields_ = [
        ("notes", ctypes.POINTER(CNoteEvent)),
        ("note_count", ctypes.c_int),
        ("sample_rate", ctypes.c_int)
    ]

class VO_SE_Engine:
    def __init__(self, sample_rate=44100):
        self.sample_rate = sample_rate
        self.current_voice_path = ""
        self.lib = self._load_library()
        self._setup_ctypes()
        self._refs = [] # C言語に渡した文字列がGCされないよう保持するリスト

    def _load_library(self):
        """OSとCPU命令セットに合わせてライブラリをロード"""
        # 2026年環境ではWindowsならAVX2/AVX512版、MacならApple Siliconネイティブを選択
        if platform.system() == "Windows":
            fname = "libvo_se.dll" # Makefileで生成される名前
        else:
            fname = "libvo_se.dylib"
        
        # パス解決（ビルド後と開発時両対応）
        base = getattr(sys, '_MEIPASS', os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
        lib_path = os.path.join(base, "bin", fname)
        
        if not os.path.exists(lib_path):
            raise FileNotFoundError(f"Engine library not found at: {lib_path}")
            
        return ctypes.CDLL(lib_path)

    def _setup_ctypes(self):
        """C関数の引数・戻り値の型を定義"""
        # 音源初期化
        self.lib.init_engine.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        self.lib.init_engine.restype = ctypes.c_int
        
        # 全体合成
        self.lib.request_synthesis_full.argtypes = [SynthesisRequest, ctypes.POINTER(ctypes.c_int)]
        self.lib.request_synthesis_full.restype = ctypes.POINTER(ctypes.c_float)
        
        # メモリ解放
        self.lib.vse_free_buffer.argtypes = [ctypes.POINTER(ctypes.c_float)]

    def set_voice(self, voice_name: str, voice_path: str):
        """使用する音源ライブラリを切り替える"""
        self.current_voice_path = voice_path
        self.lib.init_engine(voice_name.encode('utf-8'), voice_path.encode('utf-8'))

    def synthesize(self, score_data: List[NoteEvent]) -> np.ndarray:
        """NoteEventのリストから音声を合成し、numpy配列を返す"""
        count = len(score_data)
        note_array = (CNoteEvent * count)()
        self._refs = [] # 以前の参照をクリア

        for i, note in enumerate(score_data):
            # 先行発声(pre_utterance)分だけ開始を早める
            # 例: 1.0秒開始で先行発声が0.1秒なら、0.9秒から子音を鳴らし始める
            corrected_start = note.start_time - note.pre_utterance
            corrected_duration = note.duration + note.pre_utterance
            
            note_array[i].start_time = max(0.0, corrected_start)
            note_array[i].duration = corrected_duration
            note_array[i].note_number = note.note_number
            note_array[i].velocity = note.velocity
            note_array[i].pre_utterance = note.pre_utterance
            note_array[i].overlap = note.overlap
            
            # 音素リストの処理
            p_list = note.phonemes if note.phonemes else [note.lyric]
            for j, ph in enumerate(p_list[:8]):
                ph_b = ph.encode('utf-8')
                self._refs.append(ph_b) # Python側で生存期間を保証
                note_array[i].phonemes[j] = ph_b
            note_array[i].phoneme_count = min(len(p_list), 8)

        # Cエンジンへ要求
        req = SynthesisRequest(note_array, count, self.sample_rate)
        out_samples = ctypes.c_int()
        ptr = self.lib.request_synthesis_full(req, ctypes.byref(out_samples))
        
        if not ptr:
            print("Synthesis failed: Engine returned null pointer.")
            return None

        # Cのメモリをnumpy配列へコピーし、即座に解放
        raw_array = np.ctypeslib.as_array(ptr, shape=(out_samples.value,))
        audio_out = np.copy(raw_array)
        self.lib.vse_free_buffer(ptr)
        
        return audio_out

    def play(self, audio_data: np.ndarray):
        """合成結果を再生"""
        if audio_data is not None:
            sd.play(audio_data, self.sample_rate)
            sd.wait()
