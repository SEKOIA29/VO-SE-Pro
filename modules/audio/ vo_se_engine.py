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

# ==========================================================================
# C言語エンジン互換の構造体定義 (ctypes)
# ==========================================================================
# 将来的にC++ DLL/dylibをロードする場合でも、このレイアウトを維持することで
# MainWindow側の変更なしで差し替えが可能です。

class CNoteEvent(ctypes.Structure):
    """C/C++エンジン側とメモリレイアウトを統一した構造体"""
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

# ==========================================================================
# メインエンジンクラス
# ==========================================================================

class VO_SE_Engine:
    def __init__(self, sample_rate=44100):
        self.sample_rate = sample_rate
        self.current_voice_path = ""
        self.oto_map = {}
        self._refs = []  # Python側の文字列がGCで消されないように保持するリスト

    def set_oto_data(self, oto_map):
        """MainWindow（または音源マネージャー）から受け取った原音設定を保持"""
        self.oto_map = oto_map

    def set_voice_library(self, path):
        """使用する音源フォルダのパスを設定"""
        self.current_voice_path = path

    # ----------------------------------------------------------------------
    # 核心部：ピッチシフト対応 WORLD合成ロジック
    # ----------------------------------------------------------------------

    def _generate_single_note_world(self, wav_path, target_hz, duration_sec, offset_ms):
        """
        1つの音素(WAV)を、WORLDエンジンで解析し、指定ピッチで再合成する
        """
        try:
            # 1. 音声のロード
            # offsetは秒単位で指定 (ミリ秒 / 1000)
            x, fs = librosa.load(wav_path, sr=self.sample_rate, offset=offset_ms / 1000.0)
            
            # 極端に短いデータ（無音など）に対するクラッシュ防止
            if len(x) < 128:
                return np.zeros(int(duration_sec * self.sample_rate))
                
            x = x.astype(np.float64)

            # 2. WORLDによる解析（分解）
            # dio: 基本周波数(F0)推定 / cheaptrick: スペクトル包絡 / d4c: 非周期性指標
            _f0, t = pw.dio(x, fs)
            f0 = pw.stonemask(x, _f0, t, fs)
            sp = pw.cheaptrick(x, f0, t, fs)
            ap = pw.d4c(x, f0, t, fs)

            # 3. 【ピッチシフト実行】
            # ノートで指定された Hz で塗りつぶし、完璧な音程を生成
            modified_f0 = np.ones_like(f0) * target_hz

            # 4. 再合成
            y = pw.synthesize(modified_f0, sp, ap, fs)
            
            # 5. 時間軸の調整
            # 合成された音声がノートの長さに足りない、または超える場合にリサンプリング
            target_samples = int(duration_sec * self.sample_rate)
            if len(y) != target_samples:
                y = librosa.resample(y, orig_sr=len(y), target_sr=target_samples)
                
            return y
        except Exception as e:
            print(f"Synthesis error for {wav_path}: {e}")
            return np.zeros(int(duration_sec * self.sample_rate))

    # ----------------------------------------------------------------------
    # 公開メソッド (MainWindowから呼び出す)
    # ----------------------------------------------------------------------

    def synthesize(self, notes_list: List) -> np.ndarray:
        """
        タイムライン上のすべてのノートを高品質に繋ぎ合わせ、1つのNumPy配列を生成
        """
        if not notes_list:
            return np.zeros(0, dtype=np.float32)

        # 1. 最終出力バッファを確保 (最後のノートの終了時間に1秒の余韻を追加)
        max_time = max(n.start_time + n.duration for n in notes_list)
        total_samples = int((max_time + 1.0) * self.sample_rate)
        output_buffer = np.zeros(total_samples, dtype=np.float32)

        for note in notes_list:
            # 歌詞（またはエイリアス）が音源に存在するか確認
            lyric = note.lyrics if hasattr(note, 'lyrics') else getattr(note, 'lyric', "ら")
            if lyric not in self.oto_map:
                continue

            config = self.oto_map[lyric]
            
            # --- 優先順位1位：ピッチ計算 (MIDI -> Hz) ---
            target_hz = 440.0 * (2.0 ** ((note.note_number - 69) / 12.0))
            
            # 赤線(onset)による補正計算
            user_offset_ms = getattr(note, 'onset', 0.0) * 1000.0
            final_wav_offset = config['offset'] + user_offset_ms
            
            # ノート合成実行
            y_note = self._generate_single_note_world(
                config['wav_path'],
                target_hz,
                note.duration,
                final_wav_offset
            )

            # 配置タイミングの計算 (先行発声を考慮)
            corrected_preutter = config['preutterance'] - user_offset_ms
            start_idx = int((note.start_time - (corrected_preutter / 1000.0)) * self.sample_rate)
            
            if start_idx < 0: start_idx = 0
            
            # オーバーラップ (クロスフェード)
            overlap_samples = int(config['overlap'] / 1000.0 * self.sample_rate)
            if overlap_samples > 0 and len(y_note) > overlap_samples:
                fade_curve = np.linspace(0, 1, overlap_samples)
                y_note[:overlap_samples] *= fade_curve

            # Mix (バッファ加算)
            end_idx = start_idx + len(y_note)
            if end_idx <= total_samples:
                output_buffer[start_idx:end_idx] += y_note.astype(np.float32)
            else:
                available = total_samples - start_idx
                if available > 0:
                    output_buffer[start_idx:] += y_note[:available].astype(np.float32)

        # 音割れ防止のノーマライズ
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

    def clear_cache(self):
        """キャッシュクリア用"""
        self._refs = []

    def update_notes_data(self, notes):
        """タイムラインからの更新通知（スタブ）"""
        pass
