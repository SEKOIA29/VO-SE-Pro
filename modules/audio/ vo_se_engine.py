# vo_se_engine.py

import ctypes
import os
import platform
import sys
import numpy as np
import sounddevice as sd
import soundfile as sf

# C++の構造体定義 (vose_core.dllと完全一致)
class CNoteEvent(ctypes.Structure):
    _fields_ = [
        ("wav_path", ctypes.c_char_p),
        ("pitch_curve", ctypes.POINTER(ctypes.c_float)),
        ("pitch_length", ctypes.c_int)
    ]

class VO_SE_Engine:
    def __init__(self, voice_lib_dir="voices"):
        # 1. ライブラリ(DLL)のロード
        self.lib = self._load_core_library()
        self._refs = []  # メモリ解放防止用参照保持
        
        # 2. 音源ライブラリの自動インポート
        self.oto_map = {}
        self.import_voices(voice_lib_dir)

    def _load_core_library(self):
        base = os.path.dirname(__file__)
        ext = ".dll" if platform.system() == "Windows" else ".dylib"
        # 実行ファイルからの相対パスやbinフォルダを探索
        search_paths = [
            os.path.join(base, "..", "bin", f"vose_core{ext}"),
            os.path.join(base, f"vose_core{ext}"),
            f"./vose_core{ext}"
        ]
        for p in search_paths:
            if os.path.exists(p):
                lib = ctypes.CDLL(os.path.abspath(p))
                # C++関数の型を定義
                lib.execute_render.argtypes = [
                    ctypes.POINTER(CNoteEvent), 
                    ctypes.c_int, 
                    ctypes.c_char_p
                ]
                print(f"（╹◡╹） Engine Loaded: {p}")
                return lib
        print("ʕ⁎̯͡⁎ʔ༄ Error: vose_core library not found.")
        return None

    def import_voices(self, folder_name):
        """フォルダ内のWAVをスキャンして『歌詞: パス』の辞書を作る"""
        voice_path = os.path.join(os.path.dirname(__file__), "..", folder_name)
        if not os.path.exists(voice_path):
            os.makedirs(voice_path, exist_ok=True)
            return

        for file in os.listdir(voice_path):
            if file.endswith(".wav"):
                lyric = os.path.splitext(file)[0]  # 'あ.wav' -> 'あ'
                self.oto_map[lyric] = os.path.abspath(os.path.join(voice_path, file))
        print(f" Imported {len(self.oto_map)} voices from '{folder_name}'")

    def render(self, gui_notes, output_filename="result.wav"):
        """
        gui_notes: [{'lyric': 'あ', 'pitches': [440.0, 442.0, ...]}, ...]
        """
        if not self.lib: return
        
        count = len(gui_notes)
        c_notes = (CNoteEvent * count)()
        self._refs = []  # 以前のメモリ参照をクリア

        for i, note in enumerate(gui_notes):
            lyric = note.get('lyric', '')
            wav_path = self.oto_map.get(lyric)

            if not wav_path:
                print(f"(ﾉД`) Warning: Voice for '{lyric}' not found.")
                continue

            # ピッチ配列をCのfloat型に変換
            pitch_data = np.array(note['pitches'], dtype=np.float32)
            self._refs.append(pitch_data)  # C++実行中、Pythonがメモリを消さないように保持

            c_notes[i].wav_path = wav_path.encode('utf-8')
            c_notes[i].pitch_curve = pitch_data.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            c_notes[i].pitch_length = len(pitch_data)

        # C++側で一括合成
        output_path = os.path.abspath(output_filename)
        self.lib.execute_render(c_notes, count, output_path.encode('utf-8'))
        return output_path

    def play(self, wav_path):
        if os.path.exists(wav_path):
            data, fs = sf.read(wav_path)
            sd.play(data, fs)
