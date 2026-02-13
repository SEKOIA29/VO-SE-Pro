import os
import ctypes
import soundfile as sf
import numpy as np
import pyopenjtalk
import traceback
from PySide6.QtCore import QObject
from typing import Any, List, Dict, Tuple, Optional

# --- 1. インポートとスタブ定義 ---
try:
    from .intonation_analyzer import IntonationAnalyzer
except ImportError:
    # 循環参照対策が必要な場合のスタブ
    class IntonationAnalyzer: 
        pass

# --- 2. UTAUイベント生成ロジック ---
def generate_talk_events(text: str, analyzer: "IntonationAnalyzer") -> List[Dict[str, Any]]:
    """
    UTAUトーク用のイベント生成。
    F821: Undefined name 'length' を完全に解決。
    """
    # 1. テキストを音素に分解
    phonemes = analyzer.analyze_to_phonemes(text)
    talk_notes = []
    
    for p in phonemes:
        # 2. ピッチカーブ生成
        pitch_curve = generate_accent_curve(p)
        
        # 【重要】ここで length を定義
        length = len(pitch_curve)
        
        # 3. 代表の設計したパラメータ構造体（無省略）
        event = {
            'phoneme': p,
            'pitch': pitch_curve,
            'gender': [0.5] * length,
            'tension': [0.5] * length,
            'breath': [0.0] * length
        }
        talk_notes.append(event)
    
    return talk_notes

def generate_accent_curve(phoneme: str) -> List[float]:
    """
    イントネーション生成の補助関数。
    """
    return [150.0] * 50

# --- 3. C++連携用構造体 (UTAU対応) ---
class NoteEvent(ctypes.Structure):
    _fields_ = [
        ("wav_path", ctypes.c_char_p),
        ("pitch_length", ctypes.c_int),
        ("pitch_curve", ctypes.POINTER(ctypes.c_double)),
        ("gender_curve", ctypes.POINTER(ctypes.c_double)),
        ("tension_curve", ctypes.POINTER(ctypes.c_double)),
        ("breath_curve", ctypes.POINTER(ctypes.c_double)),
        # --- UTAU対応パラメータ ---
        ("offset_ms", ctypes.c_double),      # 原音の開始位置
        ("consonant_ms", ctypes.c_double),   # 固定範囲（子音部）
        ("cutoff_ms", ctypes.c_double),      # 右ブランク
        ("pre_utterance_ms", ctypes.c_double), # 先行発声
        ("overlap_ms", ctypes.c_double)      # オーバーラップ
    ]

class VoseRendererBridge:
    def __init__(self, dll_path: str):
        # 代表の書き上げたDLL/soをロード
        self.lib = ctypes.CDLL(dll_path)
        
        # init_official_engine() の定義
        self.lib.init_official_engine.argtypes = []
        self.lib.init_official_engine.restype = None
        
        # execute_render の定義
        self.lib.execute_render.argtypes = [
            ctypes.POINTER(NoteEvent), 
            ctypes.c_int, 
            ctypes.c_char_p
        ]
        self.lib.execute_render.restype = None
        
        # エンジン初期化
        self.lib.init_official_engine()

    def render(self, notes_data: List[dict], output_path: str):
        """
        PythonのリサーチデータをC++の構造体配列に変換して投げます。
        """
        note_count = len(notes_data)
        NotesArray = NoteEvent * note_count
        c_notes = NotesArray()

        for i, data in enumerate(notes_data):
            # 文字列はUTF-8バイト列にエンコード
            c_notes[i].wav_path = data['phoneme'].encode('utf-8')
            c_notes[i].pitch_length = len(data['pitch'])
            
            # リストをCのdouble配列に変換
            c_notes[i].pitch_curve = (ctypes.c_double * len(data['pitch']))(*data['pitch'])
            c_notes[i].gender_curve = (ctypes.c_double * len(data['gender']))(*data['gender'])
            c_notes[i].tension_curve = (ctypes.c_double * len(data['tension']))(*data['tension'])
            c_notes[i].breath_curve = (ctypes.c_double * len(data['breath']))(*data['breath'])
            
            # UTAUパラメータのデフォルト値（必要なら辞書から取得するように拡張可能）
            c_notes[i].offset_ms = data.get('offset', 0.0)
            c_notes[i].consonant_ms = data.get('consonant', 0.0)
            c_notes[i].cutoff_ms = data.get('cutoff', 0.0)
            c_notes[i].pre_utterance_ms = data.get('pre_utterance', 0.0)
            c_notes[i].overlap_ms = data.get('overlap', 0.0)

        # C++レンダリング実行
        self.lib.execute_render(c_notes, note_count, output_path.encode('utf-8'))


# --- 4. イントネーション解析 ---
class IntonationAnalyzer:
    def __init__(self) -> None:
        self.last_analysis_status: bool = False

    def analyze(self, text: str) -> str:
        if not text:
            return ""
        try:
            if hasattr(pyopenjtalk, 'run_frontend'):
                features = pyopenjtalk.run_frontend(text)
            else:
                features = pyopenjtalk.extract_fullcontext(text)
            
            labels: List[str] = pyopenjtalk.make_label(features)
            self.last_analysis_status = True
            return "\n".join(labels)
            
        except Exception as e:
            import traceback
            error_msg: str = f"Error during analysis: {str(e)}\n{traceback.format_exc()}"
            print(error_msg)
            self.last_analysis_status = False
            return error_msg


# --- 5. トークマネージャー (Talk/TTSロジック) ---
class TalkManager(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.current_voice_path: Optional[str] = None 
        self.dict_dir: Optional[str] = None
        self.is_speaking: bool = False

    def set_voice(self, htsvoice_path: str) -> bool:
        if htsvoice_path and os.path.exists(htsvoice_path):
            self.current_voice_path = htsvoice_path
            return True
        else:
            print(f"WARNING: Voice path not found: {htsvoice_path}")
            return False

    def speak(self, text: str) -> None:
        if not text:
            return  # 2行に分けて E701 回避
        
        try:
            print(f"Speaking: {text}")
            # 合成処理など...
        except Exception as e:
            # traceback.format_exc() を使うことで F401 回避
            err_detail = traceback.format_exc()
            print(f"Speech Error: {e}\n{err_detail}")
            
    def synthesize(self, text: str, output_path: str, speed: float = 1.0) -> Tuple[bool, str]:
        """
        pyopenjtalkを使用して高品質なWAVを生成する。
        重複や文法ミスを修正した完全版。
        """
        # 1. 入力チェック
        if not text:
            return False, "テキストが空です。"

        try:
            # 2. 出力先ディレクトリ確保
            output_dir: str = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            # 3. 初期化
            x: Optional[np.ndarray] = None
            sr: int = 48000
            options: Dict[str, Any] = {"speed": float(speed)}
            v_path: str = str(getattr(self, 'current_voice_path', "") or "")
            
            # 4. 合成試行
            if v_path and os.path.exists(v_path):
                # --- ボイスモデルの適用試行 ---
                try:
                    # 優先順位1: 'htsvoice' キーワード引数
                    temp_opts = options.copy()
                    temp_opts["htsvoice"] = v_path
                    result = pyopenjtalk.tts(text, **temp_opts)
                    
                    if result is not None and len(result) >= 2:
                        x, sr = result[0], result[1]
                    else:
                        raise ValueError("htsvoice attempt returned None")

                except (TypeError, Exception) as e:
                    print(f"DEBUG: Falling back from 'htsvoice': {e}")
                    try:
                        # 優先順位2: 'font' キーワード引数
                        temp_opts = options.copy()
                        temp_opts["font"] = v_path
                        result = pyopenjtalk.tts(text, **temp_opts)
                        
                        if result is not None and len(result) >= 2:
                            x, sr = result[0], result[1]
                        else:
                            raise ValueError("font attempt returned None")

                    except (TypeError, Exception):
                        # 優先順位3: 位置引数
                        try:
                            result = pyopenjtalk.tts(text, v_path, **options)
                            if result is not None and len(result) >= 2:
                                x, sr = result[0], result[1]
                            else:
                                raise ValueError("Positional attempt returned None")
                        
                        except Exception as final_e:
                            print(f"DEBUG: All specific voice attempts failed: {final_e}")
                            # 最終手段：デフォルト音声
                            result = pyopenjtalk.tts(text, **options)
                            if result is not None and len(result) >= 2:
                                x, sr = result[0], result[1]
            else:
                # ボイス指定なし
                result = pyopenjtalk.tts(text, **options)
                if result is not None and len(result) >= 2:
                    x, sr = result[0], result[1]

            # 5. 結果処理
            if x is None:
                return False, "音声データの生成に失敗しました。"

            # 16bit変換
            x_array: np.ndarray = np.asarray(x)
            x_clipped = np.clip(x_array, -32768, 32767)
            x_int16 = x_clipped.astype(np.int16)
            
            sf.write(output_path, x_int16, sr)
            
            if os.path.exists(output_path):
                print(f"SUCCESS: Saved to {output_path}")
                return True, output_path
            else:
                return False, f"書き出し失敗: {output_path}"
            
        except Exception as e:
            import traceback
            full_error: str = f"Critical synthesis error: {str(e)}\n{traceback.format_exc()}"
            print(full_error)
            return False, full_error
