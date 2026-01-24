# main_window.py 

import sys
import os
import time
import json
import ctypes
import zipfile
import platform
import threading
import numpy as np
import librosa
import soundfile as sf
import sounddevice as sd
import librosa
import wave
import pyworld as pw
from typing import List
from typing import List, Optional, Dict, Any
from scipy.io.wavfile import write as wav_write

# Qt関連
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QScrollBar, QInputDialog, QLineEdit,
    QLabel, QSplitter, QComboBox, QProgressBar, QMessageBox, QToolBar,
    QGridLayout, QFrame
)
from PySide6.QtGui import QAction, QKeySequence, QKeyEvent, QPainter, QPen, QPixmap
from PySide6.QtCore import Slot, Qt, QTimer, Signal, QThread, QUrl

# 外部ライブラリ
from janome.tokenizer import Tokenizer
import mido
import numpy as np

from .timeline_widget import TimelineWidget
from audio.vo_se_engine import VO_SE_Engine
from audio.voice_manager import VoiceManager


# ==========================================================
# 1. CreditsDialog クラス about画面
# ==========================================================
class CreditsDialog(QDialog):
    def __init__(self, partner_names=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("VO-SE Pro - About & Credits")
        self.setFixedSize(550, 650)
        self.setStyleSheet("background-color: #0d0d0d; color: #e0e0e0;")

        # 名前リストを受け取る（ID: 名前 の辞書形式）
        self.partner_names = partner_names if partner_names else {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)

        # --- ヘッダーエリア ---
        title = QLabel("VO-SE Pro")
        title.setFont(QFont("Segoe UI", 32, QFont.Weight.Bold))
        title.setStyleSheet("color: #00ffcc; letter-spacing: 2px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        version = QLabel("Version 1.0.0 Alpha | Aura AI Engine Loaded") # エンジン名
        version.setFont(QFont("Consolas", 9))
        version.setStyleSheet("color: #666;")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #333; margin: 15px 0;")
        layout.addWidget(line)

        # --- パートナーセクション ---
        header_partner = QLabel("AURAL FOUNDING VOICE PARTNERS") # パートナーセクション名
        header_partner.setFont(QFont("Impact", 14))
        header_partner.setStyleSheet("color: #ff007f; margin-bottom: 5px;")
        layout.addWidget(header_partner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        
        container = QWidget()
        self.partners_layout = QVBoxLayout(container)
        self.partners_layout.setSpacing(8)

        # 10枠を生成
        for i in range(1, 11):
            slot = self.create_partner_row(i)
            self.partners_layout.addWidget(slot)

        scroll.setWidget(container)
        layout.addWidget(scroll)

        # --- フッターエリア ---
        footer_line = QFrame()
        footer_line.setFrameShape(QFrame.Shape.HLine)
        footer_line.setStyleSheet("color: #333;")
        layout.addWidget(footer_line)

        dev_info = QLabel("Engineered by [Your Name]\n© 2026 VO-SE Project") # 2026年に更新
        dev_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dev_info.setStyleSheet("color: #444; font-size: 10px; margin-top: 10px;")
        layout.addWidget(dev_info)

    def create_partner_row(self, index):
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border: 1px solid #2d2d2d;
                border-radius: 5px;
            }
            QFrame:hover {
                border: 1px solid #00ffcc;
            }
        """)
        row = QHBoxLayout(frame)
        
        id_lbl = QLabel(f"ID-{index:02}")
        id_lbl.setStyleSheet("color: #00ffcc; font-family: 'Consolas'; font-weight: bold;")
        
        # 動的な名前判定
        name = self.partner_names.get(index, "UNDER RECRUITMENT")
        is_recruiting = (name == "UNDER RECRUITMENT")
        
        name_lbl = QLabel(name)
        if is_recruiting:
            name_lbl.setStyleSheet("color: #444; font-style: italic; font-weight: bold;")
        else:
            name_lbl.setStyleSheet("color: #ffffff; font-weight: bold;") # 決まったら白く光らせる
        
        badge = QLabel("DYNAMICS READY")
        badge.setStyleSheet("""
            background-color: #000;
            color: #00ffcc;
            border: 1px solid #00ffcc;
            border-radius: 3px;
            font-size: 8px;
            padding: 2px 5px;
        """)

        row.addWidget(id_lbl)
        row.addWidget(name_lbl, 1)
        row.addWidget(badge)
        
        return frame




class AutoOtoEngine:
    def __init__(self, sample_rate=44100):
        self.sample_rate = sample_rate

    def analyze_wav(self, file_path):
        """WAVファイルを解析して、UTAU形式のパラメータを返す"""
        with wave.open(file_path, 'rb') as f:
            n_frames = f.getnframes()
            frames = f.readframes(n_frames)
            samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32)

        # 1. 振幅のエンベロープ（外形）を計算
        # 窓幅 10ms 程度で移動平均をとる
        win_size = int(self.sample_rate * 0.01) 
        envelope = np.convolve(np.abs(samples), np.ones(win_size)/win_size, mode='same')
        max_amp = np.max(envelope)

        # 2. オフセット (Offset): 音が始まる地点 (最大振幅の 5%)
        start_idx = np.where(envelope > max_amp * 0.05)[0][0]
        offset_ms = (start_idx / self.sample_rate) * 1000

        # 3. 先行発声 (Pre-utterance): 子音から母音へ（音量が急増し終わる地点）
        # 音量の増加率が最大になる付近を特定
        diff = np.diff(envelope[start_idx : start_idx + int(self.sample_rate * 0.5)])
        accel_idx = np.argmax(diff) + start_idx
        preutter_ms = ((accel_idx - start_idx) / self.sample_rate) * 1000

        # 4. オーバーラップ (Overlap): 前の音との重なり (先行発声の 1/2)
        overlap_ms = preutter_ms / 2

        return {
            "offset": int(offset_ms),
            "preutter": int(preutter_ms),
            "overlap": int(overlap_ms),
            "constant": int(preutter_ms * 2), # 子音固定範囲
            "blank": -10 # 右ブランク（とりあえず末尾10msカット）
        }

    def generate_oto_text(self, wav_name, params):
        """1行分のoto.iniテキストを生成"""
        alias = os.path.splitext(wav_name)[0]
        return f"{wav_name}={alias},{params['offset']},{params['constant']},{params['blank']},{params['preutter']},{params['overlap']}"



    
#----------
# 1. パス解決用の関数（
#----------
def get_resource_path(relative_path):
    """内蔵DLLなどのリソースパスを取得"""
    if getattr(sys, 'frozen', False):
        # EXE化した後のパス（一時フォルダ）
        base_path = sys._MEIPASS
    else:
        # 開発中（.py実行）のパス
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)





# 内部モジュール（存在しない場合はモック実装があっった）
try:
    from GUI.vo_se_engine import VO_SE_Engine
except ImportError:


class VoSeEngine:
    def export_to_wav(self, notes, pitch_data, file_path):
        """
        notes: TimelineWidget.notes_list (NoteEventのリスト)
        pitch_data: GraphEditorWidget.pitch_events (Pitchデータのリスト)
        file_path: 保存先のフルパス (example.wav)
        """
        # 1. 再生時と同じ合成ロジックで音声波形を生成
        # (ここには既存の合成エンジンを呼び出すコードが入ります)
        audio_frames = self.generate_audio_signal(notes, pitch_data)
        
        # 2. サンプリングレートの設定 (44.1kHzが一般的)
        sample_rate = 44100
        
        # 3. numpy配列を16bit PCM形式に変換 (音割れ防止と標準フォーマット化)
        # -1.0〜1.0 の範囲を -32768〜32767 に変換
        audio_data = (audio_frames * 32767).astype(np.int16)
        
        # 4. 指定されたパスにWAVとして書き出し
        # ここで指定した file_path に実際に保存されます
        wav_write(file_path, sample_rate, audio_data)
        
        return file_path

 
from .timeline_widget import TimelineWidget
from .vo_se_engine import VO_SE_Engine
from .voice_manager import VoiceManager

try:
    from .timeline_widget import TimelineWidget
except ImportError:
    class TimelineWidget(QWidget):
        notes_changed_signal = Signal()
        def __init__(self): 
            super().__init__()
            self.notes_list = []
            self.tempo = 120
            self.key_height_pixels = 20
            self.pixels_per_beat = 40
            self.pixels_per_second = 50
            self.lowest_note_display = 21
        def get_notes_data(self): return self.notes_list
        def get_all_notes(self): return self.notes_list
        def set_notes(self, notes): self.notes_list = notes
        def get_selected_notes_range(self): return (0.0, 10.0)
        def set_current_time(self, t): pass
        def set_recording_state(self, state, time): pass
        def delete_selected_notes(self): pass
        def set_vertical_offset(self, offset): pass
        def set_horizontal_offset(self, offset): pass
        def copy_selected_notes_to_clipboard(self): pass
        def paste_notes_from_clipboard(self): pass
        def get_max_beat_position(self): return 100
        def seconds_to_beats(self, sec): return sec * self.tempo / 60
        def beats_to_pixels(self, beats): return beats * self.pixels_per_beat
        def note_to_y(self, note_num): return (127 - note_num) * self.key_height_pixels
        def get_pitch_data(self): return []
        def set_pitch_data(self, data): pass
        def add_note_from_midi(self, note_num, velocity): pass
        def update(self): super().update()

try:
    from .keyboard_sidebar_widget import KeyboardSidebarWidget
except ImportError:
    class KeyboardSidebarWidget(QWidget):
        def __init__(self, height, lowest): super().__init__()
        def set_key_height_pixels(self, h): pass

try:
    from .midi_manager import load_midi_file, MidiInputManager
except ImportError:
    def load_midi_file(path): return []
    class MidiInputManager:
        def __init__(self, port): pass
        def start(self): pass
        def stop(self): pass

try:
    from .data_models import NoteEvent, PitchEvent
except ImportError:
    class NoteEvent:
        def __init__(self, **kwargs):
            self.lyrics = kwargs.get('lyrics', '')
            self.start_time = kwargs.get('start_time', 0.0)
            self.duration = kwargs.get('duration', 0.5)
            self.note_number = kwargs.get('note_number', 60)
            self.velocity = kwargs.get('velocity', 100)
            self.pitch = kwargs.get('pitch', 440.0)
            self.phonemes = kwargs.get('phonemes', '')
            self.pre_utterance = 0.0
            self.overlap = 0.0
            self.onset = 0.0
            self.has_analysis = False
        
        def to_dict(self):
            return {
                'lyrics': self.lyrics,
                'start_time': self.start_time,
                'duration': self.duration,
                'note_number': self.note_number,
                'velocity': self.velocity,
                'pitch': self.pitch,
                'phonemes': self.phonemes
            }
        
        @staticmethod
        def from_dict(d):
            return NoteEvent(**d)
    
    class PitchEvent:
        def __init__(self, time=0.0, pitch=0.0):
            self.time = time
            self.pitch = pitch
        
        def to_dict(self):
            return {'time': self.time, 'pitch': self.pitch}
        
        @staticmethod
        def from_dict(d):
            return PitchEvent(d.get('time', 0.0), d.get('pitch', 0.0))

try:
    from .graph_editor_widget import GraphEditorWidget
except ImportError:
    class GraphEditorWidget(QWidget):
        pitch_data_updated = Signal(list)
        def __init__(self): 
            super().__init__()
            self.tempo = 120
        def set_pitch_events(self, events): pass
        def set_current_time(self, t): pass

try:
    from .voice_manager import VoiceManager
except ImportError:
    class VoiceManager:
        def __init__(self, ai):
            self.voices: Dict[str, Dict] = {}
            self.internal_voice_dir = "voice_banks"
        def first_run_setup(self): pass
        def get_current_voice_path(self): return "voice_banks/default"
        def run_batch_voice_analysis(self, dir, callback): return {}
        def scan_utau_voices(self): pass
        def install_voice_from_zip(self, path): return "NewVoice"
        def get_character_color(self, path): return "#4A90E2"

try:
    from .audio_output import AudioOutput
except ImportError:
    class AudioOutput:
        def __init__(self): pass
        def play_se(self, path): pass

try:
    from backend.intonation import IntonationAnalyzer
except ImportError:
    class IntonationAnalyzer:
        def analyze(self, text): return []
        def parse_trace_to_notes(self, trace): return []
        def analyze_to_pro_events(self, text): return []

try:
    from backend.audio_player import AudioPlayer
except ImportError:
    class AudioPlayer:
        def __init__(self, volume=0.8): pass
        def play_file(self, path): pass
        def play(self, data): pass

try:
    from utils.dynamics_ai import DynamicsAIEngine
except ImportError:
    class DynamicsAIEngine:
        def generate_emotional_pitch(self, f0): return f0


# ==============================================================================
# 設定管理クラス（モック実装）
# ==============================================================================

class ConfigHandler:  #愛なんてシャボン玉！
    """設定ファイルの読み書き"""
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
    
    def load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {"default_voice": "標準ボイス", "volume": 0.8}
    
    def save_config(self, config: Dict[str, Any]):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"設定保存エラー: {e}")


# ==============================================================================
# ボイスカードウィジェット
# ==============================================================================

class VoiceCardWidget(QFrame):
    """音源選択用のカードUI"""
    clicked = Signal(str)
    
    def __init__(self, name: str, icon_path: str, color: str):
        super().__init__()
        self.name = name
        self.is_selected = False
        
        self.setFrameStyle(QFrame.Box | QFrame.Raised)
        self.setLineWidth(2)
        self.setMaximumSize(150, 180)
        self.setMinimumSize(150, 180)
        
        layout = QVBoxLayout(self)
        
        # アイコン
        icon_label = QLabel()
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_label.setPixmap(pixmap)
        else:
            icon_label.setText("🎤")
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setStyleSheet("font-size: 48px;")
        
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)
        
        # 名前
        name_label = QLabel(name)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)
        
        self.setStyleSheet(f"background-color: {color}; border-radius: 8px;")
    
    def mousePressEvent(self, event):
        self.clicked.emit(self.name)
    
    def set_selected(self, selected: bool):
        self.is_selected = selected
        if selected:
            self.setLineWidth(4)
            self.setStyleSheet(self.styleSheet() + "border: 4px solid #FFD700;")
        else:
            self.setLineWidth(2)


# ==============================================================================
# バックグラウンドスレッド
# ==============================================================================

class AnalysisThread(QThread):
    """AI解析をバックグラウンドで実行するスレッド"""
    progress = Signal(int, str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, voice_manager, target_dir):
        super().__init__()
        self.voice_manager = voice_manager
        self.target_dir = target_dir

    def run(self):
        try:
            results = self.voice_manager.run_batch_voice_analysis(
                self.target_dir,
                self.progress.emit
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


# ==============================================================================
# メインウィンドウクラス
# ==============================================================================

class MainWindow(QMainWindow):
    """VO-SE Pro  メインウィンドウ"""

    def __init__(self, parent=None, engine=None, ai=None, config=None):
        super().__init__(parent)

        # ==============================================================================
        # --- ここで辞書を定義 ---
        self.confirmed_partners = {
            1: "UNDER RECRUITMENT",       # ID-01に反映
            2: "UNDER RECRUITMENT",       # ID-02に反映
            3: "UNDER RECRUITMENT",       # ID-03に反映
            # 未決定のIDは書かなくてOK（自動的に UNDER RECRUITMENT にならけど一応書いとく）
        }

        self.confirmed_partners = {} # これだけで10枠すべてが「UNDER RECRUITMENT」になります
       
        # ==============================================================================


        self.render_timer = QTimer()
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(self.execute_async_render)
        self.vo_se_engine = VO_SE_Engine()
         
        self.init_ui()
        self.init_engine()
        
        # --- 1. 基盤の初期化 ---
        self.config_manager = ConfigHandler()
        self.config = config if config else self.config_manager.load_config()
        self.vo_se_engine = engine if engine else VO_SE_Engine()
        self.dynamics_ai = ai if ai else DynamicsAIEngine()
        
        # 内部状態
        self.is_playing = False
        self.is_recording = False
        self.is_looping = False
        self.is_looping_selection = False
        self.current_playback_time = 0.0
        self.current_voice = self.config.get("default_voice", "標準ボイス")
        self.volume = self.config.get("volume", 0.8)
        self.pitch_data: List[PitchEvent] = []
        self.playing_notes = {}
        self.voice_cards: List[VoiceCardWidget] = []
        
        # DLLライブラリ（後で初期化）
        self.lib = None
        
        # --- 2. DLLエンジンのロード ---
        self.init_dll_engine()
        
        # --- 3. UIコンポーネントの作成 ---
        self.init_ui()
        
        # --- 4. マネージャー・解析器の起動 ---
        self.voice_manager = VoiceManager(self.dynamics_ai)
        self.voice_manager.first_run_setup()
        self.analyzer = IntonationAnalyzer()
        self.audio_player = AudioPlayer(volume=self.volume)
        self.audio_output = AudioOutput()
        self.midi_manager: Optional[MidiInputManager] = None
        
        # --- 5. 仕上げ設定 ---
        self.setAcceptDrops(True)
        self.playback_timer = QTimer(self)
        self.playback_timer.timeout.connect(self.update_playback_cursor)
        self.playback_timer.setInterval(10)
        
        self.vo_se_engine.set_active_character(self.current_voice)
        self.setup_connections()
        
        # 音源スキャン
        self.scan_utau_voices()
        # ウィンドウタイトル
        self.setWindowTitle("VO-SE Pro")

    #---------
    #エンジン接続関係
    #---------

    def init_ui(self):
        self.setWindowTitle("VO-SE Engine DAW")
        layout = QVBoxLayout()
        self.play_btn = QPushButton("再生")
        self.play_btn.clicked.connect(self.handle_playback)
        layout.addWidget(self.play_btn)
        
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def generate_pitch_curve(self, note, prev_note=None):
        """ノートのピッチをHz配列として生成（ポルタメント対応）"""
        target_hz = 440.0 * (2.0 ** ((note.note_number - 69) / 12.0))
        num_frames = int((note.duration * 1000.0) / 5.0)
        curve = np.ones(num_frames) * target_hz
        
        if prev_note:
            prev_hz = 440.0 * (2.0 ** ((prev_note.note_number - 69) / 12.0))
            port_f = min(10, num_frames)
            curve[:port_f] = np.linspace(prev_hz, target_hz, port_f)
        return curve

    def handle_playback(self):
        # 1. Timelineからノートを取得(例)
        notes = self.get_notes_from_timeline() 
        
        # 2. 各ノートにピッチカーブを付与
        prev = None
        for n in notes:
            n.pitch_curve = self.generate_pitch_curve(n, prev)
            prev = n
            
        # 3. 合成と再生
        audio = self.engine.synthesize(notes)
        self.engine.play(audio)

    def get_notes_from_timeline(self):
        # 本来はGUIのピアノロールからデータを取ってくる部分
        # ここではテスト用にダミーのリストを返します
        return []

    # ==========================================================================
    # エンジン接続スロット
    # ==========================================================================

    def prepare_rendering_data(self):
        """GUIのノート情報をエンジン用のデータ構造に変換する"""
        gui_notes = self.timeline_widget.get_all_notes()
        song_data = []

        for note in gui_notes:
            # 1. MIDIノート番号を基本周波数(Hz)に変換
            # 公式: f = 440 * 2^((n-69)/12)
            base_hz = 440.0 * (2.0 ** ((note.note_number - 69) / 12.0))

            # 2. 5msごとのフレーム数を計算 (例: 0.5秒なら100フレーム)
            # WORLDエンジンは5ms(0.005s)間隔のデータを求める
            num_frames = int(max(1, (note.duration * 1000) / 5))
        
            # 3. ピッチ配列の作成
            # 本来はここで graph_editor_widget からピッチベンド値を取得して加算します
            # 現時点では、安定した基本周波数の配列を作成
            pitch_list = np.ones(num_frames, dtype=np.float32) * base_hz

            song_data.append({
                'lyric': note.lyrics,  # 「あ」「い」など
                'pitch_list': pitch_list
            })
    
        return song_data
    
    
    def start_playback(self):
        """再生ボタンが押された時の処理"""
        # タイムライン上のノートリストを取得（NoteEventオブジェクトのリスト）
        notes = self.timeline_widget.get_all_notes()
        
        if not notes:
            self.statusBar().showMessage("再生するノートがありません。")
            return

        self.statusBar().showMessage("音声を合成中...")
        
        # 2. 合成実行 (最新のピッチシフト対応版を呼び出し)
        # 内部でMIDI番号→Hz変換、WORLD合成が行われる
        audio_data = self.vo_se_engine.synthesize(notes)

        if audio_data is not None and len(audio_data) > 0:
            # 3. 再生
            self.vo_se_engine.play(audio_data)
            self.statusBar().showMessage("再生中")
        else:
            self.statusBar().showMessage("合成に失敗しました。")

    def stop_playback(self):
        """停止ボタンが押された時の処理"""
        self.vo_se_engine.stop()
        self.statusBar().showMessage("停止しました。")

    def export_wav(self):
        """WAV書き出し処理"""
        notes = self.timeline_widget.get_all_notes()
        if not notes: return

        path, _ = QFileDialog.getSaveFileName(self, "WAV保存", "", "WAV (*.wav)")
        if path:
            audio_data = self.vo_se_engine.synthesize(notes)
            self.vo_se_engine.export_to_wav(audio_data, path)
            self.statusBar().showMessage(f"保存完了: {path}")

    # --- 音源選択時に呼び出す連携 ---
    def on_voice_library_changed(self, voice_path, oto_map):
        """音源フォルダが切り替わった時にエンジンにデータを渡す"""
        self.vo_se_engine.set_voice_library(voice_path)
        self.vo_se_engine.set_oto_data(oto_map)


    # --- 未実装のスタブ（エラー防止） ---
    def set_active_character(self, name): pass
    def set_tempo(self, tempo): pass
    def play_audio(self, audio): pass
    def stop_playback(self): pass
    def close(self): pass
    def prepare_cache(self, notes): pass

    
    # ==========================================================================
    # 初期化メソッド
    # ==========================================================================

    def init_dll_engine(self):
        """C言語レンダリングエンジンDLLの接続"""
        dll_path = os.path.join(os.path.dirname(__file__), "bin", "libvo_se.dll")
        if os.path.exists(dll_path):
            try:
                self.lib = ctypes.CDLL(dll_path)
                # 関数シグネチャの定義（実際の実装に合わせて調整）
                if hasattr(self.lib, 'execute_render'):
                    self.lib.execute_render.argtypes = [
                        ctypes.c_void_p,  # note_array
                        ctypes.c_int,     # count
                        ctypes.c_char_p,  # output_path
                        ctypes.c_int      # sample_rate
                    ]
                print("✓ Engine DLL loaded successfully")
            except Exception as e:
                print(f"⚠ DLL load error: {e}")
                self.lib = None
        else:
            print("⚠ Warning: libvo_se.dll not found")

    
    def init_engine(self):
        # パス指定
        # OSに合わせて拡張子を変える（GitHub Actionsのマルチプラットフォーム対応）
        ext = ".dll" if platform.system() == "Windows" else ".dylib"
        dll_relative_path = os.path.join("bin", f"libvo_se{ext}")
        self.dll_full_path = get_resource_path(dll_relative_path)
        
        # binフォルダ内のDLLを指名
        dll_relative_path = os.path.join("bin", f"libvo_se{ext}")
        self.dll_full_path = get_resource_path(dll_relative_path)

        # --- 【追加】公式音源の自動ロード ---
        # assets/voice/official/ という階層に音源を置く想定
        official_voice_path = get_resource_path(os.path.join("assets", "voice", "official"))
        official_oto_path = os.path.join(official_voice_path, "oto.ini")

        if os.path.exists(official_oto_path):
            print(f"✓ Official voice found: {official_voice_path}")
            # ここでVoiceManagerやEngineにパスを渡す
            # 例: self.on_voice_library_changed(official_voice_path, self.parse_oto_ini(official_oto_path))

        # 3. ロード実行
        try:
            self.lib = ctypes.CDLL(self.dll_full_path)
            print(f"Loaded Engine: {self.dll_full_path}")
        except Exception as e:
            print(f"Failed to load engine: {e}")

    def open_about(self):
        """About画面を表示"""
        dialog = CreditsDialog(self.confirmed_partners, self)
        dialog.exec()
    

    def init_ui(self):
        """UIコンポーネントの構築"""
        self.setWindowTitle("VO-SE Pro ")
        self.setGeometry(100, 100, 1200, 800)
        
        # メインウィジェット
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)
        
        # ツールバー作成
        self.toolbar = QToolBar("Main Toolbar")
        self.addToolBar(self.toolbar)
        
        # コントロールパネル（上部）
        self.setup_control_panel()
        
        # タイムライン・エディタ（中央）
        self.setup_timeline_area()
        
        # 音源選択グリッド（右サイド）
        self.setup_voice_grid()
        
        # ステータスバー（下部）
        self.setup_status_bar()
        
        # メニューとアクション
        self.setup_actions()
        self.setup_menus()
        
        # 追加UI（フォルマント、パフォーマンス、Talk）
        self.setup_formant_slider()
        self.setup_performance_toggle()
        self.init_pro_talk_ui()
        self.lyrics_button = QPushButton("歌詞一括入力")
        self.lyrics_button.clicked.connect(self.on_click_apply_lyrics_bulk)
        
        print("✓ UI components initialized")
        

    def setup_control_panel(self):
        """上部コントロールパネルの構築"""
        panel_layout = QHBoxLayout()
        
        # 時間表示
        self.time_display_label = QLabel("00:00.000")
        panel_layout.addWidget(self.time_display_label)
        
        # 再生コントロール
        self.play_button = QPushButton("▶ 再生")
        self.play_button.clicked.connect(self.on_play_pause_toggled)
        panel_layout.addWidget(self.play_button)
        
        self.record_button = QPushButton("● 録音")
        self.record_button.clicked.connect(self.on_record_toggled)
        panel_layout.addWidget(self.record_button)
        
        self.loop_button = QPushButton("ループ: OFF")
        self.loop_button.clicked.connect(self.on_loop_button_toggled)
        panel_layout.addWidget(self.loop_button)
        
        # テンポ入力
        self.tempo_label = QLabel("BPM（テンポ）:")
        self.tempo_input = QLineEdit("120")
        self.tempo_input.setFixedWidth(60)
        self.tempo_input.returnPressed.connect(self.update_tempo_from_input)
        panel_layout.addWidget(self.tempo_label)
        panel_layout.addWidget(self.tempo_input)

       
        
        # キャラクター選択
        panel_layout.addWidget(QLabel("Voice:"))
        self.character_selector = QComboBox()
        panel_layout.addWidget(self.character_selector)
        
        # MIDIポート選択
        panel_layout.addWidget(QLabel("MIDI:"))
        self.midi_port_selector = QComboBox()
        self.midi_port_selector.addItem("ポートなし", None)
        self.midi_port_selector.currentIndexChanged.connect(self.on_midi_port_changed)
        panel_layout.addWidget(self.midi_port_selector)
        
        # ファイル操作
        self.open_button = QPushButton("開く")
        self.open_button.clicked.connect(self.open_file_dialog_and_load_midi)
        panel_layout.addWidget(self.open_button)
        
        # レンダリングボタン
        self.render_button = QPushButton("合成")
        self.render_button.clicked.connect(self.on_render_button_clicked)
        panel_layout.addWidget(self.render_button)
        
        # AI解析ボタン
        self.ai_analyze_button = QPushButton(" AI Auto Setup")
        self.ai_analyze_button.setStyleSheet(
            "background-color: #4A90E2; color: white; font-weight: bold;"
        )
        self.ai_analyze_button.clicked.connect(self.start_batch_analysis)
        panel_layout.addWidget(self.ai_analyze_button)
        
        # AI歌詞配置ボタン
        self.auto_lyrics_button = QPushButton("自動歌詞")
        self.auto_lyrics_button.clicked.connect(self.on_click_auto_lyrics)
        panel_layout.addWidget(self.auto_lyrics_button)

        # --- ここからパラメーター切り替えボタンの追加 ---
        panel_layout.addSpacing(20) # 少し隙間をあける
        panel_layout.addWidget(QLabel("Edit Mode:"))
        
        # ボタングループで「どれか1つが選択されている状態」を作る
        self.param_group = QButtonGroup(self)
        self.param_buttons = {} # 後で参照しやすいように辞書に保存
        
        param_list = [
            ("Pitch", "#3498db"),   # 青
            ("Gender", "#e74c3c"),  # 赤
            ("Tension", "#2ecc71"), # 緑
            ("Breath", "#f1c40f")   # 黄
        ]
        
        for name, color in param_list:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setFixedWidth(60)
            # 選択中のボタンに色を付けるスタイルシート
            btn.setStyleSheet(f"QPushButton:checked {{ background-color: {color}; color: white; border: 1px solid white; }}")
            
            if name == "Pitch":
                btn.setChecked(True) # 初期状態
            
            panel_layout.addWidget(btn)
            self.param_group.addButton(btn)
            self.param_buttons[name] = btn

        # ボタンがクリックされたらグラフエディタのモードを切り替える
        self.param_group.buttonClicked.connect(self.on_param_mode_changed)
        # --- ライバルが多い ---

        panel_layout.addStretch()
        
        panel_layout.addStretch()
        self.main_layout.addLayout(panel_layout)

    def setup_timeline_area(self):
        """タイムラインとエディタエリアの構築"""
        # スプリッター（上下分割）
        splitter = QSplitter(Qt.Vertical)
        
        # タイムライン部分（横スクロール付き）
        timeline_container = QWidget()
        timeline_layout = QHBoxLayout(timeline_container)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        
        # キーボードサイドバー
        self.keyboard_sidebar = KeyboardSidebarWidget(20, 21)
        timeline_layout.addWidget(self.keyboard_sidebar)
        
        # タイムライン本体
        self.timeline_widget = TimelineWidget()
        timeline_layout.addWidget(self.timeline_widget)
        
        # 垂直スクロールバー
        self.v_scrollbar = QScrollBar(Qt.Vertical)
        self.v_scrollbar.valueChanged.connect(self.timeline_widget.set_vertical_offset)
        timeline_layout.addWidget(self.v_scrollbar)
        
        splitter.addWidget(timeline_container)
        
        # 水平スクロールバー
        self.h_scrollbar = QScrollBar(Qt.Horizontal)
        self.h_scrollbar.valueChanged.connect(self.timeline_widget.set_horizontal_offset)
        self.main_layout.addWidget(self.h_scrollbar)
        
        # グラフエディタ（ピッチ編集）
        self.graph_editor_widget = GraphEditorWidget()
        self.graph_editor_widget.pitch_data_updated.connect(self.on_pitch_data_updated)
        splitter.addWidget(self.graph_editor_widget)
        
        self.main_layout.addWidget(splitter)

    def setup_voice_grid(self):
        """音源選択グリッドの構築"""
        voice_container = QWidget()
        voice_container.setMaximumHeight(200)
        self.voice_grid = QGridLayout(voice_container)
        self.main_layout.addWidget(voice_container)

    def setup_status_bar(self):
        """ステータスバーの構築"""
        self.status_label = QLabel("準備完了")
        self.statusBar().addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        self.statusBar().addPermanentWidget(self.progress_bar)

    def setup_actions(self):
        """アクションの定義"""
        self.copy_action = QAction("コピー", self)
        self.copy_action.setShortcuts(QKeySequence.StandardKey.Copy)
        self.copy_action.triggered.connect(
            self.timeline_widget.copy_selected_notes_to_clipboard
        )
        
        self.paste_action = QAction("ペースト", self)
        self.paste_action.setShortcuts(QKeySequence.StandardKey.Paste)
        self.paste_action.triggered.connect(
            self.timeline_widget.paste_notes_from_clipboard
        )
        
        self.save_action = QAction("保存(&S)", self)
        self.save_action.setShortcuts(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_file_dialog_and_save_midi)

    def setup_menus(self):
        """メニューバーの構築"""
        # ファイルメニュー
        file_menu = self.menuBar().addMenu("ファイル(&F)")
        file_menu.addAction(self.save_action)
        
        export_action = QAction("WAV書き出し...", self)
        export_action.triggered.connect(self.on_export_button_clicked)
        file_menu.addAction(export_action)
        
        export_midi_action = QAction("MIDI書き出し...", self)
        export_midi_action.triggered.connect(self.export_to_midi_file)
        file_menu.addAction(export_midi_action)

        # 編集メニュー
        edit_menu = self.menuBar().addMenu("編集(&E)")
        edit_menu.addAction(self.copy_action)
        edit_menu.addAction(self.paste_action)

    def setup_connections(self):
        """シグナル/スロット接続"""
        # 1. 垂直スクロールの同期（鍵盤とノート）
        self.v_scrollbar.valueChanged.connect(self.keyboard_sidebar.set_vertical_offset)
        self.v_scrollbar.valueChanged.connect(self.timeline_widget.set_vertical_offset)

        # 2. 水平スクロールの同期（ノートとピッチグラフ）
        self.h_scrollbar.valueChanged.connect(self.timeline_widget.set_horizontal_offset)
        self.h_scrollbar.valueChanged.connect(self.graph_editor_widget.set_horizontal_offset)  

        # 3. データの更新通知
        self.timeline_widget.notes_changed_signal.connect(self.on_timeline_updated)
        

    def setup_formant_slider(self):
        """フォルマントスライダーの設定"""
        from PySide6.QtWidgets import QSlider
        
        self.formant_label = QLabel("声の太さ (Formant)")
        self.formant_slider = QSlider(Qt.Orientation.Horizontal)
        self.formant_slider.setRange(-100, 100)
        self.formant_slider.setValue(0)
        self.formant_slider.setMaximumWidth(150)
        self.formant_slider.valueChanged.connect(self.on_formant_changed)
        
        self.toolbar.addWidget(self.formant_label)
        self.toolbar.addWidget(self.formant_slider)

    def on_formant_changed(self, value):
        """フォルマント変更時の処理"""
        shift = value / 100.0
        if hasattr(self.vo_se_engine, 'vose_set_formant'):
            self.vo_se_engine.vose_set_formant(shift)

    def setup_performance_toggle(self):
        """パフォーマンスモード切り替え"""
        self.perf_action = QAction("High Mode", self)
        self.perf_action.setCheckable(True)
        self.perf_action.triggered.connect(self.toggle_performance)
        self.toolbar.addAction(self.perf_action)

    def toggle_performance(self, checked):
        """パフォーマンスモード切り替え処理"""
        mode = 1 if checked else 0
        if hasattr(self.vo_se_engine, 'lib') and hasattr(self.vo_se_engine.lib, 'vose_set_performance_mode'):
            self.vo_se_engine.lib.vose_set_performance_mode(mode)
        status = "高出力モード" if mode == 1 else "省電力モード"
        self.statusBar().showMessage(f"VO-SE: {status} に切り替えました")

    def init_pro_talk_ui(self):
        """Talk入力UI初期化"""
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("喋らせたい文章を入力（Enterで展開）...")
        self.text_input.setFixedWidth(300)
        self.text_input.returnPressed.connect(self.on_talk_execute)
        
        self.toolbar.addWidget(QLabel("Talk:"))
        self.toolbar.addWidget(self.text_input)

    def on_talk_execute(self):
        """Talk実行処理"""
        text = self.text_input.text()
        if not text:
            return
        
        new_events = self.analyzer.analyze_to_pro_events(text)
        self.timeline_widget.set_notes(new_events)
        self.timeline_widget.update()
        self.statusBar().showMessage(f"Talkモード: '{text}' を展開しました")
        self.text_input.clear()


    @Slot(QPushButton)
    def on_param_mode_changed(self, button):
        """パラメーター切り替えボタンが押された時の処理"""
        mode = button.text()
        # グラフエディタにモード変更を通知（色やデータの入れ替え）
        self.graph_editor_widget.set_mode(mode)
        self.statusBar().showMessage(f"編集モード: {mode}")

    

    # ==========================================================================
    # ドラッグ&ドロップ・ZIP解凍（文字化け対策済み）
    # ==========================================================================


    def generate_and_save_oto(self, target_voice_dir):
        """
        指定されたフォルダ内の全WAVを解析し、oto.iniを生成して保存する。
        """
        import os
        
        # 解析エンジンのインスタンス化
        analyzer = AutoOtoEngine(sample_rate=44100)
        oto_lines = []
        
        # フォルダ内のファイルをスキャン
        files = [f for f in os.listdir(target_voice_dir) if f.lower().endswith('.wav')]
        
        if not files:
            print("解析対象のWAVファイルが見つかりませんでした。")
            return

        print(f"Starting AI analysis for {len(files)} files...")

        for filename in files:
            file_path = os.path.join(target_voice_dir, filename)
            try:
                # 1. 各ファイルをAI解析
                params = analyzer.analyze_wav(file_path)
                
                # 2. UTAU互換のテキスト行を生成
                line = analyzer.generate_oto_text(filename, params)
                oto_lines.append(line)
            except Exception as e:
                print(f"Error analyzing {filename}: {e}")

        # 3. oto.iniとして書き出し (Shift-JIS / cp932)
        oto_path = os.path.join(target_voice_dir, "oto.ini")
        try:
            with open(oto_path, "w", encoding="cp932", errors="ignore") as f:
                f.write("\n".join(oto_lines))
            print(f"Successfully generated: {oto_path}")
        except Exception as e:
            print(f"Failed to write oto.ini: {e}")
            

    def dragEnterEvent(self, event):
        """ファイルドラッグ時の処理"""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """ファイルドロップ時の処理"""
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            
            # 拡張子によって処理を振り分け
            if file_path.lower().endswith('.zip'):
                self.import_voice_bank(file_path)
            elif file_path.lower().endswith(('.mid', '.midi')):
                self.load_file_from_path(file_path)
            elif file_path.lower().endswith('.json'):
                self.load_file_from_path(file_path)

    def import_voice_bank(self, zip_path: str):
        """ZIP形式の音源をインストール（Shift-JIS文字化け対策版）"""
        import zipfile
        import shutil

        # 音源保存先ディレクトリ
        extract_base_dir = get_resource_path("voices")
        os.makedirs(extract_base_dir, exist_ok=True)
        
        installed_name = None

        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                # 1. まず音源名を決定するために中身を走査
                for info in z.infolist():
                    try:
                        # Shift-JIS(cp932)の文字化けを解消
                        filename = info.filename.encode('cp437').decode('cp932')
                    except:
                        filename = info.filename
                    
                    if "oto.ini" in filename.lower():
                        # oto.iniが含まれるフォルダ名を音源名とする
                        parts = filename.replace('\\', '/').split('/')
                        installed_name = parts[0] if parts[0] else "Unknown_Voice"
                        break

                if not installed_name:
                    raise Exception("有効なUTAU音源(oto.ini)が見つかりませんでした。")

                # 2. 全ファイルを正しく解凍
                for info in z.infolist():
                    try:
                        filename = info.filename.encode('cp437').decode('cp932')
                    except:
                        filename = info.filename

                    # 保存先フルパス
                    target_path = os.path.join(extract_base_dir, filename)

                    if info.is_dir():
                        os.makedirs(target_path, exist_ok=True)
                        continue

                    # ファイル書き出し
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with z.open(info) as source, open(target_path, "wb") as target:
                        shutil.copyfileobj(source, target)

            # --- インストール成功後のUI処理 ---
            # 音源マネージャーをリロード（あなたのクラス設計に合わせて適宜微調整してください）
            if hasattr(self, 'voice_manager'):
                self.voice_manager.scan_utau_voices()
                self.refresh_voice_ui_with_scan()
            
            # UIに反映
            if hasattr(self, 'character_selector'):
                self.character_selector.setCurrentText(installed_name)
            
            self.statusBar().showMessage(f"音源 '{installed_name}' をインストールしました！", 3000)
            
            # 効果音の再生
            if hasattr(self, 'audio_output'):
                se_path = get_resource_path(os.path.join("assets", "install_success.wav"))
                self.audio_output.play_se(se_path)

        # 1. 解凍された音源のフルパスを特定
        voice_dir = os.path.join(extract_base_dir, installed_name)

        # 2. 【ここが接続！】
        # もし音源の中にAIモデル(.onnx)が含まれていたら、エンジンにセットする
        onnx_path = os.path.join(voice_dir, "model.onnx")

        if os.path.exists(onnx_path):
            # すでにモデルがあるなら、DynamicsAIEngineを新しく作り直して接続
            self.dynamics_ai = DynamicsAIEngine(model_path=onnx_path)
            print(f"Aural AI: '{installed_name}' のAIモデルを接続しました。")
　　　　　else:
            # モデルがない場合（純粋なUTAU音源の場合）
            # ここで「WAVからAI学習」へ飛ばすか、デフォルトのAIを適用する
            print(f"Aural AI: AIモデルが見つかりません。デフォルトの揺れを適用します。")
            self.dynamics_ai = DynamicsAIEngine() # デフォルト起動



        

        except Exception as e:
            QMessageBox.warning(self, "エラー", f"インストールの失敗: {str(e)}")


    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for f in files:
            if f.lower().endswith(".zip"):
                self.statusBar().showMessage(f"音源を導入中: {os.path.basename(f)}")
                # ここでVoiceManagerのインストール機能を呼ぶ
                new_voice = self.voice_manager.install_voice_from_zip(f)
                # 成功したらSEを鳴らす！
                self.audio_output.play_se(get_resource_path("assets/install_success.wav"))
                QMessageBox.information(self, "導入完了", f"音源 '{new_voice}' をインストールしました！")
                self.scan_utau_voices() # リスト更新

    # ==========================================================================
    # 再生・録音制御
    # ==========================================================================


    def on_click_play(self):
        # タイムラインのデータを渡して合成・再生
        audio = self.vo_se_engine.synthesize(self.timeline_widget.notes_list)
        self.vo_se_engine.play(audio)

    @Slot()
    def on_play_pause_toggled(self):
        """再生/停止ボタンのハンドラ"""
        if self.is_playing:
            # 停止処理
            self.is_playing = False
            self.playback_timer.stop()
            
            if hasattr(self.vo_se_engine, 'stop_playback'):
                self.vo_se_engine.stop_playback()
            
            self.play_button.setText("▶ 再生")
            self.status_label.setText("停止しました")
            self.playing_notes = {}
            return

        # 再生開始
        if self.is_recording:
            self.on_record_toggled()

        start_time, end_time = self.timeline_widget.get_selected_notes_range()
        notes = self.timeline_widget.notes_list

        if not notes or start_time >= end_time:
            self.status_label.setText("ノートが存在しません")
            return

        try:
            self.status_label.setText("音声生成中...")
            QApplication.processEvents()

            audio_track = self.vo_se_engine.synthesize_track(
                notes, self.pitch_data, start_time, end_time
            )
            
            self.current_playback_time = start_time
            self.is_playing = True
            
            # 別スレッドで再生
            playback_thread = threading.Thread(
                target=self.vo_se_engine.play_audio,
                args=(audio_track,),
                daemon=True
            )
            playback_thread.start()
            
            self.playback_timer.start()
            self.play_button.setText("■ 停止")
            self.status_label.setText(f"再生中: {start_time:.2f}s - {end_time:.2f}s")

        except Exception as e:
            self.status_label.setText(f"再生エラー: {e}")
            print(f"再生エラーの詳細: {e}")
            self.is_playing = False

    @Slot()
    def on_record_toggled(self):
        """録音開始/停止"""
        self.is_recording = not self.is_recording
        
        if self.is_recording:
            if self.is_playing:
                self.on_play_pause_toggled()
            
            self.record_button.setText("■ 録音中")
            self.status_label.setText("録音開始 - MIDI入力待機中...")
            self.timeline_widget.set_recording_state(True, time.time())
        else:
            self.record_button.setText("● 録音")
            self.status_label.setText("録音停止")
            self.timeline_widget.set_recording_state(False, 0.0)

    @Slot()
    def on_loop_button_toggled(self):
        """ループ再生切り替え"""
        self.is_looping_selection = not self.is_looping_selection
        self.is_looping = self.is_looping_selection
        
        if self.is_looping:
            self.loop_button.setText("ループ: ON")
            self.status_label.setText("選択範囲でのループ再生を有効にしました")
        else:
            self.loop_button.setText("ループ: OFF")
            self.status_label.setText("ループ再生を無効にしました")

    @Slot()
    def update_playback_cursor(self):
        """再生カーソルの更新（タイマー同期）"""
        if not self.is_playing:
            return

        # エンジンから現在時刻を取得
        if hasattr(self.vo_se_engine, 'get_current_time'):
            self.current_playback_time = self.vo_se_engine.get_current_time()
        elif hasattr(self.vo_se_engine, 'current_time_playback'):
            self.current_playback_time = self.vo_se_engine.current_time_playback

        # ループ処理
        if self.is_looping:
            p_start, p_end = self.timeline_widget.get_selected_notes_range()
            if p_end > p_start and self.current_playback_time >= p_end:
                self.current_playback_time = p_start
                if hasattr(self.vo_se_engine, 'seek_time'):
                    self.vo_se_engine.seek_time(p_start)
                elif hasattr(self.vo_se_engine, 'current_time_playback'):
                    self.vo_se_engine.current_time_playback = p_start

        # GUI更新
        self.timeline_widget.set_current_time(self.current_playback_time)
        self.graph_editor_widget.set_current_time(self.current_playback_time)
        
        # 時間表示更新
        minutes = int(self.current_playback_time // 60)
        seconds = self.current_playback_time % 60
        self.time_display_label.setText(f"{minutes:02d}:{seconds:06.3f}")

    # ==========================================================================
    # AI解析機能
    # ==========================================================================

    def start_batch_analysis(self):
        """AI一括解析の開始"""
        target_dir = self.voice_manager.get_current_voice_path()
        
        if not target_dir or not os.path.exists(target_dir):
            QMessageBox.warning(self, "エラー", "有効な音源フォルダが選択されていません")
            return

        self.analysis_thread = AnalysisThread(self.voice_manager, target_dir)
        self.analysis_thread.progress.connect(self.update_analysis_status)
        self.analysis_thread.finished.connect(self.on_analysis_complete)
        self.analysis_thread.error.connect(self.on_analysis_error)
        
        self.ai_analyze_button.setEnabled(False)
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.statusBar().showMessage("dynamics engine起動中...")
        
        self.analysis_thread.start()

    def update_analysis_status(self, percent: int, filename: str):
        """解析進捗の表示"""
        self.progress_bar.setValue(percent)
        self.statusBar().showMessage(f"解析中 [{percent}%]: {filename}")

    def on_analysis_complete(self, results: dict):
        """解析完了時の処理"""
        # 解析結果をノートに反映
        for note in self.timeline_widget.notes_list:
            if note.lyrics in results:
                res = results[note.lyrics]
                if isinstance(res, (list, tuple)) and len(res) >= 3:
                    note.onset = res[0]
                    note.overlap = res[1]
                    note.pre_utterance = res[2]
                    note.has_analysis = True
        
        self.progress_bar.hide()
        self.ai_analyze_button.setEnabled(True)
        self.statusBar().showMessage(f"解析完了: {len(results)}件処理", 3000)
        self.timeline_widget.update()
        QMessageBox.information(self, "完了", "解析が完了しました")

    def on_analysis_error(self, message: str):
        """解析エラー時の処理"""
        self.ai_analyze_button.setEnabled(True)
        self.progress_bar.hide()
        QMessageBox.critical(self, "AI解析エラー", f"エラー:\n{message}")

    # ==========================================================================
    # レンダリング
    # ==========================================================================

    @Slot()
    def on_render_button_clicked(self):
        """合成ボタンの最終接続"""
        self.statusBar().showMessage("レンダリング中...")
    
        # 1. データの準備
        song_data = self.prepare_rendering_data()
        if not song_data:
            self.statusBar().showMessage("ノートがありません")
            return

        # 2. C++エンジンでWAV生成
        # vo_se_engine.py の render() を呼び出す
        output_filename = "preview_render.wav"
        result_path = self.vo_se_engine.render(song_data, output_filename)

        # 3. 再生
        if result_path and os.path.exists(result_path):
            self.statusBar().showMessage("再生中...")
            self.vo_se_engine.play_result(result_path)
        else:
            QMessageBox.critical(self, "エラー", "合成に失敗しました。DLLまたは音源パスを確認してください。")

    @Slot()
    def on_ai_button_clicked(self):
        """AIピッチ補正ボタン"""
        f0 = self.timeline_widget.get_pitch_data()
        if not f0:
            self.statusBar().showMessage("ピッチデータがありません")
            return
        
        new_f0 = self.dynamics_ai.generate_emotional_pitch(f0)
        self.timeline_widget.set_pitch_data(new_f0)
        self.statusBar().showMessage("AIピッチ補正を適用しました")

    # ==========================================================================
    # ファイル操作
    # ==========================================================================

    def read_file_safely(self, filepath: str) -> str:
        """Shift-JIS(cp932)とUTF-8を自動判別して読み込む"""
        import chardet
        with open(filepath, 'rb') as f:
            raw_data = f.read()
    
        # 文字コード判定
        encoding = chardet.detect(raw_data)['encoding']
        if encoding is None:
            encoding = 'cp932' # 不明な場合は日本語Windows標準
        
        return raw_data.decode(encoding, errors='ignore')



    def prepare_utau_flags(self, time):
        """
        グラフエディタの値をUTAUのフラグ形式に変換する
        """
        # グラフから値を取得 (0.0 〜 1.0)
        g_val = self.graph_editor_widget.get_param_value_at("Gender", time)
        b_val = self.graph_editor_widget.get_param_value_at("Breath", time)
        
        # UTAUの一般的な範囲（gは-100〜100、Bは0〜100など）にスケーリング
        # 例：0.5を基準に、0.0ならg-50、1.0ならg+50
        g_flag = int((g_val - 0.5) * 100)
        b_flag = int(b_val * 100)
        
        return f"g{g_flag}B{b_flag}"


    def load_ust_file(self, filepath: str):
        """UTAUの .ust ファイルを読み込んでタイムラインに配置"""
        try:
            # UTAUファイルは Shift-JIS (cp932) が基本なので安全に読み込む
            content = self.read_file_safely(filepath)
            lines = content.splitlines()
            
            notes = []
            current_note = {}
            
            for line in lines:
                if line.startswith('[#'): # ノートの開始
                    if current_note:
                        notes.append(self.parse_ust_dict_to_note(current_note))
                    current_note = {}
                elif '=' in line:
                    key, val = line.split('=', 1)
                    current_note[key] = val
            
            # 最後のノートを追加
            if current_note:
                notes.append(self.parse_ust_dict_to_note(current_note))
            
            self.timeline_widget.set_notes(notes)
            self.statusBar().showMessage(f"UST読み込み完了: {len(notes)}ノート")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"UST読み込み失敗: {e}")


    @Slot()
    def on_export_button_clicked(self):
        """
        全レイヤーの曲線をサンプリングし、C++エンジンへ一括送信
        """
        notes = self.timeline_widget.notes_list
        if not notes:
            QMessageBox.warning(self, "エラー", "ノートがないため書き出しできません。")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "音声ファイルを保存", "output.wav", "WAV Files (*.wav)"
        )
        if not file_path: return

        self.statusBar().showMessage("ネイティブエンジンでレンダリング中...")

        try:
            # 1. グラフエディタから全パラメーターデータを取得
            all_params = self.graph_editor_widget.all_parameters
            
            # 2. エンジンに渡すためのノート別データを作成
            vocal_data_list = []
            res = 128 # 1ノートあたりの解像度
            
            for note in notes:
                # 削られていた「時系列サンプリング」をここで実行
                # 各ノートの開始から終了までの曲線を配列として切り出す
                note_data = {
                    "lyric": note.lyrics,
                    "phonemes": note.phonemes,
                    "note_number": note.note_number,
                    # 各レイヤーの数値を配列(numpy相当)で取得
                    "pitch_list": self._sample_range(all_params["Pitch"], note, res),
                    "gender_list": self._sample_range(all_params["Gender"], note, res),
                    "tension_list": self._sample_range(all_params["Tension"], note, res),
                    "breath_list": self._sample_range(all_params["Breath"], note, res)
                }
                vocal_data_list.append(note_data)

            # 3. 完成した vo_se_engine.py の export_to_wav を呼び出し
            # これにより C++ (vose_core.dll/dylib) が火を噴きます
            self.vo_se_engine.export_to_wav(
                vocal_data=vocal_data_list,
                tempo=self.timeline_widget.tempo,
                file_path=file_path
            )

            QMessageBox.information(self, "完了", f"レンダリングが完了しました！\n{file_path}")
            self.statusBar().showMessage("エクスポート完了")

        except Exception as e:
            QMessageBox.critical(self, "エラー", f"書き出し失敗: {e}")
            self.statusBar().showMessage("エラー発生")

    def _sample_range(self, events, note, res):
        """
        ノートの時間範囲(start 〜 start+duration)をres分割して
        グラフの値をサンプリングする補助関数
        """
        import numpy as np
        times = np.linspace(note.start_time, note.start_time + note.duration, res)
        # グラフエディタの補間関数 get_value_at_time を使用
        return [self.graph_editor_widget.get_value_at_time(events, t) for t in times]

    

    @Slot()
    def save_file_dialog_and_save_midi(self):
        """プロジェクトの保存（全データ・全パラメーター）"""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "プロジェクトを保存", "", "VO-SE Project (*.vose);;JSON Files (*.json)"
        )
        if not filepath: return

        # 全パラメーターレイヤーを取得
        all_params = self.graph_editor_widget.all_parameters
        
        save_data = {
            "app_id": "VO_SE_Pro_2026",
            "version": "1.1",
            "tempo_bpm": self.timeline_widget.tempo,
            "notes": [note.to_dict() for note in self.timeline_widget.notes_list],
            # 多重化したパラメーターをすべて保存
            "parameters": {
                mode: [{"t": p.time, "v": p.value} for p in events]
                for mode, events in all_params.items()
            }
        }
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)
            self.statusBar().showMessage(f"保存完了: {filepath}")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存失敗: {e}")

    def load_json_project(self, filepath: str):
        """JSON/VOSEプロジェクトの読み込み（復旧版）"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 1. ノートの復元
            notes = [NoteEvent.from_dict(d) for d in data.get("notes", [])]
            self.timeline_widget.set_notes(notes)
            
            # 2. テンポの復元とUI反映
            tempo = data.get("tempo_bpm", 120)
            self.tempo_input.setText(str(tempo))
            self.update_tempo_from_input()
            
            # 3. 全パラメーターの復元
            from .data_models import PitchEvent
            saved_params = data.get("parameters", {})
            
            # 旧形式(pitch_data)との互換性維持
            if "pitch_data" in data and not saved_params.get("Pitch"):
                self.graph_editor_widget.all_parameters["Pitch"] = [
                    PitchEvent.from_dict(d) for d in data["pitch_data"]
                ]
            
            # 新形式の読み込み
            for mode in self.graph_editor_widget.all_parameters.keys():
                if mode in saved_params:
                    self.graph_editor_widget.all_parameters[mode] = [
                        PitchEvent(time=p["t"], value=p["v"]) for p in saved_params[mode]
                    ]
            
            # 4. 画面更新（削られていたスクロール範囲の更新を復旧）
            self.update_scrollbar_range()
            self.update_scrollbar_v_range()
            self.graph_editor_widget.update()
            self.timeline_widget.update()
            
            self.statusBar().showMessage(f"読み込み完了: {len(notes)}ノート")
            self.setWindowTitle(f"VO-SE Pro - {os.path.basename(filepath)}")
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"読み込み失敗: {e}")

    def load_midi_file_from_path(self, filepath: str):
        """MIDI読み込み（自動歌詞変換機能付き・完全復旧）"""
        try:
            mid = mido.MidiFile(filepath)
            loaded_tempo = 120.0
            for track in mid.tracks:
                for msg in track:
                    if msg.type == 'set_tempo':
                        loaded_tempo = mido.tempo2bpm(msg.tempo)
                        break
            
            # MIDI読み込みロジック呼び出し
            notes_data = load_midi_file(filepath)
            notes = [NoteEvent.from_dict(d) for d in notes_data]
            
            # 歌詞の音素変換（ここが削られていた重要機能！）
            for note in notes:
                if note.lyrics and not note.phonemes:
                    note.phonemes = self._get_yomi_from_lyrics(note.lyrics)
            
            self.timeline_widget.set_notes(notes)
            self.tempo_input.setText(str(loaded_tempo))
            self.update_tempo_from_input()
            self.update_scrollbar_range()
            self.update_scrollbar_v_range()
            
            self.statusBar().showMessage(f"MIDI読み込み完了: {len(notes)}ノート")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"MIDI読み込み失敗: {e}")



    # ==========================================================================
    # 音源管理
    # ==========================================================================

    def scan_utau_voices(self):
        """voicesフォルダ内をスキャンし、UTAU形式の音源を抽出"""
        voice_root = os.path.join(os.getcwd(), "voices")
        if not os.path.exists(voice_root):
            os.makedirs(voice_root)
            return {}

        found_voices = {}
        
        for dir_name in os.listdir(voice_root):
            dir_path = os.path.join(voice_root, dir_name)
            
            if os.path.isdir(dir_path):
                oto_path = os.path.join(dir_path, "oto.ini")
                char_txt_path = os.path.join(dir_path, "character.txt")
                
                if os.path.exists(oto_path) or os.path.exists(char_txt_path):
                    char_name = dir_name
                    if os.path.exists(char_txt_path):
                        content = self.read_file_safely(char_txt_path)
                        for line in content.splitlines():
                            if line.startswith("name="):
                                char_name = line.split("=")[1].strip()
                                break
                    
                    icon_path = os.path.join(dir_path, "icon.png")
                    if not os.path.exists(icon_path):
                        icon_path = "resources/default_avatar.png"
                        
                    found_voices[char_name] = {
                        "path": dir_path,
                        "icon": icon_path,
                        "id": dir_name
                    }
        
        self.voice_manager.voices = found_voices
        return found_voices

    def parse_oto_ini(self, voice_path: str) -> dict:
        """
        oto.iniを解析して辞書に格納する
        戻り値: { "あ": {"wav": "a.wav", "offset": 50, "consonant": 100, ...}, ... }
        """
        oto_map = {}
        oto_path = os.path.join(voice_path, "oto.ini")
        
        if not os.path.exists(oto_path):
            return oto_map

        # 先ほど作成した「安全な読み込み」を使用
        content = self.read_file_safely(oto_path)
        
        for line in content.splitlines():
            if not line.strip() or "=" not in line:
                continue
            
            try:
                # 形式: wav_filename=alias,offset,consonant,blank,preutterance,overlap
                wav_file, params = line.split("=", 1)
                p = params.split(",")
                
                alias = p[0] if p[0] else os.path.splitext(wav_file)[0]
                
                # パラメータを辞書化（数値はfloatに変換）
                oto_map[alias] = {
                    "wav_path": os.path.join(voice_path, wav_file),
                    "offset": float(p[1]) if len(p) > 1 else 0.0,      # 左ブランク
                    "consonant": float(p[2]) if len(p) > 2 else 0.0,   # 固定範囲
                    "blank": float(p[3]) if len(p) > 3 else 0.0,       # 右ブランク
                    "preutterance": float(p[4]) if len(p) > 4 else 0.0, # 先行発声
                    "overlap": float(p[5]) if len(p) > 5 else 0.0      # オーバーラップ
                }
            except (ValueError, IndexError):
                continue
                
        return oto_map

    def refresh_voice_ui_with_scan(self):
        """スキャンを実行してUIを最新状態にする"""
        self.statusBar().showMessage("音源フォルダをスキャン中...")
        self.scan_utau_voices()
        self.update_voice_list()
        self.statusBar().showMessage(
            f"スキャン完了: {len(self.voice_manager.voices)} 個の音源",
            3000
        )

    def update_voice_list(self):
        """VoiceManagerと同期してUI（カード一覧）を再構築"""
        # 既存カードクリア
        self.voice_cards.clear()
        for i in reversed(range(self.voice_grid.count())): 
            item = self.voice_grid.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

        # カード生成
        for index, (name, data) in enumerate(self.voice_manager.voices.items()):
            path = data.get("path", "")
            icon_path = data.get("icon", os.path.join(path, "icon.png"))
            color = self.voice_manager.get_character_color(path)
            
            card = VoiceCardWidget(name, icon_path, color)
            card.clicked.connect(self.on_voice_selected)
            self.voice_grid.addWidget(card, index // 3, index % 3)
            self.voice_cards.append(card)
        
        # コンボボックス更新
        self.character_selector.clear()
        self.character_selector.addItems(self.voice_manager.voices.keys())

    @Slot(str)
    def on_voice_selected(self, character_name: str):
        """
        ボイスカード選択時の処理：音源データのロードと各エンジンへの適用
        """
        # 1. UIの選択状態（枠線など）を更新
        for card in self.voice_cards:
            card.set_selected(card.name == character_name)
        
        # 2. 音源データの存在チェック
        if character_name not in self.voice_manager.voices:
            self.statusBar().showMessage(f"エラー: {character_name} のデータが見つかりません")
            return
        
        voice_data = self.voice_manager.voices[character_name]
        path = voice_data["path"]

        try:
            # 3. 歌唱用データのロード (oto.iniの解析)
            # 先ほど作成した parse_oto_ini メソッドを呼び出す
            self.current_oto_data = self.parse_oto_ini(path)
            
            # 4. 合成エンジン (VO_SE_Engine) の更新
            # ライブラリパスと解析したOTOデータを渡す
            self.vo_se_engine.set_voice_library(path)
            if hasattr(self.vo_se_engine, 'set_oto_data'):
                self.vo_se_engine.set_oto_data(self.current_oto_data)
            
            self.current_voice = character_name

            # 5. Talkエンジン（会話用）の更新
            # UTAUフォルダ内に talk.htsvoice があれば自動適用
            talk_model = os.path.join(path, "talk.htsvoice")
            if os.path.exists(talk_model) and hasattr(self, 'talk_manager'):
                self.talk_manager.set_voice(talk_model)

            # 6. UIへのフィードバック（ステータスバーと色設定）
            char_color = self.voice_manager.get_character_color(path)
            self.statusBar().showMessage(
                f"【{character_name}】に切り替え完了 ({len(self.current_oto_data)} 音素ロード)", 
                5000
            )
            
            # ログ出力（デバッグ用）
            print(f"Selected voice: {character_name} at {path}")

        except Exception as e:
            QMessageBox.critical(self, "音源ロードエラー", f"音源の読み込み中にエラーが発生しました:\n{e}")

    def refresh_voice_list(self):
        """voice_banksフォルダを再スキャン"""
        self.scan_utau_voices()
        self.update_voice_list()
        print("ボイスリストを更新しました")

    # ==========================================================================
    # 歌詞・ノート操作
    # ==========================================================================

    @Slot()
    def on_click_auto_lyrics(self):
        """AI自動歌詞配置"""
        text, ok = QInputDialog.getText(self, "自動歌詞配置", "文章を入力:")
        if not (ok and text):
            return

        try:
            trace_data = self.analyzer.analyze(text)
            parsed_notes = self.analyzer.parse_trace_to_notes(trace_data)

            new_notes = []
            for d in parsed_notes:
                note = NoteEvent(
                    lyrics=d.get("lyric", ""),
                    start_time=d.get("start", 0.0),
                    duration=d.get("duration", 0.5),
                    note_number=d.get("pitch", 60)
                )
                new_notes.append(note)

            if new_notes:
                self.timeline_widget.set_notes(new_notes)
                self.timeline_widget.update()
                self.statusBar().showMessage(f"{len(new_notes)}個の音素を配置しました")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"歌詞解析エラー: {e}")

    def apply_lyrics_to_notes(self, text: str):
        """歌詞を既存ノートに割り当て"""
        lyrics = [char for char in text if char.strip()]
        notes = self.timeline_widget.notes_list
        
        for i, note in enumerate(notes):
            if i < len(lyrics):
                note.lyrics = lyrics[i]
        
        self.timeline_widget.update()

    @Slot()
    def on_click_apply_lyrics_bulk(self):
        """歌詞の一括流し込み（強化版）"""
        # 先ほど紹介したコードをここに書く
        text, ok = QInputDialog.getMultiLineText(self, "歌詞の一括入力", "歌詞を入力:")
        if not (ok and text): return
        
        # 1文字ずつにバラす
        lyric_list = [char for char in text if char.strip() and char not in "、。！？"]
        
        # タイムライン上のノートを取得
        notes = sorted(self.timeline_widget.notes_list, key=lambda n: n.start_time)
        
        # ノートに順番にセット
        for i in range(min(len(lyric_list), len(notes))):
            notes[i].lyrics = lyric_list[i]
            
        self.timeline_widget.update()


    def parse_ust_dict_to_note(self, d: dict):
        """USTの1ノートセクションをNoteEventに変換"""
        # 480分音符などの計算が必要
        length = int(d.get('Length', 480))
        note_num = int(d.get('NoteNum', 64))
        lyric = d.get('Lyric', 'あ')
        # 時間計算ロジック...
        return NoteEvent(lyrics=lyric, note_number=note_num, duration=length/480.0)

    def update_scrollbar_range(self):
        """ノートの長さに合わせてスクロールバーの最大値を更新"""
        max_time = self.timeline_widget.get_total_duration()
        self.horizontal_scrollbar.setMaximum(int(max_time * 100))
        # グラフエディタ側も同期

    # ==========================================================================
    # その他のスロット
    # ==========================================================================

    @Slot()
    def update_tempo_from_input(self):
        """テンポ入力の反映"""
        try:
            new_tempo = float(self.tempo_input.text())
            if not (30.0 <= new_tempo <= 300.0):
                raise ValueError("テンポは30-300の範囲で入力してください")
            
            self.timeline_widget.tempo = new_tempo
            self.vo_se_engine.set_tempo(new_tempo)
            self.graph_editor_widget.tempo = new_tempo
            self.update_scrollbar_range()
            self.status_label.setText(f"テンポ: {new_tempo} BPM")
        except ValueError as e:
            QMessageBox.warning(self, "エラー", str(e))
            self.tempo_input.setText(str(self.timeline_widget.tempo))

    @Slot()
    def on_timeline_updated(self):
        """タイムライン更新時の処理"""
        self.statusBar().showMessage("更新中...", 1000)
        updated_notes = self.timeline_widget.notes_list
        
        threading.Thread(
            target=self.vo_se_engine.prepare_cache,
            args=(updated_notes,),
            daemon=True
        ).start()

    @Slot()
    def on_notes_modified(self):
        """ノートやOnset変更時"""
        self.statusBar().showMessage("音声を更新中...", 1000)
        updated_notes = self.timeline_widget.notes_list
        
        if hasattr(self.vo_se_engine, 'update_notes_data'):
            self.vo_se_engine.update_notes_data(updated_notes)
        
        threading.Thread(
            target=self.vo_se_engine.synthesize_track,
            args=(updated_notes, self.pitch_data),
            kwargs={'preview_mode': True},
            daemon=True
        ).start()

    @Slot(list)
    def on_pitch_data_updated(self, new_pitch_events: List[PitchEvent]):
        """ピッチデータ更新"""
        self.pitch_data = new_pitch_events
        print(f"ピッチデータ更新: {len(self.pitch_data)}ポイント")

    @Slot()
    def on_midi_port_changed(self):
        """MIDIポート変更"""
        selected_port = self.midi_port_selector.currentData()
        
        if self.midi_manager:
            self.midi_manager.stop()
            self.midi_manager = None

        if selected_port and selected_port != "ポートなし":
            self.midi_manager = MidiInputManager(selected_port)
            self.midi_manager.start()
            self.status_label.setText(f"MIDI: {selected_port}")

    @Slot(int, int, str)
    def update_gui_with_midi(self, note_number: int, velocity: int, event_type: str):
        """MIDI入力信号受信"""
        if event_type == 'on':
            self.status_label.setText(f"ノートオン: {note_number} (Velocity: {velocity})")
        elif event_type == 'off':
            self.status_label.setText(f"ノートオフ: {note_number}")

    def handle_midi_realtime(self, note_number: int, velocity: int, event_type: str):
        """MIDIリアルタイム入力処理"""
        if event_type == 'on':
            self.vo_se_engine.play_realtime_note(note_number)
            if self.is_recording:
                self.timeline_widget.add_note_from_midi(note_number, velocity)
        elif event_type == 'off':
            self.vo_se_engine.stop_realtime_note(note_number)

    @Slot()
    def update_scrollbar_range(self):
        """水平スクロールバー範囲更新"""
        if not self.timeline_widget.notes_list:
            self.h_scrollbar.setRange(0, 0)
            return
        
        max_beats = self.timeline_widget.get_max_beat_position()
        max_x_position = max_beats * self.timeline_widget.pixels_per_beat
        viewport_width = self.timeline_widget.width()
        max_scroll_value = max(0, int(max_x_position - viewport_width))
        
        self.h_scrollbar.setRange(0, max_scroll_value)

    @Slot()
    def update_scrollbar_v_range(self):
        """垂直スクロールバー範囲更新"""
        key_h = self.timeline_widget.key_height_pixels
        full_height = 128 * key_h
        viewport_height = self.timeline_widget.height()

        max_scroll_value = max(0, int(full_height - viewport_height + key_h))
        self.v_scrollbar.setRange(0, max_scroll_value)

        self.keyboard_sidebar.set_key_height_pixels(key_h)


    @Slot()
    def on_notes_modified(self):
        """変更があったらタイマーをリスタート（300ms待機）"""
        self.render_timer.start(300) 

    def execute_async_render(self):
        """タイマー満了で実際にスレッドを起動"""
        threading.Thread(target=self.vo_se_engine.prepare_cache, 
                         args=(self.timeline_widget.notes_list,), 
                         daemon=True).start()

    # ==========================================================================
    # ヘルパーメソッド
    # ==========================================================================

    def _get_yomi_from_lyrics(self, lyrics: str) -> str:
        """歌詞から読みを取得（簡易実装）"""
        # 実際にはMeCabやjanomeで形態素解析
        return lyrics

    def midi_to_hz(self, midi_note: int) -> float:
        """MIDI音番号を周波数(Hz)に変換"""
        return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))

    # ==========================================================================
    # イベントハンドラ
    # ==========================================================================

    def keyPressEvent(self, event: QKeyEvent):
        """キーボードショートカット"""
        if event.key() == Qt.Key_Space:
            self.on_play_pause_toggled()
            event.accept()
        elif event.key() == Qt.Key_R and event.modifiers() == Qt.ControlModifier:
            self.on_record_toggled()
            event.accept()
        elif event.key() == Qt.Key_L and event.modifiers() == Qt.ControlModifier:
            self.on_loop_button_toggled()
            event.accept()
        elif event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.timeline_widget.delete_selected_notes()
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        """AI解析結果の可視化（オプション）"""
        super().paintEvent(event)
        # タイムラインウィジェットが独自に描画するため、ここでは何もしない

    def closeEvent(self, event):
        """ウィンドウを閉じる時に未保存の確認をする"""
        # 確認用のダイアログを表示
        reply = QMessageBox.question(
            self, 
            '確認', 
            "作業内容が失われる可能性があります。終了してもよろしいですか？",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, 
            QMessageBox.Save
        )

        if reply == QMessageBox.Save:
            # 保存を選んだら保存処理を実行
            self.on_save_project_clicked()
            event.accept() # 保存後に閉じる
        elif reply == QMessageBox.Discard:
            # 保存せずに終了を選んだらそのまま閉じる
            event.accept()
        else:
            # キャンセルを選んだら閉じるのを止める
            event.ignore()
        
        """終了処理"""
        # 設定保存
        config = {
            "default_voice": self.current_voice,
            "volume": self.volume
        }
        self.config_manager.save_config(config)
        
        # クリーンアップ
        if self.midi_manager:
            self.midi_manager.stop()
        
        if self.vo_se_engine:
            self.vo_se_engine.close()
        
        print("Application closing...")
        event.accept()


# ==============================================================================
# アプリケーションエントリーポイント
# ==============================================================================

def main():
    """アプリケーション起動"""
    app = QApplication(sys.argv)
    
    # スタイルシート適用（オプション）
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
