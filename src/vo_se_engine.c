//vo_se_engine.c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* --- マクロ定義の統一 --- */
#ifdef _WIN32
    #define DLLEXPORT __declspec(dllexport)
#else
    #define DLLEXPORT
#endif

/* --- 構造体の定義 --- */
typedef struct {
    float pitch_hz;
    const char* wav_path;
} NoteEvent;

/* --- 関数1: レンダリング処理 --- */
DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path) {
    printf("[C-Engine] レンダリング開始: %s\n", output_path);

    // 保存先ファイルをバイナリモードで開く
    FILE *f = fopen(output_path, "wb");
    if (!f) {
        printf("[Error] ファイル作成失敗: %s\n", output_path);
        return;
    }

    // ダミーのWAVヘッダー
    fprintf(f, "RIFF....WAVEfmt ");

    // 各音符の処理シミュレーション
    for (int i = 0; i < note_count; i++) {
        if (notes[i].wav_path != NULL) {
            printf("   Processing: %s (Pitch: %.2f Hz)\n", notes[i].wav_path, notes[i].pitch_hz);
        }
    }

    fclose(f);
    printf("[C-Engine] レンダリング成功。\n");
}

/* --- 関数2: 音声エフェクト処理 --- */
DLLEXPORT void process_voice(float* buffer, int length) {
    if (buffer == NULL) return;
    
    for (int i = 0; i < length; i++) {
        // 音量を0.8倍にする
        buffer[i] *= 0.8f; 
    }
}

/* --- 関数3: バージョン確認用 --- */
DLLEXPORT float get_engine_version(void) {
    return 1.0f;
}
