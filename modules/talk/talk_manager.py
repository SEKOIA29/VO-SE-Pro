# talk_manager.py
"""
VO-SE Cut Studio — コアエンジン統合モジュール
- IntonationAnalyzer : pyopenjtalk による音素・F0解析
- generate_talk_events: トークイベント生成
- NoteEvent           : C++ 構造体バインディング
- VoseRendererBridge  : DLL/dylib ブリッジ
- TalkManager         : 音声合成マネージャー

修正点:
  [FIX-1] VoseRendererBridge.render(): wav_path に音素文字列ではなく
          実際の WAV ファイルパスを渡すよう修正。
          voice_library 引数を追加し get_wav_path() で解決する。
  [FIX-2] TalkManager.speak(): TODO だった再生処理を sounddevice で実装。
          再生中フラグ (is_speaking) を正しく管理する。
  [FIX-3] TalkManager.synthesize(): float32 → int16 変換時の
          クリップ処理を修正（元コードは範囲が逆だった）。
  [FIX-4] _tts_with_voice(): pyopenjtalk の戻り値が ndarray 単体の
          バージョンにも対応するフォールバックを追加。
"""

from __future__ import annotations

import os
import ctypes
import platform
import tempfile
import traceback
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import pyopenjtalk
import sounddevice as sd
import soundfile as sf
from PySide6.QtCore import QObject, Signal


# ══════════════════════════════════════════════════════════════
# 0. 型プロトコル（voice_library の duck typing）
# ══════════════════════════════════════════════════════════════

class VoiceLibraryProtocol(Protocol):
    """
    VoseRendererBridge が必要とする音源ライブラリのインターフェース。
    VoiceManager など既存クラスがこのメソッドを持っていれば型チェックを通過する。
    """
    def get_wav_path(self, phoneme: str) -> str:
        """
        音素名（例: "a", "k", "ch"）から対応 WAV ファイルの
        絶対パスを返す。見つからない場合は空文字列 "" を返す。
        """
        ...


# ══════════════════════════════════════════════════════════════
# 1. データクラス
# ══════════════════════════════════════════════════════════════

@dataclass
class AccentPhrase:
    """アクセント句の解析結果"""
    text: str
    mora_count: int
    accent_position: int
    f0_values: list[float] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# 2. イントネーション解析
# ══════════════════════════════════════════════════════════════

class IntonationAnalyzer:
    """
    pyopenjtalk を使用したテキスト解析クラス。
    音素列・フルコンテキストラベル・アクセント句を返す。
    """

    def __init__(self) -> None:
        self.last_analysis_status: bool = False

    # ----------------------------------------------------------
    # 公開 API
    # ----------------------------------------------------------

    def analyze(self, text: str) -> str:
        """
        フルコンテキストラベルを改行区切り文字列で返す。
        GUI 表示やデバッグ用途向け。
        """
        if not text:
            return ""
        try:
            labels: list[str] = self._get_labels(text)
            self.last_analysis_status = True
            return "\n".join(labels)
        except Exception as e:
            self.last_analysis_status = False
            msg = f"Error during analysis: {e}\n{traceback.format_exc()}"
            print(msg)
            return msg

    def analyze_to_phonemes(self, text: str) -> list[str]:
        """
        テキストから音素列を抽出して返す。
        pyopenjtalk.g2p() を使用（バージョン間で最も安定した API）。

        例: "こんにちは" → ["k", "o", "N", "n", "i", "ch", "i", "w", "a"]
        """
        if not text:
            return []
        try:
            phoneme_str: str = pyopenjtalk.g2p(text, kana=False)
            return [p for p in phoneme_str.split() if p]
        except Exception as e:
            print(f"[IntonationAnalyzer] g2p error: {e}")
            return []

    def analyze_to_accent_phrases(self, text: str) -> list[AccentPhrase]:
        """
        アクセント句リストを返す（VO-SE ピッチ編集用）。
        """
        if not text:
            return []
        try:
            labels = self._get_labels(text)
            return self._parse_labels(labels)
        except Exception as e:
            print(f"[IntonationAnalyzer] accent parse error: {e}")
            return []

    # ----------------------------------------------------------
    # 内部実装
    # ----------------------------------------------------------

    def _get_labels(self, text: str) -> list[str]:
        """pyopenjtalk のバージョン差を吸収してラベルを取得する"""
        if hasattr(pyopenjtalk, "run_frontend"):
            features = pyopenjtalk.run_frontend(text)
        else:
            features = pyopenjtalk.extract_fullcontext(text)
        return pyopenjtalk.make_label(features)

    def _parse_labels(self, labels: list[str]) -> list[AccentPhrase]:
        """
        HTS フルコンテキストラベルからアクセント句・F0 を抽出する。
        ラベル形式の A: フィールド（アクセント型）と F0 推定値を利用。
        """
        phrases: list[AccentPhrase] = []
        current_moras: list[tuple[str, float]] = []
        accent_pos: int = 0
        prev_phrase_id: str = ""

        for label in labels:
            parts = label.split("-")
            phoneme = parts[1] if len(parts) > 1 else "?"
            phrase_id = self._extract_field(label, "/E:")

            if phrase_id != prev_phrase_id and current_moras:
                phrases.append(AccentPhrase(
                    text="".join(m[0] for m in current_moras),
                    mora_count=len(current_moras),
                    accent_position=accent_pos,
                    f0_values=[m[1] for m in current_moras],
                ))
                current_moras = []

            try:
                a_field = self._extract_field(label, "/A:")
                accent_pos = int(a_field.split("_")[0]) if a_field else 0
            except (ValueError, IndexError):
                accent_pos = 0

            f0 = 130.0 if accent_pos == 0 else 150.0 + accent_pos * 5.0

            if phoneme not in ("sil", "pau", "?"):
                current_moras.append((phoneme, f0))

            prev_phrase_id = phrase_id

        if current_moras:
            phrases.append(AccentPhrase(
                text="".join(m[0] for m in current_moras),
                mora_count=len(current_moras),
                accent_position=accent_pos,
                f0_values=[m[1] for m in current_moras],
            ))

        return phrases

    @staticmethod
    def _extract_field(label: str, key: str) -> str:
        """HTS ラベルから特定フィールドの値を抽出する"""
        idx = label.find(key)
        if idx == -1:
            return ""
        start = idx + len(key)
        end = label.find("/", start)
        return label[start:end] if end != -1 else label[start:]


# ══════════════════════════════════════════════════════════════
# 3. トークイベント生成
# ══════════════════════════════════════════════════════════════

def generate_accent_curve(phoneme: str, accent_pos: int = 0) -> list[float]:
    """
    音素とアクセント位置からピッチカーブを生成する。
    将来的には AccentPhrase.f0_values を直接使用することを推奨。
    """
    base_f0 = 150.0 + accent_pos * 5.0
    voiced = phoneme in list("aeiou") + ["N", "m", "n", "r", "w", "y", "v"]
    return [base_f0 if voiced else 0.0] * 50


def generate_talk_events(
    text: str,
    analyzer: IntonationAnalyzer,
    voice_library: VoiceLibraryProtocol,  # [FIX-1] 追加: WAVパス解決に使用
) -> list[dict[str, Any]]:
    """
    テキストから VO-SE エンジン用トークイベントリストを生成する。

    Returns:
        List of dicts with keys:
            phoneme, wav_path, pitch, gender, tension, breath,
            offset, consonant, cutoff, pre_utterance, overlap
    """
    phonemes = analyzer.analyze_to_phonemes(text)
    accent_phrases = analyzer.analyze_to_accent_phrases(text)

    accent_map: dict[int, int] = {}
    idx = 0
    for phrase in accent_phrases:
        for _ in range(phrase.mora_count):
            accent_map[idx] = phrase.accent_position
            idx += 1

    talk_notes: list[dict[str, Any]] = []
    for i, phoneme in enumerate(phonemes):
        accent_pos = accent_map.get(i, 0)
        pitch_curve = generate_accent_curve(phoneme, accent_pos)
        length = len(pitch_curve)

        # [FIX-1] wav_path を音素文字列ではなく実際のファイルパスで解決する
        wav_path = voice_library.get_wav_path(phoneme)
        if not wav_path:
            print(f"[generate_talk_events] WAV not found for phoneme: '{phoneme}' — skipping")
            continue

        talk_notes.append({
            "phoneme":       phoneme,
            "wav_path":      wav_path,      # [FIX-1] 実WAVパスを格納
            "pitch":         pitch_curve,
            "gender":        [0.5] * length,
            "tension":       [0.5] * length,
            "breath":        [0.1] * length,
            "offset":        0.0,
            "consonant":     0.0,
            "cutoff":        0.0,
            "pre_utterance": 0.0,
            "overlap":       0.0,
        })

    return talk_notes


# ══════════════════════════════════════════════════════════════
# 4. C++ 構造体バインディング
# ══════════════════════════════════════════════════════════════

class NoteEvent(ctypes.Structure):
    """
    VO-SE C++ エンジン用構造体。
    C++ 側の struct NoteEvent とメモリ配置を完全一致させること。
    """
    _fields_ = [
        ("wav_path",           ctypes.c_char_p),
        ("pitch_length",       ctypes.c_int),
        ("pitch_curve",        ctypes.POINTER(ctypes.c_double)),
        ("gender_curve",       ctypes.POINTER(ctypes.c_double)),
        ("tension_curve",      ctypes.POINTER(ctypes.c_double)),
        ("breath_curve",       ctypes.POINTER(ctypes.c_double)),
        ("offset_ms",          ctypes.c_double),
        ("consonant_ms",       ctypes.c_double),
        ("cutoff_ms",          ctypes.c_double),
        ("pre_utterance_ms",   ctypes.c_double),
        ("overlap_ms",         ctypes.c_double),
    ]


class VoseRendererBridge:
    """
    Python ↔ C++ DLL/dylib ブリッジ。
    GC 対策として配列参照を keep_alive に保持する。
    """

    def __init__(self, dll_path: str) -> None:
        try:
            if platform.system() == "Darwin":
                self.lib = ctypes.CDLL(dll_path, mode=ctypes.RTLD_GLOBAL)
            else:
                self.lib = ctypes.CDLL(dll_path)

            self.lib.init_official_engine.argtypes = []
            self.lib.init_official_engine.restype = None

            self.lib.execute_render.argtypes = [
                ctypes.POINTER(NoteEvent),
                ctypes.c_int,
                ctypes.c_char_p,
            ]
            self.lib.execute_render.restype = None

            self.lib.init_official_engine()
            print(f"✅ VO-SE Engine Initialized: {dll_path}")

        except Exception as e:
            print(f"❌ Engine Load Error: {e}\n{traceback.format_exc()}")
            self.lib = None

    def render(
        self,
        notes_data: list[dict[str, Any]],
        output_path: str,
        # [FIX-1] voice_library 引数を削除:
        #   generate_talk_events() の時点で wav_path が解決済みのため不要
    ) -> bool:
        """
        Python データを NoteEvent 配列に変換して C++ レンダラーに渡す。

        notes_data の各要素には "wav_path" キーに実 WAV パスが
        入っていることを前提とする（generate_talk_events() で保証）。

        Returns:
            True on success, False on failure.
        """
        if self.lib is None:
            print("❌ render() called but engine is not loaded.")
            return False

        if not notes_data:
            print("⚠️ render() called with empty notes_data.")
            return False

        note_count = len(notes_data)
        NotesArray = NoteEvent * note_count
        c_notes = NotesArray()

        keep_alive: list[Any] = []

        for i, data in enumerate(notes_data):
            p_arr = (ctypes.c_double * len(data["pitch"]))(*data["pitch"])
            g_arr = (ctypes.c_double * len(data["gender"]))(*data["gender"])
            t_arr = (ctypes.c_double * len(data["tension"]))(*data["tension"])
            b_arr = (ctypes.c_double * len(data["breath"]))(*data["breath"])
            keep_alive.extend([p_arr, g_arr, t_arr, b_arr])

            # [FIX-1] "phoneme" ではなく "wav_path" を C++ 側に渡す
            wav_path: str = data.get("wav_path", "")
            if not wav_path or not os.path.exists(wav_path):
                print(f"❌ WAV not found at render time: '{wav_path}' — aborting")
                return False

            c_notes[i].wav_path         = wav_path.encode("utf-8")
            c_notes[i].pitch_length     = len(data["pitch"])
            c_notes[i].pitch_curve      = p_arr
            c_notes[i].gender_curve     = g_arr
            c_notes[i].tension_curve    = t_arr
            c_notes[i].breath_curve     = b_arr
            c_notes[i].offset_ms        = data.get("offset",        0.0)
            c_notes[i].consonant_ms     = data.get("consonant",     0.0)
            c_notes[i].cutoff_ms        = data.get("cutoff",        0.0)
            c_notes[i].pre_utterance_ms = data.get("pre_utterance", 0.0)
            c_notes[i].overlap_ms       = data.get("overlap",       0.0)

        try:
            self.lib.execute_render(c_notes, note_count, output_path.encode("utf-8"))
            print(f"🎬 Render finished: {output_path}")
            return True
        except Exception as e:
            print(f"❌ execute_render error: {e}\n{traceback.format_exc()}")
            return False


# ══════════════════════════════════════════════════════════════
# 5. 音声合成マネージャー
# ══════════════════════════════════════════════════════════════

class TalkManager(QObject):
    """
    pyopenjtalk を使用した TTS マネージャー。
    htsvoice の切替・フォールバックを自動処理する。

    シグナル:
        speak_started  : 読み上げ開始時
        speak_finished : 読み上げ完了時（成功・失敗を問わず）
        speak_error    : エラー発生時（エラーメッセージを emit）
    """

    speak_started  = Signal()
    speak_finished = Signal()
    speak_error    = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.current_voice_path: str | None = None
        self.is_speaking: bool = False

    # ----------------------------------------------------------
    # ボイス設定
    # ----------------------------------------------------------

    def set_voice(self, htsvoice_path: str) -> bool:
        if htsvoice_path and os.path.exists(htsvoice_path):
            self.current_voice_path = htsvoice_path
            return True
        print(f"⚠️ Voice path not found: {htsvoice_path}")
        return False

    # ----------------------------------------------------------
    # スピーク（再生まで行う）  [FIX-2] 実装済み
    # ----------------------------------------------------------

    def speak(self, text: str, speed: float = 1.0) -> None:
        """
        テキストを読み上げる（合成 → sounddevice 再生まで同期実行）。

        GUI から呼ぶ場合は QThread でラップして UI をブロックしないこと。
        例:
            from PySide6.QtCore import QThreadPool, QRunnable
            class _SpeakTask(QRunnable):
                def __init__(self, mgr, text): ...
                def run(self): self.mgr.speak(text)
            QThreadPool.globalInstance().start(_SpeakTask(self.talk_manager, text))
        """
        if not text or self.is_speaking:
            return

        self.is_speaking = True
        self.speak_started.emit()
        tmp_path: str | None = None 

        try:
            # 一時ファイルに合成して再生
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            ok, result = self.synthesize(text, tmp_path, speed=speed)
            if not ok:
                self.speak_error.emit(result)
                return

            # sounddevice で同期再生
            audio_data, sample_rate = sf.read(tmp_path, dtype="float32")
            sd.play(audio_data, sample_rate)
            sd.wait()  # 再生完了まで待機

        except Exception as e:
            msg = f"speak() error: {e}\n{traceback.format_exc()}"
            print(msg)
            self.speak_error.emit(msg)
        finally:
            self.is_speaking = False
            self.speak_finished.emit()
          
            # 一時ファイルを削除
            try:
                if "tmp_path" in locals() and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    # ----------------------------------------------------------
    # WAV 合成
    # ----------------------------------------------------------

    def synthesize(
        self,
        text: str,
        output_path: str,
        speed: float = 1.0,
    ) -> tuple[bool, str]:
        """
        テキストを WAV に合成して output_path に保存する。

        Returns:
            (True, output_path) on success
            (False, error_message) on failure
        """
        if not text:
            return False, "テキストが空です。"

        try:
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            x: np.ndarray | None = None
            sr: int = 48000
            options: dict[str, Any] = {"speed": float(speed)}
            voice = self.current_voice_path or ""

            if voice and os.path.exists(voice):
                x, sr = self._tts_with_voice(text, voice, options)
            else:
                x, sr = self._tts_default(text, options)

            if x is None:
                return False, "音声データの生成に失敗しました。"

            # [FIX-3] float32 の場合は int16 スケールに変換してからクリップ
            x_arr = np.asarray(x)
            if x_arr.dtype in (np.float32, np.float64):
                # pyopenjtalk は -32768〜32767 スケールの float を返す場合がある
                # 念のため絶対値が 1.0 以下なら 32767 倍してスケール変換
                if np.abs(x_arr).max() <= 1.0:
                    x_arr = x_arr * 32767.0
            x_int16 = np.clip(x_arr, -32768, 32767).astype(np.int16)
            sf.write(output_path, x_int16, sr)

            if os.path.exists(output_path):
                print(f"✅ Saved: {output_path}")
                return True, output_path

            return False, f"書き出し失敗: {output_path}"

        except Exception as e:
            msg = f"Critical synthesis error: {e}\n{traceback.format_exc()}"
            print(msg)
            return False, msg

    # ----------------------------------------------------------
    # 内部実装
    # ----------------------------------------------------------

    def _tts_with_voice(
        self,
        text: str,
        voice: str,
        options: dict[str, Any],
    ) -> tuple[np.ndarray | None, int]:
        """
        指定ボイスで TTS を試みる。
        htsvoice → font → デフォルトの順でフォールバック。

        [FIX-4] pyopenjtalk の戻り値が ndarray 単体の場合にも対応。
        """
        for key in ("htsvoice", "font"):
            try:
                result = pyopenjtalk.tts(text, **{**options, key: voice})
                if result is None:
                    continue
                # タプル (ndarray, int) または ndarray 単体を許容
                if isinstance(result, tuple) and len(result) >= 2:
                    return result[0], int(result[1])
                if isinstance(result, np.ndarray):
                    return result, 48000
            except (TypeError, Exception) as e:
                print(f"DEBUG: '{key}' kwarg failed: {e}")

        print("DEBUG: Falling back to default voice")
        return self._tts_default(text, options)

    @staticmethod
    def _tts_default(
        text: str,
        options: dict[str, Any],
    ) -> tuple[np.ndarray | None, int]:
        """
        デフォルトボイスで TTS を実行する。

        [FIX-4] ndarray 単体の戻り値にも対応。
        """
        result = pyopenjtalk.tts(text, **options)
        if result is None:
            return None, 48000
        if isinstance(result, tuple) and len(result) >= 2:
            return result[0], int(result[1])
        if isinstance(result, np.ndarray):
            return result, 48000
        return None, 48000
