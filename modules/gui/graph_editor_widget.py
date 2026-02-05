#graph_editor_widget.py


from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, Slot, QRect, QPointF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QPaintEvent, QMouseEvent
from .data_models import PitchEvent

class GraphEditorWidget(QWidget):
    # パラメーターが変更されたことを外部（エンジン等）に通知するシグナル
    # 全データ辞書を渡すように拡張
    parameters_changed = Signal(dict) 

    PITCH_MAX = 8191
    PITCH_MIN = -8192

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setMouseTracking(True)
        
        # 描画・スクロール用設定
        self.scroll_x_offset = 0
        self.pixels_per_beat = 40.0
        self.tempo = 120.0
        
        # --- 多重パラメーター構造 ---
        self.all_parameters = {
            "Pitch": [],
            "Gender": [],
            "Tension": [],
            "Breath": []
        }
        
        self.current_mode = "Pitch"
        self.colors = {
            "Pitch": QColor(0, 255, 127),    # 緑
            "Gender": QColor(231, 76, 60),   # 赤
            "Tension": QColor(46, 204, 113),  # 濃い緑
            "Breath": QColor(241, 196, 15)    # 黄
        }

        # 編集状態管理
        self.editing_point_index = None
        self.hover_point_index = None

    @Slot(str)
    def set_mode(self, mode):
        """MainWindowからモードを切り替える"""
        if mode in self.all_parameters:
            self.current_mode = mode
            self.editing_point_index = None
            self.update()

    # --- 座標変換ロジック (Pitchとその他でY軸計算を分岐) ---
    def time_to_x(self, seconds: float) -> float:
        beats = (seconds * self.tempo) / 60.0
        return (beats * self.pixels_per_beat) - self.scroll_x_offset

    def x_to_time(self, x: float) -> float:
        absolute_x = x + self.scroll_x_offset
        beats = absolute_x / self.pixels_per_beat
        return (beats * 60.0) / self.tempo

    def value_to_y(self, value: float) -> float:
        h = self.height()
        if self.current_mode == "Pitch":
            center_y = h / 2
            range_y = center_y * 0.8
            return center_y - (value / self.PITCH_MAX) * range_y
        else:
            # 0.0〜1.0 の範囲を画面 10%〜90% の高さにマップ
            return h - (value * (h * 0.8) + (h * 0.1))

    def y_to_value(self, y: float) -> float:
        h = self.height()
        if self.current_mode == "Pitch":
            center_y = h / 2
            range_y = center_y * 0.8
            val = -((y - center_y) / range_y) * self.PITCH_MAX
            return int(max(self.PITCH_MIN, min(self.PITCH_MAX, val)))
        else:
            val = (h - y - (h * 0.1)) / (h * 0.8)
            return max(0.0, min(1.0, val))

    # --- マウスイベント (全機能統合) ---
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """ダブルクリックで新しい点を追加"""
        if event.button() == Qt.LeftButton:
            time = self.x_to_time(event.position().x())
            val = self.y_to_value(event.position().y())
            new_point = PitchEvent(time=time, value=val)
            self.all_parameters[self.current_mode].append(new_point)
            self.all_parameters[self.current_mode].sort(key=lambda x: x.time)
            self.parameters_changed.emit(self.all_parameters)
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
                    self.parameters_changed.emit(self.all_parameters)
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
            # リアルタイムで外部に通知（再生中の音色変化などに必要）
            self.parameters_changed.emit(self.all_parameters)
        
        # ホバー判定
        self.hover_point_index = None
        for i, p in enumerate(events):
            px, py = self.time_to_x(p.time), self.value_to_y(p.value)
            if QRect(int(px)-8, int(py)-8, 16, 16).contains(pos.toPoint()):
                self.hover_point_index = i
                break
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """ドラッグ終了時に再ソート"""
        if self.editing_point_index is not None:
            self.all_parameters[self.current_mode].sort(key=lambda x: x.time)
            self.editing_point_index = None
            self.update()

    # --- 描画ロジック ---
    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 背景
        painter.fillRect(self.rect(), QColor(25, 25, 25))

        # モードに応じたガイドライン
        h = self.height()
        if self.current_mode == "Pitch":
            painter.setPen(QPen(QColor(70, 70, 70), 1, Qt.DashLine))
            painter.drawLine(0, h/2, self.width(), h/2) # センター

        # 1. (オプション) 他のパラメーターを薄くガイド表示
        for mode, events in self.all_parameters.items():
            if mode == self.current_mode:
                continue
            if not events:
                continue
            color = self.colors[mode]
            color.setAlpha(40) # 非常に薄く
            painter.setPen(QPen(color, 1))
            points = [QPointF(self.time_to_x(p.time), self.value_to_y_for_mode(p.value, mode)) for p in events]
            for i in range(len(points) - 1):
                painter.drawLine(points[i], points[i+1])

        # 2. 現在のモードの描画
        events = self.all_parameters[self.current_mode]
        color = self.colors[self.current_mode]
        
        if len(events) >= 2:
            painter.setPen(QPen(color, 2))
            points = [QPointF(self.time_to_x(p.time), self.value_to_y(p.value)) for p in events]
            for i in range(len(points) - 1):
                painter.drawLine(points[i], points[i+1])

        # 3. 点の描画
        for i, p in enumerate(events):
            px, py = self.time_to_x(p.time), self.value_to_y(p.value)
            dot_color = QColor(255, 255, 255) if i == self.hover_point_index else color
            painter.setBrush(QBrush(dot_color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(px, py), 5, 5)

    def value_to_y_for_mode(self, value: float, mode: str) -> float:
        """ガイド描画用にモードを指定してY座標を計算"""
        h = self.height()
        if mode == "Pitch":
            center_y = h / 2
            return center_y - (value / self.PITCH_MAX) * (center_y * 0.8)
        else:
            return h - (value * (h * 0.8) + (h * 0.1))
