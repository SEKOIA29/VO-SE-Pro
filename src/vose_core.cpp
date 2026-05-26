// --- clamp polyfill (for C++14/macOS libc++) ---
#ifndef HAVE_STD_CLAMP
template <typename T>
constexpr const T& clamp(const T& v, const T& lo, const T& hi) {
    return (v < lo) ? lo : (hi < v) ? hi : v;
}
#endif
//vose_core.cpp

#include <vector>
#include <string>
#include <map>
#include <unordered_map>
#include <list>
#include <algorithm>
#include <cmath>
#include <sys/stat.h>
#include <unistd.h>
#include <fstream>
#include <iomanip>    
#include <random>
#include <sstream>
#include <cstring>
#include <cstdint>
#include <future>
#include <thread>
#include <mutex>
#include <mutex>
#include <condition_variable>
using VoseMutex = std::mutex;
using VoseUniqueLock = std::unique_lock<std::mutex>;
#include <memory>
#define _USE_MATH_DEFINES
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#include "vose_core.h"
#include "voice_data.h"
// ...existing code...

#include "world/synthesis.h"
#include "world/cheaptrick.h"
#include "world/d4c.h"
#include "world/harvest.h"
#include "world/audioio.h"
#include "world/constantnumbers.h"

// fs::path などは std::string で代用

// ============================================================
// FNV-1a ハッシュ
// ============================================================

static uint64_t fnv1a_hash(const std::string& str) {
    uint64_t hash = 0xcbf29ce484222325ULL;
    for (char c : str) {
        hash ^= static_cast<uint64_t>(c);
        hash *= 0x100000001b3ULL;
    }
    return hash;
}

static std::string generate_cache_hash(const std::string& wav_path) {
    struct stat st;
    if (stat(wav_path.c_str(), &st) == 0) {
        // ファイルが存在する場合: パス + 更新時刻 + サイズでハッシュ
        auto last_time = static_cast<long long>(st.st_mtime);
        auto file_size = static_cast<unsigned long long>(st.st_size);
        std::string seed = wav_path + std::to_string(last_time) + std::to_string(file_size);
        uint64_t h = fnv1a_hash(seed);
        std::stringstream ss;
        ss << std::hex << std::setw(16) << std::setfill('0') << h;
        return ss.str();
    } else {
        // エンベッドボイス（ファイルシステム上に存在しない）:
        uint64_t h = fnv1a_hash(wav_path);
        std::stringstream ss;
        ss << "emb_" << std::hex << std::setw(16) << std::setfill('0') << h;
        return ss.str();
    }
}

// ============================================================
// oto.ini DB
// ============================================================

std::map<std::string, OtoEntry> g_oto_db;
VoseMutex g_oto_db_mutex;

extern "C" void set_oto_data(const OtoEntry* entries, int count) {
    VoseUniqueLock lock(g_oto_db_mutex);
    g_oto_db.clear();
    if (!entries || count <= 0) return;
    for (int i = 0; i < count; ++i)
        g_oto_db[entries[i].alias] = entries[i];
}

// ============================================================
// データ構造
// ============================================================

struct EmbeddedVoice {
    std::string         path;
    std::vector<double> waveform;
    int                 fs;
};

static std::map<std::string, std::shared_ptr<const EmbeddedVoice>> g_voice_db;
VoseMutex g_voice_db_mutex;

struct AnalysisCache {
    std::vector<double> f0;
    std::vector<double> time;
    int                 length    = 0;
    std::vector<double> flat_spec;
    std::vector<double> flat_ap;
    int                 spec_bins = 0;
};

// ============================================================
// AnalysisCacheStore — LRU エビクション付きメモリキャッシュ
//
// 問題: g_analysis_cache が無制限に増える。
//   100音素 × (harvest_len=2000) × (spec_bins=513) × 2配列 × 8byte
//   ≈ 1音素あたり約16MB → 100音素で1.6GB
//
// 解決: 最大エントリ数を kMaxCacheEntries に制限し、
//   LRU（Least Recently Used）で古いエントリを追い出す。
//   アクセス順を std::list で管理し、O(1) エビクションを実現する。
// ============================================================
static constexpr size_t kMaxCacheEntries = 64; // 約1GB上限（16MB × 64）

struct CacheStore {
    using Key   = std::string;
    using Value = std::shared_ptr<const AnalysisCache>;

    // アクセス順リスト（先頭=最近使用）
    std::list<std::pair<Key, Value>> lru_list;
    // キー → リストイテレータ（O(1)アクセス用）
    std::unordered_map<Key, std::list<std::pair<Key,Value>>::iterator> index;

    // キャッシュに追加または更新（古いエントリを LRU で追い出す）
    void put(const Key& key, const Value& val) {
        auto it = index.find(key);
        if (it != index.end()) {
            lru_list.erase(it->second);
            index.erase(it);
        }
        lru_list.push_front({key, val});
        index[key] = lru_list.begin();

        while (index.size() > kMaxCacheEntries) {
            const Key& old_key = lru_list.back().first;
            index.erase(old_key);
            lru_list.pop_back();
        }
    }

    // キャッシュから取得（ヒット時は先頭に移動してアクセス順を更新）
    Value get(const Key& key) {
        auto it = index.find(key);
        if (it == index.end()) return nullptr;
        lru_list.splice(lru_list.begin(), lru_list, it->second);
        return it->second->second;
    }

    // キー削除（ボイス再ロード時）
    void erase(const Key& key) {
        auto it = index.find(key);
        if (it == index.end()) return;
        lru_list.erase(it->second);
        index.erase(it);
    }
};

static CacheStore      g_analysis_cache;
VoseMutex g_analysis_cache_mutex;

// ============================================================
// NoteState / NotePrepass
// ============================================================

enum class NoteState : uint8_t { INVALID, NO_VOICE, RENDERABLE };

struct NotePrepass {
    NoteState                            state        = NoteState::INVALID;
    int64_t                              note_samples = 0;
    std::shared_ptr<const EmbeddedVoice> ev;
    std::shared_ptr<const EmbeddedVoice> prev_ev;
    // raw pointer ではなく値コピー。
    // g_oto_db は set_oto_data() で再構築されうるため、
    // ポインタを長命なオブジェクトに保持すると UB になる。
    OtoEntry                             oto          = {};
    bool                                 has_oto      = false;

    NotePrepass() = default;
    NotePrepass(NoteState s, int64_t ns,
                std::shared_ptr<const EmbeddedVoice> e,
                std::shared_ptr<const EmbeddedVoice> pe = nullptr,
                const OtoEntry* o = nullptr)
        : state(s), note_samples(ns), ev(std::move(e)),
          prev_ev(std::move(pe))
    {
        if (o) { oto = *o; has_oto = true; }
    }
};

// ============================================================
// SynthesisScratchPad
// ============================================================

struct SynthesisScratchPad {
    std::vector<double>  flat_spec, flat_ap, spec_tmp;
    std::vector<double*> spec_ptrs, ap_ptrs;
    std::vector<double>  f0, time_axis;

    std::vector<double>  flat_spec_prev, flat_ap_prev;
    std::vector<double*> spec_ptrs_prev, ap_ptrs_prev;
    std::vector<double>  f0_prev, time_axis_prev;

    std::vector<double>  flat_mod_ap;
    std::vector<double*> mod_ap_ptrs;

    int reserved_f0 = 0, reserved_bins = 0;

    void ensure_spec(int f0_length, int spec_bins) {
        const bool needs_resize = (f0_length > reserved_f0 || spec_bins > reserved_bins);
        if (needs_resize) {
            reserved_f0   = std::max(f0_length,  reserved_f0);
            reserved_bins = std::max(spec_bins,  reserved_bins);
            const size_t total = static_cast<size_t>(reserved_f0) * reserved_bins;
            flat_spec     .resize(total); flat_ap      .resize(total);
            spec_tmp      .resize(reserved_bins);
            spec_ptrs     .resize(reserved_f0); ap_ptrs      .resize(reserved_f0);
            flat_spec_prev.resize(total); flat_ap_prev .resize(total);
            spec_ptrs_prev.resize(reserved_f0); ap_ptrs_prev .resize(reserved_f0);
            flat_mod_ap   .resize(total); mod_ap_ptrs  .resize(reserved_f0);
            // ポインタ再構築はリサイズ時のみ（毎呼び出しは不要）
            for (int i = 0; i < reserved_f0; ++i) {
                const size_t off  = static_cast<size_t>(i) * reserved_bins;
                spec_ptrs     [i] = &flat_spec     [off];
                ap_ptrs       [i] = &flat_ap       [off];
                spec_ptrs_prev[i] = &flat_spec_prev[off];
                ap_ptrs_prev  [i] = &flat_ap_prev  [off];
                mod_ap_ptrs   [i] = &flat_mod_ap   [off];
            }
        }
    }

    void ensure_f0(int n) {
        if (n > static_cast<int>(f0.size())) {
            f0.resize(n); time_axis.resize(n);
        }
    }
    void ensure_f0_prev(int n) {
        if (n > static_cast<int>(f0_prev.size())) {
            f0_prev.resize(n); time_axis_prev.resize(n);
        }
    }
};

thread_local SynthesisScratchPad tl_scratch;

// ============================================================
// 定数
// ============================================================

static constexpr int    kFs               = 44100;
static constexpr double kFramePeriod      = 5.0;   // ms
static constexpr double kInv32768         = 1.0 / 32768.0;
static constexpr int    kCrossfadeSamples = static_cast<int>(kFs * 0.030);
static constexpr int    kMaxPitchLength   = 120000;
static constexpr int    kTransitionFrames = static_cast<int>(60.0 / kFramePeriod);

static int64_t note_samples_safe(int p) {
    return (static_cast<int64_t>(p) - 1) * kFramePeriod / 1000.0 * kFs + 1;
}

// ============================================================
// find_voice_ref
// ============================================================

std::shared_ptr<const EmbeddedVoice> find_voice_ref(const char* key)
{
    VoseUniqueLock lock(g_voice_db_mutex);
    auto it = g_voice_db.find(key ? key : "");
    return (it != g_voice_db.end()) ? it->second : nullptr;
}

// ============================================================
// ディスクキャッシュ
// ============================================================

static std::string get_cache_dir() {
    std::string p = "cache";
    struct stat st;
    if (stat(p.c_str(), &st) != 0) {
        mkdir(p.c_str(), 0755);
    }
    return p;
}

static void save_cache(const std::string& cache_path, const AnalysisCache& cache)
{
    // 書き途中でクラッシュしても破損キャッシュが残らないよう
    // 一時ファイルに書いてからアトミックにリネームする
    std::string tmp_path = cache_path + ".tmp";

    FILE* fp = fopen(tmp_path.c_str(), "wb");
    if (!fp) return;

    bool ok = true;
    VoseCacheHeader header;
    header.magic     = 0x45534F56;
    header.length    = cache.length;
    header.spec_bins = cache.spec_bins;

    ok &= (fwrite(&header,             sizeof(header),  1,            fp) == 1);
    ok &= (fwrite(cache.f0.data(),     sizeof(double),  cache.length, fp) == static_cast<size_t>(cache.length));
    ok &= (fwrite(cache.time.data(),   sizeof(double),  cache.length, fp) == static_cast<size_t>(cache.length));
    const size_t sc = static_cast<size_t>(cache.length) * cache.spec_bins;
    ok &= (fwrite(cache.flat_spec.data(), sizeof(double), sc, fp) == sc);
    ok &= (fwrite(cache.flat_ap.data(),   sizeof(double), sc, fp) == sc);
    fclose(fp);

    if (ok) {
        std::error_code ec;
        rename(tmp_path.c_str(), cache_path.c_str());  // アトミック置換
        // 失敗時はtmpファイルを削除
        // (rename失敗時のエラー処理は省略)
    } else {
        unlink(tmp_path.c_str());  // 書き込み失敗なら一時ファイルを削除
    }
}

static std::shared_ptr<AnalysisCache> load_cache(const std::string& path,
                                                   int expected_spec_bins = 0)
{
    struct stat st;
    if (stat(path.c_str(), &st) != 0) return nullptr;

    std::ifstream ifs(path, std::ios::binary);
    if (!ifs) return nullptr;

    VoseCacheHeader header{};
    if (!ifs.read(reinterpret_cast<char*>(&header), sizeof(header))) return nullptr;

    // マジック検証
    if (header.magic != 0x45534F56) return nullptr;

    // サニティチェック: 長さ・spec_bins が異常値ならキャッシュ破棄
    if (header.length <= 0 || header.length > 1'000'000) return nullptr;
    if (header.spec_bins <= 0 || header.spec_bins > 65536) return nullptr;

    // ④ spec_bins 互換チェック:
    // fft_size が変わると spec_bins が変わる。異なるサイズのキャッシュを
    // 読み込むと配列の境界外アクセスが起きる。不一致なら再解析させる。
    if (expected_spec_bins > 0 && header.spec_bins != expected_spec_bins) {
        return nullptr;
    }

    auto cache = std::make_shared<AnalysisCache>();
    cache->length    = header.length;
    cache->spec_bins = header.spec_bins;
    cache->f0  .resize(cache->length);
    cache->time.resize(cache->length);
    const size_t sc = static_cast<size_t>(cache->length) * cache->spec_bins;
    cache->flat_spec.resize(sc);
    cache->flat_ap  .resize(sc);

    // ③ 各 read の成否を検証。途中で失敗したらキャッシュ破棄して再解析
    auto read_check = [&](void* dst, size_t bytes) -> bool {
        return static_cast<bool>(
            ifs.read(reinterpret_cast<char*>(dst), static_cast<std::streamsize>(bytes)));
    };

    if (!read_check(cache->f0.data(),        sizeof(double) * cache->length))  return nullptr;
    if (!read_check(cache->time.data(),      sizeof(double) * cache->length))  return nullptr;
    if (!read_check(cache->flat_spec.data(), sizeof(double) * sc))             return nullptr;
    if (!read_check(cache->flat_ap.data(),   sizeof(double) * sc))             return nullptr;

    // ストリームが正確に末尾に達しているか確認（余剰バイトがある = 破損）
    if (ifs.peek() != std::ifstream::traits_type::eof()) return nullptr;

    return cache;
}

// ============================================================
// build_analysis_cache
// ============================================================

static std::shared_ptr<const AnalysisCache>
build_analysis_cache(const EmbeddedVoice& ev, int fft_size, int spec_bins)
{
    auto cache = std::make_shared<AnalysisCache>();
    cache->spec_bins = spec_bins;

    HarvestOption opt;
    InitializeHarvestOption(&opt);
    opt.frame_period = kFramePeriod;
    opt.f0_floor     = 50.0;
    opt.f0_ceil      = 800.0;

    const int wav_len     = static_cast<int>(ev.waveform.size());
    const int harvest_len = GetSamplesForHarvest(ev.fs, wav_len, kFramePeriod);
    cache->f0.resize(harvest_len);
    cache->time.resize(harvest_len);
    cache->length = harvest_len;

    Harvest(ev.waveform.data(), wav_len, ev.fs, &opt,
            cache->time.data(), cache->f0.data());

    // F0補完: 無声区間を前後の有声値で線形補間
    {
        std::vector<int> vi;
        vi.reserve(harvest_len);
        for (int i = 0; i < harvest_len; ++i)
            if (cache->f0[i] > 0.0) vi.push_back(i);

        if (!vi.empty()) {
            for (int i = 0; i < vi.front(); ++i)
                cache->f0[i] = cache->f0[vi.front()];
            for (int i = vi.back()+1; i < harvest_len; ++i)
                cache->f0[i] = cache->f0[vi.back()];
            for (int v = 0; v+1 < static_cast<int>(vi.size()); ++v) {
                const int ia = vi[v], ib = vi[v+1];
                if (ib-ia <= 1) continue;
                const double fa = cache->f0[ia], fb = cache->f0[ib];
                for (int i = ia+1; i < ib; ++i)
                    cache->f0[i] = fa + static_cast<double>(i-ia)/(ib-ia)*(fb-fa);
            }
        } else {
            std::fill(cache->f0.begin(), cache->f0.end(), 440.0);
        }
    }

    const size_t sc = static_cast<size_t>(harvest_len) * spec_bins;
    cache->flat_spec.resize(sc);
    cache->flat_ap  .resize(sc);

    std::vector<double*> sp(harvest_len), ap(harvest_len);
    for (int i = 0; i < harvest_len; ++i) {
        sp[i] = &cache->flat_spec[static_cast<size_t>(i)*spec_bins];
        ap[i] = &cache->flat_ap  [static_cast<size_t>(i)*spec_bins];
    }
    CheapTrick(ev.waveform.data(), wav_len, ev.fs,
               cache->time.data(), cache->f0.data(), harvest_len, nullptr, sp.data());
    D4C(ev.waveform.data(), wav_len, ev.fs,
        cache->time.data(), cache->f0.data(), harvest_len, fft_size, nullptr, ap.data());

    return cache;
}

// ============================================================
// get_or_analyze
// ============================================================

std::shared_ptr<const AnalysisCache>
get_or_analyze(std::shared_ptr<const EmbeddedVoice> ev_sp, int fft_size, int spec_bins)
{
    const std::string& key = ev_sp->path;
    {
        VoseUniqueLock rlock(g_analysis_cache_mutex);
        auto cached = g_analysis_cache.get(key);
        if (cached) return cached;
    }

    const std::string h_str     = generate_cache_hash(ev_sp->path);
    const std::string cache_file = get_cache_dir() + "/" + h_str + ".vsc";
    auto disk_cache = load_cache(cache_file, spec_bins);  // ④ spec_bins を渡して互換チェック

    VoseUniqueLock wlock(g_analysis_cache_mutex);
    {
        auto cached = g_analysis_cache.get(key);
        if (cached) return cached;
    }
    if (disk_cache) {
        g_analysis_cache.put(key, disk_cache);
        return disk_cache;
    }

    auto cache = build_analysis_cache(*ev_sp, fft_size, spec_bins);
    g_analysis_cache.put(key, cache);
    wlock.unlock();
    save_cache(cache_file, *cache);
    return cache;
}

// ============================================================
// UTAUタイムマッピング
// ============================================================

double get_source_ms(const EmbeddedVoice& ev) {
    return static_cast<double>(ev.waveform.size()) / ev.fs * 1000.0;
}

double map_time(double t_out_ms, const OtoEntry& oto,
                        double source_wav_len_ms, double note_duration_ms)
{
    const double offset     = oto.offset;
    const double fixed      = oto.consonant;
    const double cutoff_pos = (oto.cutoff < 0)
                              ? source_wav_len_ms + oto.cutoff : oto.cutoff;
    const double source_stretch = cutoff_pos - (offset + fixed);
    const double output_stretch = note_duration_ms - fixed;
    if (t_out_ms < fixed) return t_out_ms + offset;
    const double ratio = source_stretch / std::max(1.0, output_stretch);
    return (t_out_ms - fixed) * ratio + (offset + fixed);
}

// ============================================================
// copy_cache_to_scratch
// ============================================================

static void copy_cache_to_scratch_cur(const AnalysisCache& c)
{
    tl_scratch.ensure_spec(c.length, c.spec_bins);
    const size_t total = static_cast<size_t>(c.length) * c.spec_bins;
    std::copy(c.flat_spec.begin(), c.flat_spec.begin()+total, tl_scratch.flat_spec.begin());
    std::copy(c.flat_ap  .begin(), c.flat_ap  .begin()+total, tl_scratch.flat_ap  .begin());
    tl_scratch.ensure_f0(c.length);
    std::copy(c.f0  .begin(), c.f0  .begin()+c.length, tl_scratch.f0       .begin());
    std::copy(c.time.begin(), c.time.begin()+c.length, tl_scratch.time_axis.begin());
}

static void copy_cache_to_scratch_prev(const AnalysisCache& c)
{
    tl_scratch.ensure_spec(c.length, c.spec_bins);
    const size_t total = static_cast<size_t>(c.length) * c.spec_bins;
    std::copy(c.flat_spec.begin(), c.flat_spec.begin()+total, tl_scratch.flat_spec_prev.begin());
    std::copy(c.flat_ap  .begin(), c.flat_ap  .begin()+total, tl_scratch.flat_ap_prev  .begin());
    tl_scratch.ensure_f0_prev(c.length);
    std::copy(c.f0  .begin(), c.f0  .begin()+c.length, tl_scratch.f0_prev       .begin());
    std::copy(c.time.begin(), c.time.begin()+c.length, tl_scratch.time_axis_prev.begin());
}

// ============================================================
// resample_curve
// ============================================================

inline double resample_curve(const double* curve, int src_len,
                                     int dst_idx, int dst_len)
{
    if (!curve || src_len <= 0 || dst_len <= 0) return 0.0;
    if (dst_idx < 0) return curve[0];
    if (src_len == 1) return curve[0];
    const double t     = static_cast<double>(dst_idx) / std::max(dst_len-1, 1);
    const double src_f = t * (src_len-1);
    const int    j0    = static_cast<int>(src_f);
    const int    j1    = std::min(j0+1, src_len-1);
    return (1.0-(src_f-j0))*curve[j0] + (src_f-j0)*curve[j1];
}

// ============================================================
// apply_crossfade
// ============================================================

// ============================================================
// apply_crossfade
//
// dst[offset..] に src を書き込む。先頭 xfade_len サンプルは
// dst と src を raised-cosine でブレンドする。
//
// overlap_samples: oto.ini の overlap をサンプル換算した値。
//   src の先頭を overlap 分だけスキップして書き込み開始することで、
//   子音頭がクロスフェードに食われる問題を解消する。
//   UTAU 標準の挙動に合わせている。
// ============================================================
static void apply_crossfade(std::vector<double>& dst, int64_t dst_size,
                             const std::vector<double>& src, int64_t src_size,
                             int64_t offset, int xfade_len,
                             int64_t overlap_samples = 0)
{
    if (offset < 0 || offset >= dst_size) return;

    // overlap 分だけ src の読み出し開始位置をずらす
    const int64_t src_start   = clamp(overlap_samples, int64_t(0), src_size);
    const int64_t src_usable  = src_size - src_start;
    if (src_usable <= 0) return;

    const int safe_xfade = static_cast<int>(
        std::min<int64_t>(xfade_len, std::min(src_usable, dst_size - offset)));

    for (int s = 0; s < safe_xfade; ++s) {
        const double  t       = static_cast<double>(s) / safe_xfade;
        const double  fade_in = 0.5 * (1.0 - std::cos(M_PI * t));
        const int64_t di      = offset + s;
        if (di >= dst_size) break;
        dst[di] = dst[di] * (1.0 - fade_in) + src[src_start + s] * fade_in;
    }

    const int64_t body_end = std::min(offset + src_usable, dst_size);
    for (int64_t s = offset + safe_xfade; s < body_end; ++s)
        dst[s] = src[src_start + (s - offset)];
}

// ============================================================
// apply_gender_shift
// ============================================================

// ============================================================
// apply_gender_shift  （フォルマント追従付き高音域補正）
//
// gender  ∈ [0.0, 1.0]
//   0.5 = 変更なし
//   < 0.5 = シフト比 < 1.0 → フォルマントを低域に（太い声）
//   > 0.5 = シフト比 > 1.0 → フォルマントを高域に（細い声・ファルセット）
//
// f0_ratio: 現在フレームの F0 / 音源の基準 F0（= 解析時の平均F0）
//   1.0 = 基準ピッチ（補正なし）
//   > 1.0 = 高音域 → スペクトル包絡を引き伸ばしてフォルマントを追従させる
//
// 高音域補正の効果:
//   UTAUの標準 resampler は高音でスペクトルをそのまま使うため
//   「高くなるほど声がこもる」。ここでは F0 比に応じて
//   スペクトルを対数スケールで引き伸ばすことで自然な声質を維持する。
// ============================================================

void apply_gender_shift(double* sr, int spec_bins, double gender,
                        double* tmp, double f0_ratio)
{
    if (!sr || !tmp || spec_bins <= 0) return;

    // gender シフト比 + F0 追従補正を合成
    const double gender_ratio = std::exp((gender - 0.5) * 0.4 * std::log(2.0));

    // 高音域補正: F0 が上がるほどスペクトルを引き伸ばす
    // 補正量は F0 比の 0.5 乗（完全追従は 1.0 乗だが過補正になるので 0.5 が自然）
    const double formant_ratio = (f0_ratio > 0.0)
        ? std::pow(f0_ratio, 0.5) : 1.0;

    const double shift_ratio = gender_ratio * formant_ratio;

    // gender も formant も変化なし → 処理スキップ
    if (std::abs(shift_ratio - 1.0) < 1e-4) return;

    constexpr double kFloor = 1e-12;
    for (int k = 0; k < spec_bins; ++k)
        tmp[k] = std::log(std::max(sr[k], kFloor));

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
// apply_tension_breath
// ============================================================

void apply_tension_breath(double* sr, double* ar, int spec_bins,
                                  double tension, double breath)
{
    if (!sr || !ar || spec_bins <= 1) return;
    const double inv = 1.0 / (spec_bins-1);
    for (int k = 0; k < spec_bins; ++k) {
        const double fw = static_cast<double>(k) * inv;
        if (std::abs(tension-0.5) > 1e-4) {
            const double weight     = 1.0/(1.0+std::exp(-8.0*(fw-0.35)));
            const double gain_db    = (tension-0.5)*12.0*weight;
            const double clipped_db = 6.0*std::tanh(gain_db/6.0);
            sr[k] *= std::pow(10.0, clipped_db/20.0);
        }
        if (std::abs(breath-0.5) > 1e-4) {
            const double bw     = std::pow(fw, 0.7);
            const double amount = (breath-0.5)*bw;
            ar[k] = amount >= 0.0
                ? ar[k] + amount*(1.0-ar[k])
                : ar[k] + amount*ar[k];
            ar[k] = clamp(ar[k], 0.0, 1.0);
        }
    }
}

// ============================================================
// blend_transition_spectra
// ============================================================

void blend_transition_spectra(
    double** spec_cur, double** ap_cur, int cur_len,
    double** spec_prev, double** ap_prev, int prev_len,
    int spec_bins, int transition_frames)
{
    if (!spec_cur || !spec_prev || !ap_cur || !ap_prev) return;
    if (spec_bins <= 0 || cur_len <= 0 || prev_len <= 0) return;
    const int blend = std::min(transition_frames, std::min(cur_len, prev_len));
    for (int j = 0; j < blend; ++j) {
        const double t      = static_cast<double>(j) / blend;
        const double w_prev = 0.5*(1.0-std::cos(M_PI*(1.0-t)));
        const double w_cur  = 1.0 - w_prev;
        const int    prev_j = prev_len - blend + j;
        constexpr double kFloor = 1e-12;
        double* sc = spec_cur [j];
        double* sp = spec_prev[std::max(0, prev_j)];
        double* ac = ap_cur   [j];
        double* ap = ap_prev  [std::max(0, prev_j)];
        for (int k = 0; k < spec_bins; ++k) {
            sc[k] = std::exp(w_cur *std::log(std::max(sc[k],kFloor))
                           + w_prev*std::log(std::max(sp[k],kFloor)));
            ac[k] = clamp(w_cur*ac[k] + w_prev*ap[k], 0.0, 1.0);
        }
    }
}

// ============================================================
// apply_vibrato
//
// ノート後半50%からビブラートを自然に立ち上げる。
// フェードイン: raised cosine で 0→1
// 波形: sin（6Hz・±15cent）
// 15cent = 目標Hz × (2^(15/1200) - 1) ≈ 目標Hz × 0.00868
//
// AuralAIEngineの _apply_pseudo_ai と同じ発想だが、
// C++側でフレーム単位に適用することで遅延ゼロ・Python依存なし。
// ============================================================

// ============================================================
// apply_vibrato
//
// ノート後半50%からビブラートを自然に立ち上げる。
// フェードイン: raised cosine で 0→1（後半最初の25%で飽和）
// 波形: sin（6Hz・±15cent）
//
// global_time_offset_sec: 曲先頭からこのノート開始までの秒数。
//   これを渡すことで、ノートをまたいでも位相が連続する。
//   0.0 を渡すと旧来の「ノート先頭で位相リセット」動作になる。
// ============================================================

// ============================================================
// apply_vibrato
//
// ノート後半50%からビブラートを自然に立ち上げる。
// フェードイン: raised cosine で 0→1（後半最初の25%で飽和）
//
// global_time_offset_sec : 曲先頭からこのノート開始までの秒数。
//                          ノートをまたいで位相が連続する。
// depth_curve / rate_curve: ノートごとの深さ・速さカーブ（nullptr = デフォルト）
//   depth_curve[j] ∈ [0.0, 1.0]  0=無振動, 1=±15cent フルデプス
//   rate_curve[j]  ∈ [Hz]         典型値 4〜8Hz
// ============================================================
void apply_vibrato(double* f0, int f0_length, double frame_period_ms,
                   double global_time_offset_sec,
                   const double* depth_curve,  // nullptr = 全フレーム 1.0
                   const double* rate_curve,   // nullptr = 全フレーム 6.0Hz
                   int curve_length)
{
    if (!f0 || f0_length <= 0) return;

    const int vib_start = f0_length / 2;
    const int vib_len   = f0_length - vib_start;
    if (vib_len <= 0) return;

    constexpr double kVibDepthMax = 0.00868;  // 15cent
    constexpr double kVibFreqDef  = 6.0;
    const double     frame_sec    = frame_period_ms / 1000.0;

    for (int j = vib_start; j < f0_length; ++j) {
        const double fade_progress =
            static_cast<double>(j - vib_start) / std::max(vib_len - 1, 1);
        const double fade_in = std::min(fade_progress * 4.0, 1.0);

        // カーブをリサンプリング（curve_length != f0_length でも対応）
        const double depth = depth_curve
            ? resample_curve(depth_curve, curve_length, j, f0_length)
            : 1.0;
        const double rate  = rate_curve
            ? std::max(1.0, resample_curve(rate_curve, curve_length, j, f0_length))
            : kVibFreqDef;

        const double t_global = global_time_offset_sec
                                + static_cast<double>(j) * frame_sec;
        const double vib = std::sin(2.0 * M_PI * rate * t_global)
                           * kVibDepthMax * depth * f0[j] * fade_in;
        f0[j] = std::max(50.0, f0[j] + vib);
    }
}

// ============================================================
// [NEW ③] smooth_f0_gaussian
//
// F0配列にガウシアンカーネルを畳み込んで音符境界の急変を緩和する。
// カーネル幅: 5フレーム（= 25ms @ 5ms/frame）
// 端点は折り返しパディングで処理する（ゼロパディングより自然）。
//
// 処理コスト: f0_length × 5 の乗算のみ → 無視できる
// ============================================================

void smooth_f0_gaussian(double* f0, int f0_length)
{
    if (!f0 || f0_length <= 0) return;

    // sigma=1.0 の5点ガウシアンカーネル（正規化済み）
    static constexpr double kKernel[5] = {
        0.06136, 0.24477, 0.38774, 0.24477, 0.06136
    };
    static constexpr int kRadius = 2; // カーネル半径

    std::vector<double> tmp(f0_length);
    for (int i = 0; i < f0_length; ++i) {
        double sum = 0.0;
        for (int k = -kRadius; k <= kRadius; ++k) {
            // 折り返しパディング: 端点を反射させる
            int idx = i + k;
            if (idx < 0)           idx = -idx;
            if (idx >= f0_length)  idx = 2*(f0_length-1) - idx;
            sum += f0[idx] * kKernel[k + kRadius];
        }
        tmp[i] = sum;
    }
    std::copy(tmp.begin(), tmp.end(), f0);
}

// ============================================================
// VOSE_Synthesis
// ============================================================

static void VOSE_Synthesis(
    const double* f0, int f0_length,
    double** spectrogram, double** aperiodicity,
    int fft_size, double frame_period, int fs,
    int y_length, double* y)
{
    const int spec_bins = fft_size / 2 + 1;
    tl_scratch.ensure_spec(f0_length, spec_bins);
    double** mod_ap = tl_scratch.mod_ap_ptrs.data();

    static thread_local std::mt19937 rng(
        std::random_device{}() ^
        static_cast<uint32_t>(std::hash<std::thread::id>{}(
            std::this_thread::get_id())));
    std::uniform_real_distribution<double> dist(-0.02, 0.02);

    for (int i = 0; i < f0_length; ++i) {
        double* ap_dst = mod_ap[i];
        double* ap_src = aperiodicity[i];
        double delta_f0 = 0.0;
        if (i > 0 && i < f0_length-1)
            delta_f0 = std::abs(f0[i+1]-f0[i-1])*0.5;
        const double vibrato_breath = std::min(0.15, delta_f0*0.003);
        for (int k = 0; k < spec_bins; ++k) {
            double current_ap = ap_src[k];
            const double freq = static_cast<double>(k)*fs/fft_size;
            if (freq > 2000.0) current_ap += vibrato_breath + dist(rng);
            ap_dst[k] = clamp(current_ap, 0.0, 1.0);
        }
    }

    Synthesis(f0, f0_length, spectrogram, mod_ap,
              fft_size, frame_period, fs, y_length, y);

    double prev_x = 0.0, prev_y_hp = 0.0;
    for (int i = 0; i < y_length; ++i) {
        double hp = y[i] - prev_x + 0.85*prev_y_hp;
        prev_x = y[i];
        prev_y_hp = hp;
        y[i] += hp*0.05;
    }
}

// ============================================================
// synthesize_note_impl
//
// execute_render の並列合成ラムダを自由関数に昇格。
// vose_streaming.cpp の synth_loop() からも呼べる。
// ============================================================

struct SynthNoteParams {
    const NotePrepass& pp;
    NoteEvent&         n;
    int                fft_size;
    int                spec_bins;
    double             global_time_sec = 0.0;  // 曲先頭からのオフセット（ビブラート位相連続化）
};

static const OtoEntry kDefaultOto = {};

void synthesize_note_impl(const SynthNoteParams& p, std::vector<double>& note_buf)
{
    const NotePrepass& pp    = p.pp;
    NoteEvent&         n     = p.n;
    const int   fft_size     = p.fft_size;
    const int   spec_bins    = p.spec_bins;

    if (pp.state != NoteState::RENDERABLE) return;

    const int64_t note_samples  = pp.note_samples;
    const double  note_ms       = static_cast<double>(note_samples) / kFs * 1000.0;
    const double  src_ms        = get_source_ms(*pp.ev);
    const int     output_frames = static_cast<int>(note_ms / kFramePeriod);
    const OtoEntry& current_oto = pp.has_oto ? pp.oto : kDefaultOto;

    auto cache_cur = get_or_analyze(pp.ev, fft_size, spec_bins);

    tl_scratch.ensure_f0(output_frames);
    tl_scratch.ensure_spec(output_frames, spec_bins);

    // ----------------------------------------------------------------
    // ステップ1: cur スペクトルを DSP 込みで書き込む
    // (blend_transition_spectra より先に実行する必要がある)
    // ----------------------------------------------------------------
    for (int j = 0; j < output_frames; ++j) {
        const double t_out_ms = j * kFramePeriod;
        const double t_src_ms = map_time(t_out_ms, current_oto, src_ms, note_ms);
        const int src_frame   = clamp(
            static_cast<int>(t_src_ms / kFramePeriod), 0, cache_cur->length-1);

        double* sr = tl_scratch.spec_ptrs[j];
        double* ar = tl_scratch.ap_ptrs  [j];
        std::copy_n(&cache_cur->flat_spec[static_cast<size_t>(src_frame)*spec_bins],
                    spec_bins, sr);
        std::copy_n(&cache_cur->flat_ap  [static_cast<size_t>(src_frame)*spec_bins],
                    spec_bins, ar);

        tl_scratch.f0[j] = n.pitch_curve
            ? resample_curve(n.pitch_curve, n.pitch_length, j, output_frames)
            : 440.0;
        const double gender  = n.gender_curve
            ? resample_curve(n.gender_curve,  n.pitch_length, j, output_frames) : 0.5;
        const double tension = n.tension_curve
            ? resample_curve(n.tension_curve, n.pitch_length, j, output_frames) : 0.5;
        const double breath  = n.breath_curve
            ? resample_curve(n.breath_curve,  n.pitch_length, j, output_frames) : 0.5;

        apply_gender_shift(sr, spec_bins, gender, tl_scratch.spec_tmp.data(), 1.0);
        apply_tension_breath(sr, ar, spec_bins, tension, breath);
    }

    // ----------------------------------------------------------------
    // ステップ2: prev スペクトルを scratch_prev に展開してブレンド
    // (cur が書き終わった後でないと blend の cur 側がゼロになる)
    // ----------------------------------------------------------------
    if (pp.prev_ev) {
        auto cache_prev = get_or_analyze(pp.prev_ev, fft_size, spec_bins);
        copy_cache_to_scratch_prev(*cache_prev);
        blend_transition_spectra(
            tl_scratch.spec_ptrs.data(), tl_scratch.ap_ptrs.data(), output_frames,
            tl_scratch.spec_ptrs_prev.data(), tl_scratch.ap_ptrs_prev.data(),
            cache_prev->length, spec_bins, kTransitionFrames);
    }

    smooth_f0_gaussian(tl_scratch.f0.data(), output_frames);

    // ビブラートカーブが NoteEvent にあれば使用、なければデフォルト (depth=1.0, rate=6Hz)
    // NoteEvent 側に vibrato_depth_curve / vibrato_rate_curve / vibrato_curve_length
    // フィールドを追加した場合はそのまま渡せる。未定義なら nullptr で問題ない。
    const double* vib_depth = (n.vibrato_depth_curve && n.vibrato_curve_length > 0)
                              ? n.vibrato_depth_curve : nullptr;
    const double* vib_rate  = (n.vibrato_rate_curve  && n.vibrato_curve_length > 0)
                              ? n.vibrato_rate_curve  : nullptr;
    const int     vib_clen  = n.vibrato_curve_length > 0 ? n.vibrato_curve_length : 0;

    apply_vibrato(tl_scratch.f0.data(), output_frames, kFramePeriod,
                  p.global_time_sec, vib_depth, vib_rate, vib_clen);

    note_buf.assign(static_cast<size_t>(note_samples), 0.0);
    VOSE_Synthesis(tl_scratch.f0.data(), output_frames,
                   tl_scratch.spec_ptrs.data(), tl_scratch.ap_ptrs.data(),
                   fft_size, kFramePeriod, pp.ev->fs,
                   static_cast<int>(note_samples), note_buf.data());
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

    VoseUniqueLock clock(g_analysis_cache_mutex);
    VoseUniqueLock wlock(g_voice_db_mutex);
    // パス文字列キーでキャッシュを無効化（再ロード時も確実にヒット）
    g_analysis_cache.erase(phoneme);
    ev->path = phoneme;
    g_voice_db[phoneme] = std::move(ev);
}

// ============================================================
// execute_render  (並列合成版)
//
// 並列化の設計:
//   パス2を「合成フェーズ」と「書き込みフェーズ」に分離する。
//
//   [合成フェーズ・並列]
//     各ノートの note_buf を std::async で独立して合成する。
//     ノード間の依存関係（current_offset, full_song_buffer）には
//     一切触れないので安全に並列化できる。
//     tl_scratch は thread_local なのでスレッドごとに独立している。
//
//   [書き込みフェーズ・順次]
//     future.get() で合成完了を待ち、apply_crossfade でシングルスレッドで書き込む。
//     full_song_buffer への書き込みはここだけなのでデータ競合なし。
//
// スレッド数:
//   std::thread::hardware_concurrency() を上限とするが、
//   音源の解析（get_or_analyze）は g_analysis_cache_mutex を取るため
//   キャッシュミス時だけ直列化される。通常はキャッシュヒットするので問題なし。
// ============================================================
 

DLLEXPORT void execute_render(NoteEvent* notes, int note_count, const char* output_path, int mode_flag)
{
    if (!notes || note_count <= 0 || !output_path) return;

    // ================================================================
    // Pro版（Studio Master）の判定とパラメータ設定
    // ================================================================
    bool is_pro = (mode_flag == 1);
    
    // Pro版は 32bit float (または32bit PCM)、無料版は 16bit CD音質
    int out_bit_depth = is_pro ? 32 : 16;
    
    // ※将来的に96kHz出力を行う場合は、ここの out_fs を切り替えて、
    // 最後の wavwrite 前にリサンプリング処理を挟みます。
    int out_fs = kFs; 

    const int fft_size  = GetFFTSizeForCheapTrick(kFs, nullptr);
    const int spec_bins = fft_size / 2 + 1;

    // ----------------------------------------------------------------
    // パス1: NotePrepass 構築（変更なし）
    // ----------------------------------------------------------------
    std::vector<NotePrepass> prepass(note_count);
    int     max_harvest_len  = 0;
    int64_t total_samples    = 0;
    int     xfade_count      = 0;
    bool    prev_renderable  = false;
    double  max_preutterance = 0.0;
    std::shared_ptr<const EmbeddedVoice> last_ev;

    for (int i = 0; i < note_count; ++i) {
        const int pitch_len = notes[i].pitch_length;
        if (pitch_len <= 0 || pitch_len > kMaxPitchLength) {
            prepass[i]      = NotePrepass(NoteState::INVALID, 0, nullptr);
            prev_renderable = false;
            last_ev         = nullptr;
            continue;
        }

        const int64_t ns = note_samples_safe(pitch_len);
        if (!notes[i].wav_path) {
            prepass[i]      = NotePrepass(NoteState::NO_VOICE, ns, nullptr);
            prev_renderable = false;
            last_ev         = nullptr;
            total_samples  += ns;
            continue;
        }
        auto ev = find_voice_ref(notes[i].wav_path);

        const OtoEntry* found_oto = nullptr;
        {
            VoseUniqueLock lock(g_oto_db_mutex);
            auto oto_it = g_oto_db.find(notes[i].wav_path);
            if (oto_it != g_oto_db.end()) {
                found_oto = &oto_it->second;
                max_preutterance = std::max(max_preutterance,
                                            found_oto->preutterance);
            }
        }

        if (ev) {
            prepass[i] = NotePrepass(NoteState::RENDERABLE, ns, ev,
                                     prev_renderable ? last_ev : nullptr,
                                     found_oto);
            if (prev_renderable) ++xfade_count;
            prev_renderable = true;
            last_ev         = ev;
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

    const int64_t pre_buffer_samples =
        static_cast<int64_t>(max_preutterance * kFs / 1000.0);
    const int64_t buffer_total = total_samples + pre_buffer_samples;

    tl_scratch.ensure_spec(max_harvest_len, spec_bins);
    std::vector<double> full_song_buffer(buffer_total, 0.0);

    // ----------------------------------------------------------------
    // パス2-A: 各ノートの note_buf を並列合成
    //
    // 設計上の注意:
    //   tl_scratch は thread_local なので「スレッドごとに独立」だが、
    //   std::async(launch::async) は実装によってスレッドプールを再利用する。
    //   同じスレッドが2ノード分の synthesize_note_impl を
    //   ネストして呼び出すことはないが、プールの枯渇で
    //   launch::deferred（= メインスレッドで実行）に fallback する実装もある。
    //   安全のため、1ノート = 1スレッドを明示的に生成する方式にする。
    //   スレッド数は hardware_concurrency でキャップし、バッチ処理する。
    // ----------------------------------------------------------------
    const int max_threads = static_cast<int>(
        std::max(1u, std::thread::hardware_concurrency()));

    std::vector<std::vector<double>> note_bufs(note_count);

    // RENDERABLE なノートのインデックスだけ集める
    std::vector<int> renderable_indices;
    renderable_indices.reserve(note_count);
    for (int i = 0; i < note_count; ++i)
        if (prepass[i].state == NoteState::RENDERABLE)
            renderable_indices.push_back(i);

    // ノートごとのグローバル時間オフセット（ビブラート位相連続化用）
    std::vector<double> note_global_time(note_count, 0.0);
    {
        double acc_sec = 0.0;
        for (int i = 0; i < note_count; ++i) {
            note_global_time[i] = acc_sec;
            if (prepass[i].note_samples > 0)
                acc_sec += static_cast<double>(prepass[i].note_samples) / kFs;
        }
    }

    // max_threads ずつバッチ処理
    // 各スレッドは独立した tl_scratch（thread_local）を持つため競合しない
    for (int batch_start = 0;
         batch_start < static_cast<int>(renderable_indices.size());
         batch_start += max_threads)
    {
        const int batch_end = std::min(
            batch_start + max_threads,
            static_cast<int>(renderable_indices.size()));

        std::vector<std::thread> threads;
        threads.reserve(batch_end - batch_start);

        for (int bi = batch_start; bi < batch_end; ++bi) {
            const int idx = renderable_indices[bi];
            threads.emplace_back([&, idx] {
                SynthNoteParams p{ prepass[idx], notes[idx], fft_size, spec_bins,
                                   note_global_time[idx] };
                synthesize_note_impl(p, note_bufs[idx]);
            });
        }
        for (auto& t : threads) t.join();
    }

    // ----------------------------------------------------------------
    // パス2-B: 書き込みフェーズ
    // ----------------------------------------------------------------
    int64_t current_offset     = pre_buffer_samples;
    bool    last_note_rendered = false;

    for (int idx = 0; idx < note_count; ++idx) {
        const NotePrepass& pp = prepass[idx];

        switch (pp.state) {
        case NoteState::INVALID:
        case NoteState::NO_VOICE:
            last_note_rendered = false;
            if (pp.state == NoteState::NO_VOICE) current_offset += pp.note_samples;
            continue;
        case NoteState::RENDERABLE:
            break;
        }

        const int64_t note_samples = pp.note_samples;
        const OtoEntry& current_oto = pp.has_oto ? pp.oto : kDefaultOto;

        const int64_t pre_samples     =
            static_cast<int64_t>(current_oto.preutterance * kFs / 1000.0);
        // overlap: oto.ini の overlap フィールドが存在する場合に有効。
        // vose_core.h の OtoEntry に overlap メンバがなければ 0 に変更すること。
        // (UTAUの標準的な OtoEntry には overlap が存在する)
        const int64_t overlap_samples =
            static_cast<int64_t>(current_oto.overlap * kFs / 1000.0);
        const int64_t base_offset  = last_note_rendered
                                     ? current_offset - kCrossfadeSamples
                                     : current_offset;
        const int64_t write_offset = std::max<int64_t>(0, base_offset - pre_samples);
        const int     xfade        = last_note_rendered ? kCrossfadeSamples : 0;

        apply_crossfade(full_song_buffer, buffer_total,
                        note_bufs[idx], note_samples,
                        write_offset, xfade, overlap_samples);

        current_offset += last_note_rendered
                          ? note_samples - kCrossfadeSamples
                          : note_samples;
        last_note_rendered = true;
    }

    // ----------------------------------------------------------------
    // 【有料化の要】Pro版は 32bit出力、Free版は 16bit出力
    // ----------------------------------------------------------------
    wavwrite(full_song_buffer.data() + pre_buffer_samples,
             static_cast<int>(total_samples),
             out_fs, out_bit_depth, output_path);
}
 
} // extern "C"
