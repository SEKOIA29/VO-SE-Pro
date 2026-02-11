
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
        # インストールされているデフォルトの辞書を使用
        self.dict_dir: Optional[str] = None
        self.is_speaking: bool = False

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

    def speak(self, text: str) -> None:
        if not text:
            return
        print(f"Speaking: {text}")
            
    def synthesize(self, text: str, output_path: str, speed: float = 1.0) -> Tuple[bool, str]:
        """
        pyopenjtalkを使用して高品質なWAVを生成する。
        重複インポートを排除し、F811 / F401 エラーを解決した完全防護版。
        """
        # 1. 入力チェック
        if not text:
            return False, "テキストが空です。"

        try:
            # 2. 出力先ディレクトリの確保
            output_dir: str = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            # 3. 初期値の設定（Noneガード用）
            x: Optional[np.ndarray] = None
            sr: int = 48000
            
            # 4. 合成用パラメータ辞書の構築
            # speedを強制的にfloat化し、reportArgumentTypeを回避
            options: Dict[str, Any] = {"speed": float(speed)}
            
            # 5. ボイスモデルのパス解決
            v_path: str = str(getattr(self, 'current_voice_path', ""))
            
            if v_path and os.path.exists(v_path):
                # --- ボイスモデルの適用試行（代表の設計を完全踏襲） ---
                try:
                    # 優先順位1: 'htsvoice' (公式推奨)
                    options["htsvoice"] = v_path
                    result = pyopenjtalk.tts(text, **options)
                    
                    if result is not None and len(result) >= 2:
                        x, sr = result[0], result[1]
                    else:
                        raise ValueError("TTS result is None or malformed")

                except (TypeError, Exception) as e:
                    print(f"DEBUG: Falling back from 'htsvoice' argument: {e}")
                    try:
                        # 優先順位2: 'font' (一部のラップ版対策)
                        options.pop("htsvoice", None)
                        options["font"] = v_path
                        result = pyopenjtalk.tts(text, **options)
                        
                        if result is not None and len(result) >= 2:
                            x, sr = result[0], result[1]
                        else:
                            raise ValueError("TTS result with 'font' is None")

                    except (TypeError, Exception):
                        # 優先順位3: 位置引数
                        try:
                            options.pop("font", None)
                            # 位置引数として v_path を直接渡す
                            result = pyopenjtalk.tts(text, v_path, **options)
                            
                            if result is not None and len(result) >= 2:
                                x, sr = result[0], result[1]
                            else:
                                raise ValueError("TTS result with positional arg is None")
                        except Exception as final_e:
                            print(f"DEBUG: All synthesis attempts failed: {final_e}")
            else:
                # ボイス指定がない場合はデフォルト音声で合成
                result = pyopenjtalk.tts(text, **options)
                if result is not None and len(result) >= 2:
                    x, sr = result[0], result[1]

            # 6. データ生成チェック
            if x is None:
                return False, "音声データの生成に失敗しました（データが空です）。"

            # 7. 音響的な正規化と16bit変換（代表の指定値 32768 を採用）
            # floatの場合はint16の範囲にクリッピングしてから変換
            x_clipped = np.clip(x, -32768, 32767)
            x_int16 = x_clipped.astype(np.int16)
            
            # 8. WAVファイルの書き出し
            sf.write(output_path, x_int16, sr)
            
            # 9. 最終的な確認
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
