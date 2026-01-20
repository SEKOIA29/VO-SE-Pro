#include <iostream>
#include <vector>

// WindowsでのDLLエクスポート用マクロ
#ifdef _WIN32
#define DLLEXPORT __declspec(dllexport)
#else
#define DLLEXPORT
#endif

// Python側の CNoteEvent 構造体とメモリレイアウトを完全に一致させる
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
        float* pitch_curve; // Pythonから渡される float32 配列へのポインタ
        int pitch_length;   // 配列の要素数
    };

    // 音声処理のメイン関数（テスト用）
    DLLEXPORT int process_vocal(CNoteEvent* note) {
        if (!note || !note->pitch_curve) {
            return -1; // エラー
        }

        // Pythonから渡されたデータが正しいかコンソールに出力して確認
        std::cout << "[C++ Engine] Processing Note Number: " << note->note_number << std::endl;
        std::cout << "[C++ Engine] Pitch Array Length: " << note->pitch_length << std::endl;
        
        if (note->pitch_length > 0) {
            std::cout << "[C++ Engine] First Pitch Hz: " << note->pitch_curve[0] << " Hz" << std::endl;
        }

        // ここに将来的に WORLD (cppworld) の合成ロジックを移植する
        return 0; // 成功
    }
}
