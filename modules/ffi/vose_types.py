#vose_types.py
import ctypes
from typing import Iterable


class CNoteEvent(ctypes.Structure):
    """`include/vose_core.h` の NoteEvent と ABI を一致させる。"""

    _fields_ = [
        ("wav_path", ctypes.c_char_p),
        ("pitch_curve", ctypes.POINTER(ctypes.c_double)),
        ("pitch_length", ctypes.c_int),
        ("gender_curve", ctypes.POINTER(ctypes.c_double)),
        ("tension_curve", ctypes.POINTER(ctypes.c_double)),
        ("breath_curve", ctypes.POINTER(ctypes.c_double)),
    ]


def as_c_double_array(values: Iterable[float]) -> ctypes.Array[ctypes.c_double]:
    """Python iterable を C の `double[]` に変換する。"""

    seq = tuple(float(v) for v in values)
    return (ctypes.c_double * len(seq))(*seq)

def validate_note_event_layout():
    """CNoteEvent のレイアウト検証（必要に応じて実装）"""
    # 例: print(f"CNoteEvent size: {ctypes.sizeof(CNoteEvent)}")
    pass



__all__ = ["CNoteEvent", "as_c_double_array", "validate_note_event_layout"]
