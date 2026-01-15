#GUI/text_analyzer.py

import pyopenjtalk
import numpy as np
from .data_models import NoteEvent

class TextAnalyzer:
    def __init__(self, dict_path: str = None):
        """
        dict_path: Open JTalkの辞書ディレクトリへのパス。
        Mac M3の場合、brew install等で入れたパスやプロジェクト内のパスを指定。
        """
        self.dict_path = dict_path
        # 辞書の初期化（実行環境に合わせて調整が必要）
        # pyopenjtalk.set_dic_path(self.dict_path) # 必要に応じて

    def analyze_text(self, text: str) -> list[NoteEvent]:
        """
        入力テキストを音素に分解し、抑揚情報（pitch_start/end）を含むNoteEventのリストを返す。
        """
        # 1. 音素とアクセント情報の取得
        # run_frontendは 'k o N n i ch i w a' のような形式で返す場合があるため分解
        phonemes_list = pyopenjtalk.run_frontend(text)
        
        # ※ pyopenjtalkの戻り値がアクセントラベルを含むリストの場合、
        # その情報を pitch_end の計算に反映させることができます。
        
        events = []
        current_time = 0.0
        base_pitch = 60.0 # C4 (MIDI Note Number)

        for p in phonemes_list:
            # 2. 音素に応じた標準的な長さを設定
            if p == "pau" or p == "sil":
                duration = 0.25  # ポーズ（無音）
                p_label = " "     # GUI上は空白
            elif p in "aeiou": 
                duration = 0.15  # 母音
                p_label = p
            else:
                duration = 0.08  # 子音
                p_label = p

            # 3. 簡易的な日本語イントネーションのシミュレーション
            # pitch_end に値を入れることで NoteEvent の「Talkモード」をトリガー
            # ここでは簡易的に、文末以外の母音を少し下げ、子音はフラットに設定
            is_vowel = p in "aeiou"
            
            if is_vowel:
                # 母音の場合はわずかにピッチを動かして「喋り」の生っぽさを出す
                p_start = base_pitch
                p_end = base_pitch - 1.0 
            else:
                p_start = base_pitch
                p_end = base_pitch

            # 4. NoteEventの生成
            event = NoteEvent(
                note_number=int(p_start),
                start_time=current_time,
                duration=duration,
                lyric=p_label,
                phonemes=[p],
                pitch_end=p_end,      # これによりTalkモードとして認識される
                has_analysis=True
            )
            
            events.append(event)
            current_time += duration
            
        return events
