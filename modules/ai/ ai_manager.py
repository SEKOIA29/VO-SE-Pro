#ai_manager.py

import os
import sys
import logging
import numpy as np
import onnxruntime as ort
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class AIManager(QObject):
    """
    VO-SE Pro: AI推論マネージャー

    - ThreadPoolExecutor(max_workers=1) でGUIスレッドをブロックしない
    - Signal/Slot で安全にメインスレッドへ結果を返す
    - CoreML / DirectML / CUDA / CPU の優先順位で最適なプロバイダーを自動選択
    - PyInstaller 対応のパス解決
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

    # ============================================================
    # パス解決
    # ============================================================

    def _get_model_path(self) -> str:
        """PyInstaller 環境でも動作するパス解決"""
        if getattr(sys, 'frozen', False):
            base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        else:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(base, "models", "aural_dynamics.onnx")

    # ============================================================
    # モデル初期化
    # ============================================================

    def init_model(self) -> bool:
        """ハードウェアを自動検知してモデルを初期化"""
        try:
            if not os.path.exists(self.model_path):
                self.error.emit(f"Model not found: {self.model_path}")
                return False

            available = ort.get_available_providers()

            # 2026年時点での最適プロバイダー優先順位
            priority = [
                'CoreMLExecutionProvider',  # Apple Silicon (NPU)
                'DmlExecutionProvider',     # Windows DirectML / NPU
                'CUDAExecutionProvider',    # NVIDIA GPU
                'CPUExecutionProvider',     # フォールバック
            ]
            selected = [p for p in priority if p in available]

            # プロバイダーごとのオプション（M3/M4 ML Program 最適化）
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
    # 非同期推論
    # ============================================================

    def analyze_async(self, audio_data) -> None:
        """
        GUIを止めずに推論を実行し、結果を Signal で安全に送る。
        MainWindow 側でデバウンスタイマーを挟むことで
        連打による queue 溜まりを防ぐ設計。
        """
        def task():
            try:
                if self.session is None:
                    if not self.init_model():
                        return
                result = self.predict_onset(audio_data)
                self.finished.emit(result)
            except Exception as e:
                self.error.emit(f"AI Inference Error: {e}")

        self.executor.submit(task)

    # ============================================================
    # 同期推論
    # ============================================================

    def predict_onset(self, audio_data) -> list:
        """同期推論実行"""
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
        出力 shape を検証して無言クラッシュを防止。
        """
        if not outputs or len(outputs) == 0:
            logger.error("_postprocess: empty outputs")
            return []

        raw_data = outputs[0]

        # shape チェック: [n_notes, >=1] を期待
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
