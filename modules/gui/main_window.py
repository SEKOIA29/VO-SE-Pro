# main_window.py 
import sys
import time
import json
from janome.tokenizer import Tokenizer
import mido 

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QMenu, QVBoxLayout, 
                               QPushButton, QFileDialog, QScrollBar, QInputDialog, 
                               QLineEdit, QHBoxLayout, QLabel, QSplitter, QComboBox)
from PySide6.QtGui import QAction, QKeySequence, QKeyEvent
from PySide6.QtCore import Slot, Qt, QTimer, Signal

from GUI.vo_se_engine import VO_SE_Engine

import numpy as np 

from .timeline_widget import TimelineWidget
from .keyboard_sidebar_widget import KeyboardSidebarWidget
from .midi_manager import load_midi_file, MidiInputManager, midi_signals
from .data_models import NoteEvent, PitchEvent
from .graph_editor_widget import GraphEditorWidget

from PyQt6.QtWidgets import QMainWindow, QLineEdit, QToolBar, QVBoxLayout
from .text_analyzer import TextAnalyzer
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSlider, QLabel

from .voice_manager import VoiceManager

from .audio_output import AudioOutput

from PySide6.QtWidgets import QMainWindow, QProgressBar, QMessageBox, QVBoxLayout, QPushButton
from PySide6.QtCore import QThread, Signal
from ..ai.analysis_thread import AnalysisThread
from ..engine.vo_se_engine import VO_SE_Engine
from backend.intonation import IntonationAnalyzer 
from backend.audio_player import AudioPlayer


# 1. バックグラウンドで動く作業員（スレッド）の定義
class AnalysisThread(QThread):
    progress = Signal(int, str)  # (進捗率, 現在のファイル名) を送る信号
    finished = Signal(dict)      # (解析結果の辞書) を完了時に送る信号
    error = Signal(str)          # エラー発生時にメッセージを送る信号

    def __init__(self, voice_manager, target_dir):
        super().__init__()
        self.voice_manager = voice_manager
        self.target_dir = target_dir

    def run(self):
        try:
            # 重い処理（バッチ解析）を実行
            # 前述の run_batch_voice_analysis を呼び出す
            results = self.voice_manager.run_batch_voice_analysis(
                self.target_dir, 
                self.progress.emit # 進捗を逐次報告
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

# 2. メインウィンドウ側
class MainWindow(QMainWindow):
    def __init__(self, engine, ai):
        super().__init__()

　　　　　# 設定ハンドラーの初期化
        self.config_manager = ConfigHandler()
        self.config = self.config_manager.load_config()
        
        # 以前選んでいたキャラや音量を適用する準備
        self.current_voice = self.config.get("default_voice")
        self.volume = self.config.get("volume", 0.8)
        
　　　
        # 1. エンジン・AI・マネージャーの初期化
        self.engine = engine
        self.ai_manager = ai
        self.voice_manager = VoiceManager(ai) 
        self.voice_manager.first_run_setup()
        self.analyzer = IntonationAnalyzer()
        
        self.analysis_thread = None # スレッド保持用
        self.current_voice_dir = "" # 現在選択されている音源フォルダ

        # 2. UIコンポーネントの初期化（プログレスバーをStatusBarに統合するとスッキリします）
        self.progress_bar = QProgressBar()
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.progress_bar.hide()

        # プレイヤーの初期化
        self.audio_player = AudioPlayer(volume=self.config.get("volume", 0.8))
        
        # タイムラインの再生バーと連動させる
        self.audio_player.position_changed.connect(self.timeline_widget.update_playhead)

    def closeEvent(self, event):
        """ウィンドウを閉じる時に呼ばれるイベント"""
        # 最新の状態を辞書にまとめる
        current_config = {
            "last_save_dir": self.config.get("last_save_dir"),
            "default_voice": self.current_voice,
            "volume": self.volume
        }
        # 保存実行
        self.config_manager.save_config(current_config)
        super().closeEvent(event)

    @Slot()
    def on_play_clicked(self):
        """再生ボタンが押された時"""
        # 現在のノートを合成して出力されたWavを再生
        target_wav = "temp/preview.wav" 
        self.audio_player.play_file(target_wav)
　　　
    @Slot()
    def on_click_auto_lyrics(self):
        text, ok = QInputDialog.getText(self, "AI自動歌詞配置", "文章を入力:")
        if not (ok and text): return

        # 解析実行
        trace_data = self.analyzer.analyze(text)
        # intonation.pyで定義したパース関数を呼ぶ
        parsed_notes = self.analyzer.parse_trace_to_notes(trace_data)

        new_notes = []
        for d in parsed_notes:
            note = NoteEvent(
                lyrics=d["lyric"],
                start_time=d["start"],
                duration=d["duration"],
                note_number=d["pitch"]
            )
            new_notes.append(note)

        # タイムラインへセット（1,200行側のメソッド名に合わせて調整してください）
        self.timeline_widget.set_notes(new_notes)
        self.statusBar().showMessage(f"『{text}』の解析完了", 3000)

        # 4. タイムラインに反映
        if new_notes:
            # 既存の音符を消すか、後ろに追加するか選択（ここでは全入れ替えを想定）
            self.timeline_widget.set_notes(new_notes)
            self.timeline_widget.update() # 再描画
            self.statusBar().showMessage(f"{len(new_notes)}個の音素を配置しました。")
      
    def start_batch_analysis(self):
        """AI一括解析の開始（フリーズ防止スレッド起動）"""
        # 現在選択されている音源のパスを取得
        target_dir = self.voice_manager.get_current_voice_path() 
        
        if not target_dir or not os.path.exists(target_dir):
            QMessageBox.warning(self, "エラー", "有効な音源フォルダが選択されていません。")
            return

        # スレッドの初期化
        self.analysis_thread = AnalysisThread(self.ai_manager, target_dir)
        
        # 信号の接続（演出用）
        self.analysis_thread.progress.connect(self.update_analysis_status)
        self.analysis_thread.finished.connect(self.on_analysis_complete)
        self.analysis_thread.error.connect(self.on_analysis_error)
        
        # UIのロックとプログレスバーの表示
        self.ai_analyze_button.setEnabled(False)
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.statusBar().showMessage("AIエンジン起動中...")
        
        self.analysis_thread.start()

    def update_analysis_status(self, percent, filename):
        """解析中の進捗とファイル名をリアルタイム表示"""
        self.progress_bar.setValue(percent)
        # ステータスバーに現在のファイル名を表示（かっこいい演出）
        self.statusBar().showMessage(f"AI解析実行中 [{percent}%]: {filename} をスキャン中...")

    def on_analysis_error(self, message):
        """エラー発生時のリカバリ"""
        self.ai_analyze_button.setEnabled(True)
        self.progress_bar.hide()
        QMessageBox.critical(self, "AI解析エラー", f"解析中に問題が発生しました:\n{message}")

    def on_analysis_complete(self, results):
        """解析が終わったらデータを保存し、画面を更新する"""
        # 1. 全ノートに対して解析結果を反映
        for note in self.project.notes:
            if note.lyric in results:
                res = results[note.lyric]
                note.onset = res[0]
                note.overlap = res[1]
                note.pre_utterance = res[2]
                note.has_analysis = True
        
        # 2. 解析結果を oto.ini として保存
        self.ai_manager.export_to_oto_ini(self.current_voice_dir, results)
        
        self.progress_bar.hide()
        self.statusBar().showMessage("すべての解析と保存が完了しました。")
        self.update_timeline() # 画面の線を引き直す

　　　　　self.setWindowTitle("VO-SE Pro - Vocal Synthesis Editor")
        self.resize(1000, 600)
        
        # ドラッグ＆ドロップを有効化
        self.setAcceptDrops(True)
        
        # メインレイアウト
        layout = QVBoxLayout()
        self.label = QLabel("ここにZIP形式の音源をドロップしてインポート / Ctrl+Sで保存")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)
        
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    # --- ZIP投げ入れ機能 (ドラッグ＆ドロップ) ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for f in files:
            if f.endswith('.zip'):
                self.import_voice_bank(f)

    def import_voice_bank(self, zip_path):
        target_dir = "voice_banks"
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # ZIPの名前でフォルダを作成して解凍
                folder_name = os.path.basename(zip_path).replace('.zip', '')
                dest = os.path.join(target_dir, folder_name)
                zip_ref.extractall(dest)
                QMessageBox.information(self, "成功", f"音源 '{folder_name}' をインポートしました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"ZIP展開失敗: {e}")

        self.setWindowTitle("VO-SE Pro - Vocal Synthesis Editor")
        self.resize(1000, 600)
        
        # ドラッグ＆ドロップを有効化
        self.setAcceptDrops(True)
        
        # メインレイアウト
        layout = QVBoxLayout()
        self.label = QLabel("ここにZIP形式の音源をドロップしてインポート / Ctrl+Sで保存")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)
        
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    # --- ZIP投げ入れ機能 (ドラッグ＆ドロップ) ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for f in files:
            if f.endswith('.zip'):
                self.import_voice_bank(f)

    def import_voice_bank(self, zip_path):
        target_dir = "voice_banks"
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # ZIPの名前でフォルダを作成して解凍
                folder_name = os.path.basename(zip_path).replace('.zip', '')
                dest = os.path.join(target_dir, folder_name)
                zip_ref.extractall(dest)
                QMessageBox.information(self, "成功", f"音源 '{folder_name}' をインポートしました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"ZIP展開失敗: {e}")

    # --- 保存先指定機能 ---
    def export_audio(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "音声書き出し", "", "WAV Files (*.wav)"
        )
        if file_path:
            # ここで後述のCエンジン(Wrapper経由)を呼び出す
            print(f"Saving to: {file_path}")
            # self.engine.render(file_path)

class MainWindow(QMainWindow):
    """
    アプリケーションのメインウィンドウクラス。
    UIの構築、イベント接続、全体的なアプリケーションロジックを管理する。
    """
    
    def __init__(self, engine=None, config=None):
        super().__init__(parent)

        # 渡されたエンジンと設定をクラス内で使えるように保持する
        self.vo_se_engine = engine
        self.config = config if config else {}
        
        # もしエンジンが渡されなかった時のための予備
        if self.vo_se_engine is None:
            from backend.engine import VoSeEngine
            self.vo_se_engine = VoSeEngine()

        self.setup_ui()

        self.voice_manager = VoiceManager()
        status = self.voice_manager.first_run_setup()
        print(status)
        
        
        # キャラクター選択メニューに名前を入れる
        self.voice_selector.addItems(self.voice_manager.voices.keys())
        
        # --- 1. エンジン・データ初期化 ---
        self.vo_se_engine = VO_SE_Engine()
        self.analyzer = TextAnalyzer() # 追加されていたTextAnalyzer
        self.pitch_data = []
        self.setAcceptDrops(True) # ドロップを許可

        
        # --- 2. ウィンドウ基本設定 ---
        self.setWindowTitle("VO-SE Pro")
        self.setGeometry(100, 100, 700, 400)

        # --- 3. UIコンポーネントの初期化 ---
        self.status_label = QLabel("起動中... =」", self)
        
        # GUI改修案1: 再生時間表示
        self.time_display_label = QLabel("00:00.00", self) 
        self.time_display_label.setFixedWidth(100)
        self.time_display_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #00ff00;")

        self.timeline_widget = TimelineWidget()
        self.keyboard_sidebar = KeyboardSidebarWidget(
            self.timeline_widget.key_height_pixels,
            self.timeline_widget.lowest_note_display
        )
        self.graph_editor_widget = GraphEditorWidget()
        
        self.play_button = QPushButton("再生/停止", self)
        self.record_button = QPushButton("録音 開始/停止", self)
        self.open_button = QPushButton("MIDIファイルを開く", self)
        self.loop_button = QPushButton("ループ再生: OFF", self)
        
        self.tempo_label = QLabel("BPM:", self) 
        self.tempo_input = QLineEdit(str(self.timeline_widget.tempo), self)
        self.tempo_input.setFixedWidth(50)
        
        self.h_scrollbar = QScrollBar(Qt.Horizontal)
        self.h_scrollbar.setRange(0, 0)
        self.v_scrollbar = QScrollBar(Qt.Vertical)
        self.v_scrollbar.setRange(0, 500)

        # --- 4. ツールバーの構築（キャラ選択・モード切替） ---
        self.toolbar = self.addToolBar("MainToolbar")

        # キャラ（ボイス）選択スキャン
        self.voices = self.scan_utau_voices() # 起動時にボイスを探すメソッド
        self.voice_selector = QComboBox()
        if self.voices:
            self.voice_selector.addItems(self.voices.keys())
        else:
            self.voice_selector.addItem("標準ボイス")
        self.toolbar.addWidget(QLabel(" ボイス: "))
        self.toolbar.addWidget(self.voice_selector)

        # モード切替（歌/喋り）
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(["Talkモード", "Singモード"])
        self.toolbar.addWidget(QLabel(" モード: "))
        self.toolbar.addWidget(self.mode_selector)

        # --- 5. レイアウト構築 ---
        # タイムラインエリア
        timeline_area_layout = QHBoxLayout()
        timeline_area_layout.addWidget(self.keyboard_sidebar)
        timeline_area_layout.addWidget(self.timeline_widget)
        timeline_area_layout.addWidget(self.v_scrollbar)
        timeline_area_layout.setSpacing(0)
        timeline_area_layout.setContentsMargins(0, 0, 0, 0)

        timeline_container = QWidget()
        timeline_container.setLayout(timeline_area_layout)
        
        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.addWidget(timeline_container)
        self.main_splitter.addWidget(self.graph_editor_widget)
        self.main_splitter.setSizes([self.height() * 0.7, self.height() * 0.3])
        
        # ボタン・コントロールレイアウト
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.time_display_label) 
        button_layout.addWidget(self.play_button)
        button_layout.addWidget(self.record_button)
        button_layout.addWidget(self.loop_button)

        # キャラクター選択
        self.character_selector = QComboBox(self)
        for char_id, char_info in self.vo_se_engine.characters.items(): 
            self.character_selector.addItem(char_info.name, userData=char_id)
        button_layout.addWidget(self.character_selector) 

        self.midi_port_selector = QComboBox(self)
        button_layout.addWidget(self.midi_port_selector)

        button_layout.addWidget(self.tempo_label)
        button_layout.addWidget(self.tempo_input)
        button_layout.addWidget(self.open_button)

        # メイン垂直レイアウト
        main_layout = QVBoxLayout()
        main_layout.addLayout(button_layout)
        main_layout.addWidget(self.main_splitter)
        main_layout.addWidget(self.h_scrollbar)
        main_layout.addWidget(self.status_label)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        # --- 6. 再生・録音制御変数 ---
        self.is_recording = False
        self.is_playing = False
        self.is_looping = False
        self.is_looping_selection = False
        self.current_playback_time = 0.0
        self.start_time_real = 0.0
        self.playing_notes = {}

        self.playback_timer = QTimer(self)
        self.playback_timer.timeout.connect(self.update_playback_cursor)
        self.playback_timer.setInterval(10)

        # --- 7. シグナル・スロット接続 ---
        self.vo_se_engine.set_active_character("char_001")
        self.setup_actions()
        self.setup_menus()
        self.addAction(self.copy_action)
        self.addAction(self.paste_action)
        self.addAction(self.save_action)

        self.play_button.clicked.connect(self.on_play_pause_toggled)
        self.record_button.clicked.connect(self.on_record_toggled)
        self.open_button.clicked.connect(self.open_file_dialog_and_load_midi)
        self.loop_button.clicked.connect(self.on_loop_button_toggled)
        self.tempo_input.returnPressed.connect(self.update_tempo_from_input) 
        self.character_selector.currentIndexChanged.connect(self.on_character_changed)
        self.midi_port_selector.currentIndexChanged.connect(self.on_midi_port_changed)

        midi_signals.midi_event_signal.connect(self.update_gui_with_midi)
        midi_signals.midi_event_signal.connect(self.timeline_widget.highlight_note)
        midi_signals.midi_event_record_signal.connect(self.timeline_widget.record_midi_event)
        
        self.h_scrollbar.valueChanged.connect(self.timeline_widget.set_scroll_x_offset)
        self.v_scrollbar.valueChanged.connect(self.timeline_widget.set_scroll_y_offset)
        self.v_scrollbar.valueChanged.connect(self.keyboard_sidebar.set_scroll_y_offset)
        self.h_scrollbar.valueChanged.connect(self.graph_editor_widget.set_scroll_x_offset)
        
        self.timeline_widget.zoom_changed_signal.connect(self.graph_editor_widget.set_pixels_per_beat)
        self.timeline_widget.zoom_changed_signal.connect(self.update_scrollbar_range)
        self.timeline_widget.vertical_zoom_changed_signal.connect(self.update_scrollbar_v_range)
        self.timeline_widget.notes_changed_signal.connect(self.update_scrollbar_range)
        
        self.graph_editor_widget.pitch_data_changed.connect(self.on_pitch_data_updated)

        self.audio_output = AudioOutput(self.engine)
        # プレビューやMIDI演奏時に self.audio_output.play() を呼ぶ

        # --- 8. MIDI入力初期化 ---
        available_ports = MidiInputManager.get_available_ports()
        if available_ports:
            for port_name in available_ports:
                self.midi_port_selector.addItem(port_name, userData=port_name)
        else:
            self.status_label.setText("警告: MIDIポートが見つかりません。")
            self.midi_port_selector.addItem("ポートなし")
            self.midi_port_selector.setEnabled(False)
            self.midi_manager = None
        
        self.timeline_widget.set_current_time(self.current_playback_time)

    def dragEnterEvent(self, event):
        # ドロップされたのが「ファイル」なら受け入れる
        if event.mimeData().hasUrls():
           event.accept()
        else:
            event.ignore()

    def init_ui(self):
        """UIコンポーネントの配置とレイアウトの構築"""
        # 1. 中央のメインウィジェットとメインレイアウト
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(2)

        # 2. 上部コントロールパネル（再生・録音・テンポ・ボイス選択）
        self.setup_control_panel()

        # 3. メインエリア（スプリッター：タイムライン + グラフエディタ）
        self.main_splitter = QSplitter(Qt.Vertical)
        
        # タイムラインエリア（サイドバー + メインタイムライン + 垂直スクロール）
        self.timeline_container = QWidget()
        timeline_hbox = QHBoxLayout(self.timeline_container)
        timeline_hbox.setContentsMargins(0, 0, 0, 0)
        timeline_hbox.setSpacing(0)
        
        timeline_hbox.addWidget(self.keyboard_sidebar)
        timeline_hbox.addWidget(self.timeline_widget)
        timeline_hbox.addWidget(self.v_scrollbar)
        
        # スプリッターに追加
        self.main_splitter.addWidget(self.timeline_container)
        self.main_splitter.addWidget(self.graph_editor_widget)
        
        # 初期サイズ比率（タイムライン 70% : グラフ 30%）
        self.main_splitter.setSizes([700, 300])
        
        self.main_layout.addWidget(self.main_splitter)

        # 4. 下部コントロール（水平スクロールバーとプログレスバー）
        bottom_layout = QHBoxLayout()
        bottom_layout.addWidget(self.h_scrollbar)
        
        # AI解析用のプログレスバーをStatusBarに統合
        self.statusBar().addPermanentWidget(self.progress_bar)
        
        self.main_layout.addLayout(bottom_layout)

        self.auto_btn = QPushButton("歌詞から自動生成")
        # スタイルを2026年風（Apple風）に少し整える
        self.auto_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 20);
                border-radius: 6px;
                padding: 5px 12px;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #007AFF;
            }
        """)
        
        # クリックイベントの接続
        self.auto_btn.clicked.connect(self.on_click_auto_lyrics)
        
        # ツールバーへの配置
        self.toolbar.addWidget(self.auto_btn)

    def setup_control_panel(self):
        """上部のボタンや入力欄を並べるレイアウト"""
        panel_layout = QHBoxLayout()
        
        # 再生系
        panel_layout.addWidget(self.time_display_label)
        panel_layout.addWidget(self.play_button)
        panel_layout.addWidget(self.record_button)
        panel_layout.addWidget(self.loop_button)
        
        # テンポ
        panel_layout.addWidget(self.tempo_label)
        panel_layout.addWidget(self.tempo_input)
        
        # キャラクター/ポート選択
        panel_layout.addWidget(QLabel("Voice:"))
        panel_layout.addWidget(self.character_selector)
        panel_layout.addWidget(QLabel("MIDI:"))
        panel_layout.addWidget(self.midi_port_selector)
        
        # ファイル操作
        panel_layout.addWidget(self.open_button)
        
        # AI解析ボタン（ここ重要！）
        self.ai_analyze_button = QPushButton("AI Auto Setup")
        self.ai_analyze_button.setStyleSheet("background-color: #4A90E2; color: white; font-weight: bold;")
        self.ai_analyze_button.clicked.connect(self.start_batch_analysis)
        panel_layout.addWidget(self.ai_analyze_button)

        self.main_layout.addLayout(panel_layout)

    def paintEvent(self, event):
        super().paintEvent(event) # 既存のノート描画
        painter = QPainter(self)
    
        for note in self.notes_list:
            if hasattr(note, 'has_analysis') and note.has_analysis:
                # ノートの左端位置を計算
                x = self.beats_to_pixels(self.seconds_to_beats(note.start_time))
                y = self.note_to_y(note.note_number)
                h = self.key_height_pixels
            
                # 1. Pre-utterance (先行発声) を赤い破線で描画
                pre_x = x - (note.pre_utterance * self.pixels_per_second)
                painter.setPen(QPen(Qt.red, 1, Qt.DashLine))
                painter.drawLine(pre_x, y, pre_x, y + h)
            
                # 2. Onset (立ち上がり) を実線で描画
                onset_x = x + (note.onset * self.pixels_per_second)
                painter.setPen(QPen(Qt.cyan, 2, Qt.SolidLine))
                painter.drawLine(onset_x, y, onset_x, y + h)

    def dropEvent(self, event):
    import zipfile
    import shutil

    for url in event.mimeData().urls():
        file_path = url.toLocalFile()
        if file_path.endswith('.zip'):
            # 1. 解凍先の名前（zipファイル名）を決める
            voice_name = os.path.splitext(os.path.basename(file_path))[0]
            target_dir = os.path.join(self.voice_manager.internal_voice_dir, voice_name)

            # 2. 解凍実行
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(target_dir)

            # 3. マネージャーを再スキャンしてメニューを更新
            self.voice_manager.scan_utau_voices()
            self.voice_selector.clear()
            self.voice_selector.addItems(self.voice_manager.voices.keys())
            
            self.statusBar().showMessage(f"インストール完了: {voice_name}")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
           event.accept()
        else:
           event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith('.zip'):
            # 1. 音源をインストール
            name = self.voice_manager.install_voice_from_zip(path)
            if name:
                # 2. リストを更新して、インストールしたキャラを選択状態にする
                self.voice_manager.scan_utau_voices()
                self.voice_selector.clear()
                self.voice_selector.addItems(self.voice_manager.voices.keys())
                self.voice_selector.setCurrentText(name)
                self.statusBar().showMessage(f"音源 '{name}' をインストールしました！")
                #self.audio_output.play_se("install_success.wav") #wavファイルを再生
            else:
                self.statusBar().showMessage("エラー: 有効なUTAU音源(oto.ini)が見つかりませんでした。")
          　　
#まだ残りあるよ        
# main_window.py 続き

    def scan_utau_voices(self):
        """
        voicesフォルダ内をスキャンし、UTAU形式の音源を抽出する。
        音源名、パス、アイコン、立ち絵、原音設定の有無を辞書にまとめる。
        """
        voice_root = os.path.join(os.getcwd(), "voices")
        if not os.path.exists(voice_root):
            os.makedirs(voice_root)
            return {}

        found_voices = {}
        
        # フォルダ一覧を取得
        for dir_name in os.listdir(voice_root):
            dir_path = os.path.join(voice_root, dir_name)
            
            if os.path.isdir(dir_path):
                # UTAU音源である判断基準: oto.ini または character.txt が存在するか
                oto_path = os.path.join(dir_path, "oto.ini")
                char_txt_path = os.path.join(dir_path, "character.txt")
                
                if os.path.exists(oto_path) or os.path.exists(char_txt_path):
                    # キャラクター名の決定（character.txtがあればそこから取得、なければフォルダ名）
                    char_name = dir_name
                    if os.path.exists(char_txt_path):
                        try:
                            with open(char_txt_path, 'r', encoding='shift-jis', errors='ignore') as f:
                                for line in f:
                                    if line.startswith("name="):
                                        char_name = line.split("=")[1].strip()
                                        break
                        except:
                            pass
                    
                    # アイコンの確認（なければデフォルト）
                    icon_path = os.path.join(dir_path, "icon.png")
                    if not os.path.exists(icon_path):
                        icon_path = "resources/default_avatar.png" # 予備
                        
                    found_voices[char_name] = {
                        "path": dir_path,
                        "icon": icon_path,
                        "id": dir_name
                    }
        
        # 内部マネージャーにセット
        self.voice_manager.voices = found_voices
        return found_voices

    def refresh_voice_ui_with_scan(self):
        """スキャンを実行してUIを最新状態にする"""
        self.statusBar().showMessage("音源フォルダをスキャン中...")
        self.scan_utau_voices()
        self.update_voice_list() # 前回の統合版で実装したグリッド更新メソッド
        self.statusBar().showMessage(f"スキャン完了: {len(self.voice_manager.voices)} 個の音源が見つかりました", 3000)


    def setup_formant_slider(self):
        self.formant_label = QLabel("声の太さ (Formant)")
        self.formant_slider = QSlider(Qt.Orientation.Horizontal)
        self.formant_slider.setRange(-100, 100) # -1.0 ～ 1.0 を 100倍で扱う
        self.formant_slider.setValue(0)
        self.formant_slider.valueChanged.connect(self.on_formant_changed)
    
       # ツールバーやレイアウトに追加
        self.toolbar.addWidget(self.formant_label)
        self.toolbar.addWidget(self.formant_slider)

    def on_formant_changed(self, value):
        shift = value / 100.0
        self.engine.vose_set_formant(shift) # エンジンに即時反映

        # main_window.py のツールバー設定
    def setup_performance_toggle(self):
        self.perf_action = QAction("High Mode", self)
        self.perf_action.setCheckable(True)
        self.perf_action.triggered.connect(self.toggle_performance)
        self.toolbar.addAction(self.perf_action)

    def toggle_performance(self, checked):
        mode = 1 if checked else 0
        self.engine.lib.vose_set_performance_mode(mode)
        # Lowモードなら省電力であることをユーザーに伝える
        status = "高出力モード" if mode == 1 else "省電力モード"
        self.statusBar().showMessage(f"VO-SE: {status} に切り替えました")


    def init_pro_talk_ui(self):
        # ツールバーにTalk入力欄を統合
        self.talk_bar = QToolBar("Talk Input")
        self.addToolBar(self.talk_bar)
        
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("喋らせたい文章を入力（Enterで展開）...")
        self.text_input.setFixedWidth(300)
        self.text_input.returnPressed.connect(self.on_talk_execute)
        
        self.talk_bar.addWidget(self.text_input)

    def on_talk_execute(self):
        """QLineEditに入力されたテキストを解析してタイムラインに展開"""
        text = self.text_input.text()
        if not text: return
        
        # 形態素解析などを行いNoteEventのリストを生成
        new_events = self.analyzer.analyze_to_pro_events(text)
        
        # 既存のタイムラインへ流し込み
        self.timeline_widget.set_notes(new_events)
        self.timeline_widget.update()
        self.statusBar().showMessage(f"Talkモード: '{text}' を展開しました")







    # --- アクションとメニューの設定メソッド ---
    def setup_actions(self):
        self.copy_action = QAction("コピー", self)
        self.copy_action.setShortcuts(QKeySequence.StandardKey.Copy)
        self.copy_action.triggered.connect(self.timeline_widget.copy_selected_notes_to_clipboard)
        self.paste_action = QAction("ペースト", self)
        self.paste_action.setShortcuts(QKeySequence.StandardKey.Paste)
        self.paste_action.triggered.connect(self.timeline_widget.paste_notes_from_clipboard)
        self.save_action = QAction("プロジェクトを保存(&S)", self)
        self.save_action.setShortcuts(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_file_dialog_and_save_midi)

    def setup_menus(self):
        file_menu = self.menuBar().addMenu("ファイル(&F)")
        file_menu.addAction(self.save_action)
        
        export_action = QAction("MIDIファイルとしてエクスポート...", self)
        export_action.triggered.connect(self.export_to_midi_file)
        file_menu.addAction(export_action)

        edit_menu = self.menuBar().addMenu("編集(&E)")
        edit_menu.addAction(self.copy_action)
        edit_menu.addAction(self.paste_action)

def update_voice_list(self):
        """VoiceManagerと同期してUI（カード一覧）を再構築する"""
        # 1. 既存のカードを安全に削除
        # リストを保持している場合はクリア
        if not hasattr(self, 'voice_cards'):
            self.voice_cards = []
        else:
            self.voice_cards.clear()

        for i in reversed(range(self.voice_grid.count())): 
            item = self.voice_grid.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

        # 2. 最新の音源リストからカードを生成して配置（3列グリッド）
        # self.voice_manager.voices.items() が (名前, データ辞書) を返す想定
        for index, (name, data) in enumerate(self.voice_manager.voices.items()):
            # パス、アイコン、色の取得
            path = data.get("path", "")
            icon_path = data.get("icon", os.path.join(path, "icon.png"))
            color = self.voice_manager.get_character_color(path)
            
            # カードの生成
            card = VoiceCardWidget(name, icon_path, color)
            
            # 選択イベントの接続（ここが重要！）
            card.clicked.connect(self.on_voice_selected)
            
            # グリッドへ追加 (3列構成: index // 3 が行, index % 3 が列)
            self.voice_grid.addWidget(card, index // 3, index % 3)
            
            # 選択管理用にリストに保持
            self.voice_cards.append(card)

   @Slot(str)
   def on_voice_selected(self, character_name):
       # 1. カードの見た目を更新
       for card in self.voice_cards:
           card.set_selected(card.name == character_name)
    
       # 2. ボイス情報を取得
       voice_data = self.voice_manager.voices[character_name]
       path = voice_data["path"]

       # 3. 歌声エンジン(VO_SE_Engine)の更新
       self.vo_se_engine.set_voice_library(path)

       # 4. トークエンジン(TalkManager)の更新
       # 例: 音源フォルダ内に talk.htsvoice が入っている想定
       talk_model = os.path.join(path, "talk.htsvoice")
       if os.path.exists(talk_model):
           self.talk_manager.set_voice(talk_model)

       self.statusBar().showMessage(f"【{character_name}】に切り替え完了")


   def setup_voice_selector(self):
 
       self.voice_selector.currentIndexChanged.connect(self.on_voice_changed)
       self.layout().addWidget(self.voice_selector)

   def on_voice_changed(self):
       # 選択されたキャラ名をエンジンに伝える
       selected_name = self.voice_selector.currentText()
       self.engine.set_voice_path(f"audio_data/{selected_name}/")
       print(f"VO-SE: キャラクターを {selected_name} に変更しました")

   def setup_connections(self):
       # タイムラインで何かが変わったら、エンジンのプレビューを更新する
       self.timeline_widget.notes_changed_signal.connect(self.on_timeline_updated)



  

    @Slot()
    def on_play_pause_toggled(self):
        """再生/停止ボタンのハンドラ。録音停止、音声生成、スレッド再生を統合。"""
        
        # --- 1. すでに再生中の場合は「停止」処理 ---
        if self.is_playing:
            self.is_playing = False
            self.playback_timer.stop()
            
            try:
                # エンジン側の停止処理
                if hasattr(self.vo_se_engine, 'stop_playback'):
                    self.vo_se_engine.stop_playback()
                
                # ストリームを直接触る必要がある場合の保険
                if hasattr(self.vo_se_engine, 'stream') and self.vo_se_engine.stream.is_active():
                    self.vo_se_engine.stream.stop_stream()
            except Exception as e:
                print(f"停止処理中にエラー: {e}")

            self.play_button.setText("再生")
            self.status_label.setText("再生を停止しました。")
            self.playing_notes = {}
            return # 停止したのでここで終了

        # --- 2. 再生開始前の準備 ---
        if self.is_recording:
            self.on_record_toggled() # 録音中なら止める

        # 再生範囲の取得
        start_time, end_time = self.timeline_widget.get_selected_notes_range()
        notes = self.timeline_widget.notes_list
        pitch = self.pitch_data

        if not notes or start_time >= end_time:
            self.status_label.setText("ノートが存在しないため再生できません。")
            return

        # --- 3. 音声生成と再生開始 ---
        try:
            self.status_label.setText("音声生成中...お待ちください。")
            # GUIをフリーズさせないために一度描画を更新
            QApplication.processEvents()

            # A. トラックの生成（重い処理）
            audio_track = self.vo_se_engine.synthesize_track(notes, pitch, start_time, end_time)
            
            # B. エンジンの準備
            if hasattr(self.vo_se_engine, 'stream') and not self.vo_se_engine.stream.is_active():
                self.vo_se_engine.stream.start_stream()

            self.current_playback_time = start_time
            self.is_playing = True
            
            # C. 別スレッドで再生を実行
            import threading
            playback_thread = threading.Thread(
                target=self.vo_se_engine.play_audio, 
                args=(audio_track,),
                daemon=True
            )
            playback_thread.start()
            
            # D. GUI側のタイマーとラベルの更新
            self.playback_timer.start()
            self.play_button.setText("■ 停止")
            self.status_label.setText(f"再生中: {start_time:.2f}s - {end_time:.2f}s")

        except Exception as e:
            self.status_label.setText(f"再生エラー: {e}")
            print(f"再生エラーの詳細: {e}")
            self.is_playing = False
                
    @Slot()
    def on_loop_button_toggled(self):
        """ループ再生ボタンのハンドラ"""
        self.is_looping_selection = not self.is_looping_selection

        if self.is_looping_selection:
            self.loop_button.setText("選択範囲ループ: ON")
            self.status_label.setText("選択範囲でのループ再生を有効にしました。")
            self.is_looping = True
        else:
            self.loop_button.setText("ループ再生: OFF")
            self.status_label.setText("ループ再生を無効にしました。")
            self.is_looping = False

    @Slot()
    def on_record_toggled(self):
        """録音 開始/停止ボタンのハンドラ"""
        if self.is_recording:
            self.is_recording = False
            self.record_button.setText("録音 開始/停止")
            self.status_label.setText("録音停止しました。")
            self.timeline_widget.set_recording_state(False, 0.0)
        else:
            if self.is_playing:
                self.on_play_pause_toggled()

            import time
            self.is_recording = True
            self.record_button.setText("■ 録音中 (停止)")
            self.status_label.setText("録音開始しました。MIDI入力を待っています...")
            self.timeline_widget.set_recording_state(True, time.time())

　　　@Slot()
    def on_timeline_updated(self):
        """ノートやOnsetが変更されたときに呼ばれる"""
        # 1. 最新のノートリストを取得
        updated_notes = self.timeline_widget.notes_list
    
        # 2. エンジンに「キャッシュを破棄して再計算」させる
        # synthesis_track などのメソッドに渡す
        self.statusBar().showMessage("タイミング変更をエンジンに反映中...", 2000)
    
        # 別スレッドで軽いプレビュー生成を走らせるとUIが止まりません
        threading.Thread(
            target=self.vo_se_engine.prepare_cache, 
            args=(updated_notes,), 
            daemon=True
       ).start()

    @Slot()
    def on_notes_modified(self):
        """
        タイムラインでノートやAIの赤線（Onset）が動かされた時に実行される。
        """
        # 1. ステータスバーで通知（デバッグ時に便利）
        self.statusBar().showMessage("音声を更新中...", 1000)

        # 2. 最新のノート情報を取得
        updated_notes = self.timeline_widget.notes_list
    
        # 3. エンジンにデータの更新を知らせる
        # すでに再生中の場合は、リアルタイムに音を変えるための処理
        if hasattr(self.vo_se_engine, 'update_notes_data'):
            self.vo_se_engine.update_notes_data(updated_notes)
    
       # 4. バックグラウンドでプレビュー用のキャッシュ波形を生成
       # (合成に時間がかかる場合を想定してスレッド化)
       threading.Thread(
           target=self.vo_se_engine.synthesize_track,
           args=(updated_notes, self.pitch_data),
           kwargs={'preview_mode': True},
           daemon=True
       ).start()

    
    @Slot()
    def update_playback_cursor(self):
        """タイマー同期: エンジンの現在時刻を取得し、全ウィジェットの同期とスクロールを行う"""
        if not self.is_playing:
            return

        # 1. エンジン側から最新の再生時刻を取得
        # メソッドがない場合は内部変数、それもなければ現在時刻を維持
        if hasattr(self.vo_se_engine, 'get_current_time'):
            self.current_playback_time = self.vo_se_engine.get_current_time()
        elif hasattr(self.vo_se_engine, 'current_time_playback'):
            self.current_playback_time = self.vo_se_engine.current_time_playback

        # 2. ループ処理ロジック (GUI側で範囲を監視し、エンジンを巻き戻す)
        if self.is_looping:
            p_start, p_end = self.timeline_widget.get_selected_notes_range()
            
            if p_end > p_start:
                # 終了時間を超えたら開始時間へループ
                if self.current_playback_time >= p_end:
                    self.current_playback_time = p_start
                    if hasattr(self.vo_se_engine, 'seek_time'):
                        self.vo_se_engine.seek_time(p_start)
                    else:
                        self.vo_se_engine.current_time_playback = p_start
                
                # 安全策：開始時間より前なら開始時間へ強制移動
                elif self.current_playback_time < p_start:
                    self.current_playback_time = p_start
                    if hasattr(self.vo_se_engine, 'current_time_playback'):
                        self.vo_se_engine.current_time_playback = p_start

        # 3. GUI各部への時刻反映
        # メインタイムライン
        self.timeline_widget.set_current_time(self.current_playback_time)
        # ピッチ編集エディタ（グラフエディタ）との同期
        if hasattr(self, 'graph_editor_widget'):
            self.graph_editor_widget.set_current_time(self.current_playback_time)

        # 4. 自動スクロールのロジック (カーソルを常に中心付近に保つ)
        current_beats = self.timeline_widget.seconds_to_beats(self.current_playback_time)
        cursor_x_pos = current_beats * self.timeline_widget.pixels_per_beat
        viewport_width = self.timeline_widget.width()
        
        # カーソルが画面の右側（80%）を超えたら、あるいは中心に保つようにスクロール
        target_scroll_x = cursor_x_pos - (viewport_width / 2)
        
        # スクロールバーの値を更新（クランプ処理で範囲外エラーを防止）
        max_v = self.h_scrollbar.maximum()
        min_v = self


    @Slot()
    def update_scrollbar_range(self):
        """ズーム変更時やノートリスト変更時などに水平スクロールバーの範囲を動的に更新する"""
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
        """垂直スクロールバーの範囲とサイドバーの高さを更新する"""
        key_h = self.timeline_widget.key_height_pixels
        full_height = 128 * key_h
        viewport_height = self.timeline_widget.height()

        max_scroll_value = max(0, int(full_height - viewport_height + key_h))
        self.v_scrollbar.setRange(0, max_scroll_value)

        self.keyboard_sidebar.set_key_height_pixels(key_h)


    @Slot()
    def save_file_dialog_and_save_midi(self):
        """ファイルダイアログを開き、現在のノートデータとピッチデータをJSONファイルとして保存する。"""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "プロジェクトを保存", "", "JSON Files (*.json);;All Files (*)"
        )
        if filepath:
            notes_data = [note.to_dict() for note in self.timeline_widget.notes_list]
            pitch_data = [p_event.to_dict() for p_event in self.pitch_data] 
            
            save_data_structure = {
                "app_id": "Vocaloid_Clone_App_12345",
                "type": "note_project_data",
                "tempo_bpm": self.timeline_widget.tempo,
                "notes": notes_data,
                "pitch_data": pitch_data
            }
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(save_data_structure, f, indent=2, ensure_ascii=False)
                self.status_label.setText(f"プロジェクトを保存しました: {filepath}")
            except Exception as e:
                self.status_label.setText(f"保存エラー: {e}")

    @Slot()
    def export_to_midi_file(self):
        """現在のノートデータを標準MIDIファイル形式でエクスポートする。（歌詞は自動分割）"""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "MIDIファイルとしてエクスポート (歌詞付き)", "", "MIDI Files (*.mid *.midi)"
        )
        if filepath:
            mid = mido.MidiFile()
            track = mido.MidiTrack()
            mid.tracks.append(track)
            mid.ticks_per_beat = 480

            midi_tempo = mido.bpm2tempo(self.timeline_widget.tempo)
            track.append(mido.MetaMessage('set_tempo', tempo=midi_tempo, time=0))
            track.append(mido.MetaMessage('track_name', name='Vocal Track 1', time=0))

            sorted_notes = sorted(self.timeline_widget.notes_list, key=lambda note: note.start_time)
            tokenizer = Tokenizer() 
            current_tick = 0

            for note in sorted_notes:
                tokens = [token.surface for token in tokenizer.tokenize(note.lyrics, wakati=True)]
                note_start_beats = self.timeline_widget.seconds_to_beats(note.start_time)
                note_duration_beats = self.timeline_widget.seconds_to_beats(note.duration)
                
                if note.lyrics and tokens:
                    beats_per_syllable = note_duration_beats / len(tokens)
                    ticks_per_syllable = int(beats_per_syllable * mid.ticks_per_beat)

                    delta_time_on = int(note_start_beats * mid.ticks_per_beat) - current_tick
                    track.append(mido.Message('note_on', note=note.note_number, velocity=note.velocity, time=delta_time_on))
                    current_tick += delta_time_on

                    for i, syllable in enumerate(tokens):
                        lyric_delta_time = ticks_per_syllable if i > 0 else 0
                        track.append(mido.MetaMessage('lyric', text=syllable, time=lyric_delta_time))
                        current_tick += lyric_delta_time

                    total_syllable_ticks = len(tokens) * ticks_per_syllable
                    note_off_delta_time = int(note_duration_beats * mid.ticks_per_beat) - total_syllable_ticks
                    if note_off_delta_time < 0: note_off_delta_time = 0

                    track.append(mido.Message('note_off', note=note.note_number, velocity=note.velocity, time=note_off_delta_time))
                    current_tick += note_off_delta_time
                else:
                    delta_time_on = int(note_start_beats * mid.ticks_per_beat) - current_tick
                    track.append(mido.Message('note_on', note=note.note_number, velocity=note.velocity, time=delta_time_on))
                    current_tick += delta_time_on
                    delta_time_off = int(note_duration_beats * mid.ticks_per_beat)
                    track.append(mido.Message('note_off', note=note.note_number, velocity=note.velocity, time=delta_time_off))
                    current_tick += delta_time_off

            track.append(mido.MetaMessage('end_of_track', time=0))
            
            try:
                mid.save(filepath)
                self.status_label.setText(f"MIDIファイル（歌詞付き）のエクスポート完了: {filepath}")
            except Exception as e:
                self.status_label.setText(f"MIDIファイル保存エラー: {e}")

    @Slot()
    def open_file_dialog_and_load_midi(self):
        """ファイルダイアログを開き、MIDIファイルまたはJSONプロジェクトファイルを読み込む。"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "ファイルを開く", "",
            "Project Files (*.json);;MIDI Files (*.mid *.midi);;All Files (*)"
        )
        if filepath:
            notes_list = []
            loaded_pitch_data = []
            loaded_tempo = None

            # --- JSONプロジェクトファイルの読み込み処理 ---
            if filepath.lower().endswith('.json'):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if data.get("app_id") == "Vocaloid_Clone_App_12345":
                            notes_data = data.get("notes", [])
                            notes_list = [NoteEvent.from_dict(d) for d in notes_data]
                            pitch_data_dicts = data.get("pitch_data", [])
                            loaded_pitch_data = [PitchEvent.from_dict(d) for d in pitch_data_dicts] 
                            loaded_tempo = data.get("tempo_bpm", None)

                            self.status_label.setText(f"プロジェクトファイルの読み込み完了。ノート数: {len(notes_list)}, ピッチポイント数: {len(loaded_pitch_data)}")
                        else:
                            self.status_label.setText("エラー: サポートされていないプロジェクト形式です。")
                except Exception as e:
                    self.status_label.setText(f"JSONファイルの読み込みエラー: {e}")
                    return

            # --- 標準MIDIファイルの読み込み処理 ---
            elif filepath.lower().endswith(('.mid', '.midi')):
                try:
                    # MIDIファイルからテンポ情報を取得
                    mid = mido.MidiFile(filepath)
                    for track in mid.tracks:
                        for msg in track:
                            if msg.type == 'set_tempo':
                                loaded_tempo = mido.tempo2bpm(msg.tempo)
                                break
                        if loaded_tempo: break
                    
                    # MIDIファイルからノートデータを取得 (midi_managerのヘルパー関数を使用)
                    data_dicts = load_midi_file(filepath)
                    # ★注: load_midi_fileはdictを返すため、NoteEventオブジェクトに変換し直す
                    if data_dicts:
                        notes_list = [NoteEvent.from_dict(d) for d in data_dicts]
                      
                        for note in notes_list:
                            if note.lyrics and not note.phonemes: # 歌詞はあるが音素がない場合
                                note.phonemes = self._get_yomi_from_lyrics(note.lyrics)
                          
                        self.status_label.setText(f"MIDIファイルの読み込み完了。イベント数: {len(notes_list)}")
                except Exception as e:
                     self.status_label.setText(f"MIDIファイルの読み込みエラー: {e}")

            # --- 読み込んだデータをUIとエンジンに反映させる ---
            if notes_list or loaded_pitch_data:
                # 既存のデータをクリアし、新しいデータをセット
                self.timeline_widget.set_notes(notes_list)
                self.pitch_data = loaded_pitch_data
                self.graph_editor_widget.set_pitch_events(self.pitch_data)

                # テンポ情報があれば反映
                if loaded_tempo is not None:
                    try:
                        new_tempo = float(loaded_tempo)
                        self.tempo_input.setText(str(new_tempo))
                        # update_tempo_from_inputを呼び出して全ウィジェットに反映
                        self.update_tempo_from_input() 
                    except ValueError:
                        self.status_label.setText("警告: テンポ情報が無効なため、デフォルトテンポを使用します。")

                # スクロールバーの範囲を更新
                self.update_scrollbar_range()
                self.update_scrollbar_v_range()

    @Slot(list)
    def on_pitch_data_updated(self, new_pitch_events: list):
        """GraphEditorWidgetから更新されたピッチデータを受け取る"""
        # PitchEvent型への型ヒントを追加
        self.pitch_data: list[PitchEvent] = new_pitch_events
        print(f"ピッチデータが更新されました。総ポイント数: {len(self.pitch_data)}")


    @Slot()
    def update_tempo_from_input(self):
        """テンポ入力欄から値を取得し、タイムラインウィジェットなどに反映させる"""
        try:
            new_tempo = float(self.tempo_input.text())
            if 30.0 <= new_tempo <= 300.0:
                self.timeline_widget.tempo = new_tempo
                self.vo_se_engine.set_tempo(new_tempo)
                
                # ★修正箇所: GraphEditorWidgetにもテンポを通知する
                self.graph_editor_widget.tempo = new_tempo # コメントアウトを外す

                self.update_scrollbar_range()
                self.status_label.setText(f"テンポを {new_tempo} BPM に更新しました。")
            else:
                raise ValueError("テンポは30から300の範囲で入力してください。")
        except ValueError as e:
            self.status_label.setText(f"エラー: {e}")
            self.tempo_input.setText(str(self.timeline_widget.tempo))


    def keyPressEvent(self, event: QKeyEvent):
        """
        キーボードショートカットのイベントハンドラ。
        スペースキーで再生/停止を切り替える。
        """
        if event.key() == Qt.Key_Space:
            self.on_play_pause_toggled()
            event.accept()
        
        elif event.key() == Qt.Key_R and event.modifiers() == Qt.ControlModifier:
            self.on_record_toggled()
            event.accept()

        elif event.key() == Qt.Key_L and event.modifiers() == Qt.ControlModifier:
            self.on_loop_button_toggled()
            event.accept()

        elif event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
            if self.centralWidget().findFocus() == self.timeline_widget:
                 self.timeline_widget.delete_selected_notes()
                 event.accept()

        else:
            super().keyPressEvent(event)


    @Slot(int, int, str)
    def update_gui_with_midi(self, note_number: int, velocity: int, event_type: str):
        """MIDI入力マネージャーからの信号を受け取り、ステータスラベルを更新するスロット。"""
        if event_type == 'on':
            self.status_label.setText(f"ノートオン: {note_number} (Velocity: {velocity})")
        elif event_type == 'off':
            self.status_label.setText(f"ノートオフ: {note_number}")
          

    @Slot()
    def on_midi_port_changed(self):
        """MIDIポート選択コンボボックスの変更ハンドラ"""
        selected_port_name = self.midi_port_selector.currentData()
        
        if self.midi_manager:
            self.midi_manager.stop() # 現在のポートを停止
            self.midi_manager = None

        if selected_port_name and selected_port_name != "ポートなし":
            self.midi_manager = MidiInputManager(selected_port_name)
            self.midi_manager.start() # 新しいポートで開始
            self.status_label.setText(f"MIDIポート: {selected_port_name} に接続済み")
        else:
             self.status_label.setText("警告: 有効なMIDIポートが選択されていません。")

    


    def closeEvent(self, event):
        """アプリケーション終了時のクリーンアップ処理。"""
        
        if self.midi_manager: 
            self.midi_manager.stop()
        
        if self.vo_se_engine:
            self.vo_se_engine.close()

        event.accept()


def export_to_wav(self, notes, filename="output/result.wav"):
    # 全てのノート情報をC言語が読める構造体配列に変換して渡す
    # C言語側で「全ノートを繋ぎ合わせて一つのWAVにする」処理を実行させる
    self.lib.start_export(filename.encode('utf-8'))
    for note in notes:
        hz = self.midi_to_hz(note.pitch)
        self.lib.add_note_to_queue(hz, note.start_time, note.duration)
    self.lib.execute_render() # 実行


def on_export_button_clicked(self):
    # 1. タイムラインにノートがあるか確認
    notes = self.timeline_widget.get_all_notes()
    if not notes:
        QMessageBox.warning(self, "エラー", "書き出すノートがありません。")
        return

    # 2. ファイル保存ダイアログを表示
    # 第2引数はタイトル、第3引数はデフォルトのパス、第4引数はファイル形式のフィルタ
    default_path = os.path.expanduser("~/Documents/output.wav") # 初期値を書類フォルダに
    file_path, _ = QFileDialog.getSaveFileName(
        self, 
        "音声ファイルを保存", 
        default_path, 
        "WAV Files (*.wav);;All Files (*)"
    )

    # 3. ユーザーがキャンセルせずにパスを選択した場合のみ実行
    if file_path:
        try:
            # エンジンに選択されたパスを渡してレンダリング
            self.engine_wrapper.export_wav(notes, file_path)
            
            # 完了メッセージ
            QMessageBox.information(self, "完了", f"書き出しが完了しました：\n{file_path}")
            
            # 保存したフォルダを自動で開く（オプション）
            # os.startfile(os.path.dirname(file_path)) # Windowsの場合
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"書き出し中にエラーが発生しました：\n{str(e)}")



def apply_lyrics_to_notes(self, text):
    """
    入力された文字列（あいうえお等）を、
    現在タイムラインにあるノートに一つずつ割り当てる
    """
    # 記号や空白を除去して1文字ずつのリストにする
    lyrics = [char for char in text if char.strip()]
    
    # タイムライン上の全ノートを取得
    notes = self.timeline_widget.get_all_notes()
    
    # ノートと歌詞を順番にペアリング
    for i, note in enumerate(notes):
        if i < len(lyrics):
            note.lyric = lyrics[i]
    
    self.timeline_widget.update() # 再描画


def handle_midi_realtime(self, note_number, velocity, event_type):
        """MIDI入力マネージャーからの信号をエンジンと録音機能へ渡す"""
        if event_type == 'on':
            # 1. 遅延なしでエンジンを鳴らす
            self.vo_se_engine.play_realtime_note(note_number)
            # 2. 録音モードならタイムラインにノートを記録
            if self.is_recording:
                self.timeline_widget.add_note_from_midi(note_number, velocity)
        elif event_type == 'off':
            self.vo_se_engine.stop_realtime_note(note_number)
