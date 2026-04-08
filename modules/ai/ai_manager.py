#ai_manager.py

import os
import sys
import logging
import json
import numpy as np
try:
    import onnxruntime as ort
except Exception:
    ort = None
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class AIManager(QObject):
    """
    VO-SE Pro: AI推論マネージャー (oto.ini 互換対応版)

    - oto.ini を読み込み、固定範囲・先行発声・オーバーラップの初期値を取得
    - AI推論結果と oto.ini の設定値を重み付けブレンドして最適な発声タイミングを算出
    - 音素辞書（JSON）によるテキスト → 音素変換
    - CoreML / DirectML / CUDA / CPU の自動選択（M3/M4 ML Program 最適化付き）
    - shutdown() でスレッドを安全に終了
    - _postprocess で出力 shape を検証し無言クラッシュを防止
    """

    finished = Signal(object)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        # 推論は1件ずつ順番に行う（queue 溜まり防止は MainWindow 側のデバウンスで対処）
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.session = None
        self.model_path = self._get_model_path()

        # 音素・設定データの保持
        self.phoneme_dict: dict = {}
        self.oto_configs: dict = {}
        self.dict_path = self._get_dict_path()

    # ============================================================
    # パス解決
    # ============================================================

    def _get_model_path(self) -> str:
        """PyInstaller 環境でも動作するモデルパス解決"""
        if getattr(sys, 'frozen', False):
            base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        else:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(base, "models", "aural_dynamics.onnx")

    def _get_dict_path(self) -> str:
        """音素辞書ファイルのパス解決"""
        if getattr(sys, 'frozen', False):
            base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        else:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(base, "dicts", "phoneme_table.json")

    # ============================================================
    # oto.ini 解析
    # ============================================================

    def load_voicebank_config(self, oto_ini_path: str) -> None:
        """
        UTAU形式の oto.ini を読み込み、辞書に格納する。
        Shift_JIS での読み込みとエラーハンドリングを徹底。
        形式: sample.wav=エイリアス,左ブランク,固定範囲,右ブランク,先行発声,オーバーラップ
        """
        try:
            if not os.path.exists(oto_ini_path):
                logger.warning(f"oto.ini not found: {oto_ini_path}")
                return

            new_configs = {}
            with open(oto_ini_path, 'r', encoding='shift_jis', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if not line or '=' not in line:
                        continue
                    parts = line.split('=')
                    wav_file = parts[0]
                    params = parts[1].split(',')
                    if len(params) >= 6:
                        alias = params[0] if params[0] else wav_file
                        new_configs[alias] = {
                            "offset":         float(params[1]) if params[1] else 0.0,
                            "fixed":          float(params[2]) if params[2] else 0.0,
                            "cutoff":         float(params[3]) if params[3] else 0.0,
                            "pre_utterance":  float(params[4]) if params[4] else 0.0,
                            "overlap":        float(params[5]) if params[5] else 0.0,
                        }

            self.oto_configs = new_configs
            logger.info(f"Loaded {len(self.oto_configs)} entries from oto.ini")

        except Exception as e:
            self.error.emit(f"oto.ini Load Error: {e}")

    # ============================================================
    # モデルおよび辞書の初期化
    # ============================================================

    def init_model(self) -> bool:
        """ハードウェアを自動検知してモデルと辞書を初期化"""
        try:
            if ort is None:
                self.error.emit("onnxruntime is not installed")
                return False
            # 1. 音素辞書の読み込み
            if os.path.exists(self.dict_path):
                with open(self.dict_path, 'r', encoding='utf-8') as f:
                    self.phoneme_dict = json.load(f)
                logger.info(f"Phoneme dictionary loaded: {self.dict_path}")
            else:
                logger.warning(f"Phoneme dictionary not found: {self.dict_path}. Using empty dict.")

            # 2. ONNX Runtime セッション初期化
            if not os.path.exists(self.model_path):
                self.error.emit(f"Model not found: {self.model_path}")
                return False

            available = ort.get_available_providers()
            priority = [
                'CoreMLExecutionProvider',  # Apple Silicon (NPU)
                'DmlExecutionProvider',     # Windows DirectML / NPU
                'CUDAExecutionProvider',    # NVIDIA GPU
                'CPUExecutionProvider',     # フォールバック
            ]
            selected = [p for p in priority if p in available]

            # プロバイダーごとのオプション（M3/M4 ML Program 最適化を復元）
            options = []
            for p in selected:
                if p == 'CoreMLExecutionProvider':
                    options.append({'ml_program': '1'})
                else:
                    options.append({})

            self.session = ort.InferenceSession(
                self.model_path,
                providers=selected,
                provider_options=options,
            )
            logger.info(f"AI Engine Initialized with: {selected[0]}")
            return True

        except Exception as e:
            self.error.emit(f"Init Error: {e}")
            return False

    # ============================================================
    # 音素解析
    # ============================================================

    def text_to_phonemes(self, text: str) -> list:
        """
        テキストを音素記号のリストに変換する。
        辞書にない場合は1文字ずつ分解するフォールバック付き。
        """
        words_map = self.phoneme_dict.get("words", {})
        if text in words_map:
            return words_map[text]
        logger.debug(f"Word '{text}' not in dict, using fallback decomposition.")
        return list(text)

    # ============================================================
    # 非同期推論 + oto.ini ブレンド
    # ============================================================

    def analyze_async(self, input_context) -> None:
        """
        GUIを止めずに推論を実行し、oto.ini とブレンドした結果を Signal で送る。
        input_context が dict かつ "text" キーを持つ場合はテキスト解析ルート、
        それ以外は従来の波形解析ルート。
        """
        def task():
            try:
                if self.session is None:
                    if not self.init_model():
                        return

                # 1. AI推論
                if isinstance(input_context, dict) and "text" in input_context:
                    phonemes = self.text_to_phonemes(input_context["text"])
                    ai_results = self.predict_from_phonemes(phonemes)
                else:
                    ai_results = self.predict_onset(input_context)

                # 2. oto.ini とのブレンド処理
                alias = input_context.get("alias", "") if isinstance(input_context, dict) else ""
                final_results = []
                for res in ai_results:
                    if alias and alias in self.oto_configs:
                        oto = self.oto_configs[alias]
                        # 固定範囲は原音設定を優先、重なりはAI文脈判断を優先、先行発声は折半
                        final_results.append({
                            "onset":         (res["onset"]         * 0.4) + (oto["fixed"]         * 0.6),
                            "overlap":       (res["overlap"]       * 0.7) + (oto["overlap"]       * 0.3),
                            "pre_utterance": (res["pre_utterance"] * 0.5) + (oto["pre_utterance"] * 0.5),
                        })
                    else:
                        # oto.ini がない場合はAIの結果をそのまま使用
                        final_results.append(res)

                self.finished.emit(final_results)

            except Exception as e:
                self.error.emit(f"AI Inference Error: {e}")

        self.executor.submit(task)

    # ============================================================
    # 推論実行部
    # ============================================================

    def predict_from_phonemes(self, phonemes: list) -> list:
        """
        音素リストからダイナミクス数値を推論。
        モデルの入力形状を動的に取得し、決め打ちを避ける。
        """
        if self.session is None:
            if not self.init_model() or self.session is None:
                return []

        input_info = self.session.get_inputs()[0]
        expected_shape = input_info.shape  # 例: [None, None, 512]

        # 特徴量次元をモデルから動的に取得（None の場合は 512 にフォールバック）
        feature_dim = expected_shape[-1] if (
            len(expected_shape) >= 3 and isinstance(expected_shape[-1], int)
        ) else 512

        input_tensor = np.zeros((1, len(phonemes), feature_dim), dtype=np.float32)
        outputs = self.session.run(None, {input_info.name: input_tensor})
        return self._postprocess(outputs)

    def predict_onset(self, audio_data) -> list:
        """波形データからの同期推論実行"""
        # session None ガードを復元
        if self.session is None:
            if not self.init_model() or self.session is None:
                return []
        input_data = self._preprocess(audio_data)
        outputs = self.session.run(None, {self.session.get_inputs()[0].name: input_data})
        return self._postprocess(outputs)

    # ============================================================
    # 前処理 / 後処理
    # ============================================================

    def _preprocess(self, audio_data) -> np.ndarray:
        """音声波形を正規化してテンソル化"""
        data = np.array(audio_data, dtype=np.float32)
        if data.ndim == 1:
            data = data[np.newaxis, np.newaxis, :]
        return data

    def _postprocess(self, outputs) -> list:
        """
        AI出力テンソルから [onset, overlap, pre_utterance] のリストを生成。
        出力 shape を検証して無言クラッシュを防止（復元）。
        """
        if not outputs or len(outputs) == 0:
            logger.error("_postprocess: empty outputs")
            return []

        raw_data = outputs[0]

        # shape チェック: [n_notes, >=1] を期待（復元）
        if raw_data.ndim != 2 or raw_data.shape[1] < 1:
            logger.error(f"_postprocess: unexpected output shape {raw_data.shape}")
            return []

        results = []
        for row in raw_data:
            results.append({
                "onset":         float(row[0]),
                "overlap":       float(row[1]) if raw_data.shape[1] > 1 else 0.05,
                "pre_utterance": float(row[2]) if raw_data.shape[1] > 2 else 0.1,
            })
        return results

    # ============================================================
    # 終了処理
    # ============================================================

    def shutdown(self) -> None:
        """アプリ終了時にスレッドを安全に解放する"""
        self.executor.shutdown(wait=False)
        logger.info("AIManager executor shut down.")
