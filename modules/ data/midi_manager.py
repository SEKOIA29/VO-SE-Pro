# midi_manager.py

import mido
import mido.backends.rtmidi
import time
from typing import List, Optional, Dict, Any
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

def load_midi_file(filepath: str) -> Optional[List[Dict[str, Any]]]:
    """MIDIファイルを読み込み、NoteEventのリスト（辞書形式）を返す"""
    try:
        mid = mido.MidiFile(filepath)
        notes: List[NoteEvent] = []
        
        ticks_per_beat = mid.ticks_per_beat
        # デフォルトテンポ: 120bpm (500,000 microseconds per beat)
        current_tempo = 500000 
        
        for track in mid.tracks:
            current_tick = 0
            open_notes: Dict[int, tuple[float, int]] = {} # note_number -> (start_sec, velocity)
            
            for msg in track:
                current_tick += msg.time
                
                # テンポ変更イベントへの対応（製品としての精度向上）
                if msg.is_meta and msg.type == 'set_tempo':
                    current_tempo = msg.tempo

                # Tickから秒への変換
                current_seconds = mido.tick2second(current_tick, ticks_per_beat, current_tempo)

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
    def __init__(self, port_name: Optional[str] = None):
        self.port_name = port_name
        self.port: Any = None

    @staticmethod
    def get_available_ports() -> List[str]:
        # mido.get_input_names() が確実に存在するように型を意識
        return list(mido.get_input_names())

    def start(self) -> None:
        if not self.port_name:
            ports = self.get_available_ports()
            if not ports:
                print("MIDIデバイスが見つかりません。")
                return
            self.port_name = ports[0]

        try:
            # ポートオープン
            self.port = mido.open_input(self.port_name, callback=self.midi_callback)
            print(f"MIDI入力開始: {self.port_name}")
        except Exception as e:
            print(f"MIDIポートのオープンに失敗: {e}")

    def stop(self) -> None:
        if self.port:
            self.port.close()
            print("MIDIポートを閉じました。")

    def midi_callback(self, message: mido.Message) -> None:
        """外部MIDIメッセージ受信時の処理"""
        timestamp = time.time()
        # message.type の型安全性を考慮
        m_type = str(message.type)
        
        if m_type == 'note_on' and message.velocity > 0:
            midi_signals.midi_event_signal.emit(message.note, message.velocity, 'on')
            midi_signals.midi_event_record_signal.emit(message.note, message.velocity, 'on', timestamp)
        elif m_type == 'note_off' or (m_type == 'note_on' and message.velocity == 0):
            midi_signals.midi_event_signal.emit(message.note, message.velocity, 'off')
            midi_signals.midi_event_record_signal.emit(message.note, message.velocity, 'off', timestamp)
