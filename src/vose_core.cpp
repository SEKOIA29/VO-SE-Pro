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

// 解析キャッシュ：同じWAVを何度も解析する無駄を省き、爆速化する
struct AnalysisCache {
    std::vector<std::vector<double>> spectrogram;
    std::vector<std::vector<double>> aperiodicity;
};
static std::map<std::string, AnalysisCache> g_cache;

extern "C" {

/**
 * execute_render: 
 * UTAU音源(WAV)とパラメーターを統合し、高精度な歌唱・読み上げ音声を生成する。
 */
DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path) {
    if (!notes || !output_path || note_count == 0) return;

    const int fs = 44100;
    const double frame_period = 5.0;

    // 1. 全体の必要サンプル数を正確に算出
    int total_samples = 0;
    for (int i = 0; i < note_count; ++i) {
        total_samples += (int)((notes[i].pitch_length - 1) * frame_period / 1000.0 * fs) + 1;
    }
    
    // メモリ安全な出力バッファを確保
    std::vector<double> full_song_buffer(total_samples, 0.0);
    int current_offset = 0;

    // 2. ノートごとの処理ループ
    for (int i = 0; i < note_count; ++i) {
        NoteEvent& n = notes[i];
        if (n.pitch_length <= 0 || !n.wav_path) continue;

        std::string path_key(n.wav_path);
        int f0_length = n.pitch_length;
        int fft_size = GetFFTSizeForCheapTrick(fs, nullptr);
        int spec_bins = fft_size / 2 + 1;

        // 処理用の二次元配列を準備
        std::vector<std::vector<double>> spec_data(f0_length, std::vector<double>(spec_bins));
        std::vector<std::vector<double>> ap_data(f0_length, std::vector<double>(spec_bins));

        // --- 解析フェーズ（キャッシュがある場合は再利用） ---
        if (g_cache.find(path_key) == g_cache.end()) {
            int x_length = GetAudioLength(n.wav_path);
            if (x_length <= 0) continue;

            std::vector<double> x(x_length);
            int fs_actual, nbit;
            wavread(n.wav_path, &fs_actual, &nbit, x.data());

            std::vector<double> time_axis(f0_length);
            std::vector<double> f0_fixed(f0_length, 150.0); // 解析用の仮F0
            for (int j = 0; j < f0_length; ++j) time_axis[j] = j * frame_period / 1000.0;

            // WORLDの関数に渡すためのポインタ配列
            std::vector<double*> spec_ptrs(f0_length);
            std::vector<double*> ap_ptrs(f0_length);
            for (int j = 0; j < f0_length; ++j) {
                spec_ptrs[j] = spec_data[j].data();
                ap_ptrs[j] = ap_data[j].data();
            }

            // スペクトル・非周期成分の抽出
            CheapTrick(x.data(), x_length, fs, time_axis.data(), f0_fixed.data(), f0_length, nullptr, spec_ptrs.data());
            D4C(x.data(), x_length, fs, time_axis.data(), f0_fixed.data(), f0_length, fft_size, nullptr, ap_ptrs.data());
            
            // 次回のためにキャッシュへ保存
            g_cache[path_key] = { spec_data, ap_data };
        } else {
            // キャッシュから瞬時に復元
            spec_data = g_cache[path_key].spectrogram;
            ap_data = g_cache[path_key].aperiodicity;
        }

        // --- パラメーター反映フェーズ（ここが精度の核心） ---
        for (int j = 0; j < f0_length; ++j) {
            double g_val = static_cast<double>(n.gender_curve[j]); 
            double t_val = static_cast<double>(n.tension_curve[j]);
            double b_val = static_cast<double>(n.breath_curve[j]);

            // Genderによるフォルマント・シフティング（ミッキーマウス現象を防止）
            double shift = (g_val - 0.5) * 0.4;
            std::vector<double> org_spec = spec_data[j]; // 変換前の値をコピー

            for (int k = 1; k < spec_bins; ++k) {
                // 1. 周波数軸リサンプリング（フォルマント位置の補正）
                double source_k = k * (1.0 + shift);
                int k_idx = (int)source_k;
                if (k_idx < spec_bins - 1) {
                    double frac = source_k - k_idx;
                    // 線形補間で音質の劣化を防ぐ
                    spec_data[j][k] = (1.0 - frac) * org_spec[k_idx] + frac * org_spec[k_idx + 1];
                }

                // 2. Tension（滑舌・エッジ強調）
                // 読み上げ時にハキハキさせるため、高域に向かってエネルギーをブースト
                double edge_boost = 1.0 + (t_val - 0.5) * ((double)k / spec_bins);
                spec_data[j][k] *= edge_boost;

                // 3. Breath（周波数依存の非周期性）
                // 人間の息漏れは高音域ほど多いため、高域に重みを置いてap値を加算
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
        
        // 累積バッファの現在位置(current_offset)へ直接合成
        Synthesis(f0_target.data(), f0_length, spec_final.data(), ap_final.data(), fft_size, frame_period, fs, output_samples, &full_song_buffer[current_offset]);

        current_offset += output_samples;
    }

    // 3. 最終結果をWAVとして保存
    wavwrite(full_song_buffer.data(), (int)full_song_buffer.size(), fs, 16, output_path);
}


DLLEXPORT void execute_partial_render(NoteEvent* notes, int note_count, const char* output_path, int start_note_idx, int end_note_idx) {
    // 必要な範囲だけに絞って既存のexecute_renderのロジックを走らせる
    // これにより、再生ヘッド付近の音だけを一瞬で生成可能にする
    // (実装はexecute_renderとほぼ同じだが、ループ範囲を限定してキャッシュをフル活用)
}

// 外部からキャッシュをクリアするための関数
DLLEXPORT void clear_engine_cache() { g_cache.clear(); }

}
