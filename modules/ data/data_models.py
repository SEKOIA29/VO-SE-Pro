

# data_models.py
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
import json

@dataclass
class PitchEvent:
    """
    ピッチベンド（オートメーション）の1点を示すデータ構造
    """
    time: float   # 秒単位
    value: int    # -8192 ～ 8191 (MIDI Pitch Bend規格)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'PitchEvent':
        return PitchEvent(**data)


@dataclass
class NoteEvent:
    """
    音符および読み上げユニットのデータ構造。
    歌唱合成とTalk系（抑揚）の両方のパラメータを統合。
    """
    note_number: int            # MIDIノート番号 (69 = A4)
    start_time: float           # 開始時間（秒）
    duration: float             # 長さ（秒）
    lyric: str = ""             # 歌詞（「あ」「こんにちは」など）
    phonemes: List[str] = field(default_factory=list) # 解析済み音素（["k", "o", "n"]など）
    velocity: int = 100         # 音の強さ (0-127)
    onset_offset: float = 0.0      # AIが解析した「音の始まり」の補正値
    pre_utterance: float = 0.0
    
    # --- 歌唱（Singing）用パラメータ ---
    vibrato_depth: float = 0.0  # ビブラートの深さ (0.0 - 1.0)
    vibrato_rate: float = 5.5   # ビブラートの速さ (Hz)
    formant_shift: float = 0.0  # フォルマントシフト（声質の太さ変化）
    
    # --- 読み上げ（Talk）用パラメータ ---
    # pitch_endに数値が入っている場合、startからdurationにかけてピッチがスライドする（抑揚）
    # None の場合は、歌唱モードとして note_number の一定ピッチで合成される
    pitch_end: Optional[float] = None 
    
    # --- GUI/編集用フラグ（保存対象外） ---
    is_selected: bool = False
    is_playing: bool = False
    
    # AI解析結果を保持するフィールド
    # onset: 音の物理的な開始位置, overlap: 前の音との重なり, pre_utterance: 先行発声
    onset: float = 0.0
    overlap: float = 0.0
    pre_utterance: float = 0.0

    # AI解析で得られる「原音設定」の3要素
    onset: float = 0.0          # 立ち上がり
    pre_utterance: float = 0.0   # 先行発声
    overlap: float = 0.0         # オーバーラップ
    
    has_analysis: bool = False   # 解析済みかどうかのフラグ

    def to_dict(self):
        d = asdict(self)
        # GUIフラグ以外はすべて保存対象に含める
        d.pop('is_selected', None)
        return d

    def __repr__(self):
        mode = "Talk" if self.pitch_end is not None else "Sing"
        return f"Note({mode}, pitch={self.note_number}, lyric='{self.lyric}', start={self.start_time:.2f}s)"

    def to_dict(self) -> Dict[str, Any]:
        """ファイル保存やコピー＆ペースト用に辞書化（GUI用フラグは除外）"""
        d = asdict(self)
        d.pop('is_selected')
        d.pop('is_playing')
        return d

    def save_project(self, file_path):
        # ProjectModel を辞書化（中身の NoteEvent も to_dict される）
        project_data = self.project.serialize()
    
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(project_data, f, indent=4, ensure_ascii=False)
    
        print("プロジェクトを保存しました。")

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'NoteEvent':
        """辞書データからオブジェクトを復元"""
        # GUIフラグが辞書にない場合でも安全に読み込めるように処理
        data.pop('is_selected', None)
        data.pop('is_playing', None)
        return NoteEvent(**data)


@dataclass
class CharacterInfo:
    """
    音源キャラクター（ボイスバンク）の定義。
    UTAU形式やAIモデルのディレクトリ管理に使用。
    """
    id: str                     # 内部ID (例: "aoi_v1")
    name: str                   # 表示名 (例: "アオイ")
    audio_dir: str              # wavファイルやモデルが格納されている絶対パス
    description: str = ""       # キャラクター説明
    waveform_type: str = "sample_based" # "sample_based", "onnx_ai", "sine" など
    engine_params: Dict[str, Any] = field(default_factory=dict) # エンジン固有設定

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectModel:
    """
    楽曲・プロジェクト全体のデータを保持するトップレベルのモデル。
    これをまるごとJSON保存することで、プロジェクトファイル(.vose)になる。
    """
    project_name: str = "Untitled"
    tempo: float = 120.0
    notes: List[NoteEvent] = field(default_factory=list)
    pitch_automation: List[PitchEvent] = field(default_factory=list)
    character_id: str = ""
    
    def serialize(self) -> Dict[str, Any]:
        """プロジェクト全体をシリアライズ"""
        return {
            "project_name": self.project_name,
            "tempo": self.tempo,
            "character_id": self.character_id,
            "notes": [n.to_dict() for n in self.notes],
            "pitch_automation": [p.to_dict() for p in self.pitch_automation]
        }
