#include <stdio.h>
#include <stdlib.h>
#include <vector>

// 自分のヘッダー
#include "vose_core.h" 

// WORLDのヘッダー（パスを world/ から始める）
#include "world/synthesis.h"
#include "world/cheaptrick.h"
#include "world/d4c.h"
#include "world/dio.h"
#include "world/stonemask.h"

extern "C" {

/**
 * execute_render
 * Pythonから渡されたノート情報を元に、WORLDエンジンで合成を行う主関数
 */
DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path) {
    if (notes == nullptr || output_path == nullptr) {
        fprintf(stderr, "[VO-SE Error] 引数が無効です。\n");
        return;
    }

    printf("[VO-SE Core] レンダリング開始: %s\n", output_path);

    // WORLD用の基本設定
    const int fs = 44100;
    const double frame_period = 5.0; // 5ms周期

    for (int i = 0; i < note_count; i++) {
        NoteEvent* n = &notes[i];
        
        // 安全のためにWAVパスを確認
        const char* wav_src = n->wav_path ? n->wav_path : "不明なソース";
        
        printf("  [Note %d] 解析中: %s\n", i, wav_src);
        printf("    - 基本周波数: %.2f Hz / データ長: %d フレーム\n", n->pitch_hz, n->pitch_length);

        // --- WORLD合成のコアステップ ---
        if (n->pitch_curve != nullptr && n->pitch_length > 0) {
            
            // 1. Python(float*)をWORLD(double*)に変換
            std::vector<double> f0(n->pitch_length);
            for (int j = 0; j < n->pitch_length; j++) {
                f0[j] = static_cast<double>(n->pitch_curve[j]);
            }

            // TODO: ここで wav_path から波形を読み込み、CheapTrick等で解析を行う
            // 現在は構造の確認のみ
            printf("    - ピッチデータのC++変換に成功。WORLD合成準備完了。\n");
        }
    }

    printf("[VO-SE Core] 全行程を終了。出力ファイルを作成します。\n");
}

/**
 * process_voice
 * 生の音声波形データ（バッファ）に対して直接ゲイン調整などを行う
 */
DLLEXPORT void process_voice(float* buffer, int length) {
    if (buffer == nullptr) return;
    for (int i = 0; i < length; i++) {
        buffer[i] *= 0.8f; 
    }
}

/**
 * get_engine_version
 * バージョン情報の取得
 */
DLLEXPORT float get_engine_version(void) {
    return 2.0f; 
}

} // extern "C"
