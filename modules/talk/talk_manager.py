import os
import sys
import numpy as np
import soundfile as sf
import pyopenjtalk
from PySide6.QtCore import QObject

class IntonationAnalyzer:
    def __init__(self):
        # ライブラリが内部で辞書を持つため、複雑なパス設定は不要です
        pass

    def analyze(self, text):
        """
        テキストを解析してフルコンテキストラベル（イントネーション情報）を返す
        ノート反映モードの核となるデータです
        """
        try:
            # pyopenjtalkで解析
            labels = pyopenjtalk.make_label(pyopenjtalk.run_frontend(text))
            # タイムラインに反映しやすいよう、改行区切りのテキストとして返却
            return "\n".join(labels)
        except Exception as e:
            return f"Error: {e}"


class TalkManager(QObject):
    def __init__(self):
        super().__init__()
        # デフォルトのHTSボイス（必要に応じてパスを指定）
        # pyopenjtalk.get_static_vocal_chitose() なども使えます
        self.current_voice_path = None 

    def set_voice(self, htsvoice_path):
        """外部からボイスモデル(.htsvoice)を切り替える"""
        if os.path.exists(htsvoice_path):
            self.current_voice_path = htsvoice_path
            return True
        return False

    def synthesize(self, text, output_path):
        """pyopenjtalkを使用して高品質なWAVを生成"""
        try:
            # 音声合成 (x: 波形データ, sr: サンプリングレート)
            # font引数にボイスパスを渡すことで声の種類を変更可能
            x, sr = pyopenjtalk.tts(text, font=self.current_voice_path)
            
            # 16bit PCMとして書き出し
            sf.write(output_path, x.astype(np.int16), sr)
            
            if os.path.exists(output_path):
                return True, output_path
            return False, "ファイルの書き出しに失敗しました。"
            
        except Exception as e:
            return False, str(e)
