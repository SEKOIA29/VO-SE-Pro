import wave
import numpy as np
import glob
import os

def pack_all_voices():
    output_path = "src/voice_data.h"
    # assets/official_voices/ 内のWAVをスキャン
    wav_files = glob.glob("assets/official_voices/*.wav")
    
    with open(output_path, 'w', encoding='utf-8') as h:
        h.write("#pragma once\n#include <stdint.h>\n\n")
        
        voice_entries = []
        
        for wav_path in wav_files:
            # ファイル名（例: "あ"）を取得
            base_name = os.path.splitext(os.path.basename(wav_path))[0]
            # 安全な変数名を作成（日本語を16進数文字列に変換）
            # 例: "あ" -> "VAR_3042" (英数字のみになるのでC++で100%通る)
            safe_id = "".join(f"{ord(c):04x}" for c in base_name)
            var_name = f"OFFICIAL_VOICE_{safe_id}"
            
            with wave.open(wav_path, 'rb') as f:
                params = f.getparams()
                frames = f.readframes(f.getnframes())
                data = np.frombuffer(frames, dtype=np.int16)
                
                h.write(f"// Original name: {base_name}\n")
                h.write(f"const int16_t {var_name}[] = {{\n    ")
                
                # データをC++配列として書き出し
                for i, val in enumerate(data):
                    h.write(f"{val},")
                    if (i + 1) % 15 == 0:
                        h.write("\n    ")
                
                h.write(f"\n}};\n")
                h.write(f"const int {var_name}_LEN = {len(data)};\n\n")
                
                voice_entries.append((base_name, var_name))

        # 最後に一括登録用の関数を自動生成
        h.write("inline void register_all_embedded_voices() {\n")
        for original_name, var_name in voice_entries:
            # C++側の load_embedded_resource(名前, ポインタ, 長さ) を呼ぶ
            h.write(f'    load_embedded_resource("{original_name}", {var_name}, {var_name}_LEN);\n')
        h.write("}\n")

    print(f"Success: Generated {output_path} with {len(wav_files)} voices.")

if __name__ == "__main__":
    pack_all_voices()
