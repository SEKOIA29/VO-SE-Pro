import subprocess
import os
import sys

class TalkManager:
    def __init__(self):
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
