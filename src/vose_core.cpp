#include <vector>
#include <memory>
#include <string>
#include <map>
#include <algorithm>
#include <cmath>
#include "vose_core.h"

// WORLD Headers
#include "world/synthesis.h"
#include "world/cheaptrick.h"
#include "world/d4c.h"
#include "world/audioio.h"

// 解析キャッシュ：WAVパスをキーにスペクトルデータを保持
struct AnalysisCache {
    std::vector<std::vector<double>> spectrogram;
    std::vector<std::vector<double>> aperiodicity;
};
static std::map<std::string, AnalysisCache> g_cache;

extern "C" {

/**
 * execute_render: 歌唱・読み上げ統合レンダリングエンジン
 */
DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path) {
    if (!notes || !output_path || note_count == 0) return;

    const int fs = 44100;
    const double frame_period = 5.0;

    // 1. 全体サンプル数の計算
    int total_samples = 0;
    for (int i = 0; i < note_count; ++i) {
        total_samples += (int)((notes[i].pitch_length - 1) * frame_period / 1000.0 * fs) + 1;
    }
    std::vector<double> full_song_buffer(total_samples, 0.0);
    int current_offset = 0;

    for (int i = 0; i < note_count; ++i) {
        NoteEvent& n = notes[i];
        if (n.pitch_length <= 0 || !n.wav_path) continue;

        std::string path_key(n.wav_path);
        int f0_length = n.pitch_length;
        int fft_size = GetFFTSizeForCheapTrick(fs, nullptr);
        int spec_bins = fft_size / 2 + 1;

        // 作業用バッファ（std::vectorで自動メモリ管理）
        std::vector<std::vector<double>> spec_data(f0_length, std::vector<double>(spec_bins));
        std::vector<std::vector<double>> ap_data(f0_length, std::vector<double>(spec_bins));

        // --- 解析フェーズ（キャッシュ活用） ---
        if (g_cache.find(path_key) == g_cache.end()) {
            int x_length = GetAudioLength(n.wav_path);
            std::vector<double> x(x_length);
            int fs_actual, nbit;
            wavread(n.wav_path, &fs_actual, &nbit, x.data());

            std::vector<double> time_axis(f0_length);
            std::vector<double> f0_fixed(f0_length, 150.0); 
            for (int j = 0; j < f0_length; ++j) time_axis[j] = j * frame_period / 1000.0;

            std::vector<double*> spec_ptrs(f0_length);
            std::vector<double*> ap_ptrs(f0_length);
            for (int j = 0; j < f0_length; ++j) {
                spec_ptrs[j] = spec_data[j].data();
                ap_ptrs[j] = ap_data[j].data();
            }

            CheapTrick(x.data(), x_length, fs, time_axis.data(), f0_fixed.data(), f0_length, nullptr, spec_ptrs.data());
            D4C(x.data(), x_length, fs, time_axis.data(), f0_fixed.data(), f0_length, fft_size, nullptr, ap_ptrs.data());
            
            g_cache[path_key] = { spec_data, ap_data };
        } else {
            spec_data = g_cache[path_key].spectrogram;
            ap_data = g_cache[path_key].aperiodicity;
        }

        // --- 高精度パラメーター加工フェーズ ---
        for (int j = 0; j < f0_length; ++j) {
            double g_val = static_cast<double>(n.gender_curve[j]); 
            double t_val = static_cast<double>(n.tension_curve[j]);
            double b_val = static_cast<double>(n.breath_curve[j]);

            // フォルマント・シフト量の計算 (0.5基準で ±20%)
            double shift = (g_val - 0.5) * 0.4;
            
            // 一時的なスペクトルをコピーして伸縮処理
            std::vector<double> org_spec = spec_data[j];

            for (int k = 1; k < spec_bins; ++k) {
                // 1. フォルマント保護（周波数リサンプリング）
                double source_k = k * (1.0 + shift);
                int k_idx = (int)source_k;
                if (k_idx < spec_bins - 1) {
                    double frac = source_k - k_idx;
                    spec_data[j][k] = (1.0 - frac) * org_spec[k_idx] + frac * org_spec[k_idx + 1];
                }

                // 2. Tension（滑舌・エッジ）: 高域ほど強調
                double edge_boost = 1.0 + (t_val - 0.5) * ((double)k / spec_bins);
                spec_data[j][k] *= edge_boost;

                // 3. Breath（周波数依存の息漏れ）: 高域にノイズを乗せる
                double high_freq_noise = b_val * ((double)k / spec_bins);
                ap_data[j][k] = std::min(1.0, ap_data[j][k] + high_freq_noise);
            }
        }

        // --- 合成フェーズ ---
        std::vector<double*> spec_final(f0_length);
        std::vector<double*> ap_final(f0_length);
        std::vector<double> f0_target(f0_length);
        for(int j=0; j<f0_length; ++j) {
            spec_final[j] = spec_data[j].data();
            ap_final[j] = ap_data[j].data();
            f0_target[j] = static_cast<double>(n.pitch_curve[j]);
        }

        int output_samples = (int)((f0_length - 1) * frame_period / 1000.0 * fs) + 1;
        Synthesis(f0_target.data(), f0_length, spec_final.data(), ap_final.data(), fft_size, frame_period, fs, output_samples, &full_song_buffer[current_offset]);

        current_offset += output_samples;
    }

    // 5. 保存
    wavwrite(full_song_buffer.data(), (int)full_song_buffer.size(), fs, 16, output_path);
}

// メモリ解放用
DLLEXPORT void clear_engine_cache() { g_cache.clear(); }

}
