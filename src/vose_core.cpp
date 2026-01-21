#include <stdio.h>
#include <stdlib.h>
#include <vector>
#include <iostream>

// 自分のヘッダー
#include "vose_core.h" 

// WORLDのヘッダー
#include "world/synthesis.h"
#include "world/cheaptrick.h"
#include "world/d4c.h"
#include "world/dio.h"
#include "world/stonemask.h"
#include "world/constantnumbers.h"
#include "world/audioio.h" // WAV読み込み用

extern "C" {

/**
 * 二次元配列（ポインタの配列）の確保
 */
double** AllocateMatrix(int rows, int cols) {
    double** matrix = new double*[rows];
    for (int i = 0; i < rows; ++i) {
        matrix[i] = new double[cols];
        for (int j = 0; j < cols; ++j) matrix[i][j] = 0.0;
    }
    return matrix;
}

void FreeMatrix(double** matrix, int rows) {
    for (int i = 0; i < rows; ++i) delete[] matrix[i];
    delete[] matrix;
}

/**
 * execute_render: 
 * 1. WAVを読み込む
 * 2. CheapTrickで音色を解析する
 * 3. D4Cで非周期性を解析する
 * 4. 新しいF0で再合成する
 */
DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path) {
    if (notes == nullptr || output_path == nullptr) return;

    printf("[VO-SE Core] Rendering Engine v2.0 - Full Pipeline\n");

    const int fs = 44100;           
    const double frame_period = 5.0; 

    for (int i = 0; i < note_count; i++) {
        NoteEvent* n = &notes[i];
        if (n->pitch_length <= 0 || n->pitch_curve == nullptr || n->wav_path == nullptr) continue;

        // --- 1. 元のWAVファイルの読み込み ---
        int x_length = getAudioLength(n->wav_path);
        if (x_length <= 0) {
            printf("  [Error] WAV file not found or empty: %s\n", n->wav_path);
            continue;
        }
        double* x = new double[x_length];
        int fs_actual, nbit;
        wavread(n->wav_path, &fs_actual, &nbit, x);

        // --- 2. 解析の準備 ---
        int f0_length = n->pitch_length;
        std::vector<double> f0_new(f0_length);
        std::vector<double> time_axis(f0_length);
        for (int j = 0; j < f0_length; j++) {
            f0_new[j] = static_cast<double>(n->pitch_curve[j]);
            time_axis[j] = j * frame_period / 1000.0;
        }

        CheapTrickOption ct_option = { 0 };
        InitializeCheapTrickOption(fs, &ct_option);
        D4COption d4c_option = { 0 };
        InitializeD4COption(&d4c_option);

        int fft_size = GetFFTSizeForCheapTrick(fs, &ct_option);
        int spec_bins = fft_size / 2 + 1;
        
        double** spectrogram = AllocateMatrix(f0_length, spec_bins);
        double** aperiodicity = AllocateMatrix(f0_length, spec_bins);

        // --- 3. 音声解析 (Analysis) ---
        // 元の波形xから、指定された時間軸とF0に基づいて音色とハスキーさを抽出
        CheapTrick(x, x_length, fs, time_axis.data(), f0_new.data(), f0_length, &ct_option, spectrogram);
        D4C(x, x_length, fs, time_axis.data(), f0_new.data(), f0_length, fft_size, &d4c_option, aperiodicity);

        // --- 4. 合成 (Synthesis) ---
        int y_length = (int)((f0_length - 1) * frame_period / 1000.0 * fs) + 1;
        double* y = new double[y_length];

        Synthesis(f0_new.data(), f0_length, spectrogram, aperiodicity, fft_size, frame_period, fs, y_length, y);

        // --- 5. 結果の書き出し (とりあえず1つ目のノートのみテスト保存する場合) ---
        // 本来は全ノートを結合して一つのファイルにします
        if (i == 0) {
            wavwrite(y, y_length, fs, 16, output_path);
            printf("  [Note %d] Saved to: %s\n", i, output_path);
        }

        // 6. メモリ解放
        delete[] x;
        delete[] y;
        FreeMatrix(spectrogram, f0_length);
        FreeMatrix(aperiodicity, f0_length);
    }

    printf("[VO-SE Core] All processing finished.\n");
}

DLLEXPORT float get_engine_version(void) {
    return 2.0f; 
}

} // extern "C"
