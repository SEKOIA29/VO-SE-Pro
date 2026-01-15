# audio_output.py

import sounddevice as sd
import numpy as np
import ctypes
import platform

class AudioOutput:
    def __init__(self, sample_rate=44100, block_size=256):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.stream = None
        self.is_playing = False
        self.engine_callback = None # C言語エンジンへの橋渡し用
        
        # OSに合わせた最適なデバイス設定
        self._initialize_device()

    def _initialize_device(self):
        """OSごとの最適なオーディオドライバを自動選択"""
        if platform.system() == "Windows":
            best_idx = self._get_best_device_for_windows()
            if best_idx is not None:
                sd.default.device = best_idx
                print(f"VO-SE: Windows高速出力デバイス選択 -> {sd.query_devices(best_idx)['name']}")
        elif platform.system() == "Darwin": # macOS
            # M3 Macは標準のCore Audioで十分低遅延
            print("VO-SE: macOS Core Audioで初期化 (Apple Silicon Optimized)")

    def _get_best_device_for_windows(self):
        devices = sd.query_devices()
        # 1. ASIO (最強)
        for i, dev in enumerate(devices):
            if "ASIO" in dev['name']: return i
        # 2. WASAPI (次点)
        for i, dev in enumerate(devices):
            if "WASAPI" in dev['name'] and dev['max_output_channels'] > 0: return i
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
        ここでは重い処理（ファイルI/Oや複雑なAI推論）は厳禁。
        """
        if status:
            print(f"Audio Output Status: {status}")

        if not self.is_playing:
            outdata.fill(0)
            return

        # 出力用バッファ（ゼロクリア）
        # エンジンがデータを書き込まなかった時のために無音で初期化
        outdata.fill(0)

        # C言語エンジンとの連携（実装予定）
        if self.engine_callback:
            # エンジン側で outdata に直接 float32 データを書き込ませる
            # 例: self.engine_callback(outdata.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), frames)
            self.engine_callback(outdata, frames)

    def get_latency(self):
        """現在の実測遅延（秒）を取得。M3 Macなら 0.005 (5ms) 程度が理想"""
        if self.stream:
            return self.stream.latency
        return 0
