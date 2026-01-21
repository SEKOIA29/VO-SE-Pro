# vo_se_engine.py


 import ctypes
import os
import platform
import sys
import numpy as np
import sounddevice as sd
import soundfile as sf
from typing import List

# ==========================================================================
# C言語エンジン互換の構造体定義 (ctypes)
# ==========================================================================
# ※あなたが src/vose_core.h で定義した順番と型に厳密に合わせています
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
    def __init__(self, sample_rate=44100):
        self.sample_rate = sample_rate
        self.lib = self._load_core_library()
        self._temp_pitch_refs = [] # C++に渡すメモリを保持するためのリスト

    def _load_core_library(self):
        """ビルドしたDLL/dylibをロードする"""
        if hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
        else:
            # binフォルダ、またはカレントディレクトリを探索
            base_path = os.path.join(os.path.dirname(__file__), "bin")

        current_os = platform.system()
        lib_name = "vose_core.dll" if current_os == "Windows" else "vose_core.dylib"
        
        target_path = os.path.join(base_path, lib_name)
        if not os.path.exists(target_path):
            target_path = lib_name # カレントディレクトリも探す

        try:
            lib = ctypes.CDLL(target_path)
            # 関数の型定義
            lib.execute_render.argtypes = [
                ctypes.POINTER(CNoteEvent), 
                ctypes.c_int, 
                ctypes.c_char_p
            ]
            print(f"○ Successfully loaded engine: {target_path}")
            return lib
        except Exception as e:
            print(f"✖️ Failed to load engine: {e}")
            return None

    def render_and_save(self, gui_notes, output_path="result.wav"):
        """
        ピアノロールGUIから渡されたノートリストをC++エンジンで合成する
        gui_notes: [ {'wav': 'path/to/a.wav', 'pitch_list': [440.0, ...]}, ... ]
        """
        if not self.lib:
            print("Engine library not loaded.")
            return

        note_count = len(gui_notes)
        c_notes_array = (CNoteEvent * note_count)()
        self._temp_pitch_refs = [] # メモリ参照をクリア

        for i, note in enumerate(gui_notes):
            # 1. ピッチリストをCのfloat配列に変換
            pitch_data = np.array(note['pitch_list'], dtype=np.float32)
            pitch_ptr = pitch_data.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            
            # Python側でメモリが解放されないように参照を保持
            self._temp_pitch_refs.append(pitch_data)

            # 2. 構造体にセット
            c_notes_array[i].wav_path = note['wav'].encode('utf-8')
            c_notes_array[i].pitch_curve = pitch_ptr
            c_notes_array[i].pitch_length = len(pitch_data)

        # 3. C++エンジンの実行
        try:
            print(f"Rendering {note_count} notes...")
            self.lib.execute_render(c_notes_array, note_count, output_path.encode('utf-8'))
            print(f"○  Exported to: {output_path}")
        except Exception as e:
            print(f"✖️ Synthesis Error: {e}")

    # --- 再生・管理用 ---
    def play_result(self, filepath="result.wav"):
        if os.path.exists(filepath):
            data, fs = sf.read(filepath)
            sd.play(data, fs)

    def stop(self):
        sd.stop()




                        
