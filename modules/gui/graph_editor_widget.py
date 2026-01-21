#graph_editor_widget.py

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, Slot, QRect, QPoint
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QPaintEvent, QMouseEvent
from .data_models import PitchEvent

class GraphEditorWidget(QWidget):
    pitch_data_changed = Signal(list) 

    # MIDI Pitch Bendの定数
    PITCH_MAX = 8191
    PITCH_MIN = -8192

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setMouseTracking(True) # ホバー検知のため有効化
        
        self.scroll_x_offset = 0
        self.pixels_per_beat = 40.0
        self._current_playback_time = 0.0
        self.pitch_events: list[PitchEvent] = []
        
        self.editing_point_index = None
        self.hover_point_index = None
        self.drag_start_pos = None
        self.drag_start_value = None
        self.tempo = 120.0

    def prepare_rendering_data(self):
        gui_notes = self.timeline_widget.get_all_notes()
        song_data = []

        for note in gui_notes:
            base_hz = 440.0 * (2.0 ** ((note.note_number - 69) / 12.0))
            num_frames = int(max(1, (note.duration * 1000) / 5))
        
            # --- ここが重要！グラフからピッチ補正を取得 ---
            pitches = []
            for i in range(num_frames):
                # 5msごとの絶対時間を計算
                current_time = note.start_time + (i * 0.005) 
                # グラフマネージャーからその時間の「ベンド値（半音単位）」を取得
                bend = self.graph_editor_widget.get_value_at(current_time) 
            
                # ベンド値を加味した周波数計算
                hz = 440.0 * (2.0 ** ((note.note_number + bend - 69) / 12.0))
                pitches.append(hz)
             # ------------------------------------------

            song_data.append({
                'lyric': note.lyrics,
                'pitch_list': np.array(pitches, dtype=np.float32)
            })
        return song_data

    # --- 座標変換ユーティリティ ---
    def time_to_x(self, seconds: float) -> float:
        beats = (seconds * self.tempo) / 60.0
        return (beats * self.pixels_per_beat) - self.scroll_x_offset

    def x_to_time(self, x: float) -> float:
        absolute_x = x + self.scroll_x_offset
        beats = absolute_x / self.pixels_per_beat
        return (beats * 60.0) / self.tempo

    def value_to_y(self, value: int) -> float:
        h = self.height()
        center_y = h / 2
        # 上下5%のマージンを残して描画
        range_y = center_y * 0.9
        return center_y - (value / self.PITCH_MAX) * range_y

    def y_to_value(self, y: float) -> int:
        h = self.height()
        center_y = h / 2
        range_y = center_y * 0.9
        val = -((y - center_y) / range_y) * self.PITCH_MAX
        return int(max(self.PITCH_MIN, min(self.PITCH_MAX, val)))

    # --- スロット ---
    @Slot(int)
    def set_scroll_x_offset(self, offset_pixels: int):
        self.scroll_x_offset = offset_pixels
        self.update()

    @Slot(float)
    def set_current_time(self, time_in_seconds: float):
        self._current_playback_time = time_in_seconds
        self.update()

    # --- イベント処理 ---
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            pos = event.position()
            self.editing_point_index = None
            
            for i, p in enumerate(self.pitch_events):
                px, py = self.time_to_x(p.time), self.value_to_y(p.value)
                if QRect(int(px)-6, int(py)-6, 12, 12).contains(pos.toPoint()):
                    self.editing_point_index = i
                    self.drag_start_pos = pos
                    self.drag_start_value = p.value
                    break
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()
        
        # ドラッグ編集
        if event.buttons() & Qt.LeftButton and self.editing_point_index is not None:
            delta_y = pos.y() - self.drag_start_pos.y()
            # Y方向の移動距離をピッチ値に変換
            range_y = (self.height() / 2) * 0.9
            value_delta = -(delta_y /




                            
　

    
