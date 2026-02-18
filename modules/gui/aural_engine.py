import numpy as np
import os
import ctypes
import _ctypes
import platform


try:
    import onnxruntime as ort
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False


class DynamicsMemoryManager:
    def __init__(self, dll_path):
        self.path = dll_path
        # DLLをメモリにロード
        self._handle = ctypes.CDLL(self.path)
        print(f"Loaded: {self.path}")

    def safe_release_audio(self, audio_ptr):
        """C言語側でmallocした音声バッファをピンポイントで解放する"""
        if audio_ptr and self._handle is not None:
            # 前に作った vse_free_buffer を呼び出す
            free_buffer = getattr(self._handle, "vse_free_buffer", None)
            if callable(free_buffer):
                free_buffer(audio_ptr)
                print("C-side audio buffer released.")

    def unload_engine(self):
        """DLLそのものをメモリから完全に消去する（キャラ切り替え用）"""
        if self._handle:
            # まずC側の内部ライブラリ（g_lib）を掃除
            self._handle.terminate_engine()
            
            # DLLのハンドルをOSに返却してメモリから消す
            handle_val = self._handle._handle
            if platform.system() == "Windows":
                free_library = getattr(_ctypes, "FreeLibrary", None)
                if callable(free_library):
                    free_library(handle_val)
            else:
                dlclose = getattr(_ctypes, "dlclose", None)
                if callable(dlclose):
                    dlclose(handle_val)
            
            self._handle = None
            print("DLL memory fully unloaded.")
            

class AuralAIEngine:
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
        delta_arr = np.asarray(delta, dtype=np.float32).reshape(-1)
        return base_f0_array + delta_arr

    def _apply_pseudo_ai(self, f0):
        """AIモデルがない時のための予備ロジック（ビブラート等）"""
        x = np.linspace(0, 10, len(f0))
        vibrato = np.sin(x * 5) * 2 # 5Hzで2Hz幅の揺れ
        return f0 + vibrato
