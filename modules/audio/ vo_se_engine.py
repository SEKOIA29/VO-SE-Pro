# vo_se_engine.py


import ctypes
import os
import platform
import sys
import numpy as np
import sounddevice as sd
import librosa
import pyworld as pw
import soundfile as sf
from typing import List

# --- C言語エンジン互換の構造体定義 ---
# 将来的にC++ DLLに差し替える場合もこのレイアウトを維持します
class CNoteEvent(ctypes.Structure):
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

class VO_SE_Engine:
    def __init__(self, sample_rate=44100):
        self.sample_rate = sample_rate
        self.current_voice_path = ""
        self.oto_map = {}  # UTAU原音設定 (oto.iniの解析結果)
        self._refs = []    # ctypes文字列のGC防止用

    # --- 設定系メソッド ---
    def set_oto_data(self, oto_map):
        """MainWindowから受け取った原音設定を格納"""
        self.oto_map = oto_map

    def set_voice_library(self, path):
        """音源フォルダのパスを設定"""
        self.current_voice_path = path

    # --- 合成核心部 (WORLDエンジン) ---
    def _generate_single_note_world(self, wav_path, target_hz, duration_sec, offset_ms):
        """
        【内部ロジック】WORLDを使用して1つの音素を再合成する
        """
        try:
            # 1. ロード（左ブランク + 赤線移動分をスキップ）
            # offsetは秒単位で指定
            x, fs = librosa.load(wav_path, sr=self.sample_rate, offset=offset_ms / 1000.0)
            x = x.astype(np.float64)

            # 2. WORLD解析 (基本周波数、スペクトル、非周期性)
            _f0, t = pw.dio(x, fs)
            f0 = pw.stonemask(x, _f0, t, fs)
            sp = pw.cheaptrick(x, f0, t, fs)
            ap = pw.d4c(x, f0, t, fs)

            # 3. 目標ピッチに書き換え
            modified_f0 = np.ones_like(f0) * target_hz

            # 4. 再合成
            y = pw.synthesize(modified_f0, sp, ap, fs)
            
            # 5. ノートの長さに厳密にリサイズ
            target_samples = int(duration_sec * self.sample_rate)
            if len(y) != target_samples:
                y = librosa.resample(y, orig_sr=len(y), target_sr=target_samples)
            return y
        except Exception as e:
            print(f"Synthesis error for {wav_path}: {e}")
            return np.zeros(int(duration_sec * self.sample_rate))

    # --- 外部呼び出し用インターフェース ---
    def synthesize(self, score_data: List) -> np.ndarray:
        """
        [統合版] ノートリストから全音声を合成し、一つのnumpy配列を返す
        """
        if not score_data:
            return np.zeros(0, dtype=np.float32)

        # 1. 全体のバッファサイズを計算（最後のノート + 余韻1秒）
        max_time = max(n.start_time + n.duration for n in score_data)
        total_samples = int((max_time + 1.0) * self.sample_rate)
        output_buffer = np.zeros(total_samples, dtype=np.float32)

        for note in score_data:
            # 歌詞（エイリアス）の取得
            lyric = note.lyrics if hasattr(note, 'lyrics') else getattr(note, 'lyric', "ら")
            if lyric not in self.oto_map:
                continue

            config = self.oto_map[lyric]
            
            # 2. 赤線(onset)による補正計算
            # user_offset_ms: ユーザーが赤線を右に動かした量（秒→ミリ秒）
            user_offset_ms = getattr(note, 'onset', 0.0) * 1000.0
            
            # パラメータ確定
            target_hz = 440.0 * (2.0 ** ((note.note_number - 69) / 12.0))
            # 実際のWAV読み込み位置 = 元のoffset + ユーザー移動分
            final_wav_offset = config['offset'] + user_offset_ms
            
            # 3. 個別ノート合成実行
            y_note = self._generate_single_note_world(
                config['wav_path'],
                target_hz,
                note.duration,
                final_wav_offset
            )

            # 4. 配置タイミングの計算 (UTAU方式)
            # 配置位置 = 開始時間 - (先行発声 - 赤線移動分)
            corrected_preutter = config['preutterance'] - user_offset_ms
            start_idx = int((note.start_time - (corrected_preutter / 1000.0)) * self.sample_rate)
            
            if start_idx < 0: start_idx = 0
            
            # 5. オーバーラップ（クロスフェード）
            overlap_samples = int(config['overlap'] / 1000.0 * self.sample_rate)
            if overlap_samples > 0 and len(y_note) > overlap_samples:
                fade_curve = np.linspace(0, 1, overlap_samples)
                y_note[:overlap_samples] *= fade_curve

            # 6. バッファへ加算（Mix）
            end_idx = start_idx + len(y_note)
            if end_idx <= total_samples:
                output_buffer[start_idx:end_idx] += y_note.astype(np.float32)
            else:
                available = total_samples - start_idx
                output_buffer[start_idx:] += y_note[:available].astype(np.float32)

        # 7. ノーマライズ（音割れ防止）
        max_val = np.max(np.abs(output_buffer))
        if max_val > 0:
            output_buffer = (output_buffer / max_val) * 0.9

        return output_buffer

    def play(self, audio_data: np.ndarray):
        """合成結果を再生"""
        if audio_data is not None and len(audio_data) > 0:
            sd.play(audio_data, self.sample_rate)

    def stop(self):
        """再生停止"""
        sd.stop()

    def export_to_wav(self, audio_data: np.ndarray, filepath: str):
        """WAV保存"""
        sf.write(filepath, audio_data, self.sample_rate)

    # 互換性維持のためのメソッド
    def clear_cache(self):
        self._refs = []

    def update_notes_data(self, notes):
        """タイムラインからの更新通知（スタブ）"""
        pass
