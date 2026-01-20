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
from typing import List, Optional, Dict, Any

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

# 1. パス解決用の関数（
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
    class VO_SE_Engine:
        def __init__(self): pass
        def set_active_character(self, name): pass
        def set_tempo(self, tempo): pass
        def synthesize_track(self, notes, pitch, start, end): return np.array([])
        def play_audio(self, audio): pass
        def stop_playback(self): pass
        def close(self): pass
        def set_voice_library(self, path): pass
        def prepare_cache(self, notes): pass
        def export_to_wav(self, notes, pitch, path): pass
        def play_realtime_note(self, note): pass
        def stop_realtime_note(self, note): pass

 
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

        self.render_timer = QTimer()
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(self.execute_async_render)


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
        
        # binフォルダ内のDLLを指名
        dll_relative_path = os.path.join("bin", f"libvo_se{ext}")
        self.dll_full_path = get_resource_path(dll_relative_path)

        # 3. ロード実行
        try:
            self.lib = ctypes.CDLL(self.dll_full_path)
            print(f"Loaded Engine: {self.dll_full_path}")
        except Exception as e:
            print(f"Failed to load engine: {e}")

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
        self.tempo_label = QLabel("BPM:")
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

    

    # ==========================================================================
    # ドラッグ&ドロップ処理
    # ==========================================================================

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
            
            if file_path.lower().endswith('.zip'):
                self.import_voice_bank(file_path)
            elif file_path.lower().endswith(('.mid', '.midi')):
                self.load_file_from_path(file_path)
            elif file_path.lower().endswith('.json'):
                self.load_file_from_path(file_path)

    def import_voice_bank(self, zip_path: str):
        """ZIP形式の音源をインストール"""
        name = self.voice_manager.install_voice_from_zip(zip_path)
        if name:
            self.voice_manager.scan_utau_voices()
            self.refresh_voice_ui_with_scan()
            self.character_selector.setCurrentText(name)
            self.statusBar().showMessage(f"音源 '{name}' をインストールしました！", 3000)
            self.audio_output.play_se("install_success.wav")
        else:
            QMessageBox.warning(
                self,
                "エラー",
                "有効なUTAU音源(oto.ini)が見つかりませんでした。"
            )

    # ==========================================================================
    # 再生・録音制御
    # ==========================================================================

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
        """合成ボタンが押された時の動作"""
        self.statusBar().showMessage("歌唱を生成中...")
        
        gui_notes = self.timeline_widget.get_notes_data()
        if not gui_notes:
            self.statusBar().showMessage("ノートがありません")
            return
        
        if not self.lib:
            QMessageBox.warning(self, "エラー", "レンダリングエンジンが利用できません")
            return
        
        try:
            # 簡易実装：プレビュー再生
            audio_data = self.vo_se_engine.synthesize_track(
                gui_notes, self.pitch_data, 0.0, 100.0
            )
            self.audio_player.play(audio_data)
            self.statusBar().showMessage("レンダリング完了！")
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"レンダリングエラー: {e}")

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

    @Slot()
    def save_file_dialog_and_save_midi(self):
        """プロジェクトの保存"""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "プロジェクトを保存", "", "JSON Files (*.json)"
        )
        if not filepath:
            return

        save_data = {
            "app_id": "VO_SE_Pro_2026",
            "version": "1.0",
            "tempo_bpm": self.timeline_widget.tempo,
            "notes": [note.to_dict() for note in self.timeline_widget.notes_list],
            "pitch_data": [p.to_dict() for p in self.pitch_data]
        }
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)
            self.status_label.setText(f"保存完了: {filepath}")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存失敗: {e}")


    def read_file_safely(self, file_path):
    """ファイルのエンコーディングを自動判別して読み込む"""
    try:
        with open(file_path, 'rb') as f:
            raw_data = f.read()
            # 文字コードを判定
            result = chardet.detect(raw_data)
            encoding = result['encoding']
            
            # 判定失敗や信頼度が低い場合は、日本語音源に多い cp932(Shift-JIS) を試す
            if not encoding or result['confidence'] < 0.7:
                encoding = 'cp932'
                
            return raw_data.decode(encoding, errors='ignore')
    except Exception as e:
        print(f"読み込みエラー: {e}")
        return ""

    @Slot()
    def open_file_dialog_and_load_midi(self):
        """ファイルを開く"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "ファイルを開く", "",
            "All Supported (*.json *.mid *.midi);;JSON Files (*.json);;MIDI Files (*.mid *.midi)"
        )
        if filepath:
            self.load_file_from_path(filepath)

    def load_file_from_path(self, filepath: str):
        """ファイルパスから読み込み"""
        if filepath.lower().endswith('.json'):
            self.load_json_project(filepath)
        elif filepath.lower().endswith(('.mid', '.midi')):
            self.load_midi_file_from_path(filepath)

    def load_json_project(self, filepath: str):
        """JSONプロジェクトの読み込み"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            notes = [NoteEvent.from_dict(d) for d in data.get("notes", [])]
            pitch_data = [PitchEvent.from_dict(d) for d in data.get("pitch_data", [])]
            tempo = data.get("tempo_bpm", 120)
            
            self.timeline_widget.set_notes(notes)
            self.pitch_data = pitch_data
            self.graph_editor_widget.set_pitch_events(self.pitch_data)
            self.tempo_input.setText(str(tempo))
            self.update_tempo_from_input()
            
            self.update_scrollbar_range()
            self.update_scrollbar_v_range()
            
            self.status_label.setText(f"読み込み完了: {len(notes)}ノート")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"読み込み失敗: {e}")

    def load_midi_file_from_path(self, filepath: str):
        """MIDIファイルの読み込み"""
        try:
            # テンポ取得
            mid = mido.MidiFile(filepath)
            loaded_tempo = None
            for track in mid.tracks:
                for msg in track:
                    if msg.type == 'set_tempo':
                        loaded_tempo = mido.tempo2bpm(msg.tempo)
                        break
                if loaded_tempo:
                    break
            
            # ノートデータ取得
            notes_data = load_midi_file(filepath)
            notes = [NoteEvent.from_dict(d) for d in notes_data]
            
            # 歌詞の音素変換
            for note in notes:
                if note.lyrics and not note.phonemes:
                    note.phonemes = self._get_yomi_from_lyrics(note.lyrics)
            
            self.timeline_widget.set_notes(notes)
            
            if loaded_tempo:
                self.tempo_input.setText(str(loaded_tempo))
                self.update_tempo_from_input()
            
            self.update_scrollbar_range()
            self.update_scrollbar_v_range()
            
            self.status_label.setText(f"MIDI読み込み完了: {len(notes)}ノート")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"MIDI読み込み失敗: {e}")

    @Slot()
    def on_export_button_clicked(self):
        """WAV書き出し"""
        notes = self.timeline_widget.notes_list
        if not notes:
            QMessageBox.warning(self, "エラー", "書き出すノートがありません")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "音声ファイルを保存", "output.wav", "WAV Files (*.wav)"
        )
        
        if file_path:
            try:
                self.vo_se_engine.export_to_wav(notes, self.pitch_data, file_path)
                QMessageBox.information(self, "完了", f"書き出し完了:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"書き出し失敗: {e}")

@Slot()
    def export_to_midi_file(self):  #同じクラスになるだけで9分の1だね
        """
        MIDIファイルエクスポート（標準的な1ノート1歌詞形式）
        """
        # 1. 保存先の決定
        filepath, _ = QFileDialog.getSaveFileName(
            self, "MIDIファイルとしてエクスポート", "", "MIDI Files (*.mid *.midi)"
        )
        if not filepath:
            return

        try:
            # 2. MIDIファイルの初期化
            mid = mido.MidiFile()
            track = mido.MidiTrack()
            mid.tracks.append(track)
            
            # 分解能（TPQN）の設定：480が一般的
            ticks_per_beat = 480
            mid.ticks_per_beat = ticks_per_beat

            # 3. メタデータの追加（テンポ・トラック名）
            # テンポは1マイクロ秒あたりの四分音符の時間で指定
            midi_tempo = mido.bpm2tempo(self.timeline_widget.tempo)
            track.append(mido.MetaMessage('set_tempo', tempo=midi_tempo, time=0))
            track.append(mido.MetaMessage('track_name', name='Vocal Track', time=0))

            # 4. ノートのソート（時間順）
            sorted_notes = sorted(self.timeline_widget.notes_list, key=lambda n: n.start_time)
            
            # 現在の累積チック数
            current_tick = 0

            for note in sorted_notes:
                # 時間計算：秒からビート、そしてチックへ変換
                # start_tick: 曲の冒頭からの絶対位置
                start_tick = int(self.timeline_widget.seconds_to_beats(note.start_time) * ticks_per_beat)
                duration_tick = int(self.timeline_widget.seconds_to_beats(note.duration) * ticks_per_beat)

                # delta_time_on: 前のイベントからの相対時間
                delta_time_on = max(0, start_tick - current_tick)
                
                # --- MIDIメッセージの構成 ---
                
                # A. Note ON
                track.append(mido.Message(
                    'note_on', 
                    note=note.note_number, 
                    velocity=note.velocity if hasattr(note, 'velocity') else 100, 
                    time=delta_time_on
                ))
                current_tick += delta_time_on

                # B. Lyric (歌詞メタデータ)
                # Note Onの直後に time=0 で配置するのが一般的
                lyric_text = note.lyrics if note.lyrics else "ら"
                track.append(mido.MetaMessage('lyric', text=lyric_text, time=0))

                # C. Note OFF
                # ノートの長さ分だけ時間を進める
                track.append(mido.Message(
                    'note_off', 
                    note=note.note_number, 
                    velocity=0, 
                    time=duration_tick
                ))
                current_tick += duration_tick

            # 5. トラック終了処理
            track.append(mido.MetaMessage('end_of_track', time=0))
            
            # ファイル保存
            mid.save(filepath)
            self.statusBar().showMessage(f"MIDIエクスポート完了: {os.path.basename(filepath)}")
            
        except Exception as e:
            QMessageBox.critical(self, "MIDIエクスポートエラー", f"保存中に問題が発生しました:\n{e}") 

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
