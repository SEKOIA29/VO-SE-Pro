#graph_editor_widget.py

import numpy as np
from PySide6.QtWidgets import QWidget, QMessageBox
from PySide6.QtCore import Qt, Signal, Slot, QRect, QPoint, QPointF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QPaintEvent, QMouseEvent
from .data_models import PitchEvent

class GraphEditorWidget(QWidget):
    pitch_data_changed = Signal(dict) # 全パラメーターを辞書で送るように変更

    PITCH_MAX = 8191
    PITCH_MIN = -8192

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setMouseTracking(True)
        
        self.scroll_x_offset = 0
        self.pixels_per_beat = 40.0
        self.tempo = 120.0
        
        # 1. 全パラメーターの器（Pitch以外も PitchEvent クラスを流用可能）
        self.all_parameters = {
            "Pitch": [],
            "Gender": [],
            "Tension": [],
            "Breath": []
        }
        
        self.current_mode = "Pitch"
        self.colors = {
            "Pitch": QColor(0, 255, 127),    # 春の緑
            "Gender": QColor(231, 76, 60),   # 赤
            "Tension": QColor(46, 204, 113),  # 緑
            "Breath": QColor(241, 196, 15)    # 黄
        }

        self.editing_point_index = None
        self.hover_point_index = None

    @Slot(str)
    def set_mode(self, mode):
        """モードを切り替える（MainWindowから呼ばれる）"""
        if mode in self.all_parameters:
            self.current_mode = mode
            self.editing_point_index = None # モード切替時に編集状態をリセット
            self.update()

    # --- 座標変換ロジック ---
    def time_to_x(self, seconds: float) -> float:
        beats = (seconds * self.tempo) / 60.0
        return (beats * self.pixels_per_beat) - self.scroll_x_offset

    def x_to_time(self, x: float) -> float:
        absolute_x = x + self.scroll_x_offset
        beats = absolute_x / self.pixels_per_beat
        return (beats * 60.0) / self.tempo

    def value_to_y(self, value: float) -> float:
        h = self.height()
        center_y = h / 2
        # Pitchモードなら中央基準、それ以外は下端(0.0)〜上端(1.0)として計算
        if self.current_mode == "Pitch":
            range_y = center_y * 0.8
            return center_y - (value / self.PITCH_MAX) * range_y
        else:
            # 0.0〜1.0 の範囲を画面の高さにマップ (値が大きいほど上=Yが小さい)
            return h - (value * (h * 0.8) + (h * 0.1))

    def y_to_value(self, y: float) -> float:
        h = self.height()
        if self.current_mode == "Pitch":
            center_y = h / 2
            range_y = center_y * 0.8
            val = -((y - center_y) / range_y) * self.PITCH_MAX
            return int(max(self.PITCH_MIN, min(self.PITCH_MAX, val)))
        else:
            # 0.0〜1.0に変換
            val = (h - y - (h * 0.1)) / (h * 0.8)
            return max(0.0, min(1.0, val))

    # --- イベント処理 ---
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            time = self.x_to_time(event.position().x())
            val = self.y_to_value(event.position().y())
            new_point = PitchEvent(time=time, value=val)
            self.all_parameters[self.current_mode].append(new_point)
            self.all_parameters[self.current_mode].sort(key=lambda x: x.time)
            self.update()

    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position()
        events = self.all_parameters[self.current_mode]
        if event.button() == Qt.LeftButton:
            self.editing_point_index = None
            for i, p in enumerate(events):
                px, py = self.time_to_x(p.time), self.value_to_y(p.value)
                if QRect(int(px)-8, int(py)-8, 16, 16).contains(pos.toPoint()):
                    self.editing_point_index = i
                    break
        elif event.button() == Qt.RightButton:
            for i, p in enumerate(events):
                px, py = self.time_to_x(p.time), self.value_to_y(p.value)
                if QRect(int(px)-8, int(py)-8, 16, 16).contains(pos.toPoint()):
                    events.pop(i)
                    break
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()
        events = self.all_parameters[self.current_mode]
        
        # ドラッグ移動
        if event.buttons() & Qt.LeftButton and self.editing_point_index is not None:
            p = events[self.editing_point_index]
            p.time = max(0, self.x_to_time(pos.x()))
            p.value = self.y_to_value(pos.y())
            # ソートが必要な場合は移動終了後に行うのが安全
        
        # ホバー判定
        self.hover_point_index = None
        for i, p in enumerate(events):
            px, py = self.time_to_x(p.time), self.value_to_y(p.value)
            if QRect(int(px)-8, int(py)-8, 16, 16).contains(pos.toPoint()):
                self.hover_point_index = i
                break
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 背景
        painter.fillRect(self.rect(), QColor(25, 25, 25))

        # モードに応じたグリッド表示
        h = self.height()
        if self.current_mode == "Pitch":
            painter.setPen(QPen(QColor(70, 70, 70), 1, Qt.DashLine))
            painter.drawLine(0, h/2, self.width(), h/2) # センターライン

        # 現在のモードのデータを描画
        events = self.all_parameters[self.current_mode]
        color = self.colors.get(self.current_mode, QColor(255, 255, 255))
        
        if len(events) >= 2:
            painter.setPen(QPen(color, 2))
            for i in range(len(events) - 1):
                p1 = QPointF(self.time_to_x(events[i].time), self.value_to_y(events[i].value))
                p2 = QPointF(self.time_to_x(events[i+1].time), self.value_to_y(events[i+1].value))
                painter.drawLine(p1, p2)

        # 点の描画
        for i, p in enumerate(events):
            px, py = self.time_to_x(p.time), self.value_to_y(p.value)
            dot_color = QColor(255, 255, 255) if i == self.hover_point_index else color
            painter.setBrush(QBrush(dot_color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(px, py), 5, 5)
