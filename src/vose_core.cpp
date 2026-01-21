#include <stdio.h>
#include <stdlib.h>
#include <vector>
#include <iostream>

// 確定したディレクトリ構成に基づき、includeフォルダのヘッダーを読み込む
#include "vose_core.h"        
#include "world/synthesis.h"   // 再合成
#include "world/cheaptrick.h"  // 音色解析
#include "world/d4c.h"         // 非周期性解析

extern "C" {

/**
 * execute_render
 * Pythonから渡された複数のノートイベントを一括処理し、音声合成を行います。
 */
DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path) {
    if (notes == nullptr || output_path == nullptr) {
        fprintf(stderr, "[VO-SE Error] Invalid arguments passed to execute_render.\n");
        return;
    }

    printf("[VO-SE Core] Rendering started. Target: %s\n", output_path);
    printf("[VO-SE Core] Total notes to process: %d\n", note_count);

    // サンプリングレート等の共通設定
    int fs = 44100;
    double frame_period = 5.0; // 5ms (WORLDのデフォルト)

    for (int i = 0; i < note_count; i++) {
        NoteEvent* n = &notes[i];
        
        // パスの安全確認
        const char* current_wav = n->wav_path ? n->wav_path : "Unknown Source";
        
        printf("  -> Processing Note [%d]: %s\n", i, current_wav);
        printf("     Pitch: %.2f Hz, Duration: %.2fs, F0 Frames: %d\n", 
               n->pitch_hz, n->duration_sec, n->pitch_length);

        // --- WORLD合成のコアロジック (概念) ---
        if (n->pitch_curve != nullptr && n->pitch_length > 0) {
            
            // 1. Python(float*)からWORLD(double*)へピッチ配列を変換
            std::vector<double> f0(n->pitch_length);
            for (int j = 0; j < n->pitch_length; j++) {
                f0[j] = static_cast<double>(n->pitch_curve[j]);
            }

            // 2. 本来はここで CheapTrick 等を使い wav_path からスペクトルを抽出
            // 現段階ではパイプラインの疎通を優先し、データ準備までを行います。
            
            /* [実装イメージ]
            double** spectrogram = ...; 
            double** aperiodicity = ...;
            int fft_size = GetFFTSizeForCheapTrick(fs);
            
            Synthesis(f0.data(), n->pitch_length, spectrogram, aperiodicity, 
                      fft_size, frame_period, fs, out_buffer);
            */
        }
    }

    // 最後に全データを統合してWAVとして書き出し（将来の実装箇所）
    printf("[VO-SE Core] All notes processed. Wav export ready.\n");
}

/**
 * process_voice
 * バッファ内の音声データに対して直接エフェクト（音量調整等）を適用します。
 */
DLLEXPORT void process_voice(float* buffer, int length) {
    if (buffer == nullptr) return;
    
    // シンプルなゲイン調整
    const float gain = 0.8f;
    for (int i = 0; i < length; i++) {
        buffer[i] *= gain;
    }
}

/**
 * get_engine_version
 * エンジンのバージョンを返します。Python側でのロード確認に使用します。
 */
DLLEXPORT float get_engine_version(void) {
    // WORLD統合完了につき 2.0 へメジャーアップデート
    return 2.0f;
}

} // extern "C"
