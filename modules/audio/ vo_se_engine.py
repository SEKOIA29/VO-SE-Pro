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

        self.cache = OrderedDict()
        
        # 1. PCのスペックに応じてキャッシュ制限を自動設定
        self.max_cache_bytes = self._calculate_cache_limit()
        self.current_cache_bytes = 0
        
        # 2. SSDスワップモード設定 (Trueならメモリが溢れた時にディスクへ逃がす)
        self.ssd_swap_enabled = True
        self.swap_dir = "temp_cache"
        if not os.path.exists(self.swap_dir):
            os.makedirs(self.swap_dir)

    def set_oto_data(self, oto_map):
        """MainWindow（または音源マネージャー）から受け取った原音設定を保持"""
        self.oto_map = oto_map

    def set_voice_library(self, path):
        """使用する音源フォルダのパスを設定"""
        self.current_voice_path = path

    # ----------------------------------------------------------------------
    # 核心部：ピッチシフト対応 WORLD合成ロジック
    # ----------------------------------------------------------------------

    def _generate_single_note_world(self, wav_path, target_hz, duration_sec, offset_ms, config):
        """
        [アップグレード版] 
        子音(固定範囲)は維持し、母音部分だけをノート長に合わせてストレッチする
        """
        try:
            # 1. 音声のロード
            x, fs = librosa.load(wav_path, sr=self.sample_rate, offset=offset_ms / 1000.0)
            x = x.astype(np.float64)
            if len(x) < 128: return np.zeros(int(duration_sec * self.sample_rate))

            # 2. WORLD解析
            _f0, t = pw.dio(x, fs)
            f0 = pw.stonemask(x, _f0, t, fs)
            sp = pw.cheaptrick(x, f0, t, fs)
            ap = pw.d4c(x, f0, t, fs)

            # 3. 【核心】ストレッチ・ロジック
            # config['consonant'] は固定する範囲（ミリ秒）
            consonant_ms = config.get('consonant', 0)
            consonant_frames = np.sum(t < (consonant_ms / 1000.0))
            
            # 目標のフレーム数を計算
            target_frames = int(duration_sec * fs / (t[1] - t[0]) / fs) # 簡易計算
            # 実際にはもっと単純に: WORLDのデフォルトフレーム周期(5ms)で計算
            frame_period = 5.0 
            target_total_frames = int((duration_sec * 1000.0) / frame_period)
            
            vowel_frames_needed = max(1, target_total_frames - consonant_frames)
            
            # 母音部分（固定範囲より後ろ）をリサンプリングして伸ばす
            def stretch_param(param, c_frames, v_needed):
                consonant_part = param[:c_frames]
                vowel_part = param[c_frames:]
                # 母音部分だけを必要な長さに補間
                indices = np.linspace(0, len(vowel_part) - 1, v_needed)
                stretched_vowel = np.array([vowel_part[int(i)] for i in indices])
                return np.concatenate([consonant_part, stretched_vowel])

            # 各パラメータをストレッチ
            new_sp = stretch_param(sp, consonant_frames, vowel_frames_needed)
            new_ap = stretch_param(ap, consonant_frames, vowel_frames_needed)
            
            # 4. ピッチ(F0)の上書き（ストレッチ後の長さに合わせる）
            new_f0 = np.ones(len(new_sp)) * target_hz

            # 5. 再合成
            y = pw.synthesize(new_f0, new_sp, new_ap, fs)
            
            # 念のための最終リサイズ（サンプリング単位の微調整）
            target_samples = int(duration_sec * self.sample_rate)
            if len(y) != target_samples:
                y = librosa.resample(y, orig_sr=len(y), target_sr=target_samples)
                
            return y
        except Exception as e:
            print(f"ストレッチ合成エラー: {e}")
            return np.zeros(int(duration_sec * self.sample_rate))

    #=========================================
    #メモリ管理
    #=========================================


    def _calculate_cache_limit(self):
        """搭載メモリ(RAM)に応じて制限値を決定"""
        total_ram_gb = psutil.virtual_memory().total / (1024**3)
        
        if total_ram_gb <= 8:
            limit = 800 * (1024**2)  # 800MB
        elif total_ram_gb <= 16:
            limit = 1.5 * (1024**3)  # 1.5GB
        elif total_ram_gb <= 32:
            limit = 4 * (1024**3)    # 4GB
        elif total_ram_gb <= 64:
            limit = 10 * (1024**3)   # 10GB
        else:
            limit = 16 * (1024**3)   # 16GB
        
        print(f"Detected RAM: {total_ram_gb:.1f}GB. Cache Limit set to: {limit/(1024**2):.1f}MB")
        return limit

    def _get_cache_key(self, wav_path, target_hz, duration_sec):
        return f"{os.path.basename(wav_path)}_{target_hz}_{duration_sec}"

    def _manage_cache(self, key, audio_data):
        """キャッシュの追加とメモリ制限の維持"""
        data_size = audio_data.nbytes
        
        # 制限を超える場合は古いものから消す
        while self.current_cache_bytes + data_size > self.max_cache_bytes and self.cache:
            old_key, old_data = self.cache.popitem(last=False)
            
            # SSDスワップが有効ならディスクへ保存してからメモリから消す
            if self.ssd_swap_enabled:
                swap_path = os.path.join(self.swap_dir, f"{old_key}.npy")
                np.save(swap_path, old_data)
                
            self.current_cache_bytes -= old_data.nbytes

        self.cache[key] = audio_data
        self.current_cache_bytes += data_size

    def _generate_single_note_world(self, wav_path, target_hz, duration_sec, offset_ms, config):
        key = self._get_cache_key(wav_path, target_hz, duration_sec)
        
        # 1. メモリキャッシュを確認
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        
        # 2. SSDスワップを確認
        swap_path = os.path.join(self.swap_dir, f"{key}.npy")
        if self.ssd_swap_enabled and os.path.exists(swap_path):
            data = np.load(swap_path)
            self._manage_cache(key, data) # メモリに戻す
            return data

        # 3. キャッシュになければ新規合成 (重い処理)
        try:
            # --- 以前実装したWORLD合成ロジック (中略なしでここに配置) ---
            # (ここでは例としてダミー波形を生成しますが、実際は前回のWORLDロジックが入ります)
            y_note = np.random.uniform(-0.1, 0.1, int(duration_sec * self.sample_rate)).astype(np.float32)
            # -------------------------------------------------------

            # キャッシュに保存
            self._manage_cache(key, y_note)
            return y_note
            
        except Exception as e:
            print(f"Error: {e}")
            return np.zeros(int(duration_sec * self.sample_rate))

    def clear_all_cache(self):
        """メモリもSSDもすべて空にする"""
        self.cache.clear()
        self.current_cache_bytes = 0
        for f in os.listdir(self.swap_dir):
            os.remove(os.path.join(self.swap_dir, f))

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
