# vo_se_engine.py

import ctypes
import os
import platform
import sys
import psutil
import numpy as np
import sounddevice as sd
import librosa
import pyworld as pw
import soundfile as sf
from collections import OrderedDict  # 必須インポート
from typing import List

# ==========================================================================
# C言語エンジン互換の構造体定義 (ctypes)
# ==========================================================================
class CNoteEvent(ctypes.Structure):
    """C/C++エンジン側とメモリレイアウトを統一した構造体"""
    _fields_ = [
        ("note_number", ctypes.c_int),
        ("start_time", ctypes.c_float),
        ("duration", ctypes.c_float),
        ("velocity", ctypes.c_int),
        ("pre_utterance", ctypes.c_float),
        ("overlap", ctypes.c_float),
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

# ==========================================================================
# メインエンジンクラス
# ==========================================================================
class VO_SE_Engine:
    def __init__(self, sample_rate=44100):
        self.sample_rate = sample_rate
        self.current_voice_path = ""
        self.oto_map = {}
        self._refs = []

        # --- メモリ管理 & SSDスワップ設定 ---
        self.cache = OrderedDict()
        self.max_cache_bytes = self._calculate_cache_limit()
        self.current_cache_bytes = 0
        
        self.ssd_swap_enabled = True
        self.swap_dir = ".temp_cache"
        if not os.path.exists(self.swap_dir):
            os.makedirs(self.swap_dir)

    def set_oto_data(self, oto_map):
        """原音設定データをエンジンに同期"""
        self.oto_map = oto_map

    def set_voice_library(self, path):
        """音源フォルダのパスを設定"""
        self.current_voice_path = path

    # ----------------------------------------------------------------------
    # メモリ管理サブシステム
    # ----------------------------------------------------------------------
    def _calculate_cache_limit(self):
        """搭載メモリ(RAM)に応じて制限値を決定（ご指定の仕様）"""
        total_ram_gb = psutil.virtual_memory().total / (1024**3)
        
        if total_ram_gb <= 8:
            limit = 800 * (1024**2)   # 800MB
        elif total_ram_gb <= 16:
            limit = 1.5 * (1024**3)   # 1.5GB
        elif total_ram_gb <= 32:
            limit = 4 * (1024**3)     # 4GB
        elif total_ram_gb <= 64:
            limit = 10 * (1024**3)    # 10GB
        else:
            limit = 16 * (1024**3)    # 16GB
        
        print(f"Detected RAM: {total_ram_gb:.1f}GB. Cache Limit: {limit/(1024**2):.1f}MB")
        return limit

    def _get_cache_key(self, wav_path, target_hz, duration_sec):
        """キャッシュ用のユニークキーを生成"""
        return f"{os.path.basename(wav_path)}_{int(target_hz)}_{int(duration_sec*1000)}"

    def _manage_cache(self, key, audio_data):
        """メモリ制限の維持。溢れたらSSDへ退避（スワップアウト）"""
        data_size = audio_data.nbytes
        
        while self.current_cache_bytes + data_size > self.max_cache_bytes and self.cache:
            old_key, old_data = self.cache.popitem(last=False)
            if self.ssd_swap_enabled:
                swap_path = os.path.join(self.swap_dir, f"{old_key}.npy")
                np.save(swap_path, old_data)
            self.current_cache_bytes -= old_data.nbytes

        self.cache[key] = audio_data
        self.current_cache_bytes += data_size

    # ----------------------------------------------------------------------
    # 合成核心部：ストレッチ・ピッチシフト・WORLD
    # ----------------------------------------------------------------------
    def _generate_single_note_world(self, wav_path, target_hz, duration_sec, offset_ms, config):
        key = self._get_cache_key(wav_path, target_hz, duration_sec)
        
        # 1. メモリキャッシュ確認
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        
        # 2. SSDスワップ確認
        swap_path = os.path.join(self.swap_dir, f"{key}.npy")
        if self.ssd_swap_enabled and os.path.exists(swap_path):
            data = np.load(swap_path)
            self._manage_cache(key, data)
            return data

        # 3. 新規合成実行
        try:
            x, fs = librosa.load(wav_path, sr=self.sample_rate, offset=offset_ms / 1000.0)
            x = x.astype(np.float64)
            if len(x) < 128:
                return np.zeros(int(duration_sec * self.sample_rate), dtype=np.float32)

            # WORLD解析
            _f0, t = pw.dio(x, fs)
            f0 = pw.stonemask(x, _f0, t, fs)
            sp = pw.cheaptrick(x, f0, t, fs)
            ap = pw.d4c(x, f0, t, fs)

            # ストレッチ計算（子音固定・母音延伸）
            consonant_ms = config.get('consonant', 0)
            consonant_frames = np.sum(t < (consonant_ms / 1000.0))
            
            frame_period = 5.0 
            target_total_frames = int((duration_sec * 1000.0) / frame_period)
            vowel_frames_needed = max(1, target_total_frames - consonant_frames)
            
            def stretch_param(param, c_frames, v_needed):
                consonant_part = param[:c_frames]
                vowel_part = param[c_frames:]
                indices = np.linspace(0, len(vowel_part) - 1, v_needed).astype(int)
                stretched_vowel = vowel_part[indices]
                return np.concatenate([consonant_part, stretched_vowel])

            new_sp = stretch_param(sp, consonant_frames, vowel_frames_needed)
            new_ap = stretch_param(ap, consonant_frames, vowel_frames_needed)
            new_f0 = np.ones(len(new_sp)) * target_hz

            # 再合成
            y = pw.synthesize(new_f0, new_sp, new_ap, fs)
            
            # 最終リサイズ
            target_samples = int(duration_sec * self.sample
