import ctypes
import os

# 構造体の定義
class NoteEvent(ctypes.Structure):
    _fields_ = [
        ("wav_path", ctypes.c_char_p),
        ("pitch_curve", ctypes.POINTER(ctypes.c_float)),
        ("pitch_length", ctypes.c_int)
    ]

class VoseEngine:
    def __init__(self):
        # dllの場所を指定（main.pyからの相対パス）
        dll_path = os.path.join(os.path.dirname(__file__), "bin", "vose_core.dll")
        self.lib = ctypes.CDLL(dll_path)
        
        # 関数の設定
        self.lib.execute_render.argtypes = [
            ctypes.POINTER(NoteEvent),
            ctypes.c_int,
            ctypes.c_char_p
        ]

    def render(self, notes_data, output_path="output.wav"):
        num_notes = len(notes_data)
        c_notes = (NoteEvent * num_notes)()
        keep_alive = []

        for i, data in enumerate(notes_data):
            # HzリストをCの配列に変換
            pitches = data['pitches']
            c_pitches = (ctypes.c_float * len(pitches))(*pitches)
            keep_alive.append(c_pitches)

            c_notes[i].wav_path = data['wav'].encode('utf-8')
            c_notes[i].pitch_curve = c_pitches
            c_notes[i].pitch_length = len(pitches)

        # 実行
        self.lib.execute_render(c_notes, num_notes, output_path.encode('utf-8'))
