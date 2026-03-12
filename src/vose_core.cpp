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
            flat_spec.resize(static_cast<size_t>(reserved_f0) * reserved_bins);
            flat_ap  .resize(static_cast<size_t>(reserved_f0) * reserved_bins);
            spec_tmp .resize(reserved_bins);
            spec_ptrs.resize(reserved_f0);
            ap_ptrs  .resize(reserved_f0);
            need_rebuild = true;
        }
        if (need_rebuild)
            for (int i = 0; i < reserved_f0; ++i) {
                spec_ptrs[i] = &flat_spec[static_cast<size_t>(i) * reserved_bins];
                ap_ptrs  [i] = &flat_ap  [static_cast<size_t>(i) * reserved_bins];
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

static constexpr int    kFs               = 44100;
static constexpr double kFramePeriod      = 5.0;
static constexpr double kInv32768         = 1.0 / 32768.0;
static constexpr int    kCrossfadeSamples = static_cast<int>(kFs * 0.030); // 30ms

// ============================================================
// analyze_source_f0
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
            tl_scratch.time_harvest.data(), tl_scratch.f0_harvest.data());

    double last_voiced = 150.0;
    for (int i = 0; i < harvest_len; ++i) {
        if (tl_scratch.f0_harvest[i] > 0.0) last_voiced = tl_scratch.f0_harvest[i];
        else                                 tl_scratch.f0_harvest[i] = last_voiced;
    }
    return harvest_len;
}

// ============================================================
// resample_curve
// ============================================================

static inline double resample_curve(const double* curve, int src_len,
                                     int dst_idx, int dst_len)
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
// ============================================================

static void apply_crossfade(std::vector<double>& dst, int64_t dst_size,
                             const std::vector<double>& src, int64_t src_size,
                             int64_t offset, int xfade_len)
{
    const int safe_xfade = static_cast<int>(
        std::min<int64_t>(xfade_len,
            std::min(src_size, dst_size - offset)));

    for (int s = 0; s < safe_xfade; ++s) {
        const double t       = static_cast<double>(s) / safe_xfade;
        const double fade_in = 0.5 * (1.0 - std::cos(M_PI * t));
        const int64_t di     = offset + s;
        if (di >= dst_size) break;
        dst[di] = dst[di] * (1.0 - fade_in) + src[s] * fade_in;
    }

    const int64_t body_end = std::min(offset + src_size, dst_size);
    for (int64_t s = offset + safe_xfade; s < body_end; ++s)
        dst[s] = src[s - offset];
}

// ============================================================
// voice_exists (ロックなしで呼んではいけない専用ヘルパー)
// ============================================================

static const EmbeddedVoice* find_voice(const char* key)
{
    std::lock_guard<std::mutex> lock(g_voice_db_mutex);
    auto it = g_voice_db.find(key ? key : "");
    return (it != g_voice_db.end()) ? &it->second : nullptr;
}

// ============================================================
// extern "C" API
// ============================================================

extern "C" {

void init_official_engine() { register_all_embedded_voices(); }

DLLEXPORT void load_embedded_resource(const char* phoneme,
                                      const int16_t* raw_data, int sample_count)
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
 * execute_render  (v7)
 *
 * v6 からの修正点:
 *
 *   [FIX-1] total_samples をパス1で正確に求められない問題を解決。
 *           パス1でボイスの存在を先行チェックし、実際にクロスフェードが
 *           発生するノート間数を数えて total_samples を正確に計算する。
 *           これにより末尾ノートのクリップを根絶する。
 *
 *   [FIX-2] breath シェイピングを tension と対称な設計に統一。
 *           breath も (breath - 0.5) * 係数 で中心化し、
 *           breath=0.5 がニュートラル（変化なし）になるよう修正。
 *           係数は breath=1.0 で ap を最大 +0.5 押し上げる 1.0 とした。
 *
 *   [FIX-3] スキップノートの current_offset を正確に管理。
 *           スキップノートは「クロスフェードなし・丸々進める」が正しく、
 *           かつ last_note_rendered=false にリセットするため
 *           後続ノートのオフセットもずれない。
 *           （v6 でスキップ後オフセットがずれていた根本原因を除去）
 */
DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path)
{
    if (!notes || note_count <= 0 || !output_path) return;

    const int fft_size  = GetFFTSizeForCheapTrick(kFs, nullptr);
    const int spec_bins = fft_size / 2 + 1;

    // ----------------------------------------------------------------
    // パス1: total_samples を正確に計算する
    //
    // [FIX-1] クロスフェードが実際に発生するのは
    //         「連続して音源ありノートが並ぶ境界」だけ。
    //         スキップノートを挟む場合はその境界ではクロスフェードしない。
    //         よって「音源ありノートの連続区間ごとの境界数」を数える。
    //
    // 例: [有,有,無,有,有,有] → 境界は (有,有) + (有,有) + (有,有) = 3回
    //     total_samples から 3 * kCrossfadeSamples を引く
    // ----------------------------------------------------------------

    int     max_f0           = 0;
    int64_t total_samples    = 0;
    int     xfade_count      = 0;   // 実際にクロスフェードが発生する回数
    bool    prev_has_voice   = false;

    for (int i = 0; i < note_count; ++i) {
        const int f = notes[i].pitch_length;
        if (f > max_f0) max_f0 = f;
        total_samples += static_cast<int64_t>((f - 1) * kFramePeriod / 1000.0 * kFs) + 1;

        const bool cur_has_voice = (find_voice(notes[i].wav_path) != nullptr);
        if (cur_has_voice && prev_has_voice) ++xfade_count;
        prev_has_voice = cur_has_voice;
    }

    total_samples -= static_cast<int64_t>(kCrossfadeSamples) * xfade_count;
    if (total_samples <= 0) return;

    tl_scratch.ensure_spec(max_f0, spec_bins);
    std::vector<double> full_song_buffer(total_samples, 0.0);
    std::vector<double> note_buf;

    int64_t current_offset     = 0;
    bool    last_note_rendered = false;

    // ----------------------------------------------------------------
    // パス2: ノートごとの合成
    // ----------------------------------------------------------------

    for (int i = 0; i < note_count; ++i) {
        NoteEvent& n = notes[i];

        const EmbeddedVoice* ev_ptr = find_voice(n.wav_path);

        const int64_t note_samples =
            static_cast<int64_t>((n.pitch_length - 1) * kFramePeriod / 1000.0 * kFs) + 1;

        if (!ev_ptr) {
            // [FIX-3] スキップ: フラグリセット・丸々進める（オーバーラップなし）
            last_note_rendered = false;
            current_offset    += note_samples;
            continue;
        }

        const EmbeddedVoice& ev     = *ev_ptr;
        const int            f0_len = n.pitch_length;

        // Harvest 解析
        const int harvest_len = analyze_source_f0(ev, kFramePeriod);
        tl_scratch.ensure_spec(harvest_len, spec_bins);

        // WORLD 解析
        CheapTrick(ev.waveform.data(), static_cast<int>(ev.waveform.size()), kFs,
                   tl_scratch.time_harvest.data(), tl_scratch.f0_harvest.data(),
                   harvest_len, nullptr, tl_scratch.spec_ptrs.data());

        D4C(ev.waveform.data(), static_cast<int>(ev.waveform.size()), kFs,
            tl_scratch.time_harvest.data(), tl_scratch.f0_harvest.data(),
            harvest_len, fft_size, nullptr, tl_scratch.ap_ptrs.data());

        // pitch_curve を harvest_len にリサンプル
        for (int j = 0; j < harvest_len; ++j)
            tl_scratch.f0_harvest[j] =
                resample_curve(n.pitch_curve, f0_len, j, harvest_len);

        // パラメータ・シェイピング
        double* const spec_tmp = tl_scratch.spec_tmp.data();
        for (int j = 0; j < harvest_len; ++j) {
            double* sr = tl_scratch.spec_ptrs[j];
            double* ar = tl_scratch.ap_ptrs[j];

            const double gender  = resample_curve(n.gender_curve,  f0_len, j, harvest_len);
            const double tension = resample_curve(n.tension_curve, f0_len, j, harvest_len);
            const double breath  = resample_curve(n.breath_curve,  f0_len, j, harvest_len);
            const double shift   = (gender - 0.5) * 0.4;

            // Gender: フォルマントシフト
            memcpy(spec_tmp, sr, sizeof(double) * spec_bins);
            for (int k = 0; k < spec_bins; ++k) {
                const double tk = static_cast<double>(k) * (1.0 + shift);
                const int    k0 = static_cast<int>(tk);
                sr[k] = (k0 >= spec_bins - 1)
                    ? spec_tmp[spec_bins - 1]
                    : (1.0 - (tk - k0)) * spec_tmp[k0] + (tk - k0) * spec_tmp[k0 + 1];
            }

            // Tension / Breath
            // [FIX-2] breath を tension と対称な中心化設計に統一。
            //   tension: (tension - 0.5) → 0.5 がニュートラル
            //   breath:  (breath  - 0.5) → 0.5 がニュートラル（修正前は 0.0 がニュートラル）
            //   breath の係数 1.0 は tension の係数と同スケール。
            //   breath=1.0 → ap を高域で最大 +0.5 押し上げ（息っぽさが強まる）
            //   breath=0.0 → ap を高域で最大 -0.5 引き下げ（クリアな声になる）
            const double inv = 1.0 / (spec_bins - 1);
            for (int k = 0; k < spec_bins; ++k) {
                const double fw = static_cast<double>(k) * inv;
                sr[k] *= (1.0 + (tension - 0.5) * fw);
                ar[k]  = std::clamp(ar[k] + (breath - 0.5) * fw, 0.0, 1.0);
            }
        }

        // 波形合成
        note_buf.assign(note_samples, 0.0);
        Synthesis(tl_scratch.f0_harvest.data(), harvest_len,
                  tl_scratch.spec_ptrs.data(), tl_scratch.ap_ptrs.data(),
                  fft_size, kFramePeriod, kFs,
                  static_cast<int>(note_samples), note_buf.data());

        // クロスフェード書き込み
        const bool    do_xfade     = last_note_rendered;
        const int64_t write_offset = do_xfade
            ? current_offset - kCrossfadeSamples
            : current_offset;
        const int xfade = do_xfade ? kCrossfadeSamples : 0;

        apply_crossfade(full_song_buffer, total_samples,
                        note_buf, note_samples, write_offset, xfade);

        current_offset += do_xfade
            ? note_samples - kCrossfadeSamples
            : note_samples;

        last_note_rendered = true;
    }

    wavwrite(full_song_buffer.data(),
             static_cast<int>(full_song_buffer.size()), kFs, 16, output_path);
}

} // extern "C"
