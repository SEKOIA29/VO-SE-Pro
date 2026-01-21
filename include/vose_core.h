#ifndef VOSE_CORE_H
#define VOSE_CORE_H

#ifdef _WIN32
  #define DLLEXPORT __declspec(dllexport)
#else
  #define DLLEXPORT __attribute__((visibility("default")))
#endif

extern "C" {
    // Python側の CNoteEvent とメモリレイアウトを統一
    struct CNoteEvent {
        int note_number;      // ノート番号 (60=C4)
        float start_time;     // 開始時間 (秒)
        float duration;       // 長さ (秒)
        int velocity;         // ベロシティ (0-127)
        float pre_utterance;  // 先吹き
        float overlap;        // オーバーラップ
        
        // 音素リスト（最大8つ）
        const char* phonemes[8]; 
        int phoneme_count;    // 実際に使っている音素の数
        
        // ピッチデータ（今回追加した重要項目）
        float* pitch_curve;   // Hz配列へのポインタ
        int pitch_length;     // 配列の長さ（フレーム数）
    };

    // エンジンのエントリーポイント
    DLLEXPORT int process_vocal(CNoteEvent* note);
}

#endif
