#ai_manager.py

from .timeline_widget import TimelineWidget  # 同一パッケージ内からの相対インポート
from ..ai.manager import AIManager          # 上位フォルダ(ai)からのインポート
import os
import sys
import time
import platform
import numpy as np
import onnxruntime as ort
from concurrent.futures import ThreadPoolExecutor

class AIManager:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.session = None
        # パス解決を初期化時に行う
        self.model_path = self._get_model_path()
        # デバイス判定
        self.device_provider = self._detect_device_provider()

    def _get_model_path(self):
        """ビルド後もモデルを見失わないパス解決"""
        if getattr(sys, 'frozen', False):
            base = sys._MEIPASS
        else:
            # プロジェクト構成に合わせて調整（ここでは1階層上を想定）
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "assets", "models", "onset_detector.onnx")

    def _detect_device_provider(self):
        """ハードウェアに最適なプロバイダーを判定"""
        providers = ort.get_available_providers()
        if 'CoreMLExecutionProvider' in providers:
            return 'CoreML'
        elif 'OpenVINOExecutionProvider' in providers:
            return 'OpenVINO'
        return 'CPU'

    def init_model(self):
        """モデルの読み込み (起動時)"""
        if not os.path.exists(self.model_path):
            print(f"Model not found at: {self.model_path}")
            return False

        providers = ort.get_available_providers()
    
        # 優先順位を自動切り替え
        priority = [
            'CoreMLExecutionProvider',  # Mac NPU
            'DMLExecutionProvider',     # Windows NPU/GPU (DirectML)
            'CUDAExecutionProvider',    # NVIDIA GPU
            'CPUExecutionProvider'      # 最終手段 (AVX加速)
        ]
    
        selected = [p for p in priority if p in providers]
        self.session = ort.InferenceSession(self.model_path, providers=selected)
        
        # プロバイダーのオプション設定
        if self.device_provider == 'CoreML':
            providers = [('CoreMLExecutionProvider', {'ml_program': '1'})]
        elif self.device_provider == 'OpenVINO':
            providers = ['OpenVINOExecutionProvider']
        else:
            providers = ['CPUExecutionProvider']

        self.session = ort.InferenceSession(self.model_path, providers=providers)
        return True

    def analyze_async(self, audio_data, callback):
        """GUIをフリーズさせないための非同期実行"""
        def task():
            return self.predict_onset(audio_data)
        
        future = self.executor.submit(task)
        future.add_done_callback(lambda f: callback(f.result()))

    def predict_onset(self, audio_data):
        """推論のメインロジック"""
        if self.session is None: return None
        
        input_data = self._preprocess(audio_data)
        outputs = self.session.run(None, {'input': input_data})
        return self._postprocess(outputs)

    def _preprocess(self, data):
        """波形をモデルの入力形式（float32, 4Dテンソルなど）に整形"""
        # dataがnumpy配列であることを想定
        return data.astype(np.float32).reshape(1, 1, -1)

    def _postprocess(self, outputs):
        """推論結果（確率値など）を具体的な時間やoto.ini用の数値に変換"""
        # ここはモデルの出力形式に合わせて実装（現在はそのまま返す）
        return outputs

    def save_as_oto_ini(self, character_id, results_dict):
        """
        results_dict: { "filename.wav": [onset, overlap, pre_utterance], ... }
        を UTAU 互換の oto.ini 形式で保存する
        """
        with open(f"audio_data/{character_id}/oto.ini", "w") as f:
            for filename, vals in results_dict.items():
                f.write(f"{filename}={vals[0]},{vals[1]},{vals[2]}...\n")

    def on_ai_analysis_finished(self, note_id, ai_result):
        """
        AIの解析が終わった時に呼ばれるコールバック
        ai_result: [onset, overlap, pre_utterance] のリストを想定
        """
        # 1. 対象のノートを探す
        note = self.project.get_note_by_id(note_id)
        
        # 2. 解析結果を NoteEvent に書き戻す
        # ai_result の単位がサンプルの場合は、秒に変換して格納
        note.onset = ai_result[0]
        note.overlap = ai_result[1]
        note.pre_utterance = ai_result[2]
    
        print(f"AI解析完了: {note.lyric} -> 先行発声: {note.pre_utterance}s")
    
        # 3. GUIを更新（解析済みの印をつけるなど）
        self.view.update_note_display(note_id)

    def run_batch_voice_analysis(self, voice_dir, progress_callback=None):
        """
        指定されたフォルダ内の全WAVファイルをAI解析し、結果をリストで返す
        progress_callback: 進捗率 %) を報告する関数
        """
        # 1. WAVファイルのリストアップ
        wav_files = [f for f in os.listdir(voice_dir) if f.endswith('.wav')]
        total_files = len(wav_files)
        analysis_results = {}

        if total_files == 0:
            return analysis_results

        for i, filename in enumerate(wav_files):
            path = os.path.join(voice_dir, filename)
        
            # 2. 音声データの読み込み（簡易版）
            # ※実際には scipy.io.wavfile などで読み込む
            audio_data = self._load_wav(path) 
        
            # 3. AI推論の実行
            # 同期メソッド predict_onset を呼び出す
            result = self.ai_manager.predict_onset(audio_data)
        
            # 4. 結果を保持 (filename: [onset, overlap, pre_utterance])
            analysis_results[filename] = result
        
            # 5. 進捗を報告
            if progress_callback:
                percent = int((i + 1) / total_files * 100)
                progress_callback(percent, filename)

        return analysis_results

    def export_to_oto_ini(self, voice_dir, results):
        """
        AI解析結果を UTAU互換の oto.ini 形式で保存
        フォーマット: ファイル名=エイリアス,左ブランク,固定範囲,右ブランク,先行発声,オーバーラップ
        """
        output_path = os.path.join(voice_dir, "oto_ai_generated.ini")
    
        with open(output_path, "w", encoding="shift_jis") as f: # UTAUは通常Shift-JIS
            for filename, r in results.items():
                # r[0]:onset, r[1]:overlap, r[2]:pre_utterance
                # 固定範囲や右ブランクは簡易的に設定
                line = f"{filename}=,{r[0]},100,-100,{r[2]},{r[1]}\n"
                f.write(line)
            
         print(f"解析結果を保存しました: {output_path}")
