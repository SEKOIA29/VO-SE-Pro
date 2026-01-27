import wave
import numpy as np
import glob
import os

def pack_all_voices():
    # 出力先
    output_path = "src/voice_data.h"
    # WAVがある場所
    wav_files = glob.glob("assets/official_voices/*.wav")
    
    with open(output_path, 'w', encoding='utf-8') as h:
        h.write("#pragma once\n#include <stdint.h>\n\n")
        
        for wav_path in wav_files:
            name = os.path.splitext(os.path.basename(wav_path))[0]
            # 日本語ファイル名対策（"あ" -> "A" などに内部で置換するか、ID管理する）
            # ここではシンプルにそのまま upper 変換
            var_name = f"OFFICIAL_VOICE_{name.upper()}"
            
            with wave.open(wav_path, 'rb') as f:
                data = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
                
                h.write(f"const int16_t {var_name}[] = {{\n    ")
                for i, val in enumerate(data):
                    h.write(f"{val},")
                    if (i + 1) % 15 == 0: h.write("\n    ")
                h.write(f"\n}};\n")
                h.write(f"const int {var_name}_LEN = {len(data)};\n\n")
    
    print(f"✅ {len(wav_files)}個の音源を {output_path} にまとめました！")

if __name__ == "__main__":
    pack_all_voices()
