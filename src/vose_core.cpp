#include "vose_core.h"        // include/ フォルダにある想定
#include "world/synthesis.h"  // include/world/ フォルダにある想定
#include <vector>
#include <cstdio>

extern "C" {
    DLLEXPORT int process_vocal(CNoteEvent* note) {
        if (!note || !note->pitch_curve) return -1;

        // Pythonから渡されたHz配列(float)を、WORLDが求めるdouble配列に変換
        int num_frames = note->pitch_length;
        std::vector<double> f0(num_frames);
        for (int i = 0; i < num_frames; ++i) {
            f0[i] = static_cast<double>(note->pitch_curve[i]);
        }

        // 解析データ（スペクトル包絡など）が揃えば、ここで WORLD の Synthesis を呼ぶ
        // 例: Synthesis(f0.data(), num_frames, spectrogram, aperiodicity, fft_size, frame_period, fs, y);

        std::printf("[C++ Core] Header linked successfully. Processing Note: %d\n", note->note_number);
        
        return 0;
    }
}
