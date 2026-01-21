#include "world/synthesis.h" // cppworldのヘッダ
#include <vector>

extern "C" {
    // Pythonから渡されたピッチ配列を元に、C++側で波形を生成する
    DLLEXPORT float* process_and_synthesize(CNoteEvent* note, int* out_sample_count) {
        
        // 1. Pythonから届いた pitch_curve (float*) を doubleに変換
        int num_frames = note->pitch_length;
        std::vector<double> f0(num_frames);
        for(int i=0; i<num_frames; ++i) f0[i] = (double)note->pitch_curve[i];

        // 2. スペクトル包絡(sp)と非周期性指標(ap)の準備
        // ※ 本来はここで原音(WAV)の解析データが必要
        
        // 3. WORLD合成関数の呼び出し
        // Synthesis(f0.data(), f0_length, spectrogram, aperiodicity, fft_size, frame_period, fs, y);
        
        // 4. 生成した波形を Python に返す
        // ※ Python側で受け取れるようにメモリを確保してポインタを渡す
        float* result_buffer = (float*)malloc(sizeof(float) * total_samples);
        *out_sample_count = total_samples;
        return result_buffer; 
    }
}
