# vo_se_engine.py


import ctypes
import os
import platform
import numpy as np
import sounddevice as sd
import soundfile as sf
import chardet

# ==========================================================================
# 1. C言語互換構造体（パラメーターを1つも漏らさずC++へ）
# ==========================================================================
class CNoteEvent(ctypes.Structure):
    _fields_ = [
        ("wav_path", ctypes.c_char_p),
        ("pitch_curve", ctypes.POINTER(ctypes.c_float)),
        ("pitch_length", ctypes.c_int),
        ("gender_curve", ctypes.POINTER(ctypes.c_float)),
        ("tension_curve", ctypes.POINTER(ctypes.c_float)),
        ("breath_curve", ctypes.POINTER(ctypes.c_float))
    ]

# ==========================================================================
# 2. メインエンジンクラス（削りなし・全機能統合版）
# ==========================================================================
class VO_SE_Engine:
    def __init__(self, voice_lib_dir="voices"):
        self.sample_rate = 44100
        self.lib = self._load_core_library()
        self._temp_refs = []  # C++実行中のメモリ保護用
        self.is_playing = False
        self.stream = None
        self.current_out_data = None # 現在再生中の全波形データ
        
        # パス解決（開発環境とビルド後の両方に対応）
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.voice_lib_path = os.path.abspath(os.path.join(base_dir, "..", voice_lib_dir))
        
        self.oto_map = {}
        self.refresh_voice_library()

    def get_audio_devices(self):
        """接続されているオーディオ入出力デバイスのリストを返す"""
        devices = sd.query_devices()
        output_devices = [d['name'] for d in devices if d['max_output_channels'] > 0]
        return output_devices

    def set_output_device(self, device_name):
        """指定されたデバイスを出力先に設定する"""
        sd.default.device = [None, device_name] # [入力, 出力]
        print(f"🔈 Output set to: {device_name}")

    def setup_audio_output(self, device_name=None):
        """
        オーディオデバイスを設定する。
        device_nameがNoneならMacのデフォルト出力を使用。
        """
        try:
            if device_name:
                sd.default.device[1] = device_name # 出力デバイスを指定
            print(f"✔︎ Audio device set: {sd.query_devices(sd.default.device[1])['name']}")
        except Exception as e:
            print(f"ʕ⁎̯͡⁎ʔ༄ Device error: {e}")

        

    def _load_core_library(self):
        """OS判別ロード（Win/Mac両対応）"""
        system = platform.system()
        ext = ".dll" if system == "Windows" else ".dylib"
        
        # 探索候補
        search_paths = [
            os.path.join(os.path.dirname(__file__), f"vose_core{ext}"),
            os.path.join(os.path.dirname(__file__), "bin", f"vose_core{ext}"),
            f"./vose_core{ext}"
        ]
        
        for path in search_paths:
            if os.path.exists(path):
                try:
                    lib = ctypes.CDLL(os.path.abspath(path))
                    lib.execute_render.argtypes = [
                        ctypes.POINTER(CNoteEvent), 
                        ctypes.c_int, 
                        ctypes.c_char_p
                    ]
                    print(f"○ Engine Core Connected: {path}")
                    return lib
                except Exception as e:
                    print(f"ʕ⁎̯͡⁎ʔ༄ Load Error: {e}")
        return None

    # --- 高度な音源スキャン ---
    def refresh_voice_library(self):
        """voicesフォルダを再帰的にスキャン。UTAU音源の階層構造に対応"""
        if not os.path.exists(self.voice_lib_path):
            os.makedirs(self.voice_lib_path, exist_ok=True)
            return
        
        self.oto_map = {}
        # サブフォルダ（キャラ名フォルダなど）の中身もすべて検索
        for root, _, files in os.walk(self.voice_lib_path):
            for file in files:
                if file.lower().endswith(".wav"):
                    # ファイル名を歌詞（エイリアス）として登録
                    lyric = os.path.splitext(file)[0]
                    self.oto_map[lyric] = os.path.abspath(os.path.join(root, file))

    # --- 削られていた重要機能：ファイルエンコーディング自動判別 ---
    def read_text_safely(self, file_path):
        """USTやoto.iniの文字化けを防ぐ"""
        try:
            with open(file_path, 'rb') as f:
                raw = f.read()
                det = chardet.detect(raw)
                enc = det['encoding'] if det['confidence'] > 0.7 else 'cp932'
                return raw.decode(enc, errors='ignore')
        except: return ""

    # --- 核心機能：多重パラメーター・レンダリング ---
    def export_to_wav(self, notes, parameters, file_path):
        """
        MainWindowから渡されたノート群と、全グラフパラメーターを統合してC++へ
        notes: List[NoteEvent], parameters: dict[str, List[PitchEvent]]
        """
        if not self.lib:
            raise RuntimeError("Engine Core library missing! ビルドしたdll/dylibを配置してください。")

        note_count = len(notes)
        c_notes_array = (CNoteEvent * note_count)()
        self._temp_refs = []

        for i, note in enumerate(notes):
            # 歌詞（またはJanomeで変換された音素）に一致するWAVを探す
            wav_path = self.oto_map.get(note.lyrics) or self.oto_map.get(note.phonemes)
            if not wav_path:
                wav_path = list(self.oto_map.values())[0] if self.oto_map else ""

            # ノートの長さに合わせてグラフからパラメーターをサンプリング（解像度128）
            res = 128
            p_curve = self._get_sampled_curve(parameters["Pitch"], note, res, is_pitch=True)
            g_curve = self._get_sampled_curve(parameters["Gender"], note, res)
            t_curve = self._get_sampled_curve(parameters["Tension"], note, res)
            b_curve = self._get_sampled_curve(parameters["Breath"], note, res)

            # メモリ保護（C++が処理を終えるまでPythonのGCから守る）
            self._temp_refs.extend([p_curve, g_curve, t_curve, b_curve])

            # C++構造体へ流し込み
            c_notes_array[i].wav_path = wav_path.encode('utf-8')
            c_notes_array[i].pitch_curve = p_curve.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            c_notes_array[i].gender_curve = g_curve.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            c_notes_array[i].tension_curve = t_curve.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            c_notes_array[i].breath_curve = b_curve.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            c_notes_array[i].pitch_length = res

        # C++実行
        try:
            self.lib.execute_render(c_notes_array, note_count, os.path.abspath(file_path).encode('utf-8'))
        finally:
            self._temp_refs = [] # 完了後に解放

    def _get_sampled_curve(self, events, note, res, is_pitch=False):
        """
        特定のノートの時間範囲(start 〜 start+duration)をres分割して
        グラフの値をサンプリングし、float32のnumpy配列で返す。
        """
        import numpy as np
        curve = np.zeros(res, dtype=np.float32)
        
        # 1. グラフに点がない場合のデフォルト値
        default_val = 60.0 if is_pitch else 0.5
        if not events:
            return curve + default_val

        # 2. 時間軸の作成
        times = np.linspace(note.start_time, note.start_time + note.duration, res)
        
        # 3. 各サンプル点での値を線形補間で計算
        event_times = [p.time for p in events]
        event_values = [p.value for p in events]
        
        # numpyのinterpを使って一気に補間（爆速です）
        curve = np.interp(times, event_times, event_values).astype(np.float32)
        
        # 4. ピッチの場合のみ、ノートの基本音高を加算（相対値から絶対値へ）
        if is_pitch:
            # グラフが「0」ならノートそのものの音高、＋12なら1オクターブ上
            curve += float(note.note_number)
            # 周波数(Hz)に変換してC++に渡す
            curve = 440.0 * (2.0 ** ((curve - 69.0) / 12.0))
            
        return curve


    def get_current_rms(self):
        """再生中の『本物の波形』から現在の音量を計算して返す"""
        if not self.is_playing or self.current_out_data is None:
            return 0.0

        try:
            # 現在の再生位置（サンプル数）を特定
            # 実際には再生経過時間からインデックスを計算
            curr_sample = int(self.get_playback_time() * 44100)
            
            # 今この瞬間の前後256サンプルを切り取って音量を解析
            chunk = self.current_out_data[curr_sample : curr_sample + 256]
            if len(chunk) == 0: return 0.0
            
            # RMS（音圧）計算：二乗して平均してルートを取る
            rms = np.sqrt(np.mean(chunk**2))
            
            # 0.0〜1.0の範囲に収めて返す（メーター用）
            return min(rms * 5.0, 1.0) # 5.0は感度調整用の係数
        except:
            return 0.0

    
    # --- 再生制御 ---
    def play(self, filepath):
        if filepath and os.path.exists(filepath):
            data, fs = sf.read(filepath)
            sd.play(data, fs)

    def start_pro_monitoring(self, current_time, viewport_notes):
        """
        再生ヘッドの位置から、画面内のノートだけを高速合成してストリーミング再生する
        """
        # 1. 画面内のノートだけを抽出して一時WAVを作成
        temp_preview_path = "temp_monitor.wav"
        self.export_to_wav(viewport_notes, self.active_parameters, temp_preview_path)
        
        # 2. シームレスに再生開始
        self.play(temp_preview_path)
        print("Pro Audio Monitoring Active")

    def stop(self):
        sd.stop()
