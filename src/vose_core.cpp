#include <iostream>
#include <cstdio>

#ifdef _WIN32
  #define DLLEXPORT __declspec(dllexport)
#else
  #define DLLEXPORT __attribute__((visibility("default")))
#endif

extern "C" {
    struct CNoteEvent {
        int note_number;
        float start_time;
        float duration;
        int velocity;
        float pre_utterance;
        float overlap;
        const char* phonemes[8];
        int phoneme_count;
        float* pitch_curve; // PythonのNumPy配列(float32)のポインタ
        int pitch_length;
    };

    DLLEXPORT int process_vocal(CNoteEvent* note) {
        if (!note || !note->pitch_curve) return -1;

        // ビルド後のデバッグ用出力
        std::printf("[C++ Core] Note:%d Start:%.2f Duration:%.2f Frames:%d\n", 
                    note->note_number, note->start_time, note->duration, note->pitch_length);
        
        if (note->pitch_length > 0) {
            std::printf("[C++ Core] Initial Pitch: %.2f Hz\n", note->pitch_curve[0]);
        }
        
        return 0; // 成功
    }
}
