import subprocess
import os
import sys


class IntonationAnalyzer:
    def __init__(self):
        # パス設定（ビルド後と開発時両対応）
        if getattr(sys, 'frozen', False):
            self.root = sys._MEIPASS
        else:
            self.root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
        self.exe = os.path.join(self.root, "bin", "open_jtalk", "open_jtalk.exe")
        self.dic = os.path.join(self.root, "bin", "open_jtalk", "dic")

    def analyze(self, text):
        """テキストを解析してアクセント句情報を返す"""
        temp_input = "temp_in.txt"
        temp_trace = "temp_trace.txt"
        
        with open(temp_input, "w", encoding="utf-8") as f:
            f.write(text)
            
        # -ot (trace) で解析結果を出力し、-ow NUL で音声生成をスキップ
        cmd = [self.exe, "-x", self.dic, "-ot", temp_trace, "-ow", "NUL", temp_input]
        
        try:
            subprocess.run(cmd, check=True, shell=True, capture_output=True)
            with open(temp_trace, "r", encoding="utf-8") as f:
                trace_data = f.read()
            return trace_data
        except Exception as e:
            return f"Error: {e}"
        finally:
            # 掃除
            for t in [temp_input, temp_trace]:
                if os.path.exists(t): os.remove(t)



class TalkManager:
    def __init__(self):
        # 実行パスの解決（既存のロジックを維持）
        if getattr(sys, 'frozen', False):
            self.base_bin = os.path.join(sys._MEIPASS, "bin", "open_jtalk")
        else:
            self.base_bin = os.path.join(os.path.dirname(__file__), "../../bin/open_jtalk")

        self.exe = os.path.join(self.base_bin, "open_jtalk.exe")
        self.dic = os.path.join(self.base_bin, "dic")
        
        # デフォルトボイス
        self.current_voice_path = os.path.join(self.base_bin, "voice", "mei_normal.htsvoice")

    def set_voice(self, htsvoice_path):
        """外部からボイスモデルを切り替える（MainWindowから呼ばれる）"""
        if os.path.exists(htsvoice_path):
            self.current_voice_path = htsvoice_path
            return True
        return False

    def synthesize(self, text, output_path):
        """選択中のボイスモデルでWAVを生成"""
        if not os.path.exists(self.exe):
            return False, "Open JTalk本体が見つかりません。"

        command = [
            self.exe,
            "-x", self.dic,
            "-m", self.current_voice_path, # ここを動的に
            "-ow", output_path
        ]
        # 実行環境に合わせたパスの取得
        if getattr(sys, 'frozen', False):
            self.base_bin = os.path.join(sys._MEIPASS, "bin", "open_jtalk")
        else:
            self.base_bin = os.path.join(os.path.dirname(__file__), "../../bin/open_jtalk")

        self.exe = os.path.join(self.base_bin, "open_jtalk.exe")
        self.dic = os.path.join(self.base_bin, "dic")
        self.voice = os.path.join(self.base_bin, "voice", "mei_normal.htsvoice")

    def synthesize(self, text, output_path):
        """テキストをWAVに変換して保存する"""
        if not os.path.exists(self.exe):
            return False, "Open JTalk本体が見つかりません。"

        # コマンドの組み立て
        command = [
            self.exe,
            "-x", self.dic,
            "-m", self.voice,
            "-ow", output_path
        ]

        try:
            # テキストを標準入力経由で渡して実行
            process = subprocess.Popen(
                command, 
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            process.communicate(input=text.encode('utf-8'))
            
            if os.path.exists(output_path):
                return True, output_path
            return False, "音声生成に失敗しました。"
            
        except Exception as e:
            return False, str(e)
