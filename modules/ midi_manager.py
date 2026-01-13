# midi_manager.py

import mido
import threading
from PySide6.QtCore import Signal, QObject
from data_models import NoteEvent 

class MidiSignals(QObject):
    midi_event_signal = Signal(int, int, str)
    midi_event_record_signal = Signal(int, int, str, float) 
        def __init__(self, callback):
        self.callback = callback # 音を鳴らすための関数
        self.input_port = None

    def start_listening(self):
        # 利用可能なMIDIポートを探して開く
        ports = mido.get_input_names()
        if ports:
            self.input_port = mido.open_input(ports[0], callback=self.on_message)
            print(f"VO-SE: MIDI入力開始 -> {ports[0]}")

    def on_message(self, msg):
        if msg.type == 'note_on' and msg.velocity > 0:
            # 鍵盤が押されたらピッチをエンジンに送る
            self.callback(msg.note, True)
        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            # 鍵盤が離されたら音を止める
            self.callback(msg.note, False)

midi_signals = MidiSignals()


def load_midi_file(filepath):
    try:
        mid = mido.MidiFile(filepath)
        notes = []
        for track in mid.tracks:
            current_time = 0
            open_notes = {}
            for msg in track:
                current_time += msg.time 
                if msg.type == 'note_on' and msg.velocity > 0:
                    open_notes[msg.note] = current_time
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    if msg.note in open_notes:
                        start = open_notes.pop(msg.note)
                        duration = current_time - start
                        if duration > 0:
                            notes.append(NoteEvent(msg.note, start, duration, msg.velocity))
        return [n.to_dict() for n in notes]
    except Exception as e:
        print(f"MIDIファイルの読み込みに失敗しました: {e}")
        return None

class MidiInputManager:
    def __init__(self, port_name=None):
        self.port_name = port_name
        self.port = None

    @staticmethod
    def get_available_ports():
        try:
            names = mido.get_input_names()
            return names if names else None
        except Exception as e:
            print(f"MIDIポートの取得中にエラー: {e}")
            return None

    def start(self):
        if not self.port_name:
            return
        try:
            self.port = mido.open_input(self.port_name, callback=self.midi_callback)
            print(f"MIDIポートをリッスン中: {self.port_name}")
        except ValueError as e:
            print(f"MIDIポート {self.port_name} を開けません: {e}")

    def stop(self):
        if self.port:
            self.port.close()
            print("MIDIポートを閉じました。")

    def midi_callback(self, message):
        import time
        timestamp = time.time()
        if message.type == 'note_on' and message.velocity > 0:
            midi_signals.midi_event_signal.emit(message.note, message.velocity, 'on')
            midi_signals.midi_event_record_signal.emit(message.note, message.velocity, 'on', timestamp)
        elif message.type == 'note_off' or (message.type == 'note_on' and message.velocity == 0):
            midi_signals.midi_event_signal.emit(message.note, message.velocity, 'off')
            midi_signals.midi_event_record_signal.emit(message.note, message.velocity, 'off', timestamp)
