#ifndef VOSE_CORE_H
#define VOSE_CORE_H

#ifdef _WIN32
    #define DLLEXPORT __declspec(dllexport)
#else
    #define DLLEXPORT
#endif

// GUI（Python）とやり取りするための構造体
// 順序や型をPython側の CNoteEvent と完全に一致させる必要があります
struct NoteEvent {
    const char* wav_path;        // 音源WAVのパス
    float* pitch_curve;          // 周波数(Hz)の配列
    int pitch_length;            // 配列の長さ
    
    // --- 追加：ここがエラーの原因でした ---
    float* gender_curve;         // ジェンダー(0.0-1.0)
    float* tension_curve;        // テンション(0.0-1.0)
    float* breath_curve;         // ブレス(0.0-1.0)
};

extern "C" {
    // レンダリング実行関数
    DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path);
    
    // バージョン取得用
    DLLEXPORT float get_engine_version(void);
}

#endif // VOSE_CORE_H
