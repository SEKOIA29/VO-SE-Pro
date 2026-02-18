#ai_manager.py

import os
import sys
import numpy as np
import onnxruntime as ort
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, Signal

class AIManager(QObject):
    # MainWindowに結果を届けるための信号
    finished = Signal(object)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        # 推論は1件ずつ順番に行う
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.session = None
        self.model_path = self._get_model_path()

    def _get_model_path(self):
        """PyInstaller環境でも動作するパス解決（修正版）"""
        if getattr(sys, 'frozen', False):
            # PyInstallerで固められた時用のパス
            base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        else:
            # 開発環境用のパス
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        # モデルファイルへのフルパスを組み立てて返す
        return os.path.join(base, "models", "aural_dynamics.onnx")

    def init_model(self):
        """ハードウェアを自動検知してモデルを初期化"""
        try:
            if not os.path.exists(self.model_path):
                self.error.emit(f"Model not found: {self.model_path}")
                return False

            available_providers = ort.get_available_providers()
            
            # 2026年時点での最適なプロバイダー選択優先度（代表のオリジナル優先度）
            priority = [
                'CoreMLExecutionProvider',  # Apple Silicon (NPU)
                'DmlExecutionProvider',     # Windows (DirectML/NPU)
                'CUDAExecutionProvider',    # NVIDIA GPU
                'CPUExecutionProvider'      # Default
            ]
            
            selected_providers = [p for p in priority if p in available_providers]
            
            # 実行時オプション（代表こだわりのMac M3/M4用最適化）
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
        except Exception as e:
            self.error.emit(f"Init Error: {str(e)}")
            return False

    def analyze_async(self, audio_data):
        """GUIを止めずに推論を実行し、結果をSignalで安全にMainWindowへ送る"""
        def task():
            try:
                # セッションがなければ初期化
                if self.session is None:
                    if not self.init_model():
                        return
                
                # 推論実行
                result = self.predict_onset(audio_data)
                
                # 直接コールバックを呼ぶとGUIスレッドを破壊するため、Signalを使用
                self.finished.emit(result)
            except Exception as e:
                self.error.emit(f"AI Inference Error: {e}")
        
        self.executor.submit(task)

    def predict_onset(self, audio_data):
        """同期推論実行（代表のロジック）"""
        if self.session is None:
            if not self.init_model() or self.session is None:
                return []
        session = self.session
        input_data = self._preprocess(audio_data)
        # モデルの入力名に合わせて実行
        outputs = session.run(None, {session.get_inputs()[0].name: input_data})
        return self._postprocess(outputs)

    def _preprocess(self, audio_data):
        """音声波形を正規化してテンソル化"""
        data = np.array(audio_data).astype(np.float32)
        if data.ndim == 1:
            data = data[np.newaxis, np.newaxis, :]
        return data

    def _postprocess(self, outputs):
        """
        AIの出力テンソルから [onset, overlap, pre_utterance] のリストを生成
        outputs: モデルからの生の出力
        """
        all_results = []
        
        # モデルの出力形状に合わせてループを回す
        # 例: outputs[0] が [n_notes, 3] の形状だとする
        raw_data = outputs[0]
        
        for data in raw_data:
            # 1つずつの発音データを整形
            res = {
                "onset": float(data[0]),
                "overlap": float(data[1]) if len(data) > 1 else 0.05,
                "pre_utterance": float(data[2]) if len(data) > 2 else 0.1
            }
            all_results.append(res)
            
        return all_results # リストを丸ごと返す
