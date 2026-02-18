#graph_editor_widget.py


from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, Slot, QRect, QPointF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QPaintEvent, QMouseEvent
from modules.data.data_models import PitchEvent

class GraphEditorWidget(QWidget):
    parameters_changed = Signal(dict) 

    PITCH_MAX = 8191
    PITCH_MIN = -8192

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setMouseTracking(True)
        
        self.scroll_x_offset = 0
        self.pixels_per_beat = 40.0
        self.tempo = 120.0
        
        self.all_parameters = {
            "Pitch": [],
            "Gender": [],
            "Tension": [],
            "Breath": []
        }
        
        self.current_mode = "Pitch"
        self.colors = {
            "Pitch": QColor(0, 255, 127),
            "Gender": QColor(231, 76, 60),
            "Tension": QColor(46, 204, 113),
            "Breath": QColor(241, 196, 15)
        }

        self.editing_point_index = None
        self.hover_point_index = None

    @Slot(str)
    def set_mode(self, mode):
        if mode in self.all_parameters:
            self.current_mode = mode
            self.editing_point_index = None
            self.update()

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

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        # Qt.LeftButton -> Qt.MouseButton.LeftButton
        if event.button() == Qt.MouseButton.LeftButton:
            time = self.x_to_time(event.position().x())
            val = self.y_to_value(event.position().y())
            new_point = PitchEvent(time=time, value=int(round(val)))
            self.all_parameters[self.current_mode].append(new_point)
            self.all_parameters[self.current_mode].sort(key=lambda x: x.time)
            self.parameters_changed.emit(self.all_parameters)
            self.update()

    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position()
        events = self.all_parameters[self.current_mode]
        # Qt.LeftButton -> Qt.MouseButton.LeftButton
        if event.button() == Qt.MouseButton.LeftButton:
            self.editing_point_index = None
            for i, p in enumerate(events):
                px, py = self.time_to_x(p.time), self.value_to_y(p.value)
                if QRect(int(px)-8, int(py)-8, 16, 16).contains(pos.toPoint()):
                    self.editing_point_index = i
                    break
        # Qt.RightButton -> Qt.MouseButton.RightButton
        elif event.button() == Qt.MouseButton.RightButton:
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
        
        # event.buttons() & Qt.LeftButton -> Qt.MouseButton.LeftButton
        if event.buttons() & Qt.MouseButton.LeftButton and self.editing_point_index is not None:
            p = events[self.editing_point_index]
            p.time = max(0, self.x_to_time(pos.x()))
            p.value = self.y_to_value(pos.y())
            self.parameters_changed.emit(self.all_parameters)
        
        self.hover_point_index = None
        for i, p in enumerate(events):
            px, py = self.time_to_x(p.time), self.value_to_y(p.value)
            if QRect(int(px)-8, int(py)-8, 16, 16).contains(pos.toPoint()):
                self.hover_point_index = i
                break
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.editing_point_index is not None:
            self.all_parameters[self.current_mode].sort(key=lambda x: x.time)
            self.editing_point_index = None
            self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        # QPainter.Antialiasing -> QPainter.RenderHint.Antialiasing
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        painter.fillRect(self.rect(), QColor(25, 25, 25))

        h = self.height()
        if self.current_mode == "Pitch":
            # Qt.DashLine -> Qt.PenStyle.DashLine
            painter.setPen(QPen(QColor(70, 70, 70), 1, Qt.PenStyle.DashLine))
            # 座標を int にキャストして型エラー回避
            painter.drawLine(0, int(h/2), self.width(), int(h/2))

        for mode, events in self.all_parameters.items():
            if mode == self.current_mode:
                continue
            if not events:
                continue
            color = self.colors[mode]
            color.setAlpha(40)
            painter.setPen(QPen(color, 1))
            points = [QPointF(self.time_to_x(p.time), self.value_to_y_for_mode(p.value, mode)) for p in events]
            for i in range(len(points) - 1):
                painter.drawLine(points[i], points[i+1])

        events = self.all_parameters[self.current_mode]
        color = self.colors[self.current_mode]
        
        if len(events) >= 2:
            painter.setPen(QPen(color, 2))
            points = [QPointF(self.time_to_x(p.time), self.value_to_y(p.value)) for p in events]
            for i in range(len(points) - 1):
                painter.drawLine(points[i], points[i+1])

        for i, p in enumerate(events):
            px, py = self.time_to_x(p.time), self.value_to_y(p.value)
            dot_color = QColor(255, 255, 255) if i == self.hover_point_index else color
            painter.setBrush(QBrush(dot_color))
            # Qt.NoPen -> Qt.PenStyle.NoPen
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(px, py), 5, 5)

    def value_to_y_for_mode(self, value: float, mode: str) -> float:
        h = self.height()
        if mode == "Pitch":
            center_y = h / 2
            return center_y - (value / self.PITCH_MAX) * (center_y * 0.8)
        else:
            return h - (value * (h * 0.8) + (h * 0.1))
