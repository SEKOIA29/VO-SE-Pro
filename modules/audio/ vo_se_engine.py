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
from collections import OrderedDict
from typing import List

# ==========================================================================
# C言語エンジン互換の構造体定義 (ctypes)
# ==========================================================================

class CNoteEvent(ctypes.Structure):
    _fields_ = [
        ("note_number", ctypes.c_int),
        ("start_time", ctypes.c_float),
        ("duration", ctypes.c_float),
        ("velocity", ctypes.c_int),
        ("pre_utterance", ctypes.c_float),
        ("overlap", ctypes.c_float),
        ("phonemes", ctypes.c_char_p * 8),
        ("phoneme_count", ctypes.c_int),
        ("pitch_curve", ctypes.POINTER(ctypes.c_float)),
        ("pitch_length", ctypes.c_int)
    ]

class SynthesisRequest(ctypes.Structure):
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
        self.lib = self._load_core_library()

        # --- メモリ管理 & SSDスワップ設定 ---
        self.cache = OrderedDict()
        self.max_cache_bytes = self._calculate_cache_limit()
        self.current_cache_bytes = 0
        
        self.ssd_swap_enabled = True
        self.swap_dir = ".temp_cache"
        if not os.path.exists(self.swap_dir):
            os.makedirs(self.swap_dir)

    def set_oto_data(self, oto_map):
        self.oto_map = oto_map

    def set_voice_library(self, path):
        self.current_voice_path = path

    # ----------------------------------------------------------------------
    # メモリ管理サブシステム
    # ----------------------------------------------------------------------
    def _calculate_cache_limit(self):
        total_ram_gb = psutil.virtual_memory().total / (1024**3)
        if total_ram_gb <= 8:
            limit = 800 * (1024**2) #800MB
        elif total_ram_gb <= 16:
            limit = 1.5 * (1024**3) #1.5GB
        elif total_ram_gb <= 32:
            limit = 4 * (1024**3) #4GB
        elif total_ram_gb <= 64:
            limit = 10 * (1024**3) #10
        else:
            limit = 16 * (1024**3)
        print(f"Detected RAM: {total_ram_gb:.1f}GB. Cache Limit: {limit/(1024**2):.1f}MB")
        return limit

    def _get_cache_key(self, wav_path, target_hz, duration_sec):
        return f"{os.path.basename(wav_path)}_{int(target_hz)}_{int(duration_sec*1000)}"

    def _manage_cache(self, key, audio_data):
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
    # 補助関数：パラメータストレッチ
    # ----------------------------------------------------------------------
    def _stretch_param(self, param, c_frames, v_needed):
        consonant_part = param[:c_frames]
        vowel_part = param[c_frames:]
        if len(vowel_part) <= 1: return param # 安全策
        indices = np.linspace(0, len(vowel_part) - 1, v_needed).astype(int)
        stretched_vowel = vowel_part[indices]
        return np.concatenate([consonant_part, stretched_vowel])

    # ----------------------------------------------------------------------
    # 合成核心部：ストレッチ・ピッチカーブ対応WORLD
    # ----------------------------------------------------------------------
    def _generate_single_note_world(self, wav_path, target_hz, duration_sec, offset_ms, config, pitch_curve=None):
        # キャッシュキー作成（ピッチカーブがある場合はハッシュ値などで識別するのが理想ですが、一旦簡易化）
        key = self._get_cache_key(wav_path, target_hz, duration_sec)
        
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        
        swap_path = os.path.join(self.swap_dir, f"{key}.npy")
        if self.ssd_swap_enabled and os.path.exists(swap_path):
            data = np.load(swap_path)
            self._manage_cache(key, data)
            return data

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

            # ストレッチ計算
            consonant_ms = config.get('consonant', 0)
            consonant_frames = np.sum(t < (consonant_ms / 1000.0))
            target_total_frames = int((duration_sec * 1000.0) / 5.0) # 5ms period
            vowel_frames_needed = max(1, target_total_frames - consonant_frames)
            
            new_sp = self._stretch_param(sp, consonant_frames, vowel_frames_needed)
            new_ap = self._stretch_param(ap, consonant_frames, vowel_frames_needed)

            # ピッチ配列の適用
            if pitch_curve is not None:
                # ユーザー定義カーブをフレーム数にリサイズ
                if len(pitch_curve) != len(new_sp):
                    new_f0 = np.interp(
                        np.linspace(0, len(pitch_curve), len(new_sp)),
                        np.arange(len(pitch_curve)),
                        pitch_curve
                    )
                else:
                    new_f0 = pitch_curve
            else:
                new_f0 = np.ones(len(new_sp)) * target_hz

            # 再合成
            y = pw.synthesize(new_f0.astype(np.float64), new_sp, new_ap, fs)
            
            # 最終リサイズ
            target_samples = int(duration_sec * self.sample_rate)
            if len(y) != target_samples:
                y = librosa.resample(y, orig_sr=len(y), target_sr=target_samples)
                
            y_final = y.astype(np.float32)
            self._manage_cache(key, y_final)
            return y_final

        except Exception as e:
            print(f"Synthesis Error: {e}")
            return np.zeros(int(duration_sec * self.sample_rate), dtype=np.float32)


#エンジン接続関係
#------------
    def _load_core_library(self):
        """EXE化後も対応したライブラリロード"""
        # PyInstaller環境かどうかの判定
        if hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
        else:
            # 開発時は bin フォルダまたはカレントディレクトリを探す
            base_path = os.path.join(os.path.dirname(__file__), "bin")

        current_os = platform.system()
        if current_os == "Windows":
            lib_name = "vose_core.dll"
        elif current_os == "Darwin":
            lib_name = "vose_core.dylib"
        else:
            return None

        for path in [os.path.join(base_path, lib_name), lib_name]:
            if os.path.exists(path):
                return ctypes.CDLL(path)
        return None

    def call_cpp_engine(self, note):
        if not self.lib or not hasattr(note, 'pitch_curve'):
            return
        
        # NumPy配列をCポインタに変換
        pitch_data = note.pitch_curve.astype(np.float32)
        pitch_ptr = pitch_data.ctypes.data_as(ctypes.POINTER(ctypes.c_float))

        c_note = CNoteEvent()
        c_note.note_number = note.note_number
        c_note.start_time = note.start_time
        c_note.duration = note.duration
        c_note.pitch_curve = pitch_ptr
        c_note.pitch_length = len(pitch_data)

        self.lib.process_vocal.argtypes = [ctypes.POINTER(CNoteEvent)]
        self.lib.process_vocal(ctypes.byref(c_note))

    # ----------------------------------------------------------------------
    # 公開メソッド
    # ----------------------------------------------------------------------
    def synthesize(self, notes_list: List) -> np.ndarray:
        if not notes_list:
            return np.zeros(0, dtype=np.float32)

        max_time = max(n.start_time + n.duration for n in notes_list)
        total_samples = int((max_time + 1.0) * self.sample_rate)
        output_buffer = np.zeros(total_samples, dtype=np.float32)

        for note in notes_list:
            lyric = note.lyrics if hasattr(note, 'lyrics') else getattr(note, 'lyric', "ら")
            if lyric not in self.oto_map:
                continue

            config = self.oto_map[lyric]
            
            # ピッチ取得（カーブがあればそれを優先、なければ固定値）
            pitch_curve = getattr(note, 'pitch_curve', None)
            target_hz = 440.0 * (2.0 ** ((note.note_number - 69) / 12.0))
            if pitch_curve is not None:
                target_hz = np.mean(pitch_curve) # キャッシュキー用の代表値
            
            user_offset_ms = getattr(note, 'onset', 0.0) * 1000.0
            
            y_note = self._generate_single_note_world(
                config['wav_path'], target_hz, note.duration, 
                config['offset'] + user_offset_ms, config,
                pitch_curve=pitch_curve
            )

            # 配置
            corrected_preutter = config['preutterance'] - user_offset_ms
            start_idx = int((note.start_time - (corrected_preutter / 1000.0)) * self.sample_rate)
            start_idx = max(0, start_idx)
            
            # クロスフェード
            ov_samples = int(config['overlap'] / 1000.0 * self.sample_rate)
            if ov_samples > 0 and len(y_note) > ov_samples:
                y_note[:ov_samples] *= np.linspace(0, 1, ov_samples)

            # ミックス
            end_idx = start_idx + len(y_note)
            if end_idx <= total_samples:
                output_buffer[start_idx:end_idx] += y_note
            else:
                available = total_samples - start_idx
                if available > 0:
                    output_buffer[start_idx:] += y_note[:available]

        # ノーマライズ
        max_val = np.max(np.abs(output_buffer))
        if max_val > 0:
            output_buffer = (output_buffer / max_val) * 0.9
        return output_buffer

    def play(self, data):
        if data is not None and len(data) > 0:
            sd.play(data, self.sample_rate)

    def stop(self):
        sd.stop()

    def export_to_wav(self, data, filepath):
        sf.write(filepath, data, self.sample_rate)

    def clear_all_cache(self):
        self.cache.clear()
        self.current_cache_bytes = 0
        if os.path.exists(self.swap_dir):
            for f in os.listdir(self.swap_dir):
                if f.endswith(".npy"):
                    os.remove(os.path.join(self.swap_dir, f))




                        
