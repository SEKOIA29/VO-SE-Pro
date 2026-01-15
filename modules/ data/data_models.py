

# data_models.py
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
import json

@dataclass
class PitchEvent:
    """ピッチベンド（オートメーション）の1点を示すデータ構造"""
    time: float   # 秒単位
    value: int    # -8192 ～ 8191 (MIDI Pitch Bend規格)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'PitchEvent':
        return PitchEvent(**data)


@dataclass
class NoteEvent:
    """音符および読み上げユニットのデータ構造"""
    note_number: int            # MIDIノート番号 (69 = A4)
    start_time: float           # 開始時間（秒）
    duration: float             # 長さ（秒）
    lyric: str = ""             # 歌詞
    phonemes: List[str] = field(default_factory=list) # 解析済み音素
    velocity: int = 100         # 音の強さ (0-127)
    
    # --- 歌唱（Singing）用パラメータ ---
    vibrato_depth: float = 0.0  # ビブラートの深さ (0.0 - 1.0)
    vibrato_rate: float = 5.5   # ビブラートの速さ (Hz)
    formant_shift: float = 0.0  # フォルマントシフト
    
    # --- 読み上げ（Talk）用パラメータ ---
    # 数値が入っている場合は抑揚スライド。Noneは歌唱固定ピッチ。
    pitch_end: Optional[float] = None 
    
    # --- AI/エンジン解析結果 (原音設定の3要素) ---
    onset: float = 0.0          # 立ち上がり(物理開始)
    pre_utterance: float = 0.0  # 先行発声
    overlap: float = 0.0        # 前の音との重なり
    has_analysis: bool = False  # 解析済みフラグ

    # --- GUI/編集用フラグ（シリアライズ対象外） ---
    is_selected: bool = field(default=False, repr=False)
    is_playing: bool = field(default=False, repr=False)


    def __init__(self, lyrics, start_time, duration, note_number, onset=0.0):
        self.lyrics = lyrics
        self.start_time = start_time    # 開始秒
        self.duration = duration        # 長さ秒
        self.note_number = note_number  # MIDI番号 (60=C4)
        self.onset = onset              # 発音位置オフセット（AI赤線）

    def __repr__(self):
        mode = "Talk" if self.pitch_end is not None else "Sing"
        return f"Note({mode}, pitch={self.note_number}, lyric='{self.lyric}', start={self.start_time:.2f}s)"

    def to_dict(self) -> Dict[str, Any]:
        """保存用に辞書化（GUI用フラグは除外）"""
        d = asdict(self)
        d.pop('is_selected', None)
        d.pop('is_playing', None)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NoteEvent':
        """辞書データから復元（不要なキーを無視）"""
        # クラスのフィールドに存在しないキーを除去して初期化
        valid_keys = cls.__dataclass_fields__.keys()
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered_data)


@dataclass
class CharacterInfo:
    """音源キャラクター（ボイスバンク）の定義"""
    id: str
    name: str
    audio_dir: str
    description: str = ""
    waveform_type: str = "sample_based"
    engine_params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectModel:
    """楽曲プロジェクト全体のデータを管理"""
    project_name: str = "Untitled"
    tempo: float = 120.0
    notes: List[NoteEvent] = field(default_factory=list)
    pitch_automation: List[PitchEvent] = field(default_factory=list)
    character_id: str = ""
    
    def serialize(self) -> Dict[str, Any]:
        return {
            "project_name": self.project_name,
            "tempo": self.tempo,
            "character_id": self.character_id,
            "notes": [n.to_dict() for n in self.notes],
            "pitch_automation": [p.to_dict() for p in self.pitch_automation]
        }

    def save_to_file(self, file_path: str):
        """JSONとしてファイル保存"""
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.serialize(), f, indent=4, ensure_ascii=False)
