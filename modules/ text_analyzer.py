#GUI/text_analyzer.py

import pyopenjtalk
import numpy as np
from .data_models import NoteEvent

class TextAnalyzer:
    def __init__(self, dict_path):
        self.dict_path = dict_path # Mac M3の絶対パスを指定

    def analyze_text(self, text: str) -> list[NoteEvent]:
        # 1. Open JTalkでフルコンテキスト解析（文字化け防止のためUTF-8明示）
        # 2026年版 pyopenjtalk では辞書パスを直接指定可能
        labels = pyopenjtalk.extract_fullcontext(text)
        
        # 2. 日本語フロントエンドの実行
        # 音素(p)とアクセント情報(a)を取得
        phonemes = pyopenjtalk.run_frontend(text)
        
        events = []
        current_time = 0.0
        
        for p in phonemes:
            # 読み上げの標準的な長さ(秒)を計算
            duration = 0.12 if p != "pau" else 0.2
            
            # --- Pro版の抑揚ロジック ---
            # pitch_start(出だし)とpitch_end(語尾)を分けることで「喋り」を作る
            # 基準MIDIピッチ 60 (C4)
            base_pitch = 60.0 
            
            # 日本語特有の「語尾下げ」を自動生成（簡易版）
            p_end = base_pitch - 1.5 if p not in ["?", "？"] else base_pitch + 2.0
            
            event = NoteEvent(
                lyric=p,
                start_time=current_time,
                duration=duration,
                pitch_start=base_pitch,
                pitch_end=p_end,
                vibrato_depth=0.0, # 喋りなので初期値は0
                formant_shift=0.0  # デフォルトの太さ
            )
            events.append(event)
            current_time += duration
            
        return events

