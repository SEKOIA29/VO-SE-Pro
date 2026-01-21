##include <stdio.h>
#include <stdlib.h>
#include <vector>
#include "vose_core.h"        // 構造体定義
#include "world/synthesis.h"  // WORLD合成
#include "world/cheaptrick.h" // 音色解析（将来用）

extern "C" {

/* --- 関数1: レンダリング処理 (WORLD統合版) --- */
DLLEXPORT void execute_render(CNoteEvent* notes, int note_count, const char* output_path) {
    printf("[VO-SE Core] レンダリング開始: %s\n", output_path);

    for (int i = 0; i < note_count; i++) {
        CNoteEvent* note = &notes[i];
        
        if (note->pitch_length <= 0 || note->pitch_curve == nullptr) continue;

        // 1. Pythonから届いた float配列を WORLD用の double配列に変換
        std::vector<double> f0(note->pitch_length);
        for (int j = 0; j < note->pitch_length; j++) {
            f0[j] = static_cast<double>(note->pitch_curve[j]);
        }

        // 2. WORLD合成の準備 (サンプリングレートやフレーム周期の設定)
        double frame_period = 5.0; // 5ms
        int fs = 44100;
        
        // ※ 本来はここで CheapTrick 等で解析したスペクトルデータ(spectrogram)を使います
        // 現時点では構造の疎通確認のため、ログ出力までを行います
        printf("   [Note %d] Processing %d frames, Pitch[0]: %.2f Hz\n", 
               i, note->pitch_length, f0[0]);

        /* 実際の合成処理(例):
           Synthesis(f0.data(), note->pitch_length, spectrogram, aperiodicity, 
                     fft_size, frame_period, fs, out_wave);
        */
    }

    printf("[VO-SE Core] 全ノートの処理完了。\n");
}

/* --- 関数2: 音声エフェクト処理 --- */
DLLEXPORT void process_voice(float* buffer, int length) {
    if (buffer == NULL) return;
    for (int i = 0; i < length; i++) {
        buffer[i] *= 0.8f; // 音量調整
    }
}

/* --- 関数3: バージョン確認 --- */
DLLEXPORT float get_engine_version(void) {
    return 2.0f; // WORLD統合版は 2.0
}

} // extern "C"
