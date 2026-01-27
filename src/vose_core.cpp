#include <vector>
#include <string>
#include <map>
#include <algorithm>
#include <cmath>
#include "vose_core.h"

// WORLDライブラリの全機能をフル活用
#include "world/synthesis.h"
#include "world/cheaptrick.h"
#include "world/d4c.h"
#include "world/audioio.h"

struct EmbeddedVoice {
    std::vector<double> waveform;
    int fs;
};
static std::map<std::string, EmbeddedVoice> g_voice_db;

extern "C" {

/**
 * 音源登録（無省略）
 */
DLLEXPORT void load_embedded_resource(const char* phoneme, const int16_t* raw_data, int sample_count) {
    if (!phoneme || !raw_data) return;
    std::string key(phoneme);
    
    EmbeddedVoice ev;
    ev.waveform.assign(sample_count, 0.0);
    ev.fs = 44100;
    
    // 整数から浮動小数点への厳密な変換
    for (int i = 0; i < sample_count; ++i) {
        ev.waveform[i] = static_cast<double>(raw_data[i]) / 32768.0;
    }
    g_voice_db[key] = std::move(ev);
}

/**
 * execute_render (真のフルスペック版)
 */
DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path) {
    if (!notes || note_count == 0 || !output_path) return;

    const int fs = 44100;
    const double frame_period = 5.0;

    // 1. 全体バッファの計算とゼロ初期化（省略なし）
    int total_samples = 0;
    for (int i = 0; i < note_count; ++i) {
        total_samples += static_cast<int>((notes[i].pitch_length - 1) * frame_period / 1000.0 * fs) + 1;
    }
    std::vector<double> full_song_buffer(total_samples, 0.0);
    int current_offset = 0;

    // 2. ノートごとの合成処理
    for (int i = 0; i < note_count; ++i) {
        NoteEvent& n = notes[i];
        if (g_voice_db.find(n.wav_path) == g_voice_db.end()) continue;
        
        EmbeddedVoice& ev = g_voice_db[n.wav_path];
        int f0_length = n.pitch_length;
        int fft_size = GetFFTSizeForCheapTrick(fs, nullptr);
        int spec_bins = fft_size / 2 + 1;

        // --- 内部バッファの厳密な管理 ---
        std::vector<double*> spec_ptrs(f0_length);
        std::vector<double*> ap_ptrs(f0_length);
        std::vector<std::vector<double>> spec_data(f0_length, std::vector<double>(spec_bins, 0.0));
        std::vector<std::vector<double>> ap_data(f0_length, std::vector<double>(spec_bins, 0.0));

        for (int j = 0; j < f0_length; ++j) {
            spec_ptrs[j] = spec_data[j].data();
            ap_ptrs[j] = ap_data[j].data();
        }

        // --- タイムスタンプ軸の生成 ---
        std::vector<double> time_axis(f0_length);
        double source_duration = static_cast<double>(ev.waveform.size()) / fs;
        for (int j = 0; j < f0_length; ++j) {
            // ノートの長さに合わせて音源の読み取り位置を伸縮させる
            time_axis[j] = (static_cast<double>(j) / (f0_length - 1)) * source_duration;
        }

        // WORLD解析（CheapTrick & D4C）
        std::vector<double> f0_fixed(f0_length, 150.0);
        CheapTrick(ev.waveform.data(), static_cast<int>(ev.waveform.size()), fs, time_axis.data(), f0_fixed.data(), f0_length, nullptr, spec_ptrs.data());
        D4C(ev.waveform.data(), static_cast<int>(ev.waveform.size()), fs, time_axis.data(), f0_fixed.data(), f0_length, fft_size, nullptr, ap_ptrs.data());

        // --- パラメータ反映：Gender/Tension/Breath (全ループ展開) ---
        for (int j = 0; j < f0_length; ++j) {
            double shift_factor = (n.gender_curve[j] - 0.5) * 0.4;
            double tension = n.tension_curve[j];
            double breath = n.breath_curve[j];

            std::vector<double> spec_temp = spec_data[j]; // 補間用の一時コピー
            for (int k = 1; k < spec_bins; ++k) {
                // フォルマント・シフティング（リサンプリング）
                double src_k = static_cast<double>(k) * (1.0 + shift_factor);
                int k0 = static_cast<int>(src_k);
                int k1 = std::min(k0 + 1, spec_bins - 1);
                double frac = src_k - k0;
                
                if (k0 < spec_bins - 1) {
                    spec_data[j][k] = (1.0 - frac) * spec_temp[k0] + frac * spec_temp[k1];
                }

                // 分岐なしの特性付与
                double freq_ratio = static_cast<double>(k) / spec_bins;
                spec_data[j][k] *= (1.0 + (tension - 0.5) * freq_ratio);
                ap_data[j][k] = std::min(1.0, ap_data[j][k] + (breath * freq_ratio));
            }
        }

        // 最終波形合成
        int out_samples = static_cast<int>((f0_length - 1) * frame_period / 1000.0 * fs) + 1;
        if (current_offset + out_samples <= total_samples) {
            Synthesis(n.pitch_curve, f0_length, spec_ptrs.data(), ap_ptrs.data(), fft_size, frame_period, fs, out_samples, &full_song_buffer[current_offset]);
            current_offset += out_samples;
        }
    }

    // 3. ファイル保存
    wavwrite(full_song_buffer.data(), static_cast<int>(full_song_buffer.size()), fs, 16, output_path);
}

}
