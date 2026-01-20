#include <iostream>
#include <vector>

// WindowsとmacOS/Linuxでエクスポート宣言を切り替える
#ifdef _WIN32
  #define DLLEXPORT __declspec(dllexport)
#else
  #define DLLEXPORT __attribute__((visibility("default")))
#endif

extern "C" {
    // Python側の CNoteEvent とメモリレイアウトを完全に一致させる
    struct CNoteEvent {
        int note_number;
        float start_time;
        float duration;
        int velocity;
        float pre_utterance;
        float overlap;
        const char* phonemes[8];
        int phoneme_count;
        float* pitch_curve; // Pythonから渡される float32 配列へのポインタ
        int pitch_length;   // 配列の要素数
    };

    // 音声処理のメイン関数
    DLLEXPORT int process_vocal(CNoteEvent* note) {
        if (!note || !note->pitch_curve) {
            return -1;
        }

        // 標準出力に出力（macOSのターミナルに表示されます）
        std::printf("[Engine] Note:%d, Frames:%d, FirstPitch:%.2f Hz\n", 
                    note->note_number, note->pitch_length, note->pitch_curve[0]);
        
        return 0;
    }
}
