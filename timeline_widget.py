import json
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, Slot, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtGui import QWheelEvent

from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QWidget, QApplication, QInputDialog, QLineEdit
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal
from data_models import NoteEvent
from janome.tokenizer import Tokenizer
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QMouseEvent, QPaintEvent
from PySide6.QtGui import QMouseEvent, QPaintEvent, QPainter
from PySide6.QtGui import QKeyEvent
from PySide6.QtGui import QWheelEvent
from PySide6.QtGui import QClipboard
from PySide6.QtGui import QPen, QBrush, QColor
from PySide6.QtGui import QMouseEvent, QPaintEvent, QPainter
from PySide6.QtCore import QRect, Qt, Signal, Slot




class TimelineWidget(QWidget):
    zoom_changed_signal = Signal()
    vertical_zoom_changed_signal = Signal()
    notes_changed_signal = Signal()
 
    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = VoSeEngineWrapper()
        self.pixels_per_second = 100
        self.note_height = 20  # 1音階の高さ
        self.base_midi = 84    # 上端の音程(C5)
        self.notes = []

    def y_to_midi(self, y):
        return self.base_midi - (y // self.note_height)

    def mousePressEvent(self, event):
# A. まず音程プレビュー
        midi_note = self.y_to_midi(event.position().y())
        self.engine.set_pitch(midi_note)
        self.engine.play_preview() 
        
        # B. 線のドラッグ判定
        drag_triggered = False
        for note in self.notes_list:
            if not getattr(note, 'has_analysis', False): continue
            
            onset_x = self.get_x_from_time(note.start_time + note.onset)
            if abs(event.position().x() - onset_x) < 7: # 少し判定を広めに(7px)
                self.dragging_note = note
                self.drag_mode = "ONSET"
                drag_triggered = True
                break # ターゲットが見つかったらループ終了
        
        # C. 線を掴んでいない時だけ、通常の選択・移動処理へ
        if not drag_triggered:
            super().mousePressEvent(event)
        
        self.update()

    def mouseMoveEvent(self, event):
        if hasattr(self, 'dragging_note') and self.dragging_note:
            # マウスの位置を時間(秒)に変換
            new_time = self.get_time_from_x(event.x())
            
            if self.drag_mode == "ONSET":
                # Onsetの値を更新（相対値として保存）
                self.dragging_note.onset = new_time - self.dragging_note.start_time
            
            self.update() # リアルタイム描画更新
            return
            
        super().mouseMoveEvent(event)


    def set_notes(self, new_notes):
        """外部からノートリストを更新し、再描画をかける"""
        self.notes_list = new_notes
        self.update() # これで paintEvent が走り、AIの解析線が描画される

    def paintEvent(self, event):
        painter = QPainter(self)
        # 背景（ピアノロール風の横線）
        self._draw_piano_roll_grid(painter)
        
　　　　　# 2. 各ノートと解析線の描画
        for note in self.notes_list: # notes -> notes_list に合わせる
            # ノートの位置計算
            x = int(note.start_time * self.pixels_per_second)
            y = self.midi_to_y(note.note_number) # pitch -> note_number に合わせる
            width = int(note.duration * self.pixels_per_second)
            
            # --- ノート本体の描画 ---
            rect = QRect(x, y, width, self.note_height)
            painter.setBrush(QColor(150, 200, 255, 200)) # 少し透明に
            painter.setPen(QPen(Qt.black, 1))
            painter.drawRect(rect)
            
            # 歌詞の表示
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, note.lyric)

            # --- AI解析線（Onset）の描画 ---
            if hasattr(note, 'has_analysis') and note.has_analysis:
                # onsetは相対値なので start_time を足す
                onset_x = int((note.start_time + note.onset) * self.pixels_per_second)
                
                # 赤い太めの線で描画（これがマウスで動かせる線）
                painter.setPen(QPen(QColor(255, 50, 50), 2))
                painter.drawLine(onset_x, y, onset_x, y + self.note_height)
                
                # Pre-utterance（先行発声）も薄く青い点線で出すとよりプロっぽい
                pre_x = int((note.start_time - note.pre_utterance) * self.pixels_per_second)
                painter.setPen(QPen(QColor(50, 50, 255), 1, Qt.PenStyle.DashLine))
                painter.drawLine(pre_x, y, pre_x, y + self.note_height)

    def _draw_piano_roll_grid(self, painter):
　　　　　　# 背景の横線
        painter.setPen(QPen(QColor(230, 230, 230), 1))
        for i in range(0, self.height(), self.note_height):
            painter.drawLine(0, i, self.width(), i)
        
        # 小節線（垂直線）も少し入れるとリズムがわかりやすい
        painter.setPen(QPen(QColor(210, 210, 210), 1))
        beat_width = self.pixels_per_second * (60.0 / self.tempo)
        for i in range(0, self.width(), int(beat_width * 4)): # 4拍ごと
            painter.drawLine(i, 0, i, self.height())

    def mouseReleaseEvent(self, event):
        # クリックした位置から音程を特定
        midi_note = self.y_to_midi(int(event.position().y()))
        print(f"選択された音程: MIDI {midi_note}")
        
        # 【重要】ここでC言語エンジンへ音程変更を通知する
        # self.engine.set_pitch(midi_note) 
        # self.engine.render_preview()
    
        self.dragging_note = None
        self.drag_mode = None
        super().mouseReleaseEvent(event)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 200)
        self.setFocusPolicy(Qt.StrongFocus)
        self.selection_start_pos = None
        self.selection_end_pos = None
        self.notes_list: list[NoteEvent] = []
 
        self.pixels_per_beat = 40.0
        self.key_height_pixels = 12.0
        self.lowest_note_display = 24
        self.scroll_x_offset = 0  
        self.scroll_y_offset = 0
        self.tempo = 120
        self._current_playback_time = 0.0
        
        self.edit_mode = None
        self.drag_start_pos = None
        self.drag_start_note_pos = None
        self.target_note = None
        self.is_additive_selection_mode = False
        
        self.quantize_resolution = 0.25
 
        self.is_recording = False
        self.recording_start_system_time = 0.0
        self.open_recorded_notes = {}
        self.tokenizer = Tokenizer() 

def add_note_from_midi(self, pitch):
    # 現在の再生カーソルの位置に、弾いた音の高さでノートを置く
    new_note = NoteEvent(
        lyric="あ", # 初期値
        start_time=self.current_cursor_time,
        duration=0.5, # 標準的な長さ
        pitch_start=pitch
    )
    self.notes.append(new_note)
    self.update() # 画面を更新してノートを表示


    #---  ---

    def _get_yomi_from_lyrics(self, lyrics: str) -> list[str]:
        tokens = self.tokenizer.tokenize(lyrics)
        yomi_list = []
        for token in tokens:
            # janomeの feature には '読み' が含まれている
            yomi = token.read
            if yomi:
                # カタカナ1文字ずつに分割してリストに追加
                yomi_list.extend(list(yomi))
        return yomi_list
 
    # --- SEKOIAとヘルパー関数の愉快な仲間達---
    def seconds_to_beats(self, seconds: float) -> float:
        seconds_per_beat = 60.0 / self.tempo
        return seconds / seconds_per_beat
 
    def beats_to_seconds(self, beats: float) -> float:
        seconds_per_beat = 60.0 / self.tempo
        return beats * seconds_per_beat
    
    def quantize_value(self, value, resolution):
        if resolution <= 0: return value
        return round(value / resolution) * resolution
 
    @Slot(int)
    def set_scroll_x_offset(self, offset_pixels: int):
        self.scroll_x_offset = offset_pixels
        self.update()
 
    @Slot(int)
    def set_scroll_y_offset(self, offset_pixels: int):
        self.scroll_y_offset = offset_pixels
        self.update()
 
    @Slot(float)
    def set_current_time(self, time_in_seconds: float):
        self._current_playback_time = time_in_seconds
        self.update()
 
    def set_notes(self, new_notes: list[NoteEvent]):
        self.notes_list = new_notes
        self.update()
        self.notes_changed_signal.emit()

    @Slot(int, int, str, float)
    def record_midi_event(self, note_number: int, velocity: int, event_type: str, timestamp: float):
        if not self.is_recording: return
        relative_time = timestamp - self.recording_start_system_time
        if event_type == 'on':
            self.open_recorded_notes[note_number] = relative_time
        elif event_type == 'off':
            if note_number in self.open_recorded_notes:
                start_time = self.open_recorded_notes.pop(note_number)
                duration = relative_time - start_time
                if duration > 0:
                    duration_beats = self.seconds_to_beats(duration)
                    quantized_duration = self.quantize_value(duration_beats, self.quantize_resolution)
                    if quantized_duration < 0.01: quantized_duration = 0.01
                    
                    new_note = NoteEvent(
                        note_number=note_number,
                        start_time=self.beats_to_seconds(self.quantize_value(self.seconds_to_beats(start_time), self.quantize_resolution)),
                        duration=self.beats_to_seconds(quantized_duration),
                        velocity=velocity,
                        lyrics="あ"
                    )
                    self.notes_list.append(new_note)
                    self.update()
                    self.notes_changed_signal.emit()
    
    def set_recording_state(self, state: bool, start_time: float):
        self.is_recording = state
        self.recording_start_system_time = start_time
        if not state: self.open_recorded_notes = {}
        self.update()
    
    def update_scrollbar_range_after_recording(self):
        pass

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        click_beat = (event.position().x() + self.scroll_x_offset) / self.pixels_per_beat
        quantized_beat = self.quantize_value(click_beat, self.quantize_resolution)
        start_time = self.beats_to_seconds(quantized_beat)

        click_y = event.position().y() + self.scroll_y_offset
        note_number = self.lowest_note_display + 1 - int(click_y / self.key_height_pixels)

        new_lyric, ok = QInputDialog.getText(self, "音符の作成", "歌詞を入力してください:", QLineEdit.Normal, "あ")
        
        if ok and new_lyric:
            yomi_list = self._get_yomi_from_lyrics(new_lyric)

            new_note = NoteEvent(
                note_number=note_number,
                start_time=start_time,
                duration=self.beats_to_seconds(self.quantize_resolution * 2),
                velocity=100,
                lyrics=new_lyric,
                phonemes=yomi_list 
            )
            self.notes_list.append(new_note)
            self.update()
            self.notes_changed_signal.emit()
            print(f"新しい音符を作成しました: {new_note}")

    def get_project_duration_and_start(self) -> tuple[float, float]:
        if not self.notes_list:
            return 0.0, 0.0
        
        start_times = [note.start_time for note in self.notes_list]
        end_times = [note.start_time + note.duration for note in self.notes_list]
        
        min_start = min(start_times) if start_times else 0.0
        max_end = max(end_times) if end_times else 0.0
        
        return max(0.0, min_start - 0.5), max_end + 0.5

    # --- (1) 描画処理: paintEvent ---
    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # 背景色を暗いグレーに変更
        painter.fillRect(event.rect(), QColor(30, 30, 30)) 
        
        if self.pixels_per_beat * 4 > 150:    display_res = 0.25
        elif self.pixels_per_beat * 2 > 100:  display_res = 0.5
        elif self.pixels_per_beat > 80:       display_res = 1.0
        else:                                 display_res = 4.0
 
        start_beat = self.scroll_x_offset / self.pixels_per_beat
        end_beat = start_beat + self.width() / self.pixels_per_beat
 
        i = 0
        while True:
            beat = i * display_res
            if beat > end_beat: break
 
            x = (beat * self.pixels_per_beat) - self.scroll_x_offset
            if x >= 0:
                if beat % 4.0 == 0:
                    painter.setPen(QPen(QColor(180, 180, 180), 2)) # 小節線
                elif beat % 1.0 == 0:
                    painter.setPen(QPen(QColor(100, 100, 100), 1)) # 拍線
                else:
                    painter.setPen(QPen(QColor(60, 60, 60), 1)) # 細線
                
                painter.drawLine(int(x), 0, int(x), self.height())
            i += 1
 
        for note in self.notes_list:
            start_x = (self.seconds_to_beats(note.start_time) * self.pixels_per_beat) - self.scroll_x_offset
            width = (self.seconds_to_beats(note.duration) * self.pixels_per_beat)
            y_pos = (self.lowest_note_display + 1 - note.note_number) * self.key_height_pixels - self.scroll_y_offset
            height = self.key_height_pixels
 
            if note.is_selected: 
                painter.setBrush(QBrush(QColor(0, 100, 255, 180))) # 選択色
            elif note.is_playing: 
                painter.setBrush(QBrush(QColor(255, 100, 100))) # 再生中色
            else: 
                painter.setBrush(QBrush(QColor(0, 150, 255))) # 通常色
            
            painter.setPen(Qt.NoPen)
            painter.drawRect(int(start_x), int(y_pos), int(width), int(height))
            
            if note.lyrics:
                painter.setPen(QColor(255, 255, 255)) # 白いテキスト
                text_rect = QRect(int(start_x + 2), int(y_pos), int(width - 4), int(height))
                painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.ElideRight, note.lyrics)
            
        playback_beats = self.seconds_to_beats(self._current_playback_time)
        cursor_x = (playback_beats * self.pixels_per_beat) - self.scroll_x_offset
        if cursor_x >= 0 and cursor_x <= self.width():
            painter.setPen(QPen(QColor(255, 50, 50), 2)) # 再生カーソル（赤）
            painter.drawLine(int(cursor_x), 0, int(cursor_x), self.height())
 
        if self.edit_mode == 'select_box' and self.selection_start_pos and self.selection_end_pos:
            selection_rect = QRect(self.selection_start_pos, self.selection_end_pos).normalized()
            painter.setPen(QPen(QColor(0, 0, 0), 1, Qt.DashLine))
            painter.setBrush(QColor(0, 100, 255, 80)) # 選択ボックス（半透明青）
            painter.drawRect(selection_rect)


    # --- (2) マウスイベント処理 ---
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.selection_start_pos = event.position().toPoint()
            self.selection_end_pos = None
            clicked_point = event.position().toPoint()
            self.edit_mode = None
            self.target_note = None
            self.is_additive_selection_mode = event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)
            clicked_on_note = False
            for note in self.notes_list:
                start_x = (self.seconds_to_beats(note.start_time) * self.pixels_per_beat) - self.scroll_x_offset
                width = (self.seconds_to_beats(note.duration) * self.pixels_per_beat)
                y_pos = (self.lowest_note_display + 1 - note.note_number) * self.key_height_pixels - self.scroll_y_offset
                height = self.key_height_pixels
                note_rect = QRect(int(start_x), int(y_pos), int(width), int(height))
                if note_rect.contains(clicked_point):
                    clicked_on_note = True
                    if self.is_additive_selection_mode: note.is_selected = not note.is_selected
                    else: note.is_selected = True
                    self.target_note = note
                    self.drag_start_pos = clicked_point
                    self.drag_start_note_pos = {'start': note.start_time, 'duration': note.duration, 'pitch': note.note_number}
                    self.edit_mode = 'resize' if abs(clicked_point.x() - (start_x + width)) < 5 else 'move'
                    break
            if not clicked_on_note:
                if not self.is_additive_selection_mode:
                    for note in self.notes_list: note.is_selected = False
                self.edit_mode = 'select_box'
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.LeftButton:
            if self.edit_mode == 'select_box': self.selection_end_pos = event.position().toPoint()
            elif self.edit_mode == 'move' and self.target_note:
                delta_x = event.position().x() - self.drag_start_pos.x()
                delta_y = event.position().y() - self.drag_start_pos.y()
                delta_beats = delta_x / self.pixels_per_beat
                delta_pitch = round(delta_y / self.key_height_pixels)
                self.target_note.start_time = self.beats_to_seconds(self.seconds_to_beats(self.drag_start_note_pos['start']) + delta_beats)
                self.target_note.note_number = self.drag_start_note_pos['pitch'] - delta_pitch
            elif self.edit_mode == 'resize' and self.target_note:
                delta_x = event.position().x() - self.drag_start_pos.x()
                delta_beats = delta_x / self.pixels_per_beat
                new_duration_beats = self.seconds_to_beats(self.drag_start_note_pos['duration']) + delta_beats
                if new_duration_beats > 0.01: self.target_note.duration = self.beats_to_seconds(new_duration_beats)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if self.edit_mode == 'select_box' and self.selection_start_pos and self.selection_end_pos:
                final_rect = QRect(self.selection_start_pos, self.selection_end_pos).normalized()
                for note in self.notes_list:
                    start_x = (self.seconds_to_beats(note.start_time) * self.pixels_per_beat) - self.scroll_x_offset
                    width = (self.seconds_to_beats(note.duration) * self.pixels_per_beat)
                    y_pos = (self.lowest_note_display + 1 - note.note_number) * self.key_height_pixels - self.scroll_y_offset
                    height = self.key_height_pixels
                    note_rect = QRect(int(start_x), int(y_pos), int(width), int(height))
                    if final_rect.intersects(note_rect):
                        note.is_selected = True
                    elif not self.is_additive_selection_mode:
                         note.is_selected = False
                self.selection_start_pos = None
                self.selection_end_pos = None
                self.update()
            
            if self.edit_mode in ('move', 'resize') and self.target_note:
                self.target_note.start_time = self.beats_to_seconds(
                    self.quantize_value(self.seconds_to_beats(self.target_note.start_time), self.quantize_resolution)
                )
                self.target_note.duration = self.beats_to_seconds(
                    self.quantize_value(self.seconds_to_beats(self.target_note.duration), self.quantize_resolution)
                )
                if self.target_note.duration < 0.01: self.target_note.duration = self.beats_to_seconds(0.01)

                self.notes_changed_signal.emit()
                self.update()

            self.edit_mode = None
            self.drag_start_pos = None
            self.drag_start_note_pos = None
            self.target_note = None

    # --- (3) キーボードイベント処理とアクション ---
    def keyPressEvent(self, event: QKeyEvent):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_C: self.copy_selected_notes_to_clipboard()
        elif event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_V: self.paste_notes_from_clipboard()
        elif event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace: self.delete_selected_notes()
        else: event.ignore(); super().keyPressEvent(event)

    def copy_selected_notes_to_clipboard(self):
        selected_list = [note for note in self.notes_list if note.is_selected]
        if not selected_list: return
        notes_data_dicts = [note.to_dict() for note in selected_list]
        clipboard_data_structure = {"app_id": "Vocaloid_Clone_App_12345", "type": "note_clip_data", "notes": notes_data_dicts}
        json_string = json.dumps(clipboard_data_structure, indent=2)
        clipboard: QClipboard = QApplication.clipboard(); clipboard.setText(json_string)
        print(f"選択された {len(selected_list)} 件の音符をクリップボードにコピーしました。")

    def paste_notes_from_clipboard(self):
        clipboard: QClipboard = QApplication.clipboard(); json_string = clipboard.text()
        if not json_string: return
        try:
            clipboard_data = json.loads(json_string)
            if clipboard_data.get("app_id") != "Vocaloid_Clone_App_12345": return
            pasted_notes_data = clipboard_data.get("notes", [])
            if not pasted_notes_data: return
            paste_start_time = self.get_current_playback_time()
            min_original_start = min(note_data['start'] for note_data in pasted_notes_data)
            time_offset = paste_start_time - min_original_start
            new_notes = []
            for note_data in pasted_notes_data:
                new_start_time = note_data['start'] + time_offset
                new_start_time_beats = self.seconds_to_beats(new_start_time)
                new_start_time = self.beats_to_seconds(self.quantize_value(new_start_time_beats, self.quantize_resolution))

                new_note = NoteEvent.from_dict(note_data)
                new_note.start_time = new_start_time
                new_note.is_selected = True
                new_notes.append(new_note)
            self.notes_list.extend(new_notes)
            self.update()
            self.notes_changed_signal.emit()
            print(f"クリップボードから {len(new_notes)} 件の音符をペーストしました。")
        except json.JSONDecodeError: print("JSONエラー")
        except Exception as e: print(f"ペーストエラー: {e}")

    def delete_selected_notes(self):
        count_before = len(self.notes_list)
        self.notes_list = [note for note in self.notes_list if not note.is_selected]
        count_after = len(self.notes_list)
        if count_after < count_before: 
            print(f"{count_before - count_after} 件の音符を削除しました。")
            self.update()
            self.notes_changed_signal.emit()

    def get_current_playback_time(self) -> float:
        return self._current_playback_time

    @Slot(int, str)
    def highlight_note(self, note_number: int, event_type: str):
        for note in self.notes_list:
            if note.note_number == note_number:
                if event_type == 'on': note.is_playing = True
                elif event_type == 'off': note.is_playing = False
        self.update()

    def get_max_beat_position(self) -> float:
        if not self.notes_list:
            return 0.0
        
        end_times_seconds = [note.start_time + note.duration for note in self.notes_list]
        max_end_time_seconds = max(end_times_seconds)
        
        max_end_beats = self.seconds_to_beats(max_end_time_seconds)
        return max_end_beats + 4.0

    def get_selected_notes_range(self) -> tuple[float, float]:
        selected_notes = [note for note in self.notes_list if note.is_selected]
        if not selected_notes:
            return self.get_project_duration_and_start()

        start_times = [note.start_time for note in selected_notes]
        end_times = [note.start_time + note.duration for note in selected_notes]
        
        min_start = min(start_times) if start_times else 0.0
        max_end = max(end_times) if end_times else 0.0
        
        return min_start, max_end

    

    def wheelEvent(self, event: QWheelEvent):
        """マウスホイールイベントを処理してズームまたは垂直スクロールを行う"""
        
        # Ctrlキーを押しながらホイールした場合、水平ズーム
        if event.modifiers() == Qt.ControlModifier:
            delta_beats = event.angleDelta().y() / 120.0
            zoom_factor = 1.1 if delta_beats > 0 else (1.0 / 1.1)
            
            # ズームの中心位置（ビート）を計算する
            mouse_x_pos = event.position().x()
            current_beat_at_mouse = (mouse_x_pos + self.scroll_x_offset) / self.pixels_per_beat
            
            self.pixels_per_beat *= zoom_factor
            
            # ズーム範囲の制限
            self.pixels_per_beat = max(10.0, min(200.0, self.pixels_per_beat))

            # ズームの中心を維持するようにスクロール位置を調整
            new_scroll_x_offset = (current_beat_at_mouse * self.pixels_per_beat) - mouse_x_pos
            self.scroll_x_offset = int(new_scroll_x_offset)
            
            # MainWindowにズーム変更を通知
            self.zoom_changed_signal.emit()
            self.update()
            
        # Shiftキーを押しながらホイールした場合、垂直ズーム（鍵盤の高さ）
        elif event.modifiers() == Qt.ShiftModifier:
            delta_pixels = event.angleDelta().y() / 120.0
            if delta_pixels > 0:
                self.key_height_pixels += 1.0
            else:
                self.key_height_pixels -= 1.0

            # 高さの範囲制限
            self.key_height_pixels = max(8.0, min(30.0, self.key_height_pixels))
            
            # MainWindowに垂直ズーム変更を通知
            self.vertical_zoom_changed_signal.emit()
            self.update()

        # 修飾キーなしの場合、デフォルトの垂直スクロール動作を維持
        else:
            event.ignore()
            # QWidgetのデフォルト動作を呼び出す
            # super().wheelEvent(event) # デフォルトのスクロールバー連携はMainWindowで行うため不要


