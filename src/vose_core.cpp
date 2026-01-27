#include <vector>
#include <string>
#include <map>
#include <algorithm>
#include <cmath>
#include <cstring>
#include "vose_core.h"

// WORLDライブラリ (徹底的に使い倒す)
#include "world/synthesis.h"
#include "world/cheaptrick.h"
#include "world/d4c.h"
#include "world/audioio.h"

// --- グローバルデータベース (スレッドセーフへの布石) ---
struct EmbeddedVoice {
    std::vector<double> waveform;
    int fs;
};
static std::map<std::string, EmbeddedVoice> g_voice_db;

extern "C" {

/**
 * load_embedded_resource (無省略・バリデーション付き)
 */
DLLEXPORT void load_embedded_resource(const char* phoneme, const int16_t* raw_data, int sample_count) {
    if (phoneme == nullptr || raw_data == nullptr || sample_count <= 0) return;
    
    std::string key(phoneme);
    EmbeddedVoice ev;
    ev.waveform.assign(sample_count, 0.0);
    ev.fs = 44100;
    
    // 分岐を排除した高速キャスト変換
    for (int i = 0; i < sample_count; ++i) {
        ev.waveform[i] = static_cast<double>(raw_data[i]) / 32768.0;
    }
    g_voice_db[key] = std::move(ev);
}

/**
 * execute_render (究極の無省略・プロフェッショナル版)
 */
DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path) {
    // 1. パラメータの厳格なバリデーション
    if (notes == nullptr || note_count <= 0 || output_path == nullptr) return;

    const int fs = 44100;
    const double frame_period = 5.0;

    // 2. 最終出力バッファの精密な事前確保
    int64_t total_samples_required = 0;
    for (int i = 0; i < note_count; ++i) {
        total_samples_required += static_cast<int64_t>((notes[i].pitch_length - 1) * frame_period / 1000.0 * fs) + 1;
    }
    
    std::vector<double> full_song_buffer(total_samples_required, 0.0);
    int64_t current_offset = 0;

    // 3. メイン・シンセシス・ループ
    for (int i = 0; i < note_count; ++i) {
        NoteEvent& n = notes[i];
        
        // 音源の存在確認 (ここでコケるとノイズになるので厳密に)
        if (n.wav_path == nullptr || g_voice_db.find(n.wav_path) == g_voice_db.end()) {
            // 見つからない場合はそのノートの長さ分だけオフセットを進める (無音挿入)
            current_offset += static_cast<int64_t>((n.pitch_length - 1) * frame_period / 1000.0 * fs) + 1;
            continue;
        }

        EmbeddedVoice& ev = g_voice_db[n.wav_path];
        const int f0_length = n.pitch_length;
        
        // FFTサイズの動的決定 ( CheapTrickの仕様に完全準拠 )
        int fft_size = GetFFTSizeForCheapTrick(fs, nullptr);
        int spec_bins = fft_size / 2 + 1;

        // --- 内部バッファ：生ポインタ配列の構築 (WORLD APIへの完全適合) ---
        std::vector<double*> spec_ptrs(f0_length);
        std::vector<double*> ap_ptrs(f0_length);
        std::vector<std::vector<double>> spec_data(f0_length, std::vector<double>(spec_bins, 0.0));
        std::vector<std::vector<double>> ap_data(f0_length, std::vector<double>(spec_bins, 0.0));

        for (int j = 0; j < f0_length; ++j) {
            spec_ptrs[j] = spec_data[j].data();
            ap_ptrs[j] = ap_data[j].data();
        }

        // --- タイムストレッチ軸の精密計算 ---
        std::vector<double> time_axis(f0_length);
        double source_duration = static_cast<double>(ev.waveform.size()) / fs;
        for (int j = 0; j < f0_length; ++j) {
            time_axis[j] = (static_cast<double>(j) / (f0_length - 1)) * source_duration;
        }

        // WORLD解析：F0固定でのスペクトル抽出
        std::vector<double> f0_for_analysis(f0_length, 150.0);
        CheapTrick(ev.waveform.data(), static_cast<int>(ev.waveform.size()), fs, time_axis.data(), f0_for_analysis.data(), f0_length, nullptr, spec_ptrs.data());
        D4C(ev.waveform.data(), static_cast<int>(ev.waveform.size()), fs, time_axis.data(), f0_for_analysis.data(), f0_length, fft_size, nullptr, ap_ptrs.data());

        // --- プロフェッショナル・パラメータ・シェイピング (一切の妥協なし) ---
        for (int j = 0; j < f0_length; ++j) {
            const double g_val = n.gender_curve[j];
            const double t_val = n.tension_curve[j];
            const double b_val = n.breath_curve[j];
            const double shift = (g_val - 0.5) * 0.4;

            // スペクトルのコピー (フォルマントシフトの破壊的変更を避けるため)
            std::vector<double> spec_orig = spec_data[j];

            for (int k = 0; k < spec_bins; ++k) {
                // 1. 周波数リサンプリング (Gender)
                double target_k = static_cast<double>(k) * (1.0 + shift);
                int k0 = static_cast<int>(target_k);
                int k1 = std::min(k0 + 1, spec_bins - 1);
                double frac = target_k - k0;
                
                if (k0 < spec_bins - 1) {
                    spec_data[j][k] = (1.0 - frac) * spec_orig[k0] + frac * spec_orig[k1];
                }

                // 2. 高域特性の調整 (Tension / Breath)
                double freq_weight = static_cast<double>(k) / (spec_bins - 1);
                spec_data[j][k] *= (1.0 + (t_val - 0.5) * freq_weight);
                ap_data[j][k] = std::clamp(ap_data[j][k] + (b_val * freq_weight), 0.0, 1.0);
            }
        }

        // --- 波形合成 (出力範囲の最終チェック付き) ---
        int note_samples = static_cast<int>((f0_length - 1) * frame_period / 1000.0 * fs) + 1;
        if (current_offset + note_samples <= total_samples_required) {
            Synthesis(n.pitch_curve, f0_length, spec_ptrs.data(), ap_ptrs.data(), fft_size, frame_period, fs, note_samples, &full_song_buffer[current_offset]);
            current_offset += note_samples;
        }
    }

    // 4. 物理ファイルへの書き出し
    wavwrite(full_song_buffer.data(), static_cast<int>(full_song_buffer.size()), fs, 16, output_path);
}

}
