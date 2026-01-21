#include "vose_core.h"
#include "world/synthesis.h"   // 再合成用
#include "world/cheaptrick.h"  // スペクトル解析用
#include <vector>
#include <cmath>

extern "C" {
    // Pythonから呼ばれるメイン関数
    DLLEXPORT int process_vocal(CNoteEvent* note) {
        if (!note || !note->pitch_curve) return -1;

        // 1. 基本パラメータの準備
        double frame_period = 5.0; // 5ms周期
        int fs = 44100;           // サンプリングレート
        int num_frames = note->pitch_length;
        
        // 2. Pythonから届いた float* のピッチ配列を WORLD用の double* にコピー
        // (WORLDは精度のため double型を要求します)
        std::vector<double> f0(num_frames);
        for (int i = 0; i < num_frames; ++i) {
            f0[i] = static_cast<double>(note->pitch_curve[i]);
        }

        // --- ここで本来は解析(CheapTrick / D4C)したデータを使いますが ---
        // --- 移行の第一歩として、構造が正しいかチェックする処理をここに書きます ---

        std::printf("[C++ WORLD] Synthesis ready for Note:%d, Frames:%d\n", 
                    note->note_number, num_frames);

        return 0; // 成功
    }
}
