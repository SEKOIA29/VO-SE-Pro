//vo_se_engine .h
#include <stdint.h>

// Python側の NoteStructure とバイナリレベルで一致させる
typedef struct {
    float pitch_hz;      // 音程(Hz)
    float start_sec;     // 開始時間(秒)
    float duration_sec;  // 長さ(秒)
    float pre_utterance; // 先行発声(秒)
    float overlap;       // オーバーラップ(秒)
    const char* wav_path; // WAVファイルのフルパス (char_p)
} NoteEvent;

// 外部（Python）から呼び出せる関数
// notes: NoteEventの配列, note_count: 配列の要素数, output_path: 保存先
void execute_render(NoteEvent* notes, int note_count, const char* output_path);
