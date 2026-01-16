import numpy as np
import os

try:
    import onnxruntime as ort
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False

class DynamicsAIEngine:
    def __init__(self, model_path="models/pitch_dynamics.onnx"):
        self.model_path = model_path
        self.session = None
        
        if ONNX_AVAILABLE and os.path.exists(self.model_path):
            try:
                # CPUでも軽量に動く設定
                self.session = ort.InferenceSession(
                    self.model_path, 
                    providers=['CPUExecutionProvider']
                )
                print(f"[Dynamics AI] Model loaded: {self.model_path}")
            except Exception as e:
                print(f"[Dynamics AI] Load Error: {e}")

    def generate_emotional_pitch(self, base_f0_array):
        """真っ直ぐなピッチに人間らしい『揺れ』を加える"""
        if not self.session:
            # モデルがない場合は、簡易的なビブラート（数学的シミュレーション）を返す
            return self._apply_pseudo_ai(base_f0_array)

        # AI推論の実行（入力整形）
        input_data = base_f0_array.astype(np.float32).reshape(1, -1, 1)
        delta = self.session.run(None, {"input": input_data})[0]
        
        return base_f0_array + delta.flatten()

    def _apply_pseudo_ai(self, f0):
        """AIモデルがない時のための予備ロジック（ビブラート等）"""
        x = np.linspace(0, 10, len(f0))
        vibrato = np.sin(x * 5) * 2 # 5Hzで2Hz幅の揺れ
        return f0 + vibrato
