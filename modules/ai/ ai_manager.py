#ai_manager.py

import os
import sys
import numpy as np
import onnxruntime as ort
from concurrent.futures import ThreadPoolExecutor

class AIManager:
    def __init__(self):
        # 推論は1件ずつ順番に行うため worker=1
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.session = None
        self.model_path = self._get_model_path()

    def _get_model_path(self):
        """PyInstaller環境でも動作するパス解決"""
        if getattr(sys, 'frozen', False):
            base = sys._MEIPASS
        else:
            # プロジェクトルートからの相対パス
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(base, "assets", "models", "onset_detector.onnx")

    def init_model(self):
        """ハードウェアを自動検知してモデルを初期化"""
        if not os.path.exists(self.model_path):
            print(f"Model not found: {self.model_path}")
            return False

        available_providers = ort.get_available_providers()
        
        # 2026年時点での最適なプロバイダー選択優先度
        priority = [
            'CoreMLExecutionProvider',  # Apple Silicon (NPU)
            'DmlExecutionProvider',      # Windows (DirectML/NPU)
            'CUDAExecutionProvider',     # NVIDIA GPU
            'CPUExecutionProvider'       # Default
        ]
        
        selected_providers = [p for p in priority if p in available_providers]
        
        # 実行時オプション（Mac M3/M4用最適化など）
        provider_options = []
        for p in selected_providers:
            if p == 'CoreMLExecutionProvider':
                provider_options.append({'ml_program': '1'}) # ML Program形式を優先
            else:
                provider_options.append({})

        self.session = ort.InferenceSession(
            self.model_path, 
            providers=selected_providers,
            provider_options=provider_options
        )
        print(f"AI Engine Initialized with: {selected_providers[0]}")
        return True

    def analyze_async(self, audio_data, callback):
        """GUIスレッドを止めずに推論を実行"""
        def task():
            try:
                return self.predict_onset(audio_data)
            except Exception as e:
                print(f"AI Inference Error: {e}")
                return None
        
        future = self.executor.submit(task)
        # コールバックを実行
        if callback:
            future.add_done_callback(lambda f: callback(f.result()))

    def predict_onset(self, audio_data):
        """同期推論実行"""
        if self.session is None:
            if not self.init_model(): return None
        
        input_data = self._preprocess(audio_data)
        # モデルの入力名（'input'）に合わせて実行
        outputs = self.session.run(None, {self.session.get_inputs()[0].name: input_data})
        return self._postprocess(outputs)

    def _preprocess(self, audio_data):
        """音声波形を正規化してテンソル化"""
        # numpy配列化し、モデルが期待する型・形状に変更 (1, 1, samples)
        data = np.array(audio_data).astype(np.float32)
        if data.ndim == 1:
            data = data[np.newaxis, np.newaxis, :]
        return data

    def _postprocess(self, outputs):
        """推論結果（確率値）をミリ秒/秒単位の [onset, overlap, pre_utterance] に変換"""
        # ここはモデルの仕様に合わせて実装
        # 例: 最初の出力テンソルの最大値インデックスを時間に変換するなど
        res = outputs[0][0] 
        return res # [onset_sec, overlap_sec, pre_utterance_sec]
