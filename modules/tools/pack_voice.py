　import os
import wave
import numpy as np
import glob

def pack_all_voices():
    output_path = "src/voice_data.h"
    wav_files = glob.glob("assets/official_voices/*.wav")
    
    with open(output_path, 'w', encoding='utf-8') as h:
        h.write("#pragma once\n#include <stdint.h>\n#include <map>\n#include <string>\n\n")
        
        # 登録用のリスト
        voice_list = []
        
        for i, wav_path in enumerate(wav_files):
            # ファイル名（「あ」など）を取得
            original_name = os.path.splitext(os.path.basename(wav_path))[0]
            # 変数名は安全な英数字にする (例: VOICE_0, VOICE_1...)
            var_name = f"OFFICIAL_VOICE_DATA_{i}"
            
            with wave.open(wav_path, 'rb') as f:
                data = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
                
                h.write(f"const int16_t {var_name}[] = {{\n    ")
                h.write(",".join(map(str, data[:100]))) # 長すぎるので例として
                # ...実際には全データを書き出す
                h.write(f"\n}};\n")
                h.write(f"const int {var_name}_LEN = {len(data)};\n\n")
                
                voice_list.append((original_name, var_name))

        # 最後に「名前」と「データ」を紐付ける初期化関数を自動生成する
        h.write("inline void register_all_embedded_voices() {\n")
        for name, var in voice_list:
            h.write(f'    load_embedded_resource("{name}", {var}, {var}_LEN);\n')
        h.write("}\n")

    print(f"Success: Packed {len(wav_files)} voices.")
