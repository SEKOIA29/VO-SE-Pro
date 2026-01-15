# audio_output.py

import sounddevice as sd
import numpy as np
import ctypes

class AudioOutput:
    def __init__(self, sample_rate=44100):
        self.sample_rate = sample_rate
        self.stream = None
        self._select_best_device()

    def _select_best_device(self):
        if platform.system() == "Windows":
            for i, dev in enumerate(sd.query_devices()):
                if "ASIO" in dev['name']:
                    sd.default.device = i
                    break

    def start_stream(self, callback):
        self.stream = sd.OutputStream(
            samplerate=self.sample_rate,
            blocksize=256, # M3なら128まで攻められる
            channels=1,
            callback=callback
        )
        self.stream.start()

    def stop_stream(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()

    def _callback(self, outdata, frames, time, status):
        """
        オーディオデバイスから「次のサンプルをくれ」と呼ばれた時に実行される
        """
        if status:
            print(f"Audio Output Status: {status}")

        if not self.is_playing:
            outdata.fill(0)
            return

        # 1. C言語エンジンの「リアルタイム合成関数」を呼び出す
        # 共有バッファ（numpy配列）をC言語側に直接渡して書き込ませる
        # これが2026年で最も低遅延な方法です
        buffer = np.zeros(frames, dtype=np.float32)
        
        # C言語側の関数: void vose_generate_realtime_audio(float* out_buffer, int num_samples)
        # self.engine.lib.vose_generate_realtime_audio(
        #     buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        #     frames
        # )

        # 2. 生成されたデータをスピーカーのバッファへコピー
        outdata[:] = buffer.reshape(-1, 1)

    def play(self):
        """再生開始（リアルタイムMIDI演奏時やプレビュー時に使用）"""
        if self.stream is None:
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                channels=1,
                callback=self._callback
            )
            self.stream.start()
        self.is_playing = True

    def stop(self):
        """再生停止"""
        self.is_playing = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def get_latency(self):
        """現在の遅延（秒）を取得。 Apple M3が実行環境だから0.005前後を目指す"""
        if self.stream:
            return self.stream.latency
        return 0

def _get_best_device_for_windows(self):
    devices = sd.query_devices()
    # 1. まずはASIOを探す（プロ仕様）
    for i, dev in enumerate(devices):
        if "ASIO" in dev['name']:
            return i
    # 2. 無ければWASAPIを探す（準プロ仕様）
    for i, dev in enumerate(devices):
        if "WASAPI" in dev['name'] and dev['max_output_channels'] > 0:
            return i
    # 3. どちらも無ければ標準
    return None

　　

# 初期化時に実行
if platform.system() == "Windows":
    best_idx = self._get_best_device_for_windows()
    if best_idx is not None:
        sd.default.device = best_idx

