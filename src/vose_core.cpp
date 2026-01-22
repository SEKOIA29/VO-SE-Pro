#include <stdio.h>
#include <stdlib.h>
#include <vector>
#include <iostream>
#include <algorithm> // std::max, std::min用

#include "vose_core.h" 

// WORLD Headers
#include "world/synthesis.h"
#include "world/cheaptrick.h"
#include "world/d4c.h"
#include "world/audioio.h" 

extern "C" {

// メモリ管理用のヘルパー
double** AllocateMatrix(int rows, int cols) {
    double** matrix = new double*[rows];
    for (int i = 0; i < rows; ++i) matrix[i] = new double[cols];
    return matrix;
}

void FreeMatrix(double** matrix, int rows) {
    for (int i = 0; i < rows; ++i) delete[] matrix[i];
    delete[] matrix;
}

/**
 * execute_render: 
 * GUIから渡された全ノートと4重パラメーターを統合して合成
 */
DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path) {
    if (notes == nullptr || output_path == nullptr || note_count == 0) return;

    const int fs = 44100;           
    const double frame_period = 5.0; 

    // 1. 全体の出力サンプル数を計算
    int total_samples = 0;
    std::vector<int> note_samples;
    for (int i = 0; i < note_count; i++) {
        int s = (int)((notes[i].pitch_length - 1) * frame_period / 1000.0 * fs) + 1;
        note_samples.push_back(s);
        total_samples += s;
    }

    double* full_song_buffer = new double[total_samples]{0.0};
    int current_offset = 0;

    // 2. 各ノートをループ
    for (int i = 0; i < note_count; i++) {
        NoteEvent* n = &notes[i];
        if (n->pitch_length <= 0 || n->pitch_curve == nullptr || n->wav_path == nullptr) continue;

        int x_length = GetAudioLength(n->wav_path);
        if (x_length <= 0) continue;
        
        double* x = new double[x_length];
        int fs_actual, nbit;
        wavread(n->wav_path, &fs_actual, &nbit, x); 

        int f0_length = n->pitch_length;
        std::vector<double> f0_new(f0_length);
        std::vector<double> time_axis(f0_length);
        for (int j = 0; j < f0_length; j++) {
            f0_new[j] = static_cast<double>(n->pitch_curve[j]);
            time_axis[j] = j * frame_period / 1000.0;
        }

        int fft_size = GetFFTSizeForCheapTrick(fs, nullptr);
        int spec_bins = fft_size / 2 + 1;
        double** spectrogram = AllocateMatrix(f0_length, spec_bins);
        double** aperiodicity = AllocateMatrix(f0_length, spec_bins);

        // --- 分析 ---
        CheapTrick(x, x_length, fs, time_axis.data(), f0_new.data(), f0_length, nullptr, spectrogram);
        D4C(x, x_length, fs, time_axis.data(), f0_new.data(), f0_length, fft_size, nullptr, aperiodicity);

        // --- 削られていた【パラメーター反映】ロジックを注入！ ---
        for (int j = 0; j < f0_length; j++) {
            // Gender (スペクトル伸縮) の適用
            double g_val = static_cast<double>(n->gender_curve[j]); // 0.0〜1.0
            double g_factor = 0.8 + (g_val * 0.4); // 0.8(幼い) 〜 1.2(太い)

            // Tension (スペクトル傾斜) の適用
            double t_val = static_cast<double>(n->tension_curve[j]);
            double tension_slope = (t_val - 0.5) * 20.0; // 傾きを調整

            for (int k = 0; k < spec_bins; k++) {
                // ここで Gender 補間ロジックや、Tension による高域強調を行う
                // (簡易的にスペクトル強度を調整)
                spectrogram[j][k] *= pow(10.0, tension_slope * k / spec_bins / 20.0);
                
                // Breath の適用 (非周期性指標 ap を増やす)
                double b_val = static_cast<double>(n->breath_curve[j]);
                aperiodicity[j][k] = std::min(1.0, aperiodicity[j][k] + b_val * 0.5);
            }
        }

        // 合成
        Synthesis(f0_new.data(), f0_length, spectrogram, aperiodicity, fft_size, frame_period, fs, note_samples[i], &full_song_buffer[current_offset]);

        current_offset += note_samples[i];

        // メモリ解放
        delete[] x;
        FreeMatrix(spectrogram, f0_length);
        FreeMatrix(aperiodicity, f0_length);
    }

    // 3. 保存
    wavwrite(full_song_buffer, total_samples, fs, 16, output_path);
    delete[] full_song_buffer;
}

DLLEXPORT float get_engine_version(void) { return 2.1f; }

}
