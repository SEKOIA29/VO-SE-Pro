from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, Slot, QSize, QRect, QPoint
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QPaintEvent, QMouseEvent
from data_models import PitchEvent # PitchEventをインポート

class GraphEditorWidget(QWidget):
    # ピッチデータが変更されたことをMainWindowに通知するシグナル
    pitch_data_changed = Signal(list) 

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(100)
        self.scroll_x_offset = 0
        self.pixels_per_beat = 40.0 # TimelineWidgetと同期させる
        self._current_playback_time = 0.0
        self.pitch_events: list[PitchEvent] = [] # ここにPitchEventのリストが格納される
        self.editing_point_index = None # ドラッグ中の点のインデックス
        self.drag_start_pos = None
        self.drag_start_value = None
        self.tempo = 120.0 # MainWindowから同期させる必要がある

    @Slot(int)
    def set_scroll_x_offset(self, offset_pixels: int):
        self.scroll_x_offset = offset_pixels
        self.update()

    @Slot(float)
    def set_pixels_per_beat(self, pixels_per_beat: float):
        self.pixels_per_beat = pixels_per_beat
        self.update()
        
    @Slot(float)
    def set_current_time(self, time_in_seconds: float):
        self._current_playback_time = time_in_seconds
        self.update()

    def set_pitch_events(self, events: list[PitchEvent]):
        self.pitch_events = events
        self.update()

    def seconds_to_beats(self, seconds: float, tempo=120.0) -> float:
        seconds_per_beat = 60.0 / tempo
        return seconds / seconds_per_beat

    def quantize_value(self, value, resolution):
        if resolution <= 0: return value
        return round(value / resolution) * resolution

    # --- マウスイベント処理 ---
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            clicked_point = event.position().toPoint()
            self.editing_point_index = None
            
            for i, p in enumerate(self.pitch_events):
                x = (self.seconds_to_beats(p.time, self.tempo) * self.pixels_per_beat) - self.scroll_x_offset
                y = self.value_to_y(p.value, self.height())
                
                # クリック範囲を広めにとる
                if QRect(int(x)-5, int(y)-5, 10, 10).contains(clicked_point):
                    self.editing_point_index = i
                    self.drag_start_pos = clicked_point
                    self.drag_start_value = p.value
                    break

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.LeftButton and self.editing_point_index is not None:
            delta_y = event.position().y() - self.drag_start_pos.y()
            
            widget_height = self.height()
            center_y = widget_height / 2
            max_midi_pitch_value = 8191.0
            
            value_delta = - (delta_y / (center_y * 0.9)) * max_midi_pitch_value
            new_value = self.drag_start_value + value_delta
            
            clamped_value = max(-8192, min(8191, int(new_value)))
            
            self.pitch_events[self.editing_point_index].value = clamped_value
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self.editing_point_index is not None:
            # ドラッグ終了時に時間でソートし直す
            self.pitch_events.sort(key=lambda p: p.time)
            self.pitch_data_changed.emit(self.pitch_events)
            self.editing_point_index = None
            self.drag_start_pos = None
            self.drag_start_value = None
            self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            click_point = event.position().toPoint()
            
            # 既存のポイント削除判定
            for i, p in enumerate(self.pitch_events):
                x = (self.seconds_to_beats(p.time, self.tempo) * self.pixels_per_beat) - self.scroll_x_offset
                y = self.value_to_y(p.value, self.height())
                if QRect(int(x)-5, int(y)-5, 10, 10).contains(click_point):
                    self.pitch_events.pop(i)
                    self.pitch_events.sort(key=lambda p: p.time)
                    self.pitch_data_changed.emit(self.pitch_events)
                    self.update()
                    return # 削除したら新規作成は行わない

            # 新規ポイント作成
            absolute_x_pixel = click_point.x() + self.scroll_x_offset
            clicked_beats = absolute_x_pixel / self.pixels_per_beat
            quantized_beats = self.quantize_value(clicked_beats, 0.25)
            
            new_time = (quantized_beats * 60.0) / self.tempo
            
            widget_height = self.height()
            center_y = widget_height / 2
            max_midi_pitch_value = 8191.0
            click_y = event.position().y()
            value_at_click = -((click_y - center_y) / (center_y * 0.9)) * max_midi_pitch_value
            clamped_value_at_click = max(-8192, min(8191, int(value_at_click)))

            new_pitch_event = PitchEvent(time=new_time, value=clamped_value_at_click) 
            self.pitch_events.append(new_pitch_event)
            self.pitch_events.sort(key=lambda p: p.time)
            self.pitch_data_changed.emit(self.pitch_events)
            self.update()

    # ヘルパー関数: ピッチ値をY座標にマッピング
    def value_to_y(self, value: int, widget_height: int) -> float:
        center_y = widget_height / 2
        max_midi_pitch_value = 8191.0
        # 90%の範囲に収めるように調整
        y = center_y - (value / max_midi_pitch_value) * (center_y * 0.9) 
        return y
    
    # paintEvent メソッド
    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(event.rect(), QColor(50, 50, 50))

        widget_height = self.height()
        center_y = widget_height / 2
        
        # 中央の基準線を描画
        painter.setPen(QPen(QColor(100, 100, 100), 1, Qt.DashLine))
        painter.drawLine(0, int(center_y), self.width(), int(center_y))

        if self.pitch_events:
            painter.setPen(QPen(QColor(0, 150, 255), 2))
            max_midi_pitch_value = 8191.0
            
            # 線を描画
            for i in range(1, len(self.pitch_events)):
                p1 = self.pitch_events[i-1]
                p2 = self.pitch_events[i]
                
                x1 = (self.seconds_to_beats(p1.time, self.tempo) * self.pixels_per_beat) - self.scroll_x_offset
                x2 = (self.seconds_to_beats(p2.time, self.tempo) * self.pixels_per_beat) - self.scroll_x_offset
                
                y1 = self.value_to_y(p1.value, widget_height)
                y2 = self.value_to_y(p2.value, widget_height)

                painter.drawLine(int(x1), int(y1), int(x2), int(y2))

            # ポイント（点）を描画
            for i, p in enumerate(self.pitch_events):
                x = (self.seconds_to_beats(p.time, self.tempo) * self.pixels_per_beat) - self.scroll_x_offset
                y = self.value_to_y(p.value, widget_height)

                if i == self.editing_point_index:
                     painter.setBrush(QBrush(QColor(255, 255, 0))) # 選択中は黄色
                else:
                    painter.setBrush(QBrush(QColor(0, 150, 255)))
                
                # 点の境界線
                painter.setPen(QPen(Qt.black, 1))
                painter.drawEllipse(int(x)-4, int(y)-4, 8, 8)

        # 再生カーソルを描画
        playback_beats = self.seconds_to_beats(self._current_playback_time)
        cursor_x = (playback_beats * self.pixels_per_beat) - self.scroll_x_offset
        if cursor_x >= 0 and cursor_x <= self.width():
            painter.setPen(QPen(QColor(255, 50, 50), 2))
            painter.drawLine(int(cursor_x), 0, int(cursor_x), self.height())
