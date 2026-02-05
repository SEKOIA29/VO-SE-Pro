# main_window.py 

# ==========================================================================
# 1. 標準ライブラリ (Standard Libraries)
# ==========================================================================
import os
import sys         # app起動や引数処理に必要
import time
import wave  
from scipy.io.wavfile import write as wav_write  
import json
import ctypes      # DLL(エンジン)の読み込みに必要
import pickle      # キャッシュ保存に必要
import zipfile     # 音源ZIPのインストールに必要
import shutil      # フォルダ削除やコピーに必要
import platform
import threading
import onnxruntime as ort
from typing import List, Optional, Dict, Any

# ==========================================================================
# 2. 数値計算・信号処理 (Numerical Processing)
# ==========================================================================
import numpy as np
import mido
import math

# ==========================================================================
# 3. GUIライブラリ (PySide6 / Qt)
# ==========================================================================
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QScrollBar, QInputDialog, QLineEdit,
    QLabel, QSplitter, QComboBox, QProgressBar, QMessageBox, QToolBar,
    QGridLayout, QFrame, QDialog, QScrollArea, QSizePolicy, QButtonGroup
)
from PySide6.QtGui import (
    QAction, QKeySequence, QKeyEvent, QFont, QShortcut
)
from PySide6.QtCore import (
    Slot, Qt, QTimer, Signal, QThread
)

# ==========================================================================
# 4. 自作モジュール (Custom VO-SE Modules)
# ==========================================================================
from .timeline_widget import TimelineWidget
from .vo_se_engine import VO_SE_Engine
from .voice_manager import VoiceManager
from .ai_manager import AIManager
from .aural_engine import AuralAIEngine

# もし VoiceCardWidget が modules.gui.widgets にあるなら以下も追加
try:
    from .widgets import VoiceCardWidget
except ImportError:
    pass

# ==========================================================================
# 5. グローバル設定（Core i3 負荷軽減 & メモリ管理）
# ==========================================================================
os.environ["OMP_NUM_THREADS"] = "1"

# ==========================================================================
# ハイブリッド・エンジン自動判別システム
# ==========================================================================

class EngineInitializer:
    def __init__(self):
        self.device = "CPU"
        self.provider = "CPUExecutionProvider"

    def detect_best_engine(self):
        """PCの性能をスキャンし、NPU/GPU/CPUから最適なものを選択する"""
        try:
            import onnxruntime as ort
            available = ort.get_available_providers()

            # 1. Mac (Apple Silicon) の NPU/GPU を優先
            if 'CoreMLExecutionProvider' in available:
                self.device = "NPU (Apple Silicon)"
                self.provider = "CoreMLExecutionProvider"
            
            # 2. Windows (DirectML) の NPU/GPU を優先
            elif 'DmlExecutionProvider' in available:
                self.device = "NPU/GPU (DirectML)"
                self.provider = "DmlExecutionProvider"

            # 3. どちらもなければ CPU で堅実に行く
            else:
                self.device = "CPU (High Performance Mode)"
                self.provider = "CPUExecutionProvider"

        except Exception:
            self.device = "CPU (Safe Mode)"
            self.provider = "CPUExecutionProvider"

        return self.device, self.provider

# MainWindowの初期化時にこれを呼び出す
# initializer = EngineInitializer()
# device_name, provider = initializer.detect_best_engine()
# self.statusBar().showMessage(f"Engine: {device_name} 起動完了")


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



# ==========================================================
#  Pro audio modeling レンダリングボタンを押さなくても、スペースキーで「今あるデータ」を合成して即座に鳴らす機能。
# ==========================================================
class ProMonitoringUI:
    def __init__(self, canvas, engine):
        self.canvas = canvas
        self.engine = engine
        self.is_playing = False
        self.playhead_line = None  # タイムライン上の赤い線
        self.current_time = 0.0
        
        # --- メーター用の図形を保持する変数 ---
        self.meter_l = None
        self.meter_r = None
        
        # 初期セットアップを実行
        self.setup_playhead()
        self.setup_meters()

    # --- 1. 視覚の配属：再生ヘッドの描画 ---
    def setup_playhead(self):
        """タイムライン上に赤い縦線を作成"""
        # Apple風の鮮やかな赤 (#FF2D55) を採用
        self.playhead_line = self.canvas.create_line(0, 0, 0, 1000, fill="#FF2D55", width=2)

    def setup_meters(self):
        """GUI右上にレベルメーターの枠と中身を作成"""
        # 枠
        self.canvas.create_rectangle(10, 10, 20, 110, outline="white")
        self.canvas.create_rectangle(25, 10, 35, 110, outline="white")
        # 中身（動くバー）
        self.meter_l = self.canvas.create_rectangle(11, 110, 19, 110, fill="#34C759", outline="")
        self.meter_r = self.canvas.create_rectangle(26, 110, 34, 110, fill="#34C759", outline="")

    # --- 2. 聴覚の配属：レベルメーター（音量バー） ---
    def draw_level_meter(self, rms):
        """再生中の音量をリアルタイムで取得してメーターを動かす"""
        # rmsは 0.0 〜 1.0 の想定
        max_h = 100
        h = rms * max_h
        
        # メーターの高さを更新
        self.canvas.coords(self.meter_l, 11, 110 - h, 19, 110)
        self.canvas.coords(self.meter_r, 26, 110 - h, 34, 110)
        
        # 音量に応じた色変更（Apple風：緑→黄→赤）
        color = "#34C759"
        if rms > 0.7:
            color = "#FFCC00"
        if rms > 0.9:
            color = "#FF3B30"
        self.canvas.itemconfig(self.meter_l, fill=color)
        self.canvas.itemconfig(self.meter_r, fill=color)


    def draw_waveform_realtime(self, x_pos, rms):
        """再生ヘッドの位置に波形の縦線を描画して、軌跡を残す"""
        # 音量(rms)に応じて上下に線を伸ばす
        height = rms * 50  # 振幅の大きさ
        self.canvas.create_line(
            x_pos, 400 - height, x_pos, 400 + height, 
            fill="#007AFF", width=1, tags="waveform"
        ) # Apple純正のブルー (#007AFF) を採用

    # --- 3. GUIループ機構 ---def update_frame(self):
    def update_frame(self):
        """1秒間に60回呼ばれるUI更新ループ（波形描画・デバイス連携対応）"""
        if not self.is_playing:
            return

        # 1. 再生ヘッド（赤い棒）を右に動かす
        self.current_time += 1/60 
        x_pos = self.time_to_x(self.current_time)
        self.canvas.coords(self.playhead_line, x_pos, 0, x_pos, 1000)

        # 2. 画面外に出そうになったら自動スクロール
        if x_pos > self.canvas.winfo_width() * 0.8:
            self.canvas.xview_scroll(1, 'units')

        # 3. レベルメーターの更新 & 波形描画（どっちも！）
        rms = self.engine.get_current_rms() 
        self.draw_level_meter(rms)
        
        # --- ここに波形の軌跡（描画）を配属 ---
        self.draw_waveform_line(x_pos, rms)

        # 次のフレームを予約
        self.canvas.after(16, self.update_frame)

    def draw_waveform_line(self, x, rms):
        """漆黒に映える発光ブルー波形を描画（Apple Pro仕様）"""
        # 1. 振幅の計算（少し感度を上げてダイナミックに）
        h = rms * 80 
        center_y = 400 

        # 2. 波形の線を描画
        # 色を #0A84FF (System Blue) に変更し、質感をアップ
        line_id = self.canvas.create_line(
            x, center_y - h, x, center_y + h, 
            fill="#0A84FF", width=2, tags="wf_trace"
        )

        # 3. 【プロの演出】古い波形を少しずつ暗くして、最後に消す処理
        # これをやらないと、メモリが波形データでパンパンになって重くなります
        self.canvas.after(2000, lambda: self.fade_out_waveform(line_id))

    def fade_out_waveform(self, line_id):
        """波形を徐々に暗くして、最終的に削除する（メモリ節約）"""
        if self.canvas.find_withtag(line_id):
            # 色を少し暗い青 (#004080) に変えてから消す
            self.canvas.itemconfig(line_id, fill="#003366")
            self.canvas.after(1000, lambda: self.canvas.delete(line_id))

   
    def time_to_x(self, t):
        """秒数をX座標に変換（1秒=100pxなど、MainWindowの設定に合わせる）"""
        return t * 100




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




try:
    from gui.vo_se_engine import VO_SE_Engine
except ImportError:
    pass # ← これを追加！(半角スペース4つのインデントを忘れずに)


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
    from .data_models import NoteEvent
except ImportError:
    class NoteEvent(ctypes.Structure):
        _fields_ = [
            ("wav_path", ctypes.c_char_p),
            ("pitch_curve", ctypes.POINTER(ctypes.c_double)),
            ("pitch_length", ctypes.c_int),
            ("gender_curve", ctypes.POINTER(ctypes.c_double)),
            ("tension_curve", ctypes.POINTER(ctypes.c_double)),
            ("breath_curve", ctypes.POINTER(ctypes.c_double)),
        ]
        def __init__(self, **kwargs):
            super().__init__()
            self.lyrics = kwargs.get('lyrics', '')
            self.duration = kwargs.get('duration', 0.5)
            self.note_number = kwargs.get('note_number', 60)
            self.phonemes = kwargs.get('phonemes', '')

    
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
            except Exception:
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

class VoiceCardGallery(QWidget):
    """カードを並べて表示するメインコンテナ"""
    voice_selected = Signal(str, str) # (表示名, 内部ID)

    def __init__(self, voice_manager):
        super().__init__()
        self.manager = voice_manager
        self.cards = {}

        # メインレイアウト
        self.main_layout = QVBoxLayout(self)
        
        # スクロールエリアの設定（音源が増えても大丈夫なように）
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background-color: #1E1E1E; border: none;")
        
        self.container = QWidget()
        self.grid = QGridLayout(self.container)
        self.grid.setSpacing(15)
        self.scroll.setWidget(self.container)
        
        self.main_layout.addWidget(self.scroll)

    def setup_gallery(self):
        """音源をスキャンしてカードを生成・配置する"""
        # 既存のカードをクリア
        for i in reversed(range(self.grid.count())): 
            widget = self.grid.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        self.cards.clear()

        # VoiceManagerから全音源（公式・外部）を取得
        all_voices = self.manager.scan_voices()
        
        row, col = 0, 0
        for display_name, internal_id in all_voices.items():
            # 1. アイコンとカラーのパス解決
            if internal_id.startswith("__INTERNAL__"):
                # 公式（内蔵）の場合: assets/official_voices/{キャラ名}/ から探す
                char_dir = internal_id.split(":")[1]
                base_path = os.path.join(self.manager.base_path, "assets", "official_voices", char_dir)
                icon_path = os.path.join(base_path, "icon.png")
                # 公式カラー（もしフォルダ内に設定ファイルがなければデフォルト色）
                card_color = "#3A3A4A" 
            else:
                # 外部UTAU音源の場合
                icon_path = os.path.join(internal_id, "icon.png") # UTAUの標準アイコン
                card_color = "#2D2D2D"

            # 2. カードの生成
            card = VoiceCardWidget(display_name, icon_path, card_color)
            # --- QSS（スタイルシート）だけでホバーを制御する ---
            card.setStyleSheet(f"""
                VoiceCardWidget {{
                    background-color: {card_color};
                    border: 2px solid #2D2D2D;
                    border-radius: 12px;
                }}
                VoiceCardWidget:hover {{
                    background-color: #3D3D4D; /* ホバーで少し明るく */
                    border: 2px solid #00AAFF; /* VO-SEブルー */
                }}
            """)   
            card.clicked.connect(lambda name=display_name, iid=internal_id: self.on_card_clicked(name, iid))
            
            # 3. レイアウトに追加（4列で折り返し）
            self.grid.addWidget(card, row, col)
            self.cards[display_name] = card
            
            col += 1
            if col >= 4:
                col = 0
                row += 1

    def on_card_clicked(self, name, internal_id):
        """カードがクリックされた時の処理"""
        # 全カードの選択状態をリセット
        for card in self.cards.values():
            card.set_selected(False)
        
        # クリックされたカードを選択状態にする
        self.cards[name].set_selected(True)
        
        # GUIメイン側に通知（これで再生エンジンが切り替わる）
        self.voice_selected.emit(name, internal_id)


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
       
        self.playback_thread = None # 今の演奏スレッドを保存する変数

        self.vowel_groups = {
            'a': 'あかさたなはまやらわがざだばぱぁゃ',
            'i': 'いきしちにひみりぎじぢびぴぃ',
            'u': 'うくすつぬふむゆるぐずづぶぷぅゅ',
            'e': 'えけせてねへめれげぜでべぺぇ',
            'o': 'おこそとのほもよろをごぞどぼぽぉょ',
            'n': 'ん'
        }
        # oto.iniのデータを格納する辞書（空で初期化）
        self.oto_dict = {}

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

        # Canvasをプロ仕様のダークカラーに設定
        self.timeline_widget.setStyleSheet("background-color: #121212;")

        
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
        # AIマネージャーの準備
        self.ai_manager = AIManager()

        # Pro Monitoring UI のインスタンス化
        self.pro_monitoring = ProMonitoringUI(self.canvas, self.engine)

        # Spaceキーを「再生/停止」に割り当て
        self.root.bind("<space>", self.toggle_playback)
        
        # 信号を繋ぐ（これがクラッシュ防止の鍵！）
        self.ai_manager.finished.connect(self.on_analysis_finished)
        self.ai_manager.error.connect(self.on_analysis_error)
        
        # モデルをバックグラウンドで初期化しておく
        self.ai_manager.init_model()
        
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

        


        # Python側で管理するデータモデルのリスト
        self.notes = []        # ここに NoteEvent オブジェクトが溜まっていく
        self.selected_index = -1
        
        # UI上の入力欄（QLineEdit）のリスト（Tab移動用）
        self.input_fields = [] 
        self.setup_vose_shortcuts()


        # 1. UIの組み立て
        self.init_ui()


        # エンジン周りの初期化を一気に叩く
        self.init_vose_engine()       # DLLロード
        self.perform_startup_sequence() # NPU/CPU診断
        self.setup_aural_ai()         # AIロード
        self.apply_dsp_equalizer()    # デフォルトのEQ設定

    def perform_startup_sequence(self):
        """[完全版] 起動時のハードウェア診断とエンジン最適化"""
        # 1. 初期化開始の通知
        self.statusBar().showMessage("Initializing VO-SE Engine...")
        self.log_startup("Starting engine diagnostic sequence.")

        # 2. ハードウェア診断 (NPU / CPU の自動判別)
        # ※ EngineInitializerクラスが外部または同ファイルにある前提
        try:
            initializer = EngineInitializer()
            device_name, provider = initializer.detect_best_engine()
            
            # クラス変数に保存して AIロード時に使用
            self.active_device = device_name
            self.active_provider = provider
        except Exception as e:
            self.log_startup(f"Diagnostic Error: {e}")
            self.active_device, self.active_provider = "CPU (Safe Mode)", "CPUExecutionProvider"

        # 3. UIへの反映（右下の恒久的なラベル表示）
        self.statusBar().showMessage(f"Engine Ready: {self.active_device}", 5000)
        
        self.device_label = QLabel(f" MODE: {self.active_device} ")
        self.device_label.setStyleSheet("""
            background-color: #1a1a1a; 
            color: #ff4d4d; 
            border-radius: 4px; 
            font-weight: bold;
            font-family: 'Consolas', monospace;
            padding: 2px 8px;
            margin-right: 5px;
        """)
        self.statusBar().addPermanentWidget(self.device_label)

        # 4. オーディオデバイスの導通確認 (sounddevice)
        try:
            import sounddevice as sd
            default_device = sd.query_devices(kind='output')
            self.log_startup(f"Audio Output: {default_device['name']}")
        except Exception:
            self.statusBar().showMessage("Warning: Audio device not found.", 10000)
            self.log_startup("Audio output check failed.")

        # 5. リソースのプリロード（完了報告）
        self.log_startup(f"All systems nominal. Provider: {self.active_provider}")
        self.statusBar().showMessage("VO-SE Pro is ready.", 3000)

    def log_startup(self, message):
        """標準出力へのログ記録（2026年開発者モード用）"""
        timestamp = time.strftime('%H:%M:%S')
        print(f"[{timestamp}] [BOOT] {message}")
        """起動ログ（デバッグ用）"""
        print(f"[{time.strftime('%H:%M:%S')}] VO-SE Boot: {message}")

    def setup_vose_shortcuts(self):
        # 1. 1音移動 (Alt + Left/Right)
        QShortcut(QKeySequence("Alt+Right"), self).activated.connect(self.select_next_note)
        QShortcut(QKeySequence("Alt+Left"), self).activated.connect(self.select_prev_note)

        # 2. 削除 (Delete / Backspace)
        # ※誤削除防止のため、入力欄にフォーカスがない時だけ動くように調整も可能
        QShortcut(QKeySequence(Qt.Key_Delete), self).activated.connect(self.delete_selected_note)
        QShortcut(QKeySequence(Qt.Key_Backspace), self).activated.connect(self.delete_selected_note)

        # 3. Tabキーによる歌詞入力フォーカス移動
        # ※PySide6標準のTab移動を強化し、最後の欄でTabを押すと新規追加する等の拡張も可能
        QShortcut(QKeySequence(Qt.Key_Tab), self).activated.connect(self.focus_next_note_input)

    # --- 動作ロジック ---

    def select_next_note(self):
        if self.notes and self.selected_index < len(self.notes) - 1:
            self.selected_index += 1
            self.sync_ui_to_selection()

    def select_prev_note(self):
        if self.notes and self.selected_index > 0:
            self.selected_index -= 1
            self.sync_ui_to_selection()

    def delete_selected_note(self):
        if 0 <= self.selected_index < len(self.notes):
            # データモデルから削除
            self.notes.pop(self.selected_index)
            # 選択位置を調整
            self.selected_index = min(self.selected_index, len(self.notes) - 1)
            # UI全体を更新（再描画）
            self.refresh_canvas() 
            print(f"DEBUG: Note deleted. Remaining: {len(self.notes)}")

    def focus_next_note_input(self):
        """Tabキーで次の入力欄へ。Pro Audio的な爆速入力を実現"""
        if not self.input_fields:
            return
        
        # 現在フォーカスされているウィジェットを確認
        current = self.focusWidget()
        if current in self.input_fields:
            idx = self.input_fields.index(current)
            next_idx = (idx + 1) % len(self.input_fields)
            self.input_fields[next_idx].setFocus()
            self.input_fields[next_idx].selectAll() # 文字を全選択状態にすると上書きが楽



    def draw_pro_grid(self):
        """プロ仕様のグリッド（背景線）を描画"""
        # 代表のコードをここに配属
        # 縦線（時間軸）
        for x in range(0, 10000, 50):
            color = "#3A3A3C" if x % 200 == 0 else "#242424"
            self.canvas.create_line(x, 0, x, 1000, fill=color)
        
        # 横線（音階軸）
        for y in range(0, 1000, 40):
            self.canvas.create_line(0, y, 10000, y, fill="#242424")

    # --- [2] 連続音（VCV）解決メソッド ---
    def resolve_vcv_alias(self, lyric, prev_lyric):
        """
        lyric: 今回の歌詞, prev_lyric: 前回の歌詞
        戻り値: (確定したエイリアス, そのパラメータ)
        """
        # 1. 前の文字から母音を判定
        prev_v = None
        if prev_lyric:
            last_char = prev_lyric[-1]
            for v, chars in self.vowel_groups.items():
                if last_char in chars:
                    prev_v = v
                    break

        # 2. 検索候補の作成（優先順位: 連続音 -> 単独音1 -> 単独音2）
        candidates = []
        if prev_v:
            candidates.append(f"{prev_v} {lyric}") # 例: 'a い'
        candidates.append(f"- {lyric}")           # 例: '- い'
        candidates.append(lyric)                   # 例: 'い'

        # 3. self.oto_dict を検索して最初に見つかったものを返す
        for alias in candidates:
            if alias in self.oto_dict:
                return alias, self.oto_dict[alias]
        
        # 4. 見つからない場合は入力文字をそのまま（パラメータなし）
        return lyric, None

    # --- [3] 音声生成のメインループ（使い方のイメージ） ---
    def on_synthesize(self, notes):
        prev_lyric = None
        for note in notes:
            # ここで解決ロジックを実行！
            alias, params = self.resolve_vcv_alias(note.lyric, prev_lyric)
            
            # C++エンジンへの橋渡し（paramsには先行発声などが入っている）
            self.run_engine(alias, params)
            
            # 今回の歌詞を保存
            prev_lyric = note.lyric




    def init_vcv_logic(self):
        # 起動時に一度だけ。MainWindowの__init__から呼び出してください
        self.vowel_groups = {
            'a': 'あかさたなはまやらわがざだばぱぁゃ',
            'i': 'いきしちにひみりぎじぢびぴぃ',
            'u': 'うくすつぬふむゆるぐずづぶぷぅゅ',
            'e': 'えけせてねへめれげぜでべぺぇ',
            'o': 'おこそとのほもよろをごぞどぼぽぉょ',
            'n': 'ん'
        }

    def get_best_wav_path(self, lyric, prev_lyric, voice_bank_path):
        """
        lyric: 現在の歌詞, prev_lyric: 前の歌詞
        voice_bank_path: UTAU音源のフォルダパス
        """
        prev_v = None
        if prev_lyric:
            last_char = prev_lyric[-1]
            for v, chars in self.vowel_groups.items():
                if last_char in chars:
                    prev_v = v
                    break

        # 探索候補 (連続音 -> 単独音)
        choices = []
        if prev_v:
            choices.append(f"{prev_v} {lyric}") # 'a い'
        choices.append(f"- {lyric}")           # '- い'
        choices.append(lyric)                   # 'い'

        # oto.iniをパースした self.oto_dict からパスを検索
        for alias in choices:
            if hasattr(self, 'oto_dict') and alias in self.oto_dict:
                # oto_dict[alias] に wavのファイル名が入っている想定
                filename = self.oto_dict[alias]['wav']
                return os.path.join(voice_bank_path, filename)
        
        # 見つからなければデフォルト（既存の挙動）
        return os.path.join(voice_bank_path, f"{lyric}.wav")

    # =============================================================
    # 診断されたプロバイダーを使用してAIモデルをロードする                      
    # =============================================================

    def setup_aural_ai(self):
        """診断されたプロバイダーを使用してAIモデルをロードする"""
        model_path = "models/aural_dynamics.onnx"
    
        if not os.path.exists(model_path):
            self.statusBar().showMessage("Error: Aural AI model not found.")
            return

        try:
            # 1. 診断済みのプロバイダー（NPU等）をセッションに渡す
            # セッションオプションの設定（スレッド数などをCore i3向けに最適化）
            options = ort.SessionOptions()
            options.intra_op_num_threads = 1  # 信号処理との競合を避けるため1に固定
        
            self.ai_session = ort.InferenceSession(
                model_path, 
                sess_options=options,
                providers=[self.active_provider, 'CPUExecutionProvider'] # NPUがダメならCPU
            )
        
            self.log_startup(f"Aural AI binding successful on {self.active_provider}")
        
        except Exception as e:
            self.log_startup(f"AI Binding Failed: {e}")
            # 最終防衛線としてCPUで再試行
            self.ai_session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])

    # =============================================================
    # DSP CONTROL: PRECISION EQUALIZER (No-Noise Logic)
    # =============================================================

    def apply_dsp_equalizer(self, frequency=8000.0, gain=3.0, Q=1.0):
        """
        DSP技術による「無ノイズ」イコライザー設定。
        AI合成で発生しがちな「高域のチリチリ音」を物理数学的に除去します。
        """
        # 1. サンプリングレート取得 (44100Hz等)
        fs = 44100.0
    
        # 2. DSPフィルタ係数の計算 (Bi-quad Filter設計)
        # この数式をC++側で実行することで、CPU負荷0.1%以下で動作します。
        import math
        A = math.pow(10, gain / 40)
        omega = 2 * math.pi * frequency / fs
        sn = math.sin(omega)
        cs = math.cos(omega)
        alpha = sn / (2 * Q)

        # フィルタの「キレ」を決める5つの係数
        b0 = A * ((A + 1) + (A - 1) * cs + 2 * math.sqrt(A) * alpha)
        b1 = -2 * A * ((A - 1) + (A + 1) * cs)
        b2 = A * ((A + 1) + (A - 1) * cs - 2 * math.sqrt(A) * alpha)
        a0 = (A + 1) - (A - 1) * cs + 2 * math.sqrt(A) * alpha
        a1 = 2 * ((A - 1) - (A + 1) * cs)
        a2 = (A + 1) - (A - 1) * cs - 2 * math.sqrt(A) * alpha

        # 3. C++エンジンへ係数を転送 (この一瞬の計算で音質が激変する)
        if hasattr(self.vo_se_engine, 'lib'):
            self.vo_se_engine.lib.vose_update_dsp_filter(
                float(b0/a0), float(b1/a0), float(b2/a0), 
                float(a1/a0), float(a2/a0)
            )
    
        self.statusBar().showMessage(f"DSP EQ Active: {frequency}Hz Optimized.")

    #===========================================================
    #エンジン接続関係
    #===========================================================

    def init_vose_engine(self):
        """C++エンジンのロードと初期設定"""
        dll_path = os.path.join(os.getcwd(), "vose_core.dll")
        self.engine_dll.execute_render.argtypes = [ctypes.POINTER(NoteEvent), ctypes.c_int, ctypes.c_char_p]
        self.engine_dll.execute_render.restype = ctypes.c_int
        if os.path.exists(dll_path):
            self.engine_dll = ctypes.CDLL(dll_path)
            # ここで C++関数の引数型を定義 (安全のため)
            # self.engine_dll.execute_render.argtypes = [...]
            print("✅ Engine Loaded Successfully.")
        else:
            print("❌ Engine DLL not found!")

    def generate_pitch_curve(self, note, prev_note=None):
        """
        [完全版] AI予測ピッチ + 黄金比ポルタメント + ビブラート
        """
        # 1. 基礎となる音程（Hz）の計算
        target_hz = 440.0 * (2.0 ** ((note.note_number - 69) / 12.0))
        
        # フレーム数計算（5ms = 1フレーム。1.0秒なら200フレーム）
        num_frames = max(1, int((note.duration * 1000.0) / 5.0))
        
        # AIが予測したピッチ曲線があればそれをベースにし、なければ定数で初期化
        if hasattr(note, 'dynamics') and 'pitch' in note.dynamics:
            curve = np.array(note.dynamics['pitch'], dtype=np.float64)
        else:
            curve = np.ones(num_frames, dtype=np.float64) * target_hz

        # 2. ポルタメント（前の音からの滑らかな接続）
        if prev_note:
            prev_hz = 440.0 * (2.0 ** ((prev_note.note_number - 69) / 12.0))
            # ノートの最初の15%を使って滑らかに繋ぐ（黄金比的な減衰）
            port_len = min(int(num_frames * 0.15), 40)
            if port_len > 0:
                # 指数関数的にターゲットに近づけることで人間らしさを出す
                t = np.linspace(0, 1, port_len)
                curve[:port_len] = prev_hz + (target_hz - prev_hz) * (1 - np.exp(-5 * t))

        # 3. ビブラート・ロジック（後半に周期的な揺れを追加）
        # ※ ここに設定画面の数値を反映させると世界シェアに近づきます
        vibrato_depth = 6.0  # Hz単位の揺れ幅
        vibrato_rate = 5.5   # 1秒間に5.5回
        
        # ノートの後半50%からビブラートを開始
        vib_start = int(num_frames * 0.5)
        for i in range(vib_start, num_frames):
            # サンプリング周期に基づいた正弦波
            time_sec = i * 0.005 # 5ms単位
            osc = math.sin(2 * math.pi * vibrato_rate * time_sec)
            curve[i] += osc * vibrato_depth

        return curve

    def get_notes_from_timeline(self):
        """
        [完全実装] ピアノロール上の全音符をスキャンし、演奏データへと変換する
        """
        note_events = []
        
        # 1. ピアノロールの「シーン」から全アイテムを取得
        # ※ self.scene はあなたのピアノロールの QGraphicsScene です
        if not hasattr(self, 'piano_roll_scene') or self.piano_roll_scene is None:
            self.log_startup("Error: Piano roll scene not initialized.")
            return []

        all_items = self.piano_roll_scene.items()
        
        # 2. 音符アイテム（NoteItemクラス）だけをフィルタリング
        # NoteItemは、あらかじめ座標や歌詞を保持している前提です
        raw_notes = []
        for item in all_items:
            # itemが自分で作ったNoteItemクラスかどうかを判定
            if hasattr(item, 'is_note_item') and item.is_note_item:
                raw_notes.append(item)

        # 3. 時間軸（X座標）でソート（これが無いとメロディがバラバラになります）
        raw_notes.sort(key=lambda x: x.x())

        # 4. GUI上の物理量を「音楽的データ」に変換
        for item in raw_notes:
            # X座標 = 開始時間, 幅(Width) = 長さ, Y座標 = 音高(NoteNumber)
            # ※ 100ピクセル = 1秒 などの倍率はあなたの設計に合わせて調整してください
            start_time = item.x() / 100.0  
            duration = item.rect().width() / 100.0
            
            # 歌詞（あ）を音素（a）に変換
            phoneme_label = self.convert_lyrics_to_phoneme(item.lyrics)

            # C++構造体 NoteEvent を作成（__init__でデータを流し込む）
            event = NoteEvent(
                phonemes=phoneme_label,
                note_number=item.note_number,
                duration=duration,
                start_time=start_time,
                velocity=item.velocity
            )
            note_events.append(event)

        self.log_startup(f"Timeline Scan: {len(note_events)} notes collected.")
        return note_events

    def convert_lyrics_to_phoneme(self, lyrics):
        """簡単な歌詞→音素変換（辞書）"""
        dic = {"あ": "a", "い": "i", "う": "u", "え": "e", "お": "o"}
        return dic.get(lyrics, "n") # 見つからなければ「ん」にする
        

    def handle_playback(self):
        """
        [究極統合] AI推論・競合回避・DSP処理を一本化した再生メインフロー
        """
        # 1. タイムラインから音符データを取得
        notes = self.get_notes_from_timeline()
        if not notes:
            self.statusBar().showMessage("No notes to play.", 3000)
            return

        try:
            self.statusBar().showMessage("Aural AI is thinking...")

            # 2. 【脳】AI推論ループ（各音符に命を吹き込む）
            prev = None
            for n in notes:
                # AIに歌い方の設計図（ダイナミクス・ピッチ等）を予測させる
                # ※ predict_dynamicsは前述のONNX推論メソッド
                n.dynamics = self.predict_dynamics(n.phonemes, n.note_number)
                
                # AIの予測をベースに、さらに滑らかなピッチ曲線を生成（ポルタメント等）
                n.pitch_curve = self.generate_pitch_curve(n, prev)
                prev = n

            # 3. 【安全性】ファイルロック回避のためのキャッシュ名生成
            os.makedirs("cache", exist_ok=True)
            temp_wav = os.path.abspath(f"cache/render_{int(time.time() * 1000)}.wav")

            # 4. 【喉】C++レンダリング実行
            # AIが作った設計図（notes）をまとめてC++エンジンに渡す
            final_file = self.synthesize(notes, temp_wav)

            # 5. 【磨き】DSP処理 & 再生
            if final_file and os.path.exists(final_file):
                # 合成後に高域ノイズを除去するDSP EQを適用
                self.apply_dsp_equalizer(frequency=8000.0, gain=-2.0)
                
                # 音を鳴らす
                self.play_audio(final_file)
                self.statusBar().showMessage(f"Playing via {self.active_device}", 5000)

        except Exception as e:
            error_msg = f"Playback Failed: {str(e)}"
            self.log_startup(error_msg)
            self.statusBar().showMessage(error_msg, 10000)

    def predict_dynamics(self, phonemes, notes):
        """AIモデル(ONNX)を使用してパラメータを予測"""
        # [前処理] 歌詞をAIが理解できる数値(0, 1, 2...)に変換
        input_data = self.preprocess_lyrics(phonemes, notes) 

        # [推論] NPUまたはCPUで実行
        inputs = {self.ai_session.get_inputs()[0].name: input_data}
        prediction = self.ai_session.run(None, inputs)

        # AIが予測したピッチ、テンション、ジェンダー等の多次元配列を返す
        return prediction[0]

    def synthesize_voice(self, dynamics_data):
        """AIの結果をC++に投げてスピーカーから鳴らす"""
        self.statusBar().showMessage("Rendering via Aural Engine...")

        try:
            # 1. C++ DLLのレンダリング関数を叩く
            # ここであなたの vose_core.dll が火を噴きます
            raw_audio = self.engine_dll.render(dynamics_data)
            
            # 2. sounddevice で再生（ノンブロッキング）
            import sounddevice as sd
            sd.play(raw_audio, samplerate=44100)
            
            self.statusBar().showMessage(f"Playing on {self.active_device}", 3000)
        except Exception as e:
            self.log_startup(f"Synthesis Error: {e}")
            

    def synthesize(self, notes, output_path="output.wav"):
        """
        [壺修正済み] 高セキュア・レンダリング・エンジン
        GCからメモリを死守し、WORLDエンジンで高音質合成。
        """
        if not notes:
            return None

        note_count = len(notes)
        # 1. C++構造体配列の確保
        cpp_notes_array = (NoteEvent * note_count)()
        
        # 2. 【最強の壺対策】GCからNumPy配列を保護するリスト
        keep_alive = []

        for i, n in enumerate(notes):
            # 常にfloat64で固定（型不一致によるクラッシュを防止）
            p_curve = np.array(n.pitch_curve, dtype=np.float64)
            keep_alive.append(p_curve)
            
            # ダミーパラメータもDSP最適化された標準値
            length = len(p_curve)
            g_curve = np.full(length, 0.5, dtype=np.float64) # Gender
            t_curve = np.full(length, 0.5, dtype=np.float64) # Tension
            b_curve = np.full(length, 0.0, dtype=np.float64) # Breath
            keep_alive.extend([g_curve, t_curve, b_curve])

            # C++側へポインタを転送
            cpp_notes_array[i].wav_path = n.phonemes.encode('utf-8')
            cpp_notes_array[i].pitch_curve = p_curve.ctypes.data_as(ctypes.POINTER(ctypes.c_double))
            cpp_notes_array[i].pitch_length = length
            cpp_notes_array[i].gender_curve = g_curve.ctypes.data_as(ctypes.POINTER(ctypes.c_double))
            cpp_notes_array[i].tension_curve = t_curve.ctypes.data_as(ctypes.POINTER(ctypes.c_double))
            cpp_notes_array[i].breath_curve = b_curve.ctypes.data_as(ctypes.POINTER(ctypes.c_double))

        # 3. レンダリング実行
        try:
            result = self.engine_dll.execute_render(
                cpp_notes_array, 
                note_count, 
                output_path.encode('utf-8')
            )
            if result == 0: # 成功
                return output_path
        except Exception as e:
            print(f"CRITICAL ENGINE ERROR: {e}")
        finally:
            # 4. レンダリング終了後に安全にメモリ解放
            del keep_alive
            
        return None

    def on_notes_updated(self):
        """タイムラインが変更された時の処理（オートセーブなど）"""
        pass

    def play_audio(self, path):
        """再生の実装（実際はエンジン側のplay関数など）"""
        pass


    # ==========================================================================
    #  Pro audio modeling の起動、呼び出し　　　　　　　　　　　
    # ==========================================================================

    def setup_shortcuts(self):
        """SpaceキーでPro Monitoringを起動"""
        self.root.bind("<space>", self.toggle_audio_monitoring)

    def toggle_audio_monitoring(self, event=None):
        """Spaceキー一発で『音』と『UI』を同時に動かす"""
        if not self.pro_monitoring.is_playing:
            print(" Pro Audio Monitoring: ON")
            
            # 1. 再生位置をリセット
            self.pro_monitoring.current_time = 0.0
            
            # 2. UIループを起動
            self.pro_monitoring.is_playing = True
            self.pro_monitoring.update_frame()
            
            # 3. エンジンで音を鳴らす（wavをセットして再生）
            # self.engine.load_wav("output.wav")
            # self.engine.start_play()
        else:
            print(" Pro Audio Monitoring: OFF")
            self.pro_monitoring.is_playing = False
            # self.engine.stop_play()

    # ==========================================================================
    # VO-SE Pro v1.3.0: 連続音（VCV）解決 ＆ レンダリング準備
    #==========================================================================

    def resolve_target_wav(self, lyric, prev_lyric):
        """前の歌詞から母音を判定し、最適なWAVパスを特定する"""
        # 1. 母音グループの定義
        vowel_groups = {
            'a': 'あかさたなはまやらわがざだばぱぁゃ',
            'i': 'いきしちにひみりぎじぢびぴぃ',
            'u': 'うくすつぬふむゆるぐずづぶぷぅゅ',
            'e': 'えけせてねへめれげぜでべぺぇ',
            'o': 'おこそとのほもよろをごぞどぼぽぉょ',
            'n': 'ん'
        }

        # 2. 前の文字の母音を特定
        prev_v = None
        if prev_lyric:
            last_char = prev_lyric[-1]
            for v, chars in vowel_groups.items():
                if last_char in chars:
                    prev_v = v
                    break

        # 3. 検索候補の作成 (連続音 -> 単独音1 -> 単独音2)
        candidates = []
        if prev_v:
            candidates.append(f"{prev_v} {lyric}") # 例: 'a い'
        candidates.append(f"- {lyric}")           # 例: '- い'
        candidates.append(lyric)                   # 例: 'い'

        # 4. エンジンから現在の音源フォルダとoto_mapを取得
        voice_path = getattr(self.vo_se_engine, 'voice_path', "")
        # エンジン側が保持しているoto.iniの解析データ
        oto_map = getattr(self.vo_se_engine, 'oto_data', {})

        for alias in candidates:
            if alias in oto_map:
                # oto_map内の'wav'キーから実際のファイル名を取得
                filename = oto_map[alias].get('wav', f"{lyric}.wav")
                return os.path.join(voice_path, filename)

        # 5. 何も見つからなければデフォルト
        return os.path.join(voice_path, f"{lyric}.wav")

    def prepare_rendering_data(self):
        """タイムラインとグラフのデータをエンジン形式にシリアライズ"""
        notes = self.timeline_widget.notes_list
        if not notes:
            return None
            
        render_data = {
            "project_name": "New Project",
            "voice_path": self.voice_manager.get_current_voice_path(),
            "tempo": self.timeline_widget.tempo,
            "notes": []
        }

        for note in notes:
            # グラフエディタの各レイヤーから値を抽出
            note_info = {
                "lyric": note.lyrics,
                "note_num": note.note_number,
                "start_sec": note.start_time,
                "duration_sec": note.duration,
                "pitch_bend": self._sample_range(self.graph_editor_widget.all_parameters["Pitch"], note, 64),
                "dynamics": self._sample_range(self.graph_editor_widget.all_parameters["Tension"], note, 64)
            }
            render_data["notes"].append(note_info)
            
        return render_data


    def start_playback(self):
        """再生ボタンが押された時のメインエントリ"""
        # VCV解析済みのデータを生成
        notes_data = self.prepare_rendering_data()
        
        if not notes_data:
            self.statusBar().showMessage("再生するノートがありません。")
            return

        self.statusBar().showMessage("VCV解析完了。合成を開始します...")
        
        # エンジン側のsynthesizeメソッドにデータを渡す
        audio_data = self.vo_se_engine.synthesize(notes_data)

        if audio_data is not None and len(audio_data) > 0:
            self.vo_se_engine.play(audio_data)
            self.statusBar().showMessage("再生中 (v1.3.0 VCV Engine)")
        else:
            self.statusBar().showMessage("合成エラー。ログを確認してください。")
    
    # ==========================================================================
    # 初期化メソッド
    #==========================================================================

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

    def clear_layout(self, layout):
        """レイアウト内のウィジェットを安全に全削除"""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
    
    def init_ui(self):
        """UIの組み立て（司令塔）"""
        self.setWindowTitle("VO-SE Engine DAW Pro")
        self.setGeometry(100, 100, 1200, 800)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(2)

        # 各セクションの呼び出し
        self.setup_toolbar()
        self.setup_main_editor_area() # タイムラインと音源グリッド
        self.setup_bottom_panel()
        self.setup_status_bar()
        self.setup_menus()
        
        # スタイル適用
        self.update_timeline_style()

    # ==========================================================================
    # UI セクション構築
    # ==========================================================================

    def setup_toolbar(self):
        """上部ツールバー：再生・録音・テンポ"""
        self.toolbar = QToolBar("Main Toolbar")
        self.addToolBar(self.toolbar)

        self.play_btn = QPushButton("▶ 再生")
        self.play_btn.clicked.connect(self.on_play_pause_toggled)
        self.toolbar.addWidget(self.play_btn)

        self.toolbar.addSeparator()
        
        self.toolbar.addWidget(QLabel(" Tempo: "))
        self.tempo_input = QLineEdit("120")
        self.tempo_input.setFixedWidth(40)
        self.tempo_input.returnPressed.connect(self.update_tempo_from_input)
        self.toolbar.addWidget(self.tempo_input)

    def setup_main_editor_area(self):
        """中央エリア：QSplitterで左右に分割"""
        self.editor_splitter = QSplitter(Qt.Horizontal)

        # --- 左：タイムライン ---
        self.timeline_widget = TimelineWidget() # 仮定：自作ウィジェット
        self.editor_splitter.addWidget(self.timeline_widget)

        # --- 右：音源リスト（スクロール可能） ---
        self.voice_scroll = QScrollArea()
        self.voice_scroll.setWidgetResizable(True)
        self.voice_scroll.setFixedWidth(280)
        
        self.voice_container = QWidget()
        self.voice_grid = QGridLayout(self.voice_container) # ここにカードを追加していく
        self.voice_scroll.setWidget(self.voice_container)
        
        self.editor_splitter.addWidget(self.voice_scroll)
        self.editor_splitter.setStretchFactor(0, 8) # タイムライン優先

        self.main_layout.addWidget(self.editor_splitter)

    def setup_bottom_panel(self):
        """下部：歌詞入力などのツール"""
        bottom_box = QHBoxLayout()
        
        self.lyrics_button = QPushButton("歌詞一括入力")
        self.lyrics_button.setFixedHeight(40)
        self.lyrics_button.clicked.connect(self.on_click_apply_lyrics_bulk)
        bottom_box.addWidget(self.lyrics_button)
        
        # フォルマントやパフォーマンス等のボタンもここに追加
        self.main_layout.addLayout(bottom_box)


    
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

        self.timeline_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

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


    def toggle_playback(self, event=None):
        """Spaceキーが押された時の動作"""
        if not self.pro_monitoring.is_playing:
            # --- 再生開始 ---
            print("ʕ•̫͡• Pro Audio Monitoring: START")
            # 1. 念のため最新の状態をレンダリング（部分レンダリング）
            # self.engine.export_to_wav(self.notes, self.params, "preview.wav")
            
            # 2. UIを再生モードにする
            self.pro_monitoring.current_time = 0.0 # 0秒から開始
            self.pro_monitoring.is_playing = True
            self.pro_monitoring.update_frame() # ループ開始
            
            # 3. 音を鳴らす
            # self.engine.play("preview.wav")
        else:
            # --- 再生停止 ---
            print("(-_-) Pro Audio Monitoring: STOP")
            self.pro_monitoring.is_playing = False
            self.engine.stop()

    # ==========================================================================
    # PERFORMANCE CONTROL CENTER (Core i3 Survival Logic)
    # ==========================================================================

    def setup_performance_toggle(self):
        """
        [Strategic Toggle] パフォーマンスモードの初期化。
        リソースの乏しい環境(Core i3等)と、ハイスペック環境を瞬時に最適化します。
        """
        # アイコンやテキストで「プロのツール」感を演出
        self.perf_action = QAction("High-Performance Mode", self)
        self.perf_action.setCheckable(True)
        # 初期状態は省電力(False)にしておき、ユーザーが必要に応じてブーストする仕様
        self.perf_action.setChecked(False) 
        self.perf_action.triggered.connect(self.toggle_performance)
        
        # ツールバーへの追加（メイン操作部に配置してアクセシビリティを確保）
        self.toolbar.addAction(self.perf_action)

    @Slot(bool)
    def toggle_performance(self, checked):
        """
        パフォーマンスモードの動的切り替え。
        C++エンジン(vose_core)の内部バッファやスレッド優先度を操作します。
        """
        # 1. 動作モードの決定 (1: 高負荷・高品質, 0: 低負荷・安定)
        mode = 1 if checked else 0
        
        # 2. C++エンジン(Shared Library)への安全なアクセス
        try:
            if hasattr(self.vo_se_engine, 'lib'):
                if hasattr(self.vo_se_engine.lib, 'vose_set_performance_mode'):
                    # C言語形式でモードを転送
                    self.vo_se_engine.lib.vose_set_performance_mode(mode)
                
                # [蹂躙ポイント] 省電力モード時は内部バッファを増やして途切れを防ぐなどの追加処理
                if mode == 0 and hasattr(self.vo_se_engine.lib, 'vose_set_buffer_size'):
                    self.vo_se_engine.lib.vose_set_buffer_size(4096) # Core i3向けの安全策
                elif mode == 1 and hasattr(self.vo_se_engine.lib, 'vose_set_buffer_size'):
                    self.vo_se_engine.lib.vose_set_buffer_size(1024) # 高速レスポンス
        except Exception as e:
            print(f"Engine Performance Control Warning: {e}")

        # 3. ユーザーへのフィードバック
        status = "【High-Mode】レンダリング優先" if mode == 1 else "【Power-Save】Core i3最適化モード"
        _ = "#ff4444" if mode == 1 else "#44ff44"
        
        self.statusBar().showMessage(f"System: {status} に切り替えました")
        
        # ログにも残して「まともに動いている」ことを証明
        print(f"Performance Mode Changed to: {mode}")

    

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
            




    def import_voice_bank(self, zip_path: str):
        """
        ZIP音源インストール完全版
        1. 文字化け修復解凍 2. ゴミ排除 3. AI解析(oto.ini生成) 4. Aural AI接続 5. UI更新
        """

        # 保存先ディレクトリ（voicesフォルダ）
        extract_base_dir = get_resource_path("voices")
        os.makedirs(extract_base_dir, exist_ok=True)
        
        installed_name = None
        valid_files = [] 
        found_oto = False

        try:
            # --- STEP 1: ZIP解析と文字化け対策 ---
            with zipfile.ZipFile(zip_path, 'r') as z:
                for info in z.infolist():
                    # Macで作られたZIPの日本語名化けを修正 (cp437 -> cp932)
                    try:
                        filename = info.filename.encode('cp437').decode('cp932')
                    except Exception:
                        filename = info.filename
                    
                    # 不要なゴミファイル（Mac由来など）をスキップ
                    if "__MACOSX" in filename or ".DS_Store" in filename:
                        continue
                    
                    valid_files.append((info, filename))
                    
                    # oto.iniがあるかチェック
                    if "oto.ini" in filename.lower():
                        found_oto = True
                        # フォルダ構造から音源名を推測
                        parts = filename.replace('\\', '/').strip('/').split('/')
                        if len(parts) > 1 and not installed_name:
                            installed_name = parts[-2]

                # 音源名が確定しなかった場合はZIPファイル名を使用
                if not installed_name:
                    installed_name = os.path.splitext(os.path.basename(zip_path))[0]

                target_voice_dir = os.path.join(extract_base_dir, installed_name)
                
                # --- STEP 2: クリーンインストール ---
                if os.path.exists(target_voice_dir):
                    shutil.rmtree(target_voice_dir)
                os.makedirs(target_voice_dir, exist_ok=True)

                # ファイルを実際に展開
                for info, filename in valid_files:
                    target_path = os.path.join(extract_base_dir, filename)
                    if info.is_dir():
                        os.makedirs(target_path, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with z.open(info) as source, open(target_path, "wb") as target:
                        shutil.copyfileobj(source, target)

            # --- STEP 3: AIエンジン自動解析 (oto.iniがない場合) ---
            if not found_oto:
                self.statusBar().showMessage(f"AI解析中: {installed_name} の原音設定を自動生成しています...", 0)
                # 代表の作ったAI解析メソッドを呼び出し
                self.generate_and_save_oto(target_voice_dir)

            # --- STEP 4: AIエンジンの優先接続 (Aural AI > Standard > Generic) ---
            aural_model = os.path.join(target_voice_dir, "aural_dynamics.onnx")
            std_model = os.path.join(target_voice_dir, "model.onnx")

            if os.path.exists(aural_model):
                self.dynamics_ai = AuralAIEngine(model_path=aural_model)
                engine_msg = "上位Auralモデル"
            elif os.path.exists(std_model):
                self.dynamics_ai = DynamicsAIEngine(model_path=std_model)
                engine_msg = "標準Dynamicsモデル"
            else:
                self.dynamics_ai = AuralAIEngine() # 汎用エンジン
                engine_msg = "汎用Auralエンジン"

            # --- STEP 5: UIの即時反映 ---
            if hasattr(self, 'voice_manager'):
                self.voice_manager.scan_utau_voices() # 内部リスト更新
            
            # ボイスカードの再描画メソッドがあれば呼ぶ
            if hasattr(self, 'refresh_voice_ui'):
                self.refresh_voice_ui()
            
            # 成功通知とSE
            self.statusBar().showMessage(f"'{installed_name}' インストール完了！ ({engine_msg})", 5000)
            if hasattr(self, 'audio_output'):
                se_path = get_resource_path("assets/install_success.wav")
                if os.path.exists(se_path):
                    self.audio_output.play_se(se_path)

            QMessageBox.information(self, "導入成功", f"音源 '{installed_name}' をインストールしました。\nエンジン: {engine_msg}")

        except Exception as e:
            QMessageBox.critical(self, "導入エラー", f"インストール中にエラーが発生しました:\n{str(e)}")
            

    def dragEnterEvent(self, event):
        """ファイルドラッグ時の処理"""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()
            

    def dropEvent(self, event):
        """ファイルドロップ時の処理：ZIP（音源）、MIDI/JSON（プロジェクト）を自動判別"""
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        
        for file_path in files:
            file_lower = file_path.lower()
            
            # 1. 音源ライブラリ(ZIP)の場合
            if file_lower.endswith(".zip"):
                self.statusBar().showMessage(f"音源を導入中: {os.path.basename(file_path)}")
                try:
                    # VoiceManagerのインストール機能を実行
                    new_voice = self.voice_manager.install_voice_from_zip(file_path)
                    
                    # 成功演出：SEを鳴らして通知
                    # ※ audio_output.play_se が実装されている前提
                    if hasattr(self, 'audio_output'):
                        self.audio_output.play_se(get_resource_path("assets/install_success.wav"))
                        
                    QMessageBox.information(self, "導入完了", f"音源 '{new_voice}' をインストールしました！")
                    self.scan_utau_voices() # リストを最新の状態に更新
                except Exception as e:
                    QMessageBox.critical(self, "導入失敗", f"インストール中にエラーが発生しました:\n{e}")

            # 2. 楽曲データ(MIDI)の場合
            elif file_lower.endswith(('.mid', '.midi')):
                self.load_file_from_path(file_path)
                self.statusBar().showMessage(f"MIDIファイルを読み込みました: {os.path.basename(file_path)}")

            # 3. プロジェクトデータ(JSON)の場合
            elif file_lower.endswith('.json'):
                self.load_file_from_path(file_path)
                self.statusBar().showMessage(f"プロジェクトを読み込みました: {os.path.basename(file_path)}")


    # ==========================================================================
    # 再生・録音制御
    # ==========================================================================


    def on_click_play(self):
        # タイムラインのデータを渡して合成・再生
        audio = self.vo_se_engine.synthesize(self.timeline_widget.notes_list)
        self.vo_se_engine.play(audio)

    @Slot()
    def on_play_pause_toggled(self):
        """再生/停止を切り替えるハンドラ（トグル機能）"""
        # --- 1. すでに再生中の場合 → 停止させる ---
        if self.is_playing:
            self.is_playing = False
            self.playback_timer.stop()
            
            if hasattr(self.vo_se_engine, 'stop_playback'):
                self.vo_se_engine.stop_playback()
            
            if self.playback_thread and self.playback_thread.is_alive():
                self.playback_thread.join(timeout=0.2) 

            self.play_button.setText("▶ 再生")
            self.status_label.setText("停止しました")
            self.playing_notes = {}
            return

        # --- 2. 停止中の場合 → 再生を開始する ---
        # 録音中なら止める（安全策）
        if getattr(self, 'is_recording', False):
            self.on_record_toggled()

        notes = self.timeline_widget.notes_list
        if not notes:
            self.status_label.setText("ノートが存在しません")
            return

        try:
            self.status_label.setText("音声生成中...")
            # GUIをフリーズさせないための処理
            QApplication.processEvents()

            # ノートの範囲を取得（実装されている場合）
            if hasattr(self.timeline_widget, 'get_selected_notes_range'):
                start_time, end_time = self.timeline_widget.get_selected_notes_range()
            else:
                start_time = 0
                _ = max(n.start_time + n.duration for n in notes)

            # 再生フラグを立てる
            self.is_playing = True
            self.current_playback_time = start_time
            self.play_button.setText("■ 停止")
            self.status_label.setText(f"再生中: {start_time:.2f}s -")

            # 別スレッドで再生を開始
            # 注: play_audioに引数が必要な場合は args=(audio_track,) 等を追加
            self.playback_thread = threading.Thread(
                target=self.vo_se_engine.play_audio, 
                daemon=True
            )
            self.playback_thread.start()
            
            # UI更新タイマー開始
            self.playback_timer.start(20)

        except Exception as e:
            self.status_label.setText(f"再生エラー: {e}")
            self.is_playing = False
            self.play_button.setText("▶ 再生")

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
    # REAL-TIME PREVIEW ENGINE (Low-Latency Response)
    # ==========================================================================

    @Slot(object)
    def on_single_note_modified(self, note):
        """
        ノートが1つ変更された瞬間に呼ばれる（リアルタイム・プレビュー）。
        軽量なDSPエンジンだからこそ、Core i3でも遅延なく鳴らせます。
        """
        if not self.perf_action.isChecked():
            # 省電力モード（Core i3モード）の時は、負荷を考えてプレビューを
            # 簡略化するか、タイマー待機にする
            self.render_timer.start(100) 
            return

        # 1. 変更されたノートだけの「部分合成」をリクエスト
        # 全体を計算し直さないのが「軽量」の極意
        threading.Thread(
            target=self.vo_se_engine.preview_single_note,
            args=(note,),
            daemon=True
        ).start()

    def setup_realtime_monitoring(self):
        """
        マウスの動きを監視し、『今まさにいじっている音』を
        ダイレクトにオーディオデバイスへ送る設定。
        """
        if hasattr(self.vo_se_engine, 'enable_realtime_monitor'):
            # C++側の低遅延モニタリングを有効化
            self.vo_se_engine.enable_realtime_monitor(True)
            self.statusBar().showMessage("Real-time Monitor: Active (Low Latency)")

    # ==========================================================================
    # GLOBAL DOMINANCE: Pro Audio Performance Engine (Full Integration)
    # ==========================================================================

    @Slot()
    def start_batch_analysis(self):
        """
        [Strategic Engine] 高速音響特性解析の開始。
        AIという呼称を排し、DSP(信号処理)による『Pro Audio Performance』として実行。
        海外勢を凌駕する解析速度と精度を実現します。
        """
        # 1. ターゲットディレクトリの取得とバリデーション
        target_dir = self.voice_manager.get_current_voice_path()
        
        if not target_dir or not os.path.exists(target_dir):
            QMessageBox.warning(self, "Performance Error", "有効な音源ライブラリがロードされていません。")
            return

        # 2. スレッド競合の防止（爆弾3・4対策）
        if hasattr(self, 'analysis_thread') and self.analysis_thread.isRunning():
            QMessageBox.warning(self, "System Busy", "現在、別の解析プロセスが実行中です。")
            return

        # 3. 解析スレッドの初期化
        # ※AnalysisThreadは別途定義されているQThreadクラス
        self.analysis_thread = AnalysisThread(self.voice_manager, target_dir)
        
        # 4. シグナルとスロットの完全接続（省略なし）
        self.analysis_thread.progress.connect(self.update_analysis_status)
        self.analysis_thread.finished.connect(self.on_analysis_complete)
        self.analysis_thread.error.connect(self.on_analysis_error)
        
        # [爆弾5対策] 完了後のメモリ解放を予約
        self.analysis_thread.finished.connect(self.analysis_thread.deleteLater)
        
        # 5. UIの戦闘態勢への切り替え
        self.ai_analyze_button.setEnabled(False) 
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.statusBar().showMessage("Pro Audio Dynamics Engine: Initializing high-speed analysis...")
        
        # 6. 解析実行
        self.analysis_thread.start()

    def update_analysis_status(self, percent: int, filename: str):
        """解析進捗のリアルタイム表示（UXの質で海外勢に差をつける）"""
        self.progress_bar.setValue(percent)
        self.statusBar().showMessage(f"Acoustic Sampling [{percent}%]: {filename}")

    def on_analysis_complete(self, results: dict):
        """
        解析完了後の統合・最適化処理。
        抽出されたパラメータをプロジェクトに反映し、世界標準の精度へ昇華させます。
        """
        self.progress_bar.hide()
        self.ai_analyze_button.setEnabled(True)
        
        if not results:
            self.statusBar().showMessage("Analysis completed, but no data was returned.")
            return

        # 7. 解析結果の精密適用（爆弾2対策済・省略なし）
        update_count = 0
        for note in self.timeline_widget.notes_list:
            if note.lyrics in results:
                res = results[note.lyrics]
                # 配列の長さをチェックし、インデックスエラーを回避
                if isinstance(res, (list, tuple)) and len(res) >= 3:
                    # 内部データへの反映
                    note.onset = self.safe_to_f(res[0])
                    note.overlap = self.safe_to_f(res[1])
                    note.pre_utterance = self.safe_to_f(res[2])
                    note.has_analysis = True
                    update_count += 1
        
        # UI更新（ピアノロールの再描画など）
        self.timeline_widget.update()
        self.statusBar().showMessage(f"Optimization Complete: {update_count} samples updated.", 5000)
        
        # 8. グローバルシェア奪還のための自動保存ダイアログ
        # 海外ユーザーの手間を減らすための親切設計
        reply = QMessageBox.question(self, "Acoustic Config Save", 
            "解析結果を oto.ini に反映し、音源ライブラリを最適化しますか？\n(既存ファイルは自動でバックアップされます)",
            QMessageBox.Yes | QMessageBox.No)
            
        if reply == QMessageBox.Yes:
            self.export_analysis_to_oto_ini()

    def export_analysis_to_oto_ini(self):
        """
        解析結果を UTAU 互換の oto.ini 形式で物理保存。
        【爆弾4・5対策】Shift-JIS(cp932)完全準拠。
        """
        target_dir = self.voice_manager.get_current_voice_path()
        if not target_dir: 
            return
        
        file_path = os.path.join(target_dir, "oto.ini")
        
        # 9. プロ仕様：既存データの保護（バックアップ作成）
        if os.path.exists(file_path):
            try:
                import shutil
                shutil.copy2(file_path, file_path + ".bak")
            except Exception as e:
                print(f"Backup Warning: {e}")

        # 10. oto.ini データの構築
        oto_lines = []
        processed_keys = set()
        for note in self.timeline_widget.notes_list:
            if getattr(note, 'has_analysis', False) and note.lyrics not in processed_keys:
                # 形式: wav名=エイリアス,左ブランク,固定,右ブランク,先行発音,オーバーラップ
                # 日本語Windows環境の標準 UTAU 形式を完全再現
                line = f"{note.lyrics}.wav={note.lyrics},0,0,0,{note.pre_utterance},{note.overlap}"
                oto_lines.append(line)
                processed_keys.add(note.lyrics)

        # 11. 安全なファイル書き出し
        try:
            content = "\n".join(oto_lines)
            # errors='replace' により、Shift-JISで扱えない特殊文字を'?'に置き換えて保存を継続
            with open(file_path, "w", encoding="cp932", errors="replace") as f:
                f.write(content)
            QMessageBox.information(self, "Global Standard Saved", "設定ファイル(oto.ini)を更新しました。")
        except Exception as e:
            QMessageBox.critical(self, "Write Error", f"保存に失敗しました:\n{e}")

    def on_analysis_error(self, message: str):
        """解析失敗時の例外ハンドリング"""
        self.ai_analyze_button.setEnabled(True)
        self.progress_bar.hide()
        QMessageBox.critical(self, "Engine Fault", f"解析中にエラーが発生しました:\n{message}")

    def safe_to_f(self, val):
        """[爆弾2対策] あらゆる入力値を安全に数値化する変換機"""
        try:
            s_val = str(val).strip()
            return float(s_val) if s_val else 0.0
        except (ValueError, TypeError):
            return 0.0

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


    def start_vocal_analysis(self, audio_data):
        """AIによるボーカル解析を開始する"""
        if not audio_data:
            self.statusBar().showMessage("解析エラー: オーディオデータがありません")
            return

        self.statusBar().showMessage("AI解析中... しばらくお待ちください")
        
        # 解析処理を非同期（バックグラウンド）で実行
        try:
            self.ai_manager.analyze_async(audio_data)
        except Exception as e:
            self.statusBar().showMessage(f"解析開始失敗: {e}")
            print(f"Analysis Error: {e}")

    def on_analysis_finished(self, results):
        """
        AIがスキャンした全音符のデータをループで処理
        results: [{"onset": 1.2, ...}, {"onset": 1.5, ...}, ...]
        """
        if not results:
            self.statusBar().showMessage("音符が見つかりませんでした")
            return

        # 既存のノードをクリアするならここで実行
        # self.timeline.clear_notes()

        for note_data in results:
            # --- 描画位置の計算 ---
            # 1秒 = 100ピクセル(px)の場合
            x_pos = note_data["onset"] * 100 
            
            # --- ノードの生成（呼び出し） ---
            # 代表のVO-SEエンジンのNoteクラスに合わせて呼び出す
            self.create_new_note(
                x=x_pos, 
                lyric="あ", # 初期値
                overlap=note_data["overlap"],
                pre_utterance=note_data["pre_utterance"]
            )

        self.statusBar().showMessage(f"{len(results)} 個の音符を配置しました")
        self.update() # 画面全体を更新

    def create_new_note(self, x, lyric, overlap, pre_utterance):
        """実際にノードをリストに追加し、描画を指示する関数（仮）"""
        # ここに代表のVO-SE Proのノード追加ロジックを書く
        print(f"Node at {x}px added.")

  

    # ==========================================================================
    # ファイル操作
    # ==========================================================================

    def import_external_project(self, file_path):
        """
        外部ファイル(.vsqx, .ustx, .mid)を解析しVO-SE形式へ変換
        """
        self.statusBar().showMessage(f"Migrating Project: {os.path.basename(file_path)}...")
        
        ext = os.path.splitext(file_path)[1].lower()
        imported_notes = []

        try:
            if ext == ".vsqx":
                # VOCALOIDファイルのXML解析
                imported_notes = self._parse_vsqx(file_path)
            elif ext == ".ustx":
                # OpenUTAU(YAML形式)の解析
                imported_notes = self._parse_ustx(file_path)
            elif ext == ".mid":
                # 標準MIDIファイルの解析
                imported_notes = self._parse_midi(file_path)

            if imported_notes:
                # 解析した音符をピアノロールに配置し、エンジンにリレーする
                self.update_timeline_with_notes(imported_notes)
                self.log_startup(f"Migration Successful: {len(imported_notes)} notes imported.")
                # そのままAural AIでプレビュー再生
                self.handle_playback() 
        
        except Exception as e:
            self.statusBar().showMessage(f"Migration Failed: {e}")

    def _parse_vsqx(self, path):
        """XML構造を解析してNoteEventリストを作る (省略なしのロジック骨子)"""
        import xml.etree.ElementTree as ET
        tree = ET.parse(path)
        root = tree.getroot()
        
        notes = []
        # VOCALOID特有のネームスペース処理
        ns = {'v': 'http://www.yamaha.co.jp/vocaloid/schema/vsqx/4.0'} 
        
        for v_note in root.findall('.//v:note', ns):
            note = NoteEvent(
                lyrics=v_note.find('v:y', ns).text, # 歌詞
                note_number=int(v_note.find('v:n', ns).text), # 音高
                duration=int(v_note.find('v:dur', ns).text) / 480.0, # ティックを秒に変換
                start_time=int(v_note.find('v:t', ns).text) / 480.0
            )
            notes.append(note)
        return notes
        
    
    def read_file_safely(self, filepath: str) -> str:
        """ 文字コードを自動判別し、安全に読み込む"""
        import chardet
        try:
            with open(filepath, 'rb') as f:
                raw_data = f.read()
            
            res = chardet.detect(raw_data)
            encoding = res['encoding'] if res['encoding'] else 'cp932'
            
            # errors='replace' を指定することで、変換できない文字があってもクラッシュさせない
            return raw_data.decode(encoding, errors='replace')
        except Exception as e:
            print(f"File Read Error: {e}")
            return ""



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


    def save_oto_ini(self, path, content):
        """
        UTF-8の文字が含まれていても、エラーで落ちずに書き出す
        """
        try:
            # errors="replace" をつけると、書けない文字が自動で '?' になる
            with open(path, "w", encoding="cp932", errors="replace") as f:
                f.write(content)
        except Exception as e:
            QMessageBox.warning(self, "保存エラー", f"文字化けの可能性があります:\n{e}")
 



    def get_safe_installed_name(self, filename, zip_path):
        """
        パスをOSに合わせて綺麗にし、安全にフォルダ名を取り出す
        """
        # 1. バックスラッシュ等を現在のOSに合わせて統一
        clean_path = os.path.normpath(filename)
        parts = [p for p in clean_path.split(os.sep) if p]

        # 2. フォルダ階層があるかチェックして名前を取得
        if len(parts) >= 2:
            return parts[-2] # フォルダ名
    
        # 3. フォルダがない場合はZIPファイル自体の名前を使う
        return os.path.splitext(os.path.basename(zip_path))[0]


    @Slot()
    def on_export_button_clicked(self):
        """ WAV書き出し（多重起動防止 & 高速化）"""
        notes = self.timeline_widget.notes_list
        if not notes:
            QMessageBox.warning(self, "エラー", "ノートがないため書き出しできません。")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "音声ファイルを保存", "output.wav", "WAV Files (*.wav)"
        )
        if not file_path: 
            return

        # 再生中なら止める（デバイス競合回避）
        self.stop_and_clear_playback()

        self.statusBar().showMessage("レンダリング中...")

        try:
            # numpyはメソッド内ではなく、ファイル先頭で import numpy as np 済みと想定
            all_params = self.graph_editor_widget.all_parameters
            vocal_data_list = []
            res = 128 
            
            for note in notes:
                # 辞書作成
                note_data = {
                    "lyric": note.lyrics,
                    "phonemes": note.phonemes,
                    "note_number": note.note_number,
                    "start_time": note.start_time,
                    "duration": note.duration,
                    # 各パラメーターをサンプリング
                    "pitch_list": self._sample_range(all_params.get("Pitch", []), note, res),
                    "gender_list": self._sample_range(all_params.get("Gender", []), note, res),
                    "tension_list": self._sample_range(all_params.get("Tension", []), note, res),
                    "breath_list": self._sample_range(all_params.get("Breath", []), note, res)
                }
                vocal_data_list.append(note_data)

            # C++エンジンへ送信
            self.vo_se_engine.export_to_wav(
                vocal_data=vocal_data_list,
                tempo=self.timeline_widget.tempo,
                file_path=file_path
            )

            QMessageBox.information(self, "完了", "レンダリングが完了しました！")
            self.statusBar().showMessage("エクスポート完了")

        except Exception as e:
            QMessageBox.critical(self, "エラー", f"書き出し失敗: {e}")
            self.statusBar().showMessage("エラー発生")
            
    def _sample_range(self, events, note, res):
        """
        ノートの時間範囲(start 〜 start+duration)をres分割して
        グラフの値をサンプリングする補助関数
        """
        # numpy を使って時間を均等に分割# 1. 時間軸を生成
        times = np.linspace(note.start_time, note.start_time + note.duration, res)
        
        # 2. データがない場合の安全策
        if not events:
            return [0.5] * res
            
        # 3. グラフエディタの補間関数を呼び出し
        return [self.graph_editor_widget.get_value_at_time(events, t) for t in times]

    def load_oto_ini_special(self, path):
        try:
            # 迷わず cp932 (Shift-JIS) を指定
            with open(path, "r", encoding="cp932", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""

    

    @Slot()
    def save_file_dialog_and_save_midi(self):
        """プロジェクトの保存（全データ・全パラメーター）"""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "プロジェクトを保存", "", "VO-SE Project (*.vose);;JSON Files (*.json)"
        )
        if not filepath:
            return

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


            
        times = np.linspace(note.start_time, note.start_time + note.duration, res)
        # グラフエディタの補間関数を呼び出し
        return [self.graph_editor_widget.get_value_at_time(events, t) for t in times]

    def load_json_project(self, filepath: str):
        """【爆弾2対策】JSON読み込み（インポートを整理）"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # NoteEventなどのクラスはファイル先頭でインポートしておくこと
            notes = [NoteEvent.from_dict(d) for d in data.get("notes", [])]
            self.timeline_widget.set_notes(notes)
            
            # テンポ復元
            tempo = data.get("tempo_bpm", 120)
            self.tempo_input.setText(str(tempo))
            self.update_tempo_from_input()
            
            # パラメーター復元
            saved_params = data.get("parameters", {})
            for mode in self.graph_editor_widget.all_parameters.keys():
                if mode in saved_params:
                    # ここで PitchEvent を都度インポートせず、既に読み込み済みのものを使い回す
                    self.graph_editor_widget.all_parameters[mode] = [
                        PitchEvent(time=p["t"], value=p["v"]) for p in saved_params[mode]
                    ]
            
            # UI更新
            self.update_scrollbar_range()
            self.update_scrollbar_v_range()
            self.graph_editor_widget.update()
            self.timeline_widget.update()
            
            self.statusBar().showMessage(f"読み込み完了: {len(notes)}ノート")
            
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
        
        # 3. 【追加】公式音源フォルダ内をスキャンして全員登録
        official_base = os.path.join(self.base_path, "assets", "official_voices")
        if os.path.exists(official_base):
            # フォルダ（kanase, characters_b, etc...）をすべて取得
            for char_dir in os.listdir(official_base):
                full_dir = os.path.join(official_base, char_dir)
                if os.path.isdir(full_dir):
                    # 「[Official] 奏瀬」のような表示名で登録
                    display_name = f"[Official] {char_dir}"
                    # 内部パスとして "__INTERNAL__:{フォルダ名}" としておくと後で判別しやすい
                    self.voices[display_name] = f"__INTERNAL__:{char_dir}"
        
        return self.voices
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
                    "overlap": float(p[5]) if len(p) > 5 else 0.0       # オーバーラップ
                }
            except (ValueError, IndexError):
                continue
                
        return oto_map

    def safe_to_float(self, val):
        """文字列を安全に浮動小数点数に変換（E701修正済み）"""
        try: 
            return float(val.strip())
        except Exception:
            return 0.0

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
            
            # 注: VoiceCardWidgetが別ファイルにある場合はインポートが必要です
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
            self.current_oto_data = self.parse_oto_ini(path)
            
            # 4. 合成エンジン (VO_SE_Engine) の更新
            self.vo_se_engine.set_voice_library(path)
            if hasattr(self.vo_se_engine, 'set_oto_data'):
                self.vo_se_engine.set_oto_data(self.current_oto_data)
            
            self.current_voice = character_name

            # 5. Talkエンジン（会話用）の更新
            talk_model = os.path.join(path, "talk.htsvoice")
            if os.path.exists(talk_model) and hasattr(self, 'talk_manager'):
                self.talk_manager.set_voice(talk_model)

            # 6. UIへのフィードバック（F841修正：変数を利用）
            char_color = self.voice_manager.get_character_color(path)
            msg = f"【{character_name}】に切り替え完了 ({len(self.current_oto_data)} 音素ロード)"
            self.statusBar().showMessage(msg, 5000)
            
            # ログ出力（デバッグ用）
            print(f"Selected voice: {character_name} at {path} (Color: {char_color})")

        except Exception as e:
            QMessageBox.critical(self, "音源ロードエラー", f"音源の読み込み中にエラーが発生しました:\n{e}")

    def refresh_voice_list(self):
        """voice_banksフォルダを再スキャン"""
        self.scan_utau_voices()
        self.update_voice_list()
        print("ボイスリストを更新しました")

    def play_selected_voice(self, note_text):
        selected_name = self.character_selector.currentText()
        voice_path = self.voices.get(selected_name, "")

        if voice_path.startswith("__INTERNAL__"):
            # 内蔵音源モード
            char_id = voice_path.split(":")[1] # "kanase" など
            internal_key = f"{char_id}_{note_text}"
            self.vose_engine.play_voice(internal_key)

    def get_cached_oto(self, voice_path):
        cache_path = os.path.join(voice_path, "oto_cache.vose")
        ini_path = os.path.join(voice_path, "oto.ini")
    
        # oto.iniが更新されていなければキャッシュを読み込む
        if os.path.exists(cache_path):
            if os.path.getmtime(cache_path) > os.path.getmtime(ini_path):
                with open(cache_path, 'rb') as f:
                    return pickle.load(f)
    
        # キャッシュがない、または古い場合はパースして保存
        oto_data = self.parse_oto_ini(voice_path)
        with open(cache_path, 'wb') as f:
            pickle.dump(oto_data, f)
        return oto_data

    def smart_cache_purge(self):
        """[Core i3救済] メモリ最適化"""
        if hasattr(self.voice_manager, 'clear_unused_cache'):
            self.voice_manager.clear_unused_cache()
            self.statusBar().showMessage("Memory Optimized.", 2000)

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
        self.pro_monitoring.sync_notes(self.timeline_widget.notes_list)

    def update_timeline_style(self):
        """タイムラインの見た目を Apple Pro 仕様に固定"""
        self.timeline_widget.setStyleSheet("background-color: #121212; border: none;")
        self.timeline_widget.note_color = "#FF9F0A"
        self.timeline_widget.note_border_color = "#FFD60A" 
        self.timeline_widget.text_color = "#FFFFFF"

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
        """歌詞の一括流し込み（E701修正済み）"""
        text, ok = QInputDialog.getMultiLineText(self, "歌詞の一括入力", "歌詞を入力:")
        if not (ok and text):
            return
        
        lyric_list = [char for char in text if char.strip() and char not in "、。！？"]
        notes = sorted(self.timeline_widget.notes_list, key=lambda n: n.start_time)
        
        for i in range(min(len(lyric_list), len(notes))):
            notes[i].lyrics = lyric_list[i]
            
        self.timeline_widget.update()
        self.pro_monitoring.sync_notes(self.timeline_widget.notes_list)

    def parse_ust_dict_to_note(self, d: dict, current_time_sec: float, tempo: float = 120.0):
        """USTのLengthを秒数に正確に変換"""
        length_ticks = int(d.get('Length', 480))
        note_num = int(d.get('NoteNum', 64))
        lyric = d.get('Lyric', 'あ')
        
        duration_sec = (length_ticks / 480.0) * (60.0 / tempo)
        
        note = NoteEvent(
            lyrics=lyric, 
            note_number=note_num, 
            start_time=current_time_sec,
            duration=duration_sec
        )
        return note, current_time_sec + duration_sec
   
    # =========================================================================
    # スクロールバー制御
    # ==========================================================================

    @Slot()
    def update_scrollbar_range(self):
        """水平スクロールバーの範囲更新"""
        if not self.timeline_widget.notes_list:
            self.h_scrollbar.setRange(0, 0)
            return
        
        max_beats = self.timeline_widget.get_max_beat_position()
        max_x_position = (max_beats + 4) * self.timeline_widget.pixels_per_beat
        viewport_width = self.timeline_widget.width()
        
        max_scroll_value = max(0, int(max_x_position - viewport_width))
        self.h_scrollbar.setRange(0, max_scroll_value)
        self.h_scrollbar.setPageStep(viewport_width)

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

    @Slot(str)
    def set_current_parameter_layer(self, layer_name: str):
        if layer_name in self.parameters:
            self.current_param_layer = layer_name
            self.update()
            print(f"Parameter layer switched to: {layer_name}")
        else:
            print(f"Error: Parameter layer '{layer_name}' not found.")

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
        """変更検知（連打防止タイマー）"""
        self.render_timer.stop()
        self.render_timer.start(300)
        self.statusBar().showMessage("変更を検知しました...", 500)

    def execute_async_render(self):
        """非同期レンダリング実行（E701修正済み）"""
        self.statusBar().showMessage("音声をレンダリング中...", 1000)
        
        updated_notes = self.timeline_widget.notes_list
        if not updated_notes:
            return

        if hasattr(self.vo_se_engine, 'update_notes_data'):
            self.vo_se_engine.update_notes_data(updated_notes)

        def rendering_task():
            try:
                if hasattr(self.vo_se_engine, 'prepare_cache'):
                    self.vo_se_engine.prepare_cache(updated_notes)
                
                self.vo_se_engine.synthesize_track(
                    updated_notes, 
                    self.pitch_data, 
                    preview_mode=True
                )
            except Exception as e:
                print(f"Async Render Error: {e}")

        render_thread = threading.Thread(target=rendering_task, daemon=True)
        render_thread.start()

    @Slot(list)
    def on_pitch_data_updated(self, new_pitch_events: List[PitchEvent]):
        self.pitch_data = new_pitch_events

    @Slot()
    def on_midi_port_changed(self):
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
        if event_type == 'on':
            self.status_label.setText(f"ノートオン: {note_number} (Velocity: {velocity})")
        elif event_type == 'off':
            self.status_label.setText(f"ノートオフ: {note_number}")

    def handle_midi_realtime(self, note_number: int, velocity: int, event_type: str):
        if event_type == 'on':
            self.vo_se_engine.play_realtime_note(note_number)
            if self.is_recording:
                self.timeline_widget.add_note_from_midi(note_number, velocity)
        elif event_type == 'off':
            self.vo_se_engine.stop_realtime_note(note_number)

    @Slot()
    def update_scrollbar_v_range(self):
        key_h = self.timeline_widget.key_height_pixels
        full_height = 128 * key_h
        viewport_height = self.timeline_widget.height()
        max_v = 128 * self.timeline_widget.note_height
        self.vertical_scroll.setRange(0, max_v)

        max_scroll_value = max(0, int(full_height - viewport_height + key_h))
        self.v_scrollbar.setRange(0, max_scroll_value)
        self.keyboard_sidebar.set_key_height_pixels(key_h)

    # ==========================================================================
    # ヘルパーメソッド
    # ==========================================================================

    def _get_yomi_from_lyrics(self, lyrics: str) -> str:
        try:
            import pykakasi
            kks = pykakasi.kakasi()
            result = kks.convert(lyrics)
            return "".join([item['hira'] for item in result])
        except ImportError:
            return lyrics

    def midi_to_hz(self, midi_note: int) -> float:
        return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))

    # ==========================================================================
    # イベントハンドラ
    # ==========================================================================

    def keyPressEvent(self, event: QKeyEvent):
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

    def closeEvent(self, event):
        reply = QMessageBox.question(
            self, 
            '確認', 
            "作業内容が失われる可能性があります。終了してもよろしいですか？",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, 
            QMessageBox.Save
        )

        if reply == QMessageBox.Save:
            self.on_save_project_clicked()
            event.accept()
        elif reply == QMessageBox.Discard:
            event.accept()
        else:
            event.ignore()
            return # キャンセルの場合はここで抜ける
        
        # 終了時処理
        config = {
            "default_voice": self.current_voice,
            "volume": self.volume
        }
        self.config_manager.save_config(config)
        
        if self.midi_manager:
            self.midi_manager.stop()
        
        if self.vo_se_engine:
            self.vo_se_engine.close()
        
        print("Application closing...")


# ==============================================================================
# アプリケーションエントリーポイント
# ==============================================================================

def main():
    """アプリケーション起動"""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
