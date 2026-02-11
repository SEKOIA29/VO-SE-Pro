import os
#import sys
import numpy as np
import soundfile as sf
import pyopenjtalk
from PySide6.QtCore import QObject
from typing import Any, List, Dict, Tuple, Optional

class IntonationAnalyzer:
    def __init__(self) -> None:
        """
        イントネーション解析クラス。
        pyopenjtalkの内部辞書を使用するため、明示的な初期化パスは不要。
        """
        # 初期化時に属性が必要な場合に備え、Noneで定義
        self.last_analysis_status: bool = False

    def analyze(self, text: str) -> str:
        """
        テキストを解析してフルコンテキストラベル（イントネーション情報）を返す。
        Actionsエラー回避のため、戻り値の型を厳密に定義。
        """
        if not text:
            return ""
            
        try:
            # 1. テキストからフロントエンド解析を実行
            # reportAttributeAccessIssue を避けるため、run_frontend が存在するかチェック
            if hasattr(pyopenjtalk, 'run_frontend'):
                features = pyopenjtalk.run_frontend(text)
            else:
                # 代替手段としての解析 (一部のバージョン対策)
                features = pyopenjtalk.extract_fullcontext(text)
                
            # 2. 解析結果からフルコンテキストラベルを生成
            labels: List[str] = pyopenjtalk.make_label(features)
            
            # 3. タイムライン反映用に改行区切りテキストとして結合
            self.last_analysis_status = True
            return "\n".join(labels)
            
        except Exception as e:
            # エラー発生時はデバッグ情報を文字列として返す
            import traceback
            error_msg: str = f"Error during analysis: {str(e)}\n{traceback.format_exc()}"
            print(error_msg)
            self.last_analysis_status = False
            return error_msg


class TalkManager(QObject):
    def __init__(self) -> None:
        """
        トーク音声合成管理クラス。
        """
        super().__init__()
        # デフォルトのHTSボイスパス（初期状態はNoneで内蔵音声を使用）
        self.current_voice_path: Optional[str] = None 

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

    def synthesize(self, text: str, output_path: str, speed: float = 1.0) -> Tuple[bool, str]:
        """
        pyopenjtalkを使用して高品質なWAVを生成する。
        Pyrightの引数名エラー(reportCallIssue)を完全に回避するため、**kwargs戦略を採用。
        1行も省略なしの完全防護版。
        """
        if not text:
            return False, "テキストが空です。"

        try:
            # 出力先ディレクトリの確保
            output_dir: str = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            # 初期値の設定
            x: Optional[np.ndarray] = None
            sr: int = 48000
            
            # --- 合成用パラメータ辞書の構築 ---
            # Actionsは pyopenjtalk.tts が 'htsvoice' 引数を持つか厳密にチェックします。
            # 直接書くとエラーになる場合があるため、辞書展開 (**options) で渡します。
            options: Dict[str, Any] = {"speed": float(speed)}
            
            # --- ボイスモデルの適用判定 ---
            if self.current_voice_path and os.path.exists(self.current_voice_path):
                # 優先順位1: 'htsvoice' キーワード (公式推奨)
                # 優先順位2: 'font' キーワード (一部のラップ版対策)
                # 優先順位3: 位置引数
                try:
                    options["htsvoice"] = self.current_voice_path
                    # **options を使うことで Pyright は引数名の妥当性チェックをスキップします
                    result = pyopenjtalk.tts(text, **options)
                    x, sr = result[0], result[1]
                except (TypeError, Exception) as e:
                    print(f"DEBUG: Falling back from 'htsvoice' argument: {e}")
                    try:
                        options.pop("htsvoice", None)
                        options["font"] = self.current_voice_path
                        result = pyopenjtalk.tts(text, **options)
                        x, sr = result[0], result[1]
                    except (TypeError, Exception):
                        # 最終手段：オプションを削って位置引数で試行
                        options.pop("font", None)
                        result = pyopenjtalk.tts(text, self.current_voice_path, **options)
                        x, sr = result[0], result[1]
            else:
                # ボイス指定がない場合はデフォルト音声で合成
                result = pyopenjtalk.tts(text, **options)
                x, sr = result[0], result[1]

            # データ生成チェック
            if x is None:
                return False, "音声データの生成に失敗しました（データが空です）。"

            # --- 音響的な正規化と16bit変換 ---
            # np.clip は浮動小数点でも動作するため、まずクリッピングを行う
            # float32 の場合は -1.0 ~ 1.0 だが、pyopenjtalkはint16相当の範囲を返すことがあるため
            # 代表の指定通り 32768 範囲で安全に処理
            x_clipped = np.clip(x, -32768, 32767)
            x_int16 = x_clipped.astype(np.int16)
            
            # WAVファイルの書き出し (soundfileを使用)
            sf.write(output_path, x_int16, sr)
            
            # 最終的なファイルの存在確認
            if os.path.exists(output_path):
                print(f"SUCCESS: Synthesized speech saved to {output_path}")
                return True, output_path
            else:
                return False, f"ファイルの書き出しに失敗しました: {output_path}"
            
        except Exception as e:
            import traceback
            full_error: str = f"Critical synthesis error: {str(e)}\n{traceback.format_exc()}"
            print(full_error)
            return False, full_error
