#ifndef VOSE_CORE_H
#define VOSE_CORE_H

#include <stdint.h>

#ifdef _WIN32
    #define DLLEXPORT __declspec(dllexport)
#else
    #define DLLEXPORT __attribute__((visibility("default")))
#endif

extern "C" {

    // NoteEvent構造体: Python側の ctypes.Structure と完全に一致させる
    typedef struct {
        float pitch_hz;       // 代表音高(Hz)
        float start_sec;      // 開始(秒)
        float duration_sec;   // 長さ(秒)
        float pre_utterance;  // 先行発声(秒)
        float overlap;        // 重なり(秒)
        const char* wav_path; // 原音WAVへのパス
        
        float* pitch_curve;   // 時系列ピッチ配列(NumPy)へのポインタ
        int pitch_length;     // 配列の長さ
    } NoteEvent;

    // 関数宣言
    DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path);
    DLLEXPORT void process_voice(float* buffer, int length);
    DLLEXPORT float get_engine_version(void);

} // extern "C"

#endif
