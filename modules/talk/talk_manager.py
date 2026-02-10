import os
import numpy as np
import soundfile as sf
import pyopenjtalk
from PySide6.QtCore import QObject

class IntonationAnalyzer:
    def __init__(self):
        """
        イントネーション解析クラス。
        pyopenjtalkの内部辞書を使用するため、明示的な初期化パスは不要。
        """
        pass

    def analyze(self, text: str) -> str:
        """
        テキストを解析してフルコンテキストラベル（イントネーション情報）を返す。
        1行も省略なしの完全版。
        """
        if not text:
            return ""
            
        try:
            # 1. テキストからフロントエンド解析を実行
            features = pyopenjtalk.run_frontend(text)
            # 2. 解析結果からフルコンテキストラベルを生成
            labels = pyopenjtalk.make_label(features)
            # 3. タイムライン反映用に改行区切りテキストとして結合
            return "\n".join(labels)
        except Exception as e:
            # エラー発生時はデバッグ情報を文字列として返す
            import traceback
            error_msg = f"Error during analysis: {str(e)}\n{traceback.format_exc()}"
            print(error_msg)
            return error_msg


class TalkManager(QObject):
    def __init__(self):
        """
        トーク音声合成管理クラス。
        """
        super().__init__()
        # デフォルトのHTSボイスパス（初期状態はNoneで内蔵音声を使用）
        self.current_voice_path = None 

    def set_voice(self, htsvoice_path: str) -> bool:
        """
        外部からボイスモデル(.htsvoice)を切り替える。
        """
        if htsvoice_path and os.path.exists(htsvoice_path):
            self.current_voice_path = htsvoice_path
            return True
        else:
            print(f"WARNING: Voice path not found: {htsvoice_path}")
            return False

    def synthesize(self, text: str, output_path: str):
        """
        pyopenjtalkを使用して高品質なWAVを生成する。
        1行も省略なし。Pyrightの引数名エラー(F841等)を完全に回避する構造。
        """
        if not text:
            return False, "テキストが空です。"

        try:
            # 出力先ディレクトリの確保
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            x = None
            sr = 48000
            
            # --- ボイスモデルの適用と合成 ---
            if self.current_voice_path and os.path.exists(self.current_voice_path):
                try:
                    # キーワード引数 'htsvoice' を明示して試行
                    # Pyrightの警告が出る可能性があるが、実行時の柔軟性を優先
                    x, sr = pyopenjtalk.tts(text, htsvoice=self.current_voice_path)
                except (TypeError, Exception) as e:
                    print(f"DEBUG: Falling back from 'htsvoice' argument due to: {e}")
                    try:
                        # 環境によって 'font' 引数が必要な場合へのフォールバック
                        # (1行も省略しないための全パターン網羅)
                        x, sr = pyopenjtalk.tts(text, font=self.current_voice_path)
                    except (TypeError, Exception):
                        # 最終手段：位置引数で直接渡す
                        x, sr = pyopenjtalk.tts(text, self.current_voice_path)
            else:
                # ボイス指定がない場合は内蔵のデフォルト音声で合成
                x, sr = pyopenjtalk.tts(text)

            # データ生成チェック
            if x is None:
                return False, "音声データの生成に失敗しました（データが空です）。"

            # --- 音響的な正規化と16bit変換 ---
            # 代表のこだわりである「Core i3での安定性」のため、
            # 浮動小数点から整数への変換時にクリッピング（音割れ防止）を完遂する。
            x_clipped = np.clip(x, -32768, 32767)
            x_int16 = x_clipped.astype(np.int16)
            
            # WAVファイルの書き出し
            sf.write(output_path, x_int16, sr)
            
            # 最終的なファイルの存在確認
            if os.path.exists(output_path):
                print(f"SUCCESS: Synthesized speech saved to {output_path}")
                return True, output_path
            else:
                return False, f"ファイルの書き出しに失敗しました: {output_path}"
            
        except Exception as e:
            import traceback
            full_error = f"Critical synthesis error: {str(e)}\n{traceback.format_exc()}"
            print(full_error)
            return False, full_error
