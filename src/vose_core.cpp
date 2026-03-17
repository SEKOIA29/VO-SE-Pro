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
#define _USE_MATH_DEFINES
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
// oto.ini 受け渡し
// ============================================================

extern "C" void set_voice_library(const char* voice_path);
extern "C" void set_oto_data(const OtoEntry* entries, int count);

// ============================================================
// NoteState / NotePrepass
// ============================================================

enum class NoteState : uint8_t {
    INVALID,
    NO_VOICE,
    RENDERABLE,
};

struct NotePrepass {
    NoteState                            state        = NoteState::INVALID;
    int64_t                              note_samples = 0;
    std::shared_ptr<const EmbeddedVoice> ev;
    // [FIX-③] 前ノートの音素キーを保持して遷移時のブレンド元を特定する
    std::shared_ptr<const EmbeddedVoice> prev_ev;

    NotePrepass() = default;
    NotePrepass(NoteState s, int64_t ns,
                std::shared_ptr<const EmbeddedVoice> e,
                std::shared_ptr<const EmbeddedVoice> pe = nullptr)
        : state(s), note_samples(ns), ev(std::move(e)), prev_ev(std::move(pe)) {}
};

struct SynthesisScratchPad {
    std::vector<double>  flat_spec;
    std::vector<double>  flat_ap;
    std::vector<double>  spec_tmp;
    std::vector<double*> spec_ptrs;
    std::vector<double*> ap_ptrs;
    std::vector<double>  f0_harvest;
    std::vector<double>  time_harvest;

    // [FIX-③] 前音素のスペクトル包絡・非周期性をノート先頭でブレンドするための作業領域
    std::vector<double>  flat_spec_prev;
    std::vector<double>  flat_ap_prev;
    std::vector<double*> spec_ptrs_prev;
    std::vector<double*> ap_ptrs_prev;
    std::vector<double>  f0_harvest_prev;
    std::vector<double>  time_harvest_prev;

    int reserved_f0   = 0;
    int reserved_bins = 0;

    void ensure_spec(int f0_length, int spec_bins) {
        bool need_rebuild = false;
        if (f0_length > reserved_f0 || spec_bins > reserved_bins) {
            reserved_f0   = std::max(f0_length,  reserved_f0);
            reserved_bins = std::max(spec_bins,  reserved_bins);
            flat_spec     .resize(static_cast<size_t>(reserved_f0) * reserved_bins);
            flat_ap       .resize(static_cast<size_t>(reserved_f0) * reserved_bins);
            spec_tmp      .resize(reserved_bins);
            spec_ptrs     .resize(reserved_f0);
            ap_ptrs       .resize(reserved_f0);
            flat_spec_prev.resize(static_cast<size_t>(reserved_f0) * reserved_bins);
            flat_ap_prev  .resize(static_cast<size_t>(reserved_f0) * reserved_bins);
            spec_ptrs_prev.resize(reserved_f0);
            ap_ptrs_prev  .resize(reserved_f0);
            need_rebuild = true;
        }
        if (need_rebuild) {
            for (int i = 0; i < reserved_f0; ++i) {
                spec_ptrs     [i] = &flat_spec     [static_cast<size_t>(i) * reserved_bins];
                ap_ptrs       [i] = &flat_ap       [static_cast<size_t>(i) * reserved_bins];
                spec_ptrs_prev[i] = &flat_spec_prev[static_cast<size_t>(i) * reserved_bins];
                ap_ptrs_prev  [i] = &flat_ap_prev  [static_cast<size_t>(i) * reserved_bins];
            }
        }
    }

    void ensure_harvest(int length) {
        if (length > static_cast<int>(f0_harvest.size())) {
            f0_harvest  .resize(length);
            time_harvest.resize(length);
        }
    }

    void ensure_harvest_prev(int length) {
        if (length > static_cast<int>(f0_harvest_prev.size())) {
            f0_harvest_prev  .resize(length);
            time_harvest_prev.resize(length);
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

// [FIX-③] 音素遷移ブレンドのフレーム数（約60ms）
static constexpr int kTransitionFrames = static_cast<int>(60.0 / kFramePeriod);

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
// analyze_source_f0  （メインバッファ用）
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

    // [FIX-④] 無声区間の補完を改善：前後の有声F0で線形補間する
    //          端点は最近傍の有声値で外挿する（元の固定値150Hzをやめる）
    {
        // まず有声フレームのインデックスを収集
        std::vector<int> voiced_idx;
        voiced_idx.reserve(harvest_len);
        for (int i = 0; i < harvest_len; ++i)
            if (tl_scratch.f0_harvest[i] > 0.0)
                voiced_idx.push_back(i);

        if (!voiced_idx.empty()) {
            // 先端の無声区間 → 最初の有声値で外挿
            for (int i = 0; i < voiced_idx.front(); ++i)
                tl_scratch.f0_harvest[i] = tl_scratch.f0_harvest[voiced_idx.front()];

            // 末端の無声区間 → 最後の有声値で外挿
            for (int i = voiced_idx.back() + 1; i < harvest_len; ++i)
                tl_scratch.f0_harvest[i] = tl_scratch.f0_harvest[voiced_idx.back()];

            // 中間の無声区間 → 前後の有声値で線形補間
            for (int vi = 0; vi + 1 < static_cast<int>(voiced_idx.size()); ++vi) {
                const int ia = voiced_idx[vi];
                const int ib = voiced_idx[vi + 1];
                if (ib - ia <= 1) continue;
                const double fa = tl_scratch.f0_harvest[ia];
                const double fb = tl_scratch.f0_harvest[ib];
                for (int i = ia + 1; i < ib; ++i) {
                    const double t = static_cast<double>(i - ia) / (ib - ia);
                    tl_scratch.f0_harvest[i] = fa + t * (fb - fa);
                }
            }
        } else {
            // 完全無声素材：一律440Hzを入れておく（合成自体は無意味だが安全に）
            std::fill(tl_scratch.f0_harvest.begin(),
                      tl_scratch.f0_harvest.begin() + harvest_len, 440.0);
        }
    }

    return harvest_len;
}

// ============================================================
// analyze_source_f0_prev  （前音素用・_prev バッファに書く）
// ============================================================

static int analyze_source_f0_prev(const EmbeddedVoice& ev, double frame_period)
{
    HarvestOption opt;
    InitializeHarvestOption(&opt);
    opt.frame_period = frame_period;
    opt.f0_floor     = 50.0;
    opt.f0_ceil      = 800.0;

    const int wav_len     = static_cast<int>(ev.waveform.size());
    const int harvest_len = GetSamplesForHarvest(ev.fs, wav_len, frame_period);
    tl_scratch.ensure_harvest_prev(harvest_len);

    Harvest(ev.waveform.data(), wav_len, ev.fs, &opt,
            tl_scratch.time_harvest_prev.data(), tl_scratch.f0_harvest_prev.data());

    // [FIX-④] 同様の補完を前音素にも適用
    {
        std::vector<int> voiced_idx;
        voiced_idx.reserve(harvest_len);
        for (int i = 0; i < harvest_len; ++i)
            if (tl_scratch.f0_harvest_prev[i] > 0.0)
                voiced_idx.push_back(i);

        if (!voiced_idx.empty()) {
            for (int i = 0; i < voiced_idx.front(); ++i)
                tl_scratch.f0_harvest_prev[i] = tl_scratch.f0_harvest_prev[voiced_idx.front()];
            for (int i = voiced_idx.back() + 1; i < harvest_len; ++i)
                tl_scratch.f0_harvest_prev[i] = tl_scratch.f0_harvest_prev[voiced_idx.back()];
            for (int vi = 0; vi + 1 < static_cast<int>(voiced_idx.size()); ++vi) {
                const int ia = voiced_idx[vi];
                const int ib = voiced_idx[vi + 1];
                if (ib - ia <= 1) continue;
                const double fa = tl_scratch.f0_harvest_prev[ia];
                const double fb = tl_scratch.f0_harvest_prev[ib];
                for (int i = ia + 1; i < ib; ++i) {
                    const double t = static_cast<double>(i - ia) / (ib - ia);
                    tl_scratch.f0_harvest_prev[i] = fa + t * (fb - fa);
                }
            }
        } else {
            std::fill(tl_scratch.f0_harvest_prev.begin(),
                      tl_scratch.f0_harvest_prev.begin() + harvest_len, 440.0);
        }
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
    if (offset >= dst_size) return;

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
// apply_gender_shift  [FIX-①]
//
// 旧実装: スペクトルビンを線形にリマッピングするだけ（位相不連続）
// 新実装: 対数周波数軸でのスペクトルシフト（メルケプストラム近似）
//         1. スペクトルをlog振幅に変換
//         2. 対数周波数軸でシフト（ゼロ詰め or クランプ）
//         3. 線形振幅に戻す
//   これにより「声道長を伸縮させた」ような自然な変化が得られる。
// ============================================================

static void apply_gender_shift(double* sr, int spec_bins, double gender,
                                double* tmp)
{
    if (std::abs(gender - 0.5) < 1e-4) return;  // 変化なしなら何もしない

    // shift_ratio: 1.0 より大きい → 声道を短く（高い声）
    //              1.0 より小さい → 声道を長く（低い声）
    // gender=1.0 → ratio≈1.22, gender=0.0 → ratio≈0.82 程度
    const double shift_ratio = std::exp((gender - 0.5) * 0.4 * std::log(2.0));

    // log振幅に変換（ゼロ除算防止のため小さいフロアを設ける）
    constexpr double kFloor = 1e-12;
    for (int k = 0; k < spec_bins; ++k)
        tmp[k] = std::log(std::max(sr[k], kFloor));

    // 対数周波数軸でのリマッピング
    // 出力ビン k は入力の k / shift_ratio に対応する
    for (int k = 0; k < spec_bins; ++k) {
        const double src_k = static_cast<double>(k) / shift_ratio;
        const int    k0    = static_cast<int>(src_k);
        if (k0 >= spec_bins - 1) {
            sr[k] = std::exp(tmp[spec_bins - 1]);
        } else {
            const double frac = src_k - k0;
            sr[k] = std::exp((1.0 - frac) * tmp[k0] + frac * tmp[k0 + 1]);
        }
    }
}

// ============================================================
// apply_tension_breath  [FIX-②]
//
// 旧実装: sr[k] *= (1 + tension * fw)  線形・単調増加のみ
//         ap[k] += breath * fw          同上
//
// 新実装:
//   テンション: 実際の声帯の緊張は高域を非線形に強調する。
//               シグモイド型のウェイトで「高域だけ持ち上がる」特性を再現。
//               過剰な増幅を抑えるため ±6dB でソフトクリップ。
//
//   ブレス:     非周期性は低域から滑らかに増加する特性を持つ。
//               線形加算の代わりに既存値との加重ミックスにすることで
//               「全部ノイズになる」暴走を防ぐ。
// ============================================================

static void apply_tension_breath(double* sr, double* ar, int spec_bins,
                                  double tension, double breath)
{
    const double inv = 1.0 / (spec_bins - 1);

    for (int k = 0; k < spec_bins; ++k) {
        const double fw = static_cast<double>(k) * inv;   // 0→1（正規化周波数）

        // --- テンション（非線形シグモイド重み） ---
        if (std::abs(tension - 0.5) > 1e-4) {
            // pivot = 0.35 付近でカーブが急峻になるよう設計
            const double sigmoid_k  = 8.0;
            const double pivot      = 0.35;
            const double weight     = 1.0 / (1.0 + std::exp(-sigmoid_k * (fw - pivot)));
            // tension>0.5: 高域ブースト, tension<0.5: 高域カット
            const double gain_db    = (tension - 0.5) * 12.0 * weight;
            // ソフトクリップ: ±6dB を超えないよう tanh で抑制
            const double clipped_db = 6.0 * std::tanh(gain_db / 6.0);
            sr[k] *= std::pow(10.0, clipped_db / 20.0);
        }

        // --- ブレス（既存 ap との加重ミックス） ---
        if (std::abs(breath - 0.5) > 1e-4) {
            // 低域ほどブレスが乗りにくいよう fw^0.7 で重み付け
            const double bw     = std::pow(fw, 0.7);
            const double amount = (breath - 0.5) * bw;
            if (amount >= 0.0) {
                // ブレスを増やす: ap と 1.0 の間をミックス
                ar[k] = ar[k] + amount * (1.0 - ar[k]);
            } else {
                // ブレスを減らす: ap と 0.0 の間をミックス
                ar[k] = ar[k] + amount * ar[k];
            }
            ar[k] = std::clamp(ar[k], 0.0, 1.0);
        }
    }
}

// ============================================================
// blend_transition_spectra  [FIX-③]
//
// ノート先頭の kTransitionFrames フレームにわたって
// 前音素のスペクトル包絡・非周期性を現在音素に線形ブレンドする。
// これにより「音素境界でスペクトルが急変する」ロボット感を軽減する。
// ============================================================

static void blend_transition_spectra(
    double** spec_cur,  double** ap_cur,  int cur_len,
    double** spec_prev, double** ap_prev, int prev_len,
    int spec_bins, int transition_frames)
{
    const int blend_frames = std::min(transition_frames,
                                       std::min(cur_len, prev_len));
    for (int j = 0; j < blend_frames; ++j) {
        // t=0（先頭）で prev を100%, t=1（transition終わり）で cur を100%
        const double t      = static_cast<double>(j) / blend_frames;
        const double w_prev = 0.5 * (1.0 - std::cos(M_PI * (1.0 - t)));  // コサイン窓
        const double w_cur  = 1.0 - w_prev;

        // スペクトル包絡ブレンドは対数域で行う（線形ブレンドより自然）
        constexpr double kFloor = 1e-12;
        // prevの対応フレーム: prev末尾に近いフレームを使う
        const int prev_j = prev_len - blend_frames + j;

        double* sc = spec_cur [j];
        double* sp = spec_prev[std::max(0, prev_j)];
        double* ac = ap_cur   [j];
        double* ap = ap_prev  [std::max(0, prev_j)];

        for (int k = 0; k < spec_bins; ++k) {
            const double log_c = std::log(std::max(sc[k], kFloor));
            const double log_p = std::log(std::max(sp[k], kFloor));
            sc[k] = std::exp(w_cur * log_c + w_prev * log_p);
            ac[k] = std::clamp(w_cur * ac[k] + w_prev * ap[k], 0.0, 1.0);
        }
    }
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
    std::shared_ptr<const EmbeddedVoice> last_ev; // [FIX-③] 直前の音源を追跡

    for (int i = 0; i < note_count; ++i) {
        const int pitch_len = notes[i].pitch_length;

        if (pitch_len <= 0 || pitch_len > kMaxPitchLength) {
            std::fprintf(stderr,
                "[vose_core] note[%d] pitch_length=%d out of range (1..%d), skipping.\n",
                i, pitch_len, kMaxPitchLength);
            prepass[i]      = NotePrepass(NoteState::INVALID, 0, nullptr);
            prev_renderable = false;
            last_ev         = nullptr;
            continue;
        }

        const int64_t ns = note_samples_safe(pitch_len);
        auto ev = find_voice_ref(notes[i].wav_path);

        if (ev) {
            // [FIX-③] 前音素の EmbeddedVoice を prepass に記録
            prepass[i] = NotePrepass(NoteState::RENDERABLE, ns, ev,
                                     prev_renderable ? last_ev : nullptr);
            if (prev_renderable) ++xfade_count;
            prev_renderable = true;
            last_ev = ev;

            const int wav_len     = static_cast<int>(ev->waveform.size());
            const int harvest_len = GetSamplesForHarvest(ev->fs, wav_len, kFramePeriod);
            if (harvest_len > max_harvest_len) max_harvest_len = harvest_len;
        } else {
            prepass[i]      = NotePrepass(NoteState::NO_VOICE, ns, nullptr);
            prev_renderable = false;
            last_ev         = nullptr;
        }

        total_samples += ns;
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

        // [FIX-③] 前音素がある場合はスペクトル遷移ブレンドを実施
        if (pp.prev_ev) {
            const EmbeddedVoice& prev_ev = *pp.prev_ev;
            const int prev_harvest_len   = analyze_source_f0_prev(prev_ev, kFramePeriod);
            tl_scratch.ensure_spec(std::max(harvest_len, prev_harvest_len), spec_bins);

            CheapTrick(prev_ev.waveform.data(),
                       static_cast<int>(prev_ev.waveform.size()), kFs,
                       tl_scratch.time_harvest_prev.data(),
                       tl_scratch.f0_harvest_prev.data(),
                       prev_harvest_len, nullptr,
                       tl_scratch.spec_ptrs_prev.data());

            D4C(prev_ev.waveform.data(),
                static_cast<int>(prev_ev.waveform.size()), kFs,
                tl_scratch.time_harvest_prev.data(),
                tl_scratch.f0_harvest_prev.data(),
                prev_harvest_len, fft_size, nullptr,
                tl_scratch.ap_ptrs_prev.data());

            blend_transition_spectra(
                tl_scratch.spec_ptrs.data(), tl_scratch.ap_ptrs.data(), harvest_len,
                tl_scratch.spec_ptrs_prev.data(), tl_scratch.ap_ptrs_prev.data(),
                prev_harvest_len, spec_bins, kTransitionFrames);
        }

        // ピッチカーブ適用
        for (int j = 0; j < harvest_len; ++j)
            tl_scratch.f0_harvest[j] = n.pitch_curve
                ? resample_curve(n.pitch_curve, f0_len, j, harvest_len)
                : kDefaultPitch;

        // パラメータ変形（ジェンダー・テンション・ブレス）
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

            // [FIX-①] 対数域ジェンダーシフト（旧: 線形リマッピング）
            apply_gender_shift(sr, spec_bins, gender, spec_tmp);

            // [FIX-②] 非線形テンション＋加重ミックスブレス（旧: 線形加算）
            apply_tension_breath(sr, ar, spec_bins, tension, breath);
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
