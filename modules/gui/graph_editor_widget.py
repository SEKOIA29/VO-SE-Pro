#graph_editor_widget.py

import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, Slot, QRect, QPoint, QPointF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QPaintEvent, QMouseEvent
from .data_models import PitchEvent

class GraphEditorWidget(QWidget):
    pitch_data_changed = Signal(list) 

    PITCH_MAX = 8191
    PITCH_MIN = -8192

    self.all_parameters = {
        "Pitch": [],      # 従来のピッチデータ
        "Gender": [],     # 声の太さ (0.0 〜 1.0)
        "Tension": [],    # 声の張り
        "Breath": []      # 吐息の量
    }
    self.current_mode = "Pitch"  # 現在編集中のモード

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setMouseTracking(True)
        
        self.scroll_x_offset = 0
        self.pixels_per_beat = 40.0
        self._current_playback_time = 0.0
        self.pitch_events: list[PitchEvent] = []
        
        self.editing_point_index = None
        self.hover_point_index = None
        self.drag_start_pos = None
        self.tempo = 120.0

    # --- 1. エンジンへの接続ブリッジ用関数 ---
    def get_value_at(self, time: float) -> float:
        """指定時間のピッチ補正値を返す（半音単位）"""
        if not self.pitch_events:
            return 0.0

        events = sorted(self.pitch_events, key=lambda p: p.time)

        if time <= events[0].time: return events[0].value / 4096.0
        if time >= events[-1].time: return events[-1].value / 4096.0

        for i in range(len(events) - 1):
            p1, p2 = events[i], events[i+1]
            if p1.time <= time <= p2.time:
                t = (time - p1.time) / (p2.time - p1.time)
                # 線形補間
                val = p1.value + (p2.value - p1.value) * t
                return val / 4096.0 # 4096 = 1半音として計算
        return 0.0

    # --- 2. 座標変換 ---
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
        range_y = center_y * 0.8 # 余裕を持たせる
        return center_y - (value / self.PITCH_MAX) * range_y

    def y_to_value(self, y: float) -> int:
        h = self.height()
        center_y = h / 2
        range_y = center_y * 0.8
        val = -((y - center_y) / range_y) * self.PITCH_MAX
        return int(max(self.PITCH_MIN, min(self.PITCH_MAX, val)))

    # --- 3. マウスイベント（編集機能） ---
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """ダブルクリックで新しい点を追加"""
        if event.button() == Qt.LeftButton:
            time = self.x_to_time(event.position().x())
            val = self.y_to_value(event.position().y())
            new_point = PitchEvent(time=time, value=val)
            self.pitch_events.append(new_point)
            self.pitch_events.sort(key=lambda x: x.time)
            self.pitch_data_changed.emit(self.pitch_events)
            self.update()

    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position()
        if event.button() == Qt.LeftButton:
            self.editing_point_index = None
            for i, p in enumerate(self.pitch_events):
                px, py = self.time_to_x(p.time), self.value_to_y(p.value)
                if QRect(int(px)-8, int(py)-8, 16, 16).contains(pos.toPoint()):
                    self.editing_point_index = i
                    self.drag_start_pos = pos
                    break
        elif event.button() == Qt.RightButton:
            # 右クリックで点を削除
            for i, p in enumerate(self.pitch_events):
                px, py = self.time_to_x(p.time), self.value_to_y(p.value)
                if QRect(int(px)-8, int(py)-8, 16, 16).contains(pos.toPoint()):
                    self.pitch_events.pop(i)
                    self.pitch_data_changed.emit(self.pitch_events)
                    break
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()
        if event.buttons() & Qt.LeftButton and self.editing_point_index is not None:
            # ドラッグ移動（時間と値の両方を更新可能にする）
            new_time = self.x_to_time(pos.x())
            new_val = self.y_to_value(pos.y())
            
            p = self.pitch_events[self.editing_point_index]
            p.time = max(0, new_time)
            p.value = new_val
            
            # 再ソートが必要になる可能性があるが、ドラッグ中はインデックスが狂うので注意
            self.pitch_data_changed.emit(self.pitch_events)
        
        # ホバー状態の更新
        self.hover_point_index = None
        for i, p in enumerate(self.pitch_events):
            px, py = self.time_to_x(p.time), self.value_to_y(p.value)
            if QRect(int(px)-8, int(py)-8, 16, 16).contains(pos.toPoint()):
                self.hover_point_index = i
                break
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 背景
        w, h = self.width(), self.height()
        painter.fillRect(self.rect(), QColor(25, 25, 25))

        # センターライン
        painter.setPen(QPen(QColor(70, 70, 70), 1, Qt.DashLine))
        painter.drawLine(0, h/2, w, h/2)

        # データの描画
        if len(self.pitch_events) >= 2:
            painter.setPen(QPen(QColor(0, 255, 127), 2))
            points = [QPointF(self.time_to_x(p.time), self.value_to_y(p.value)) for p in self.pitch_events]
            for i in range(len(points) - 1):
                painter.drawLine(points[i], points[i+1])

        for i, p in enumerate(self.pitch_events):
            px, py = self.time_to_x(p.time), self.value_to_y(p.value)
            color = QColor(255, 255, 255) if i == self.hover_point_index else QColor(0, 255, 127)
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(px, py), 5, 5)
                            
　

    
