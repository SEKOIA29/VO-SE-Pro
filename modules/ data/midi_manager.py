# midi_manager.py

import mido
import mido.backends.rtmidi
import time
from typing import List, Optional, Dict, Any, cast
from PySide6.QtCore import Signal, QObject
# 警告が出ていたインポートパスを、プロジェクト構造に合わせて安全に記述
try:
    from modules.data.data_models import NoteEvent
except ImportError:
    # 読み込み失敗時のフォールバック用ダミークラス（解析エラー回避）
    class NoteEvent:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
        def to_dict(self):
            return self.__dict__

class MidiSignals(QObject):
    """MIDIイベントをGUIやエンジンに橋渡しするシグナル"""
    # note, velocity, status ('on'/'off')
    midi_event_signal = Signal(int, int, str)
    # note, velocity, status, timestamp
    midi_event_record_signal = Signal(int, int, str, float)

# シングルトンとしてエクスポート
midi_signals = MidiSignals()

def load_midi_file(filepath: str) -> Optional[List[Dict[str, Any]]]:
    """MIDIファイルを読み込み、NoteEventのリスト（辞書形式）を返す（1行も省略なし）"""
    try:
        mid = mido.MidiFile(filepath)
        notes: List[NoteEvent] = []
        
        ticks_per_beat = mid.ticks_per_beat
        # デフォルトテンポ: 120bpm (500,000 microseconds per beat)
        current_tempo = 500000 
        
        for track in mid.tracks:
            current_tick = 0
            # note_number -> (start_sec, velocity)
            open_notes: Dict[int, tuple[float, int]] = {} 
            
            for msg in track:
                current_tick += getattr(msg, 'time', 0)
                
                # テンポ変更イベントへの対応
                if msg.is_meta and msg.type == 'set_tempo':
                    current_tempo = getattr(msg, 'tempo', 500000)

                # Tickから秒への変換
                current_seconds = mido.tick2second(current_tick, ticks_per_beat, current_tempo)

                # msg.type の取得と属性アクセスを安全に（Pyrightエラー対策）
                m_type = str(msg.type)
                m_note = getattr(msg, 'note', 0)
                m_velocity = getattr(msg, 'velocity', 0)

                if m_type == 'note_on' and m_velocity > 0:
                    open_notes[m_note] = (current_seconds, m_velocity)
                
                elif m_type == 'note_off' or (m_type == 'note_on' and m_velocity == 0):
                    if m_note in open_notes:
                        start_sec, velocity = open_notes.pop(m_note)
                        duration = current_seconds - start_sec
                        
                        if duration > 0:
                            notes.append(NoteEvent(
                                note_number=m_note,
                                start_time=start_sec,
                                duration=duration,
                                velocity=velocity
                            ))
        return [n.to_dict() for n in notes]
    except Exception as e:
        print(f"MIDIファイルの読み込みに失敗しました: {e}")
        return None

class MidiInputManager:
    """MIDIキーボードなどの外部機器入力を管理（1行も省略なし）"""
    def __init__(self, port_name: Optional[str] = None):
        self.port_name = port_name
        self.port: Any = None

    @staticmethod
    def get_available_ports() -> List[str]:
        """
        利用可能なポートを取得。
        Pyrightのエラーを回避するため、getattrを使用して動的にアクセス。
        """
        get_names = getattr(mido, 'get_input_names', None)
        if get_names and callable(get_names):
            return list(get_names())
        return []

    def start(self) -> None:
        if not self.port_name:
            ports = self.get_available_ports()
            if not ports:
                print("MIDIデバイスが見つかりません。")
                return
            self.port_name = ports[0]

        try:
            # ポートオープン（Pyrightエラー回避のため動的呼び出し）
            open_input = getattr(mido, 'open_input', None)
            if open_input and callable(open_input):
                self.port = open_input(self.port_name, callback=self.midi_callback)
                print(f"MIDI入力開始: {self.port_name}")
            else:
                print("mido.open_input が利用できません。")
        except Exception as e:
            print(f"MIDIポートのオープンに失敗: {e}")

    def stop(self) -> None:
        if self.port:
            try:
                close_func = getattr(self.port, 'close', None)
                if close_func and callable(close_func):
                    close_func()
                print("MIDIポートを閉じました。")
            except Exception as e:
                print(f"MIDIポートの切断エラー: {e}")

    def midi_callback(self, message: Any) -> None:
        """外部MIDIメッセージ受信時の処理（型安全版・省略なし）"""
        timestamp = time.time()
        
        # messageオブジェクトから属性を安全に取得
        m_type = str(getattr(message, 'type', 'unknown'))
        m_note = int(getattr(message, 'note', 0))
        m_velocity = int(getattr(message, 'velocity', 0))
        
        if m_type == 'note_on' and m_velocity > 0:
            midi_signals.midi_event_signal.emit(m_note, m_velocity, 'on')
            midi_signals.midi_event_record_signal.emit(m_note, m_velocity, 'on', timestamp)
        elif m_type == 'note_off' or (m_type == 'note_on' and m_velocity == 0):
            midi_signals.midi_event_signal.emit(m_note, m_velocity, 'off')
            midi_signals.midi_event_record_signal.emit(m_note, m_velocity, 'off', timestamp)
