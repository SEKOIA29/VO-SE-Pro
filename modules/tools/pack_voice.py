import wave
import numpy as np
import os

def pack_wav_to_header(wav_path, phoneme_name, output_header):
    # 1. WAVを開いてバイナリを読み込む
    with wave.open(wav_path, 'rb') as f:
        params = f.getparams()
        # 16bit PCMを前提に読み込み
        frames = f.readframes(f.getnframes())
        data = np.frombuffer(frames, dtype=np.int16)

    # 2. C++の配列形式に変換
    with open(output_header, 'w', encoding='utf-8') as h:
        h.write(f"// VO-SE Official Voice Data: {phoneme_name}\n")
        h.write(f"const int16_t OFFICIAL_VOICE_{phoneme_name.upper()}[] = {{\n    ")
        
        # 10個ごとに改行して見やすく出力
        for i, val in enumerate(data):
            h.write(f"{val}, ")
            if (i + 1) % 10 == 0:
                h.write("\n    ")
        
        h.write("\n};\n\n")
        h.write(f"const int OFFICIAL_VOICE_{phoneme_name.upper()}_LEN = {len(data)};\n")

    print(f"✅ {wav_path} を {output_header} にパッキングしました！")

# 実行例
# pack_wav_to_header("assets/vose_official_a.wav", "A", "src/voice_data_a.h")
