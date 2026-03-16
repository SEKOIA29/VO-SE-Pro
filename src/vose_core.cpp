#include <vector>
#include <string>
#include <map>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <cstdint>
#include <mutex>
#include <shared_mutex>
#include <memory>
#define _USE_MATH_DEFINES  // [FIX-MPI] Windows/GCC で M_PI を有効化
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
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

static std::map<std::string, std::shared_ptr<const EmbeddedVoice>> g_voice_db;
static std::shared_mutex g_voice_db_mutex;

// ============================================================
// oto.init受け渡し
// ============================================================

// oto.ini のエントリを受け取ってエンジン内部に登録
extern "C" void set_voice_library(const char* voice_path);
extern "C" void set_oto_data(const OtoEntry* entries, int count);

// ============================================================
// NoteState / NotePrepass
// ============================================================

enum class NoteState : uint8_t {
    INVALID,     // pitch_length 範囲外 → offset を動かさない
    NO_VOICE,    // pitch_length 有効・音源なし → offset だけ進める
    RENDERABLE,  // pitch_length 有効・音源あり → 合成する
};

// [FIX-BRACE] shared_ptr メンバがあると集成体初期化できないコンパイラ対策。
//             コンストラクタを明示して { } 初期化を保証する。
struct NotePrepass {
    NoteState                            state        = NoteState::INVALID;
    int64_t                              note_samples = 0;
    std::shared_ptr<const EmbeddedVoice> ev;

    NotePrepass() = default;
    NotePrepass(NoteState s, int64_t ns, std::shared_ptr<const EmbeddedVoice> e)
        : state(s), note_samples(ns), ev(std::move(e)) {}
};

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
static constexpr int    kCrossfadeSamples = static_cast<int>(kFs * 0.030);
static constexpr int    kMaxPitchLength   = 120000;

static int64_t note_samples_safe(int pitch_length)
{
    return (static_cast<int64_t>(pitch_length) - 1)
           * kFramePeriod / 1000.0 * kFs + 1;
}

// ============================================================
// find_voice_ref
// ============================================================

static std::shared_ptr<const EmbeddedVoice> find_voice_ref(const char* key)
{
    std::shared_lock<std::shared_mutex> lock(g_voice_db_mutex);
    auto it = g_voice_db.find(key ? key : "");
    if (it == g_voice_db.end()) return nullptr;
    return it->second;
}

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
    if (offset >= dst_size) return;  // [FIX-XF] 負になるケースを防ぐ

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


//先行発音
static std::map<std::string, OtoEntry> g_oto_map;
static std::string g_voice_path;

extern "C" void set_voice_library(const char* voice_path) {
    if (voice_path) g_voice_path = voice_path;
}

extern "C" void set_oto_data(const OtoEntry* entries, int count) {
    std::unique_lock<std::shared_mutex> lock(g_voice_db_mutex);
    g_oto_map.clear();
    for (int i = 0; i < count; ++i)
        g_oto_map[entries[i].alias] = entries[i];
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

    auto ev = std::make_shared<EmbeddedVoice>();
    ev->fs = kFs;
    ev->waveform.resize(sample_count);
    for (int i = 0; i < sample_count; ++i)
        ev->waveform[i] = static_cast<double>(raw_data[i]) * kInv32768;

    std::unique_lock<std::shared_mutex> lock(g_voice_db_mutex);
    g_voice_db[phoneme] = std::move(ev);
}

DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path)
{
    if (!notes || note_count <= 0 || !output_path) return;

    const int fft_size  = GetFFTSizeForCheapTrick(kFs, nullptr);
    const int spec_bins = fft_size / 2 + 1;

    // ----------------------------------------------------------------
    // パス1: NotePrepass 構築
    // ----------------------------------------------------------------

    std::vector<NotePrepass> prepass(note_count);

    int     max_harvest_len = 0;
    int64_t total_samples   = 0;
    int     xfade_count     = 0;
    bool    prev_renderable = false;

    for (int i = 0; i < note_count; ++i) {
        const int pitch_len = notes[i].pitch_length;

        if (pitch_len <= 0 || pitch_len > kMaxPitchLength) {
            std::fprintf(stderr,
                "[vose_core] note[%d] pitch_length=%d out of range (1..%d), skipping.\n",
                i, pitch_len, kMaxPitchLength);
            prepass[i] = NotePrepass(NoteState::INVALID, 0, nullptr);
            prev_renderable = false;
            continue;
        }

        // [FIX-ZENKAKU] 全角スペースを除去し ns をここで宣言
        const int64_t ns = note_samples_safe(pitch_len);
        auto ev = find_voice_ref(notes[i].wav_path);

        if (ev) {
            prepass[i] = NotePrepass(NoteState::RENDERABLE, ns, ev);
            if (prev_renderable) ++xfade_count;
            prev_renderable = true;
            const int wav_len     = static_cast<int>(ev->waveform.size());
            const int harvest_len = GetSamplesForHarvest(ev->fs, wav_len, kFramePeriod);
            if (harvest_len > max_harvest_len) max_harvest_len = harvest_len;
        } else {
            prepass[i] = NotePrepass(NoteState::NO_VOICE, ns, nullptr);
            prev_renderable = false;
        }

        total_samples += ns;  // INVALID 以外は必ず加算（1箇所に統一）
    }

    total_samples -= static_cast<int64_t>(kCrossfadeSamples) * xfade_count;
    if (total_samples <= 0) return;

    tl_scratch.ensure_spec(max_harvest_len, spec_bins);
    std::vector<double> full_song_buffer(total_samples, 0.0);
    std::vector<double> note_buf;

    static constexpr double kDefaultPitch   = 440.0;
    static constexpr double kDefaultGender  = 0.5;
    static constexpr double kDefaultTension = 0.5;
    static constexpr double kDefaultBreath  = 0.5;

    int64_t current_offset     = 0;
    bool    last_note_rendered = false;

    // ----------------------------------------------------------------
    // パス2: ノートごとの合成
    // ----------------------------------------------------------------

    for (int i = 0; i < note_count; ++i) {
        const NotePrepass& pp = prepass[i];

        switch (pp.state) {
        case NoteState::INVALID:
            last_note_rendered = false;
            continue;

        case NoteState::NO_VOICE:
            last_note_rendered = false;
            current_offset    += pp.note_samples;
            continue;

        case NoteState::RENDERABLE:
            break;
        }

        NoteEvent& n               = notes[i];
        const int64_t note_samples = pp.note_samples;
        const int     f0_len       = n.pitch_length;
        const EmbeddedVoice& ev    = *pp.ev;

        const int harvest_len = analyze_source_f0(ev, kFramePeriod);
        tl_scratch.ensure_spec(harvest_len, spec_bins);

        CheapTrick(ev.waveform.data(), static_cast<int>(ev.waveform.size()), kFs,
                   tl_scratch.time_harvest.data(), tl_scratch.f0_harvest.data(),
                   harvest_len, nullptr, tl_scratch.spec_ptrs.data());

        D4C(ev.waveform.data(), static_cast<int>(ev.waveform.size()), kFs,
            tl_scratch.time_harvest.data(), tl_scratch.f0_harvest.data(),
            harvest_len, fft_size, nullptr, tl_scratch.ap_ptrs.data());

        for (int j = 0; j < harvest_len; ++j)
            if (n.pitch_curve) {
                // pitch_curve は MIDI ノート番号（float）で渡す設計に変更
                const double midi = resample_curve(n.pitch_curve, f0_len, j, harvest_len);
                tl_scratch.f0_harvest[j] = 440.0 * std::pow(2.0, (midi - 69.0) / 12.0);
　　　　　　　　} else {             
                tl_scratch.f0_harvest[j] = kDefaultPitch;
            }

        double* const spec_tmp = tl_scratch.spec_tmp.data();
        for (int j = 0; j < harvest_len; ++j) {
            double* sr = tl_scratch.spec_ptrs[j];
            double* ar = tl_scratch.ap_ptrs[j];

            const double gender  = n.gender_curve
                ? resample_curve(n.gender_curve,  f0_len, j, harvest_len) : kDefaultGender;
            const double tension = n.tension_curve
                ? resample_curve(n.tension_curve, f0_len, j, harvest_len) : kDefaultTension;
            const double breath  = n.breath_curve
                ? resample_curve(n.breath_curve,  f0_len, j, harvest_len) : kDefaultBreath;
            const double shift   = (gender - 0.5) * 0.4;

            memcpy(spec_tmp, sr, sizeof(double) * spec_bins);
            for (int k = 0; k < spec_bins; ++k) {
                const double tk = static_cast<double>(k) * (1.0 + shift);
                const int    k0 = static_cast<int>(tk);
                sr[k] = (k0 >= spec_bins - 1)
                    ? spec_tmp[spec_bins - 1]
                    : (1.0-(tk-k0))*spec_tmp[k0] + (tk-k0)*spec_tmp[k0+1];
            }

            const double inv = 1.0 / (spec_bins - 1);
            for (int k = 0; k < spec_bins; ++k) {
                const double fw = static_cast<double>(k) * inv;
                sr[k] *= (1.0 + (tension - 0.5) * fw);
                ar[k]  = std::clamp(ar[k] + (breath - 0.5) * fw, 0.0, 1.0);
            }
        }

        note_buf.assign(note_samples, 0.0);
        Synthesis(tl_scratch.f0_harvest.data(), harvest_len,
                  tl_scratch.spec_ptrs.data(), tl_scratch.ap_ptrs.data(),
                  fft_size, kFramePeriod, kFs,
                  static_cast<int>(note_samples), note_buf.data());

        const bool    do_xfade     = last_note_rendered;
        const int64_t write_offset = do_xfade
            ? current_offset - kCrossfadeSamples : current_offset;
        const int xfade = do_xfade ? kCrossfadeSamples : 0;

        apply_crossfade(full_song_buffer, total_samples,
                        note_buf, note_samples, write_offset, xfade);

        current_offset += do_xfade
            ? note_samples - kCrossfadeSamples : note_samples;

        last_note_rendered = true;
    }

    wavwrite(
        full_song_buffer.data(),
        static_cast<int>(full_song_buffer.size()),
        kFs, 16, output_path);
}

} // extern "C"
