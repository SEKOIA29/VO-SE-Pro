#ifndef VOSE_CORE_H
#define VOSE_CORE_H

#include <stdint.h>

#ifdef _WIN32
    #define DLLEXPORT __declspec(dllexport)
#else
    #define DLLEXPORT __attribute__((visibility("default")))
#endif

// extern "C" を使わないと、Pythonが関数を見つけられません
extern "C" {

    // Python側の NoteStructure とバイナリレベルで一致させる
    typedef struct {
        float pitch_hz;      // 基本音程(Hz)
        float start_sec;     // 開始時間(秒)
        float duration_sec;  // 長さ(秒)
        float pre_utterance; // 先行発声(秒)
        float overlap;       // オーバーラップ(秒)
        const char* wav_path; // WAVファイルのフルパス
        
        // --- WORLD合成に必須のメンバを追加 ---
        float* pitch_curve;  // NumPyから渡される時系列Hz配列(ポインタ)
        int pitch_length;    // 配列の要素数
    } NoteEvent;

    // notes: NoteEventの配列, note_count: 要素数, output_path: 保存先
    DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path);
    
    // エンジン生存確認用
    DLLEXPORT float get_engine_version(void);

} // extern "C"

#endif
