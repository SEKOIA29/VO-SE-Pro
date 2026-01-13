#GUI/voice_manager.py

import os
import platform
import glob
import sys
import zipfile
import shutil

class VoiceManager:
    def __init__(self):
        self.system = platform.system()
        # PyInstaller実行時と通常時でパスを切り替え
        self.base_path = getattr(sys, '_MEIPASS', os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        self.internal_voice_dir = os.path.join(self.base_path, "audio_data")
        self.voices = {}  # { "キャラ名": "パス" }

    def scan_utau_voices(self):
        """標準的なUTAU音源パスをスキャン"""
        search_paths = []
        if self.system == "Darwin":
            search_paths.append(os.path.expanduser("~/Library/Application Support/OpenUTAU/Content/Voices/"))
        elif self.system == "Windows":
            search_paths.append(r"C:\Program Files (x86)\UTAU\voice")
            search_paths.append(os.path.expandvars(r"%APPDATA%\OpenUTAU\Content\Voices"))

        # 各パスから oto.ini を探す
        for path in search_paths:
            if os.path.exists(path):
                for ini_path in glob.glob(os.path.join(path, "**/oto.ini"), recursive=True):
                    v_dir = os.path.dirname(ini_path)
                    v_name = os.path.basename(v_dir)
                    self.voices[v_name] = v_dir
        
        # 内部フォルダもスキャン
        if os.path.exists(self.internal_voice_dir):
            for d in os.listdir(self.internal_voice_dir):
                d_path = os.path.join(self.internal_voice_dir, d)
                if os.path.isdir(d_path):
                    self.voices[d] = d_path
        return self.voices

    def parse_oto_ini(self, voice_dir):
        """oto.iniを読み込んで設定を返す"""
        config = {}
        ini_path = os.path.join(voice_dir, "oto.ini")
        if not os.path.exists(ini_path): return {}
        try:
            with open(ini_path, 'r', encoding='cp932', errors='ignore') as f:
                for line in f:
                    if '=' not in line: continue
                    fname, params = line.strip().split('=')
                    p = params.split(',')
                    alias = p[0] if p[0] else fname.replace(".wav", "")
                    config[alias] = {
                        "filename": fname,
                        "left_blank": float(p[1]) if len(p) > 1 else 0.0,
                        "pre_utterance": float(p[4]) if len(p) > 4 else 0.0
                    }
        except: pass
        return config

    def get_voice_path(self, name):
        return self.voices.get(name)
　　
    
