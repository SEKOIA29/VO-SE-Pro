#include <vector>
#include <string>
#include <map>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <cstdint>
#include <mutex>
#include "vose_core.h"
#include "voice_data.h"

// WORLDライブラリ
#include "world/synthesis.h"
#include "world/cheaptrick.h"
#include "world/d4c.h"
#include "world/harvest.h"
#include "world/audioio.h"
#include "world/constantnumbers.h"

// ============================================================
// データ構造
// ============================================================

struct EmbeddedVoice {
    std::vector<double> waveform;
    int fs;
};

static std::map<std::string, EmbeddedVoice> g_voice_db;
static std::mutex g_voice_db_mutex;

// ============================================================
// SynthesisScratchPad
// ============================================================

struct SynthesisScratchPad {
    std::vector<double>  flat_spec;
    std::vector<double>  flat_ap;
    std::vector<double>  spec_tmp;
    std::vector<double*> spec_ptrs;
    std::vector<double*> ap_ptrs;
    std::vector<double>  f0_harvest;
    std::vector<double>  time_harvest;

    int reserved_f0   = 0;
    int reserved_bins = 0;

    void ensure_spec(int f0_length, int spec_bins) {
        bool need_rebuild = false;
        if (f0_length > reserved_f0 || spec_bins > reserved_bins) {
            reserved_f0   = std::max(f0_length,  reserved_f0);
            reserved_bins = std::max(spec_bins,  reserved_bins);
            flat_spec .resize(static_cast<size_t>(reserved_f0) * reserved_bins);
            flat_ap   .resize(static_cast<size_t>(reserved_f0) * reserved_bins);
            spec_tmp  .resize(reserved_bins);
            spec_ptrs .resize(reserved_f0);
            ap_ptrs   .resize(reserved_f0);
            need_rebuild = true;
        }
        if (need_rebuild) {
            for (int i = 0; i < reserved_f0; ++i) {
                spec_ptrs[i] = &flat_spec[static_cast<size_t>(i) * reserved_bins];
                ap_ptrs  [i] = &flat_ap  [static_cast<size_t>(i) * reserved_bins];
            }
        }
    }

    void ensure_harvest(int length) {
        if (length > static_cast<int>(f0_harvest.size())) {
            f0_harvest  .resize(length);
            time_harvest.resize(length);
        }
    }
};

static thread_local SynthesisScratchPad tl_scratch;

// ============================================================
// 定数
// ============================================================

static constexpr int    kFs          = 44100;
static constexpr double kFramePeriod = 5.0;
static constexpr double kInv32768    = 1.0 / 32768.0;

// クロスフェード長: 30ms
// raised cosine でイコールパワー条件を満たす。
static constexpr int kCrossfadeSamples = static_cast<int>(kFs * 0.030);

// ============================================================
// analyze_source_f0
// Harvest を1回だけ呼び、f0_harvest/time_harvest を埋めて返す。
// 戻り値は解析フレーム数のみ
// ============================================================

static int analyze_source_f0(const EmbeddedVoice& ev, double frame_period)
{
    HarvestOption opt;
    InitializeHarvestOption(&opt);
    opt.frame_period = frame_period;
    opt.f0_floor     = 50.0;
    opt.f0_ceil      = 800.0;

    const int wav_len     = static_cast<int>(ev.waveform.size());
    const int harvest_len = GetSamplesForHarvest(ev.fs, wav_len, frame_period);

    tl_scratch.ensure_harvest(harvest_len);

    Harvest(ev.waveform.data(), wav_len, ev.fs, &opt,
            tl_scratch.time_harvest.data(),
            tl_scratch.f0_harvest.data());

    // 無声フレーム(0Hz)を直前の有声値で補間（CheapTrick破綻防止）
    double last_voiced = 150.0;
    for (int i = 0; i < harvest_len; ++i) {
        if (tl_scratch.f0_harvest[i] > 0.0)
            last_voiced = tl_scratch.f0_harvest[i];
        else
            tl_scratch.f0_harvest[i] = last_voiced;
    }

    return harvest_len;
}

// ============================================================
// resample_curve
// ============================================================

static inline double resample_curve(const double* curve,
                                     int           src_len,
                                     int           dst_idx,
                                     int           dst_len)
{
    if (src_len == 1) return curve[0];
    const double t     = static_cast<double>(dst_idx) / std::max(dst_len - 1, 1);
    const double src_f = t * (src_len - 1);
    const int    j0    = static_cast<int>(src_f);
    const int    j1    = std::min(j0 + 1, src_len - 1);
    const double frac  = src_f - j0;
    return (1.0 - frac) * curve[j0] + frac * curve[j1];
}

// ============================================================
// apply_crossfade
//
// dst の offset 位置に src をオーバーラップ加算する。
//
// 【v4 からの修正】
//   v4 はノートを隙間なく連結した後にブレンドしていたため、
//   クロスフェード区間が「前ノートの末尾」と重ならず無意味だった。
//
//   v5 では呼び出し側が offset を kCrossfadeSamples 分だけ
//   巻き戻して渡す（前ノートの末尾とオーバーラップさせる）。
//   この関数自体は純粋に「offset 位置から src を raised cosine で書く」
//   だけに責務を限定している。
//
// xfade_len == 0 のとき（最初のノート）は単純上書き。
// ============================================================

static void apply_crossfade(std::vector<double>&       dst,
                             int64_t                    dst_size,
                             const std::vector<double>& src,
                             int64_t                    src_size,
                             int64_t                    offset,
                             int                        xfade_len)
{
    const int64_t remaining  = dst_size - offset;
    const int safe_xfade = static_cast<int>(
        std::min<int64_t>(xfade_len, std::min(src_size, remaining)));

    // フェードイン区間: 前ノートの末尾（dst に残存）と今のノート先頭をブレンド
    for (int s = 0; s < safe_xfade; ++s) {
        const double t        = static_cast<double>(s) / safe_xfade;
        const double fade_in  = 0.5 * (1.0 - std::cos(M_PI * t));
        const double fade_out = 1.0 - fade_in;
        const int64_t dst_idx = offset + s;
        if (dst_idx >= dst_size) break;
        dst[dst_idx] = dst[dst_idx] * fade_out + src[s] * fade_in;
    }

    // フェードなし区間: クロスフェード後はそのまま上書き
    const int64_t body_start = offset + safe_xfade;
    const int64_t body_end   = std::min(offset + src_size, dst_size);
    for (int64_t s = body_start; s < body_end; ++s) {
        dst[s] = src[s - offset];
    }
}

// ============================================================
// extern "C" API
// ============================================================

extern "C" {

void init_official_engine() {
    register_all_embedded_voices();
}

DLLEXPORT void load_embedded_resource(const char*    phoneme,
                                      const int16_t* raw_data,
                                      int            sample_count)
{
    if (!phoneme || !raw_data || sample_count <= 0) return;

    EmbeddedVoice ev;
    ev.fs = kFs;
    ev.waveform.resize(sample_count);
    for (int i = 0; i < sample_count; ++i)
        ev.waveform[i] = static_cast<double>(raw_data[i]) * kInv32768;

    std::lock_guard<std::mutex> lock(g_voice_db_mutex);
    g_voice_db[phoneme] = std::move(ev);
}

/**
 * execute_render  (v5)
 *
 * v4 からの修正点:
 *
 *   [FIX-XF-1] クロスフェード区間を前ノートの末尾と実際にオーバーラップさせる。
 *              i > 0 のノートは write_offset を kCrossfadeSamples 分だけ
 *              巻き戻してから apply_crossfade を呼ぶ。
 *
 *   [FIX-XF-2] total_samples をオーバーラップ分だけ短縮する。
 *              (note_count - 1) * kCrossfadeSamples を差し引くことで
 *              末尾の余分な無音を排除する。
 *
 *   [FIX-XF-3] current_offset の更新も (note_samples - kCrossfadeSamples) に
 *              変更し、次ノートが正しい位置から始まるようにする。
 *              最初のノートだけはオーバーラップなしで通常通り進める。
 *
 *   [CLEANUP]  HarvestResult 構造体を廃止し analyze_source_f0 を int 返りに戻す。
 *              median_f0 は現時点で使用しないため保持しない。
 */
DLLEXPORT void execute_render(NoteEvent*  notes,
                              int         note_count,
                              const char* output_path)
{
    if (!notes || note_count <= 0 || !output_path) return;

    const int fft_size  = GetFFTSizeForCheapTrick(kFs, nullptr);
    const int spec_bins = fft_size / 2 + 1;

    // ---- パス1: 総サンプル数 & 最大フレーム長の先行計算 ----
    int     max_f0        = 0;
    int64_t total_samples = 0;
    for (int i = 0; i < note_count; ++i) {
        const int f0_len = notes[i].pitch_length;
        if (f0_len > max_f0) max_f0 = f0_len;
        total_samples += static_cast<int64_t>(
            (f0_len - 1) * kFramePeriod / 1000.0 * kFs) + 1;
    }

    // [FIX-XF-2] ノート間オーバーラップ分だけ全体長を短縮
    // note_count == 1 のときは引かない（オーバーラップなし）
    if (note_count > 1) {
        total_samples -= static_cast<int64_t>(kCrossfadeSamples) * (note_count - 1);
    }
    if (total_samples <= 0) return;  // 全ノートが極端に短い異常ケース

    tl_scratch.ensure_spec(max_f0, spec_bins);

    std::vector<double> full_song_buffer(total_samples, 0.0);
    std::vector<double> note_buf;

    // current_offset は「次ノートの書き込み開始位置（オーバーラップ前）」
    int64_t current_offset = 0;

    // ---- パス2: ノートごとの合成 ----
    for (int i = 0; i < note_count; ++i) {
        NoteEvent& n = notes[i];

        const EmbeddedVoice* ev_ptr = nullptr;
        {
            std::lock_guard<std::mutex> lock(g_voice_db_mutex);
            auto it = g_voice_db.find(n.wav_path ? n.wav_path : "");
            if (it != g_voice_db.end()) ev_ptr = &it->second;
        }

        const int64_t note_samples =
            static_cast<int64_t>(
                (n.pitch_length - 1) * kFramePeriod / 1000.0 * kFs) + 1;

        if (!ev_ptr) {
            // 音源なし: クロスフェード込みでオフセットを進める
            const int64_t advance = (i == 0)
                ? note_samples
                : note_samples - kCrossfadeSamples;
            current_offset += advance;
            continue;
        }

        const EmbeddedVoice& ev     = *ev_ptr;
        const int            f0_len = n.pitch_length;

        // Harvest で実F0を解析
        const int harvest_len = analyze_source_f0(ev, kFramePeriod);
        tl_scratch.ensure_spec(harvest_len, spec_bins);

        // WORLD 解析
        CheapTrick(ev.waveform.data(),
                   static_cast<int>(ev.waveform.size()),
                   kFs,
                   tl_scratch.time_harvest.data(),
                   tl_scratch.f0_harvest.data(),
                   harvest_len,
                   nullptr,
                   tl_scratch.spec_ptrs.data());

        D4C(ev.waveform.data(),
            static_cast<int>(ev.waveform.size()),
            kFs,
            tl_scratch.time_harvest.data(),
            tl_scratch.f0_harvest.data(),
            harvest_len,
            fft_size,
            nullptr,
            tl_scratch.ap_ptrs.data());

        // pitch_curve を harvest_len にリサンプル
        for (int j = 0; j < harvest_len; ++j) {
            tl_scratch.f0_harvest[j] =
                resample_curve(n.pitch_curve, f0_len, j, harvest_len);
        }

        // パラメータ・シェイピング
        double* const spec_tmp = tl_scratch.spec_tmp.data();
        for (int j = 0; j < harvest_len; ++j) {
            double* spec_row = tl_scratch.spec_ptrs[j];
            double* ap_row   = tl_scratch.ap_ptrs[j];

            const double gender  = resample_curve(n.gender_curve,  f0_len, j, harvest_len);
            const double tension = resample_curve(n.tension_curve, f0_len, j, harvest_len);
            const double breath  = resample_curve(n.breath_curve,  f0_len, j, harvest_len);
            const double shift   = (gender - 0.5) * 0.4;

            memcpy(spec_tmp, spec_row, sizeof(double) * spec_bins);
            for (int k = 0; k < spec_bins; ++k) {
                const double target_k = static_cast<double>(k) * (1.0 + shift);
                const int    k0       = static_cast<int>(target_k);
                if (k0 >= spec_bins - 1) {
                    spec_row[k] = spec_tmp[spec_bins - 1];
                } else {
                    const double frac = target_k - k0;
                    spec_row[k] = (1.0 - frac) * spec_tmp[k0] + frac * spec_tmp[k0 + 1];
                }
            }

            const double inv_bins_m1 = 1.0 / (spec_bins - 1);
            for (int k = 0; k < spec_bins; ++k) {
                const double freq_w = static_cast<double>(k) * inv_bins_m1;
                spec_row[k] *= (1.0 + (tension - 0.5) * freq_w);
                ap_row[k]    = std::clamp(ap_row[k] + (breath * freq_w), 0.0, 1.0);
            }
        }

        // ノート波形を note_buf へ合成
        note_buf.assign(note_samples, 0.0);
        Synthesis(tl_scratch.f0_harvest.data(),
                  harvest_len,
                  tl_scratch.spec_ptrs.data(),
                  tl_scratch.ap_ptrs.data(),
                  fft_size, kFramePeriod, kFs,
                  static_cast<int>(note_samples),
                  note_buf.data());

        // [FIX-XF-1] i > 0 のノートは kCrossfadeSamples 分だけ巻き戻して配置
        // → 前ノートの末尾と今のノートの先頭が実際にオーバーラップする
        const int64_t write_offset = (i == 0)
            ? current_offset
            : current_offset - kCrossfadeSamples;

        const int xfade = (i == 0) ? 0 : kCrossfadeSamples;

        apply_crossfade(full_song_buffer,
                        total_samples,
                        note_buf,
                        note_samples,
                        write_offset,
                        xfade);

        // [FIX-XF-3] オーバーラップ分を除いて次ノードの先頭位置を計算
        const int64_t advance = (i == 0)
            ? note_samples
            : note_samples - kCrossfadeSamples;
        current_offset += advance;
        continue; 
    }

    wavwrite(full_song_buffer.data(),
             static_cast<int>(full_song_buffer.size()),
             kFs, 16, output_path);
}

} // extern "C"
