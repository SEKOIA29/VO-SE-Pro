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
