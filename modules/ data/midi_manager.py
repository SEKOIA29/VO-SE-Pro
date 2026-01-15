# midi_manager.py

import mido
import time
from PySide6.QtCore import Signal, QObject
from modules.data.data_models import NoteEvent 

class MidiSignals(QObject):
    """MIDIイベントをGUIやエンジンに橋渡しするシグナル"""
    # note, velocity, status ('on'/'off')
    midi_event_signal = Signal(int, int, str)
    # note, velocity, status, timestamp
    midi_event_record_signal = Signal(int, int, str, float)

# シングルトンとしてエクスポート
midi_signals = MidiSignals()

def load_midi_file(filepath):
    """MIDIファイルを読み込み、NoteEventのリスト（辞書形式）を返す"""
    try:
        mid = mido.MidiFile(filepath)
        notes = []
        
        # MIDI Ticks を秒に変換するための計算
        # デフォルトは 120bpm (500,000 microseconds per beat)
        ticks_per_beat = mid.ticks_per_beat
        
        for track in mid.tracks:
            current_tick = 0
            open_notes = {} # note_number -> (start_tick, velocity)
            
            for msg in track:
                current_tick += msg.time
                
                # Tickから秒への変換 (midoのツールを使用)
                # ※簡易化のため全編120bpm想定。厳密にはTempoMetaMessageを追う必要あり
                current_seconds = mido.tick2second(current_tick, ticks_per_beat, 500000)

                if msg.type == 'note_on' and msg.velocity > 0:
                    open_notes[msg.note] = (current_seconds, msg.velocity)
                
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    if msg.note in open_notes:
                        start_sec, velocity = open_notes.pop(msg.note)
                        duration = current_seconds - start_sec
                        
                        if duration > 0:
                            notes.append(NoteEvent(
                                note_number=msg.note,
                                start_time=start_sec,
                                duration=duration,
                                velocity=velocity
                            ))
        return [n.to_dict() for n in notes]
    except Exception as e:
        print(f"MIDIファイルの読み込みに失敗しました: {e}")
        return None

class MidiInputManager:
    """MIDIキーボードなどの外部機器入力を管理"""
    def __init__(self, port_name=None):
        self.port_name = port_name
        self.port = None

    @staticmethod
    def get_available_ports():
        return mido.get_input_names()

    def start(self):
        if not self.port_name:
            # ポートが指定されていない場合は最初のポートを自動選択
            ports = self.get_available_ports()
            if not ports:
                print("MIDIデバイスが見つかりません。")
                return
            self.port_name = ports[0]

        try:
            # midoのcallbackは別スレッドで動くため、GUI操作はシグナル経由で行う
            self.port = mido.open_input(self.port_name, callback=self.midi_callback)
            print(f"MIDI入力開始: {self.port_name}")
        except Exception as e:
            print(f"MIDIポートのオープンに失敗: {e}")

    def stop(self):
        if self.port:
            self.port.close()
            print("MIDIポートを閉じました。")

    def midi_callback(self, message):
        """外部MIDIメッセージ受信時の処理"""
        timestamp = time.time()
        if message.type == 'note_on' and message.velocity > 0:
            midi_signals.midi_event_signal.emit(message.note, message.velocity, 'on')
            midi_signals.midi_event_record_signal.emit(message.note, message.velocity, 'on', timestamp)
        elif message.type == 'note_off' or (message.type == 'note_on' and message.velocity == 0):
            midi_signals.midi_event_signal.emit(message.note, message.velocity, 'off')
            midi_signals.midi_event_record_signal.emit(message.note, message.velocity, 'off', timestamp)
