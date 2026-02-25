#ai_manager.py

import os
import sys
import logging
import json
import numpy as np
import onnxruntime as ort
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

class AIManager(QObject):
    """
    VO-SE Pro: AI推論マネージャー (強化版)

    - 音素辞書(JSON)を用いたテキスト解析機能を追加
    - ThreadPoolExecutor(max_workers=1) でGUIスレッドをブロックしない
    - CoreML / DirectML / CUDA / CPU の自動選択
    - 推論結果をノートのダイナミクス(onset, overlap, pre_utterance)として出力
    """

    finished = Signal(object)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.session = None
        self.model_path = self._get_model_path()
        
        # 音素辞書データの保持用
        self.phoneme_dict = {}
        self.dict_path = self._get_dict_path()

    # ============================================================
    # パス解決
    # ============================================================

    def _get_model_path(self) -> str:
        """PyInstaller 環境でも動作するモデルパス解決"""
        if getattr(sys, 'frozen', False):
            base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        else:
            # プロジェクト構造に合わせて調整してください
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
    # モデルおよび辞書の初期化
    # ============================================================

    def init_model(self) -> bool:
        """ハードウェアを自動検知してモデルと辞書を初期化"""
        try:
            # 1. 音素辞書の読み込み
            if os.path.exists(self.dict_path):
                with open(self.dict_path, 'r', encoding='utf-8') as f:
                    self.phoneme_dict = json.load(f)
                logger.info(f"Phoneme dictionary loaded from: {self.dict_path}")
            else:
                logger.warning(f"Phoneme dictionary not found at: {self.dict_path}. Using empty dict.")

            # 2. ONNXモデルの初期化
            if not os.path.exists(self.model_path):
                self.error.emit(f"Model not found: {self.model_path}")
                return False

            available = ort.get_available_providers()
            priority = [
                'CoreMLExecutionProvider',  # Apple Silicon
                'DmlExecutionProvider',     # Windows DirectML
                'CUDAExecutionProvider',    # NVIDIA GPU
                'CPUExecutionProvider',
            ]
            selected = [p for p in priority if p in available]

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
    # 音素解析ロジック (NEW)
    # ============================================================

    def text_to_phonemes(self, text: str) -> list:
        """
        テキストを音素記号のリストに変換する
        辞書にない場合は簡易的な文字分解を行うフォールバック付き
        """
        # 辞書の 'words' セクションから検索
        words_map = self.phoneme_dict.get("words", {})
        if text in words_map:
            return words_map[text]
        
        # 辞書にない場合：1文字ずつ分解（簡易実装）
        logger.debug(f"Word '{text}' not in dict, using fallback decomposition.")
        return list(text)

    # ============================================================
    # 非同期推論
    # ============================================================

    def analyze_async(self, input_context) -> None:
        """
        GUIを止めずに推論を実行。
        input_context が dict の場合はテキスト解析、
        list/ndarray の場合は波形解析として動作。
        """
        def task():
            try:
                if self.session is None:
                    if not self.init_model():
                        return
                
                # コンテキストの内容に応じて処理を分岐
                if isinstance(input_context, dict) and "text" in input_context:
                    # テキスト -> 音素変換 -> 数値推論の流れ
                    phonemes = self.text_to_phonemes(input_context["text"])
                    # 音素リストをモデルが理解できる数値形式に変換（embedding等を想定）
                    # ここでは例として既存の predict_onset に渡せる形式に整形
                    result = self.predict_from_phonemes(phonemes)
                else:
                    # 従来の波形ベース解析
                    result = self.predict_onset(input_context)
                
                self.finished.emit(result)
            except Exception as e:
                self.error.emit(f"AI Inference Error: {e}")

        self.executor.submit(task)

    # ============================================================
    # 推論実行部
    # ============================================================
    def predict_from_phonemes(self, phonemes: list) -> list:
        # モデルが期待する入力形状を動的に取得
        input_info = self.session.get_inputs()[0]
        expected_shape = input_info.shape  # 例: [None, None, 512]
    
        # 特徴量次元をモデルから読み取る（決め打ちをやめる）
        feature_dim = expected_shape[-1] if len(expected_shape) >= 3 else 512
    
        # 形状をモデルに合わせて生成
        dummy_input = np.zeros((1, len(phonemes), feature_dim), dtype=np.float32)
    
        outputs = self.session.run(
            None, {input_info.name: dummy_input}
        )
        return self._postprocess(outputs)

    def predict_onset(self, audio_data) -> list:
        """波形データからの同期推論実行"""
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
        data = np.array(audio_data, dtype=np.float32)
        if data.ndim == 1:
            data = data[np.newaxis, np.newaxis, :]
        return data

    def _postprocess(self, outputs) -> list:
        if not outputs or len(outputs) == 0:
            logger.error("_postprocess: empty outputs")
            return []

        raw_data = outputs[0]
        if raw_data.ndim != 2 or raw_data.shape[1] < 1:
            logger.error(f"_postprocess: unexpected output shape {raw_data.shape}")
            return []

        results = []
        for row in raw_data:
            # ONNXモデルの出力 [v0, v1, v2] を VO-SE Pro のパラメータにマッピング
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
        self.executor.shutdown(wait=False)
        logger.info("AIManager executor shut down.")
