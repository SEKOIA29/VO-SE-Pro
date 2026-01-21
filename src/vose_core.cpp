#include <stdio.h>
#include <stdlib.h>
#include <vector>
#include <iostream>

#include "vose_core.h" 

// WORLD Headers
#include "world/synthesis.h"
#include "world/cheaptrick.h"
#include "world/d4c.h"
#include "world/dio.h"
#include "world/stonemask.h"
#include "world/constantnumbers.h"
#include "world/audioio.h" 

extern "C" {

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

DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path) {
    if (notes == nullptr || output_path == nullptr) return;

    const int fs = 44100;           
    const double frame_period = 5.0; 

    for (int i = 0; i < note_count; i++) {
        NoteEvent* n = &notes[i];
        if (n->pitch_length <= 0 || n->pitch_curve == nullptr || n->wav_path == nullptr) continue;

        // 1. WAV読み込み (GetAudioLengthは大文字、wavreadは小文字)
        int x_length = GetAudioLength(n->wav_path);
        if (x_length <= 0) continue;
        
        double* x = new double[x_length];
        int fs_actual, nbit;
        wavread(n->wav_path, &fs_actual, &nbit, x); 

        // 2. 解析準備
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

        // 3. 解析
        CheapTrick(x, x_length, fs, time_axis.data(), f0_new.data(), f0_length, &ct_option, spectrogram);
        D4C(x, x_length, fs, time_axis.data(), f0_new.data(), f0_length, fft_size, &d4c_option, aperiodicity);

        // 4. 合成
        int y_length = (int)((f0_length - 1) * frame_period / 1000.0 * fs) + 1;
        double* y = new double[y_length];
        Synthesis(f0_new.data(), f0_length, spectrogram, aperiodicity, fft_size, frame_period, fs, y_length, y);

        // 5. 出力 (wavwriteは小文字)
        wavwrite(y, y_length, fs, 16, output_path);

        // 6. 解放
        delete[] x;
        delete[] y;
        FreeMatrix(spectrogram, f0_length);
        FreeMatrix(aperiodicity, f0_length);
    }
}

DLLEXPORT float get_engine_version(void) { return 2.0f; }

}
