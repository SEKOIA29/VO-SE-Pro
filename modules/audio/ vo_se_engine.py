# vo_se_engine.py

import ctypes
import os
import platform
import sys
import numpy as np
import sounddevice as sd
import soundfile as sf
import subprocess
import wave

# ==========================================================================
# C言語エンジン互換の構造体定義 (ctypes)
# ==========================================================================
class CNoteEvent(ctypes.Structure):
    _fields_ = [
        ("wav_path", ctypes.c_char_p),        # 音源WAVのフルパス
        ("pitch_curve", ctypes.POINTER(ctypes.c_float)), # Hzの配列
        ("pitch_length", ctypes.c_int)        # 配列の長さ
    ]

# ==========================================================================
# メインエンジンクラス
# ==========================================================================
class VO_SE_Engine:
    def __init__(self, voice_lib_dir="voices"):
        self.lib = self._load_core_library()
        self._temp_pitch_refs = []  # C++実行中のメモリ解放を防ぐ参照保持
        self.sample_rate = 44100
        
        # 音源ライブラリのパス設定とインポート
        self.voice_lib_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", voice_lib_dir))
        self.oto_map = {}
        self.refresh_voice_library()
        

    def _load_core_library(self):
        """ビルドした vose_core.dll / dylib をロード"""
        base_path = os.path.dirname(__file__)
        ext = ".dll" if platform.system() == "Windows" else ".dylib"
        
        # 探索候補: binフォルダ または スクリプトと同階層
        search_paths = [
            os.path.join(base_path, "..", "bin", f"vose_core{ext}"),
            os.path.join(base_path, f"vose_core{ext}"),
            f"./vose_core{ext}"
        ]
        
        for path in search_paths:
            if os.path.exists(path):
                try:
                    lib = ctypes.CDLL(os.path.abspath(path))
                    lib.execute_render.argtypes = [
                        ctypes.POINTER(CNoteEvent), 
                        ctypes.c_int, 
                        ctypes.c_char_p
                    ]
                    print(f"○ Engine Loaded: {path}")
                    return lib
                except Exception as e:
                    print(f"✖ Load Error: {e}")
        return None

    def refresh_voice_library(self):
        """voicesフォルダ内のWAVをスキャンして歌詞と紐付け"""
        if not os.path.exists(self.voice_lib_path):
            return
        for file in os.listdir(self.voice_lib_path):
            if file.endswith(".wav"):
                lyric = os.path.splitext(file)[0]
                self.oto_map[lyric] = os.path.abspath(os.path.join(self.voice_lib_path, file))

    def render(self, song_data, output_path="result.wav"):
        """
        GUIから渡されたノート情報を合成
        song_data: [{'lyric': 'あ', 'pitch_list': [440.0, ...]}, ...]
        """
        if not self.lib or not song_data:
            return None

        note_count = len(song_data)
        c_notes_array = (CNoteEvent * note_count)()
        self._temp_pitch_refs = []

        for i, note in enumerate(song_data):
            lyric = note.get('lyric')
            wav_path = self.oto_map.get(lyric)

            if not wav_path:
                print(f"ʕ⁎̯͡⁎ʔ༄ Missing voice: {lyric}")
                continue

            # ピッチリストをC互換の配列に変換
            pitch_data = np.array(note['pitch_list'], dtype=np.float32)
            self._temp_pitch_refs.append(pitch_data) # Python側のGCから保護

            c_notes_array[i].wav_path = wav_path.encode('utf-8')
            c_notes_array[i].pitch_curve = pitch_data.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            c_notes_array[i].pitch_length = len(pitch_data)

        try:
            full_out_path = os.path.abspath(output_path)
            self.lib.execute_render(c_notes_array, note_count, full_out_path.encode('utf-8'))
            return full_out_path
        except Exception as e:
            print(f"✖ Synthesis Error: {e}")
            return None

    def play(self, filepath):
        if filepath and os.path.exists(filepath):
            data, fs = sf.read(filepath)
            sd.play(data, fs)

    def stop(self):
        sd.stop()
