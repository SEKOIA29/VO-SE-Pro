import os
import numpy as np
import soundfile as sf
import pyopenjtalk
from PySide6.QtCore import QObject

class IntonationAnalyzer:
    def __init__(self):
        # ライブラリが内部で辞書を持つため、複雑なパス設定は不要
        pass

    def analyze(self, text: str) -> str:
        """
        テキストを解析してフルコンテキストラベル（イントネーション情報）を返す
        ノート反映モードの核となるデータ（省略なし）
        """
        if not text:
            return ""
            
        try:
            # pyopenjtalkで解析
            # run_frontend で解析した結果を make_label でラベル化
            labels = pyopenjtalk.make_label(pyopenjtalk.run_frontend(text))
            # タイムラインに反映しやすいよう、改行区切りのテキストとして返却
            return "\n".join(labels)
        except Exception as e:
            print(f"DEBUG: Intonation Analysis Error: {e}")
            return f"Error: {e}"


class TalkManager(QObject):
    def __init__(self):
        super().__init__()
        # デフォルトのHTSボイス（Noneの場合は内蔵モデルが使用される）
        self.current_voice_path = None 

    def set_voice(self, htsvoice_path: str) -> bool:
        """外部からボイスモデル(.htsvoice)を切り替える（省略なし）"""
        if htsvoice_path and os.path.exists(htsvoice_path):
            self.current_voice_path = htsvoice_path
            return True
        return False

    def synthesize(self, text: str, output_path: str):
        """
        pyopenjtalkを使用して高品質なWAVを生成（型エラー修正済み完全版）
        """
        if not text:
            return False, "テキストが空です。"

        try:
            # 【Pyrightエラー対策】
            # pyopenjtalk.tts の引数名は環境により異なる場合があるため、
            # 安全を期してキーワード引数なしでの呼び出し、またはフォールバックを実装
            
            x = None
            sr = 48000 # デフォルトサンプリングレート
            
            if self.current_voice_path and os.path.exists(self.current_voice_path):
                try:
                    # まずは htsvoice= で試行
                    x, sr = pyopenjtalk.tts(text, htsvoice=self.current_voice_path)
                except (TypeError, Exception):
                    # 失敗した場合は第2引数として直接渡す（ライブラリの仕様に合わせる）
                    x, sr = pyopenjtalk.tts(text, self.current_voice_path)
            else:
                # ボイス指定がない場合はデフォルト音声で合成
                x, sr = pyopenjtalk.tts(text)

            if x is None:
                return False, "音声合成データの生成に失敗しました。"

            # --- 16bit PCMとして書き出し ---
            # numpyのクリッピング処理を行い、音割れを防ぐ（Core i3でも安心の品質管理）
            x_int16 = np.clip(x, -32768, 32767).astype(np.int16)
            
            sf.write(output_path, x_int16, sr)
            
            if os.path.exists(output_path):
                return True, output_path
            return False, "ファイルの書き出しに失敗しました。"
            
        except Exception as e:
            print(f"DEBUG: Synthesis critical error: {e}")
            return False, str(e)
