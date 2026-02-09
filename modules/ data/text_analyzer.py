#GUI/text_analyzer.py

import pyopenjtalk
import os
from typing import List, Optional
from .data_models import NoteEvent

class TextAnalyzer:
    def __init__(self, dict_path: Optional[str] = None):
        """
        dict_path: Open JTalkの辞書ディレクトリへのパス。
        """
        # None対策：パスが指定されていない場合は空文字にするか、デフォルトを考慮
        self.dict_path: str = dict_path if dict_path is not None else ""
        
        # 辞書のパスが実在する場合のみセットする（製品としての安全設計）
        if self.dict_path and os.path.exists(self.dict_path):
            pyopenjtalk.set_dic_path(self.dict_path)

    def analyze_text(self, text: Optional[str]) -> List[NoteEvent]:
        """
        入力テキストを音素に分解し、NoteEventのリストを返す。
        """
        # --- Pyright対策: Noneチェック ---
        if text is None or not text.strip():
            return []

        # 1. 音素とアクセント情報の取得
        # pyopenjtalk.run_frontend は List[str] を返す想定
        raw_phonemes = pyopenjtalk.run_frontend(text)
        
        # 戻り値がNoneの場合に備えた安全策
        phonemes_list: List[str] = raw_phonemes if raw_phonemes is not None else []
        
        events: List[NoteEvent] = []
        current_time: float = 0.0
        base_pitch: float = 60.0  # C4

        for p in phonemes_list:
            # 型の安全性を確保
            if not isinstance(p, str):
                continue

            # 2. 音素に応じた標準的な長さを設定
            if p in ["pau", "sil"]:
                duration = 0.25
                p_label = " "
            elif p in "aeiou": 
                duration = 0.15
                p_label = p
            else:
                duration = 0.08
                p_label = p

            # 3. イントネーションのシミュレーション
            is_vowel = p in "aeiou"
            
            p_start = base_pitch
            if is_vowel:
                # 母音は少しピッチを下げて人間味を出す
                p_end = base_pitch - 1.0 
            else:
                p_end = base_pitch

            # 4. NoteEventの生成
            event = NoteEvent(
                note_number=int(p_start),
                start_time=current_time,
                duration=duration,
                lyric=p_label,
                phonemes=[p],
                pitch_end=p_end,
                has_analysis=True
            )
            
            events.append(event)
            current_time += duration
            
        return events
