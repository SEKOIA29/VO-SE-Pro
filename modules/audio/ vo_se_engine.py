# vo_se_engine.py


import ctypes
import os
import platform
import sys
import numpy as np
import sounddevice as sd
import soundfile as sf

# ==========================================================================
# C言語エンジン互換の構造体定義 (ctypes) - パラメーター拡張版
# ==========================================================================
class CNoteEvent(ctypes.Structure):
    _fields_ = [
        ("wav_path", ctypes.c_char_p),           # 音源WAVのフルパス
        ("pitch_curve", ctypes.POINTER(ctypes.c_float)),  # Hz配列
        ("pitch_length", ctypes.c_int),
        # --- 多重パラメーター拡張領域 ---
        ("gender_curve", ctypes.POINTER(ctypes.c_float)), # 性別変化(0.0-1.0)
        ("tension_curve", ctypes.POINTER(ctypes.c_float)),# 張り(0.0-1.0)
        ("breath_curve", ctypes.POINTER(ctypes.c_float))  # 吐息(0.0-1.0)
    ]

# ==========================================================================
# メインエンジンクラス
# ==========================================================================
class VO_SE_Engine:
    def __init__(self, voice_lib_dir="voices"):
        self.lib = self._load_core_library()
        self._temp_refs = []  # GC（メモリ解放）から守るためのリスト
        self.sample_rate = 44100
        
        # 音源ライブラリのパス設定
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.voice_lib_path = os.path.join(base_dir, voice_lib_dir)
        self.oto_map = {}
        self.refresh_voice_library()

    def _load_core_library(self):
        """ビルドした vose_core.dll / dylib をロード"""
        ext = ".dll" if platform.system() == "Windows" else ".dylib"
        # 実行ファイルと同階層またはbinフォルダ
        path = os.path.join(os.path.dirname(__file__), f"vose_core{ext}")
        
        if os.path.exists(path):
            try:
                lib = ctypes.CDLL(os.path.abspath(path))
                # C側の関数定義: void execute_render(CNoteEvent* notes, int count, const char* out)
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
        """voicesフォルダ内のWAVをスキャン"""
        if not os.path.exists(self.voice_lib_path):
            os.makedirs(self.voice_lib_path, exist_ok=True)
            return
        for file in os.listdir(self.voice_lib_path):
            if file.endswith(".wav"):
                lyric = os.path.splitext(file)[0]
                self.oto_map[lyric] = os.path.abspath(os.path.join(self.voice_lib_path, file))

    def export_to_wav(self, vocal_data, tempo, file_path):
        """
        MainWindowから渡された多重パラメーター情報をCエンジンに渡す
        vocal_data: [{'note': 60, 'lyric': 'あ', 'start_time': 0, ...}]
        """
        if not self.lib or not vocal_data:
            return

        note_count = len(vocal_data)
        c_notes_array = (CNoteEvent * note_count)()
        self._temp_refs = [] # 以前のメモリ参照をクリア

        for i, data in enumerate(vocal_data):
            lyric = data.get('lyric')
            wav_path = self.oto_map.get(lyric)

            if not wav_path:
                print(f"ʕ⁎̯͡⁎ʔ༄ Missing: {lyric}")
                continue

            # 1. 各パラメーターをnumpy配列に変換（Cのfloat*に対応）
            # 時間解像度に合わせてグラフからサンプリング
            # ここでは簡単のため各100ポイントの配列として渡す例
            p_len = 100 
            
            # --- 配列生成と保護 ---
            pitch = np.zeros(p_len, dtype=np.float32) # 本来はHz曲線を計算して入れる
            gender = np.full(p_len, 0.5, dtype=np.float32)
            tension = np.full(p_len, 0.5, dtype=np.float32)
            breath = np.full(p_len, 0.0, dtype=np.float32)

            self._temp_refs.extend([pitch, gender, tension, breath]) # GC回避

            # 2. C構造体にポインタをセット
            c_notes_array[i].wav_path = wav_path.encode('utf-8')
            c_notes_array[i].pitch_curve = pitch.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            c_notes_array[i].gender_curve = gender.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            c_notes_array[i].tension_curve = tension.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            c_notes_array[i].breath_curve = breath.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            c_notes_array[i].pitch_length = p_len

        # 3. Cエンジン実行
        try:
            full_out_path = os.path.abspath(file_path)
            self.lib.execute_render(c_notes_array, note_count, full_out_path.encode('utf-8'))
            print(f"✔ Render Finished: {full_out_path}")
        except Exception as e:
            print(f"✖ Synthesis Error: {e}")

    # --- 再生制御 ---
    def play(self, filepath):
        if filepath and os.path.exists(filepath):
            data, fs = sf.read(filepath)
            sd.play(data, fs)

    def stop(self):
        sd.stop()
