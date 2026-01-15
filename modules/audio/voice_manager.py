#GUI/voice_manager.py

import os
import platform
import glob
import sys
import logging

class VoiceManager:
    def __init__(self):
        self.system = platform.system()
        # 実行環境(PyInstaller)と開発環境のパス解決を統一
        if getattr(sys, 'frozen', False):
            self.base_path = sys._MEIPASS
        else:
            # modules/audio/ から見たプロジェクトルート
            self.base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        
        self.internal_voice_dir = os.path.join(self.base_path, "voice_banks")
        self.voices = {}  # { "キャラ名": "絶対パス" }

    def scan_voices(self):
        """標準的なUTAU音源パスと内部フォルダをスキャン"""
        search_paths = []
        
        # 1. OSごとの標準パスを追加
        if self.system == "Darwin": # macOS
            search_paths.append(os.path.expanduser("~/Library/Application Support/OpenUTAU/Content/Voices/"))
            search_paths.append(os.path.expanduser("~/Library/Application Support/Vocaloid/Voices/")) # 互換用
        elif self.system == "Windows":
            search_paths.append(r"C:\Program Files (x86)\UTAU\voice")
            appdata_roaming = os.getenv('APPDATA')
            if appdata_roaming:
                search_paths.append(os.path.join(appdata_roaming, "OpenUTAU", "Content", "Voices"))

        # 2. プロジェクト内部の voice_banks フォルダを追加
        search_paths.append(self.internal_voice_dir)

        self.voices.clear()
        for path in search_paths:
            if not os.path.exists(path):
                continue
            
            # 再帰的に oto.ini を検索
            for ini_path in glob.glob(os.path.join(path, "**/oto.ini"), recursive=True):
                v_dir = os.path.dirname(ini_path)
                # キャラ名はフォルダ名、または character.txt があればそこから取得する拡張性
                v_name = os.path.basename(v_dir)
                
                # 重複した場合は、より「深い（個別設定された）」パスを優先
                self.voices[v_name] = v_dir
        
        logging.info(f"VO-SE: {len(self.voices)} 件の音源を検出しました。")
        return self.voices

    def parse_oto_ini(self, voice_dir):
        """
        指定された音源フォルダの oto.ini を解析。
        戻り値: { "あ": {"filename": "a.wav", "pre_utterance": 10.0, ...} }
        """
        config = {}
        ini_path = os.path.join(voice_dir, "oto.ini")
        if not os.path.exists(ini_path):
            return config

        try:
            # UTAU音源は伝統的に Shift-JIS (cp932)
            with open(ini_path, 'r', encoding='cp932', errors='ignore') as f:
                for line in f
