# audio_output.py

import sounddevice as sd
import platform

class AudioOutput:
    def __init__(self, sample_rate=44100, block_size=256):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.stream = None
        self.is_playing = False
        self.engine_callback = None  # C言語エンジンへの橋渡し用
        
        # OSに合わせた最適なデバイス設定
        self._initialize_device()

    def _initialize_device(self):
        """OSごとの最適なオーディオドライバを自動選択"""
        if platform.system() == "Windows":
            best_idx = self._get_best_device_for_windows()
            if best_idx is not None:
                sd.default.device = best_idx
                # デバイス情報の取得と表示
                dev_info = sd.query_devices(best_idx)
                print(f"VO-SE: Windows高速出力デバイス選択 -> {dev_info['name']}")
        elif platform.system() == "Darwin":  # macOS
            # Apple Silicon (M1/M2/M3) は Core Audio で極めて低遅延
            print("VO-SE: macOS Core Audioで初期化 (Apple Silicon Optimized)")

    def _get_best_device_for_windows(self):
        """Windows環境で低遅延なドライバ(ASIO > WASAPI)を優先的に探す"""
        devices = sd.query_devices()
        
        # 1. ASIO (DAWなどで使われる最強の低遅延ドライバ)
        for i, dev in enumerate(devices):
            if "ASIO" in dev['name']:
                return i
                
        # 2. WASAPI (Windows標準の低遅延モード)
        for i, dev in enumerate(devices):
            if "WASAPI" in dev['name'] and dev['max_output_channels'] > 0:
                return i
                
        return None

    def start(self, engine_callback=None):
        """ストリームを開始し、再生フラグを立てる"""
        self.engine_callback = engine_callback
        if self.stream is None:
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                channels=1,
                dtype='float32',
                callback=self._audio_callback
            )
            self.stream.start()
        self.is_playing = True

    def stop(self):
        """再生を停止し、ストリームを破棄する"""
        self.is_playing = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def _audio_callback(self, outdata, frames, time_info, status):
        """
        サウンドカードからの要求に応じる高プライオリティ・コールバック。
        """
        if status:
            print(f"Audio Output Status: {status}")

        if not self.is_playing:
            outdata.fill(0)
            return

        # 出力用バッファを無音で初期化
        outdata.fill(0)

        # エンジン側で outdata に直接 float32 データを書き込ませる
        if self.engine_callback:
            self.engine_callback(outdata, frames)

    def get_latency(self):
        """現在の実測遅延（秒）を取得"""
        if self.stream:
            return self.stream.latency
        return 0
