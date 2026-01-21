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

extern "C" {

/**
 * WORLDの二次元配列（double**）を確保するためのヘルパー
 */
double** AllocateMatrix(int rows, int cols) {
    double** matrix = new double*[rows];
    for (int i = 0; i < rows; ++i) matrix[i] = new double[cols];
    return matrix;
}

/**
 * 二次元配列を解放するためのヘルパー
 */
void FreeMatrix(double** matrix, int rows) {
    for (int i = 0; i < rows; ++i) delete[] matrix[i];
    delete[] matrix;
}

/**
 * execute_render: Pythonからの指示で音声を合成する
 */
DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path) {
    if (notes == nullptr || output_path == nullptr) return;

    printf("[VO-SE Core] Rendering Engine v2.0 Started.\n");

    const int fs = 44100;           // サンプリングレート
    const double frame_period = 5.0; // 5ms間隔

    for (int i = 0; i < note_count; i++) {
        NoteEvent* n = &notes[i];
        int f0_length = n->pitch_length;

        if (f0_length <= 0 || n->pitch_curve == nullptr) continue;

        // 1. F0データの準備 (float* から double* へ)
        std::vector<double> f0(f0_length);
        std::vector<double> time_axis(f0_length);
        for (int j = 0; j < f0_length; j++) {
            f0[j] = static_cast<double>(n->pitch_curve[j]);
            time_axis[j] = j * frame_period / 1000.0;
        }

        // 2. WORLD解析用オプションの初期化（ここがエラーの修正ポイント）
        CheapTrickOption ct_option = { 0 };
        InitializeCheapTrickOption(fs, &ct_option);
        
        D4COption d4c_option = { 0 };
        InitializeD4COption(fs, &d4c_option);

        // FFTサイズとスペクトルビン数の計算
        int fft_size = GetFFTSizeForCheapTrick(fs, &ct_option);
        int spec_bins = fft_size / 2 + 1;
        
        // メモリ確保
        double** spectrogram = AllocateMatrix(f0_length, spec_bins);
        double** aperiodicity = AllocateMatrix(f0_length, spec_bins);

        // 3. 合成 (Synthesis)
        // 合成される波形の長さを計算
        int y_length = (int)((f0_length - 1) * frame_period / 1000.0 * fs) + 1;
        double* y = new double[y_length];

        // --- 本来はこの直前で CheapTrick / D4C を回して音色を決定します ---
        // Synthesis関数の呼び出し
        Synthesis(f0.data(), f0_length, spectrogram, aperiodicity, fft_size, frame_period, fs, y_length, y);

        printf("  [Note %d] Synthesis Completed. (Length: %d samples)\n", i, y_length);

        // 4. 後片付け
        FreeMatrix(spectrogram, f0_length);
        FreeMatrix(aperiodicity, f0_length);
        delete[] y;
    }

    printf("[VO-SE Core] Rendering Finished.\n");
}

DLLEXPORT float get_engine_version(void) {
    return 2.0f; 
}

} // extern "C"
    
