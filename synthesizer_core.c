#define DR_WAV_IMPLEMENTATION
#include "dr_wav.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "synthesizer_core.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static char current_voice_dir[512] = "";

// エンジン初期化：音源フォルダのパスを保存
int init_engine(const char* char_id, const char* audio_dir) {
    if (!audio_dir) return -1;
    strncpy(current_voice_dir, audio_dir, 511);
    return 0;
}

// メモリ解放用
void vse_free_buffer(float* buffer) {
    if (buffer) free(buffer);
}

// 合体・合成処理のメイン
float* request_synthesis_full(SynthesisRequest req, int* out_count) {
    float last_time = 0;
    if (req.note_count > 0) {
        last_time = req.notes[req.note_count-1].start_time + req.notes[req.note_count-1].duration;
    }
    
    int total_samples = (int)((last_time + 1.0f) * req.sample_rate);
    float* output_buffer = (float*)calloc(total_samples, sizeof(float));
    if (!output_buffer) return NULL;

    for (int i = 0; i < req.note_count; i++) {
        CNoteEvent note = req.notes[i];
        
        for (int j = 0; j < note.phoneme_count; j++) {
            char wav_path[1024];
            snprintf(wav_path, sizeof(wav_path), "%s/%s.wav", current_voice_dir, note.phonemes[j]);

            unsigned int channels;
            unsigned int sampleRate;
            drwav_uint64 totalPCMFrameCount;
            
            // ファイルからPCMデータを読み込み
            float* pSampleData = drwav_open_file_and_read_pcm_frames_f32(wav_path, &channels, &sampleRate, &totalPCMFrameCount, NULL);

            if (pSampleData) {
                int start_pos = (int)(note.start_time * req.sample_rate);
                int duration_samples = (int)(note.duration * req.sample_rate);
                
                // ピッチ倍率計算 (MIDI 60 = C4基準)
                float pitch_ratio = powf(2.0f, (note.note_number - 60.0f) / 12.0f);

                for (int s = 0; s < duration_samples; s++) {
                    int target_idx = start_pos + s;
                    if (target_idx >= total_samples) break;

                    // 線形補間リサンプリング
                    float src_pos = s * pitch_ratio;
                    int idx = (int)src_pos;
                    float frac = src_pos - idx;

                    if (idx + 1 < (int)totalPCMFrameCount) {
                        float s1 = pSampleData[idx * channels];
                        float s2 = pSampleData[(idx + 1) * channels];
                        float interpolated = s1 * (1.0f - frac) + s2 * frac;
                        
                        // 加算合成
                        output_buffer[target_idx] += interpolated * (note.velocity / 127.0f) * 0.5f;
                    }
                }
                drwav_free(pSampleData, NULL);
            }
        }
    }

    *out_count = total_samples;
    return output_buffer;
}
