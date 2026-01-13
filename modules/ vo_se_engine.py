# vo_se_engine.py

from .ctypes_structures import NoteStructure
import ctypes
import platform
import os
import sys
import numpy as np
import sounddevice as sd

import ctypes

# C言語側の構造体に対応するクラス
class NoteStructure(ctypes.Structure):
    _fields_ = [
        ("pitch_hz", ctypes.c_float),
        ("start_sec", ctypes.c_float),
        ("duration_sec", ctypes.c_float),
        ("pre_utterance", ctypes.c_float),
        ("overlap", ctypes.c_float),
        ("lyric_path", ctypes.c_char_p) # WAVファイルのフルパス
    ]

# 複数ノートを一括で渡すための定義
def export_wav_bridge(lib, notes, output_path):
    # PythonのNoteEventリストをCの構造体配列に変換
    note_array_type = NoteStructure * len(notes)
    note_array = note_array_type()
    
    for i, n in enumerate(notes):
        note_array[i].pitch_hz = 440.0 * (2.0 ** ((n.note_number - 69) / 12.0))
        note_array[i].start_sec = n.start_time
        note_array[i].duration_sec = n.duration
        note_array[i].pre_utterance = n.pre_utterance
        note_array[i].lyric_path = n.wav_path.encode('utf-8')

    # C言語の関数を呼び出し
    lib.execute_render(note_array, len(notes), output_path.encode('utf-8'))


# --- C言語とやり取りするための構造体定義 ---
class CNoteEvent(ctypes.Structure):
    _fields_ = [
        ("note_number", ctypes.c_int),
        ("start_time", ctypes.c_float),
        ("duration", ctypes.c_float),
        ("velocity", ctypes.c_int),
        ("phonemes", ctypes.c_char_p * 8), # 最大8音素
        ("phoneme_count", ctypes.c_int)
    ]

class SynthesisRequest(ctypes.Structure):
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

    def _load_library(self):
        """OSに合わせてDLL/dylibをロード"""
        ext = ".dll" if platform.system() == "Windows" else ".dylib"
        fname = "engine_avx2.dll" if platform.system() == "Windows" else "engine.dylib"
        
        # 実行環境(ビルド後)か開発環境かでパスを切り替え
        base = getattr(sys, '_MEIPASS', os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        lib_path = os.path.join(base, "VO_SE_engine_C", "lib", fname)
        
        if not os.path.exists(lib_path):
            raise FileNotFoundError(f"Engine library not found at: {lib_path}")
            
        return ctypes.CDLL(lib_path)

    def _setup_ctypes(self):
        """C関数の型定義"""
        self.lib.init_engine.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        self.lib.init_engine.restype = ctypes.c_int
        
        self.lib.request_synthesis_full.restype = ctypes.POINTER(ctypes.c_float)
        self.lib.request_synthesis_full.argtypes = [SynthesisRequest, ctypes.POINTER(ctypes.c_int)]
        
        self.lib.vse_free_buffer.argtypes = [ctypes.POINTER(ctypes.c_float)]

    def set_voice(self, voice_name, voice_path):
        """使用する音源フォルダを指定"""
        self.current_voice_path = voice_path
        self.lib.init_engine(voice_name.encode('utf-8'), voice_path.encode('utf-8'))

    def synthesize(self, score_data: List[NoteEvent]):
        count = len(score_data)
        note_array = (CNoteEvent * count)()
        self._refs = [] # Cに渡す文字列が解放されないよう保持

        for i, note in enumerate(score_data):
            note_array[i].note_number = note.note_number
　　　　　　　　# 先行発声(pre_utterance)がある場合、その分だけ開始を早める　
            # これにより、子音がリズムの「前」に配置されます
            note_array[i].start_time = note.start_time - note.pre_utterance
            note_array[i].duration = note.duration + note.pre_utterance
            # 【重要】start_time を先行発声分だけ「前にずらす」  
            corrected_start = note.start_time - note.pre_utterance
            corrected_duration = note.duration + note.pre_utterance
        
            note_array[i].start_time = max(0, corrected_start) # 0秒以下にならないようガード
            note_array[i].duration = corrected_duration
            note_array[i].note_number = note.note_number
            
            # 音素(phonemes)をバイト列に変換して参照保持
            for j, ph in enumerate(note.phonemes[:8]):
                ph_b = ph.encode('utf-8')
                self._refs.append(ph_b) 
                note_array[i].phonemes[j] = ph_b
            note_array[i].phoneme_count = len(note.phonemes)

        req = SynthesisRequest(note_array, count, self.sample_rate)
        out_count = ctypes.c_int()
        
        # Cエンジンで合成実行
        ptr = self.lib.request_synthesis_full(req, ctypes.byref(out_count))
        
        if not ptr:
            return None

        # Cのメモリからnumpy配列へ安全にコピー
        # 
        raw_data = np.ctypeslib.as_array(ptr, shape=(out_count.value,))
        audio_out = np.copy(raw_data)
        
        # C側のメモリを即座に解放
        self.lib.vse_free_buffer(ptr)
        
        return audio_out

    def play(self, audio_data):
        """合成した音声を再生"""
        if audio_data is not None:
            sd.play(audio_data, self.sample_rate)
            sd.wait()

    engine.play(wav)
