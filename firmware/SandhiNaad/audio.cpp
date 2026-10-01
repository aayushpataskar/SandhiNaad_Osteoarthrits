#include "audio.h"
#include "config.h"
#include "protocol.h"
#include "dsp.h"
#include "acoustic_features.h"
#include "imu.h"
#include "model.h"
#include <esp_timer.h>
#include <math.h>
#include <string.h>

// ---------------------------------------------------------------------------
// Two INMP441 share one I2S bus: L/R=GND -> one slot, L/R=3V3 -> the other.
// (The legacy ESP32 I2S driver may swap L/R order in memory; we therefore
//  detect which slot carries a live mic instead of assuming.)
// Analysis runs on one "primary" mic; the second mic is monitored for status
// and is reserved for real localization later (the UI demo is simulated).
// ---------------------------------------------------------------------------

static volatile float   noise_floor_dbfs = -90.0f;
static volatile int     live_slot = 0;
static volatile uint8_t mic_status[2] = {ST_NOT_ATTACHED, ST_NOT_ATTACHED};

float audio_get_noise_floor_dbfs() { return noise_floor_dbfs; }
int audio_get_live_slot() { return live_slot; }
uint8_t audio_get_mic_status(int m) { return (m >= 0 && m < 2) ? mic_status[m] : ST_NOT_ATTACHED; }

// Static buffers (keeps the task stack small)
static int32_t stereo[BLOCK_SIZE * 2];
static int16_t raw16[BLOCK_SIZE];
static int16_t filt16[BLOCK_SIZE];
static int16_t hist16[BLOCK_SIZE * 2];     // previous + current filtered block (for snippets)
static float   filt_f[BLOCK_SIZE];
static float   env_f[BLOCK_SIZE];
static int16_t minmax[DISPLAY_N * 2];
static uint16_t env_disp[DISPLAY_N];
static float   noise_hist[NOISE_BLOCKS];
static float   noise_sorted[NOISE_BLOCKS];

static float median_of(const float* v, int n) {
    memcpy(noise_sorted, v, n * sizeof(float));
    for (int i = 1; i < n; i++) {                 // insertion sort, n=30
        float k = noise_sorted[i]; int j = i - 1;
        while (j >= 0 && noise_sorted[j] > k) { noise_sorted[j + 1] = noise_sorted[j]; j--; }
        noise_sorted[j + 1] = k;
    }
    return noise_sorted[n / 2];
}

static void audio_task(void*) {
    size_t got = 0;
    // 1) settle: discard first ~100 ms
    for (int i = 0; i < SAMPLE_RATE / BLOCK_SIZE / 10 + 1; i++)
        i2s_read(I2S_PORT, stereo, sizeof(stereo), &got, portMAX_DELAY);

    FilterCascade bp; bp.init((float)SAMPLE_RATE);
    EnvelopeFollower envf; envf.init((float)SAMPLE_RATE, ENV_CUTOFF);
    float px = 0, py = 0;
    float slot_std_ema[2] = {0, 0};
    int noise_idx = 0, noise_count = 0;
    uint64_t last_event = 0;

    float cyc_sum[17] = {0};
    int cyc_blocks = 0;
    uint32_t last_cycle_id = 0;

    for (;;) {
        i2s_read(I2S_PORT, stereo, sizeof(stereo), &got, portMAX_DELAY);
        uint64_t t0 = esp_timer_get_time();
        // timestamp of the FIRST sample of this block
        uint64_t ts = t0 - (uint64_t)BLOCK_SIZE * 1000000ULL / SAMPLE_RATE;

        // ---- per-slot presence (std of raw 24-bit counts) ----
        for (int s = 0; s < 2; s++) {
            float m = 0, v = 0;
            for (int i = 0; i < BLOCK_SIZE; i++) m += (float)(stereo[2 * i + s] >> 8);
            m /= BLOCK_SIZE;
            for (int i = 0; i < BLOCK_SIZE; i++) { float d = (float)(stereo[2 * i + s] >> 8) - m; v += d * d; }
            float sd = sqrtf(v / BLOCK_SIZE);
            slot_std_ema[s] = 0.9f * slot_std_ema[s] + 0.1f * sd;
            // INMP441 self-noise is ~300 counts RMS; an empty slot reads flat.
            mic_status[s] = slot_std_ema[s] > 30.0f ? ST_ATTACHED : ST_NOT_ATTACHED;
        }
        int prim = (mic_status[0] == ST_ATTACHED) ? 0 : ((mic_status[1] == ST_ATTACHED) ? 1 : 0);
        if (prim != live_slot) { live_slot = prim; bp.reset(); envf.reset(); px = py = 0; }

        if (!streaming) continue;

        // ---- DC removal -> band-pass -> envelope ----
        float sum_sq = 0, peak = 0; int peak_i = 0;
        for (int i = 0; i < BLOCK_SIZE; i++) {
            float x = (float)(stereo[2 * i + prim] >> 8) / 8388608.0f;
            raw16[i] = (int16_t)constrain(x * 32767.0f, -32768.0f, 32767.0f);
            float y = x - px + DC_ALPHA * py; px = x; py = y;
            float f = bp.process(y);
            filt_f[i] = f;
            filt16[i] = (int16_t)constrain(f * 32767.0f, -32768.0f, 32767.0f);
            env_f[i] = envf.process(f);
            sum_sq += f * f;
            float a = fabsf(f);
            if (a > peak) { peak = a; peak_i = i; }
        }
        memmove(hist16, hist16 + BLOCK_SIZE, BLOCK_SIZE * sizeof(int16_t));
        memcpy(hist16 + BLOCK_SIZE, filt16, BLOCK_SIZE * sizeof(int16_t));

        // ---- noise floor: rolling median of block RMS (~1 s) ----
        float rms = sqrtf(sum_sq / BLOCK_SIZE);
        noise_hist[noise_idx] = rms;
        noise_idx = (noise_idx + 1) % NOISE_BLOCKS;
        if (noise_count < NOISE_BLOCKS) noise_count++;
        float floor_rms = median_of(noise_hist, noise_count);
        if (floor_rms < 1e-7f) floor_rms = 1e-7f;
        noise_floor_dbfs = 20.0f * log10f(floor_rms);

        // ---- click / crepitus event ----
        float thr_lin = floor_rms * powf(10.0f, threshold_db / 20.0f);
        uint64_t peak_ts = ts + (uint64_t)peak_i * 1000000ULL / SAMPLE_RATE;
        if (noise_count >= 10 && peak > thr_lin &&
            (peak_ts - last_event) > (uint64_t)REFRACTORY_MS * 1000ULL) {
            static EventPayload ep;
            ep.event_time_us = peak_ts;
            ep.peak_dbfs = 20.0f * log10f(peak + 1e-9f);
            ep.margin_db = ep.peak_dbfs - noise_floor_dbfs;
            int first = -1, last = -1;
            for (int i = 0; i < BLOCK_SIZE; i++)
                if (fabsf(filt_f[i]) > 0.5f * thr_lin) { if (first < 0) first = i; last = i; }
            ep.duration_ms = (first >= 0) ? (last - first + 1) * 1000.0f / SAMPLE_RATE : 0.0f;
            ep.knee_angle = imu_get_knee_angle();
            ep.phase = imu_get_phase();
            int start = BLOCK_SIZE + peak_i - 128;              // index into hist16
            for (int i = 0; i < 256; i++) {
                int k = start + i;
                ep.snippet[i] = (k >= 0 && k < 2 * BLOCK_SIZE) ? hist16[k] : 0;
            }
            send_packet(PKT_EVENT, peak_ts, &ep, sizeof(ep));
            last_event = peak_ts;
            imu_add_event_to_cycle();
        }

        // ---- block features ----
        FeatBlockPayload fb = {};
        compute_time_features(filt_f, BLOCK_SIZE, &fb);
        compute_spectral_features(filt_f, BLOCK_SIZE, SAMPLE_RATE, &fb);
        fb.floor_dbfs = noise_floor_dbfs;
        send_packet(PKT_FEAT_BLOCK, ts, &fb, sizeof(fb));

        float fa[17];                            // aligned copy (packed struct)
        memcpy(fa, &fb, sizeof(fa));
        for (int i = 0; i < 17; i++) cyc_sum[i] += fa[i];
        cyc_blocks++;

        // ---- per-cycle model (triggered by a NEW completed IMU cycle) ----
        CycleData c = imu_get_last_cycle();
        if (c.id != 0 && c.id != last_cycle_id && cyc_blocks > 0) {
            last_cycle_id = c.id;
            static FeatCyclePayload fc;
            float mi[MODEL_NUM_FEATURES];
            for (int i = 0; i < 17; i++) mi[i] = cyc_sum[i] / cyc_blocks;
            mi[17] = (float)c.num_events;
            mi[18] = c.rom;
            mi[19] = c.peak_flex_vel;
            mi[20] = fabsf(c.peak_ext_vel);
            mi[21] = c.duration_s;
            fc.oa_probability = model_predict(mi);
            memcpy(fc.model_input, mi, sizeof(mi));
            fc.rom = c.rom;
            fc.peak_flex_vel = c.peak_flex_vel;
            fc.peak_ext_vel = c.peak_ext_vel;
            fc.duration_s = c.duration_s;
            fc.num_events = (float)c.num_events;
            fc.mean_rms = mi[0];
            fc.mean_spectral_centroid = mi[3];
            fc.mean_hf_ratio = mi[9];
            fc.mean_spectral_entropy = mi[10];
            fc.mean_kurtosis = mi[11];
            send_packet(PKT_FEAT_CYCLE, ts, &fc, sizeof(fc));
            for (int i = 0; i < 17; i++) cyc_sum[i] = 0;
            cyc_blocks = 0;
        }
        if (cyc_blocks > 2000) {                 // no cycles for ~1 min: restart accumulation
            for (int i = 0; i < 17; i++) cyc_sum[i] = 0;
            cyc_blocks = 0;
        }

        // ---- display streams ----
        for (int d = 0; d < DISPLAY_N; d++) {
            int16_t lo = 32767, hi = -32768; float e = 0;
            for (int k = 0; k < DISPLAY_DECIM; k++) {
                int16_t v = raw16[d * DISPLAY_DECIM + k];
                if (v < lo) lo = v;
                if (v > hi) hi = v;
                e = env_f[d * DISPLAY_DECIM + k];
            }
            minmax[2 * d] = lo; minmax[2 * d + 1] = hi;
            float es = e * 65535.0f;
            env_disp[d] = (uint16_t)(es > 65535.0f ? 65535.0f : es);
        }
        send_packet(PKT_ENVELOPE, ts, env_disp, sizeof(env_disp));      // all modes
        uint8_t mode = stream_mode;
        if (mode == MODE_DEFAULT) send_packet(PKT_AUDIO_MINMAX, ts, minmax, sizeof(minmax));
        if (mode == MODE_DEFAULT || mode == MODE_FULL) send_packet(PKT_AUDIO_FILT, ts, filt16, sizeof(filt16));
        if (mode == MODE_FULL) send_packet(PKT_AUDIO_RAW, ts, raw16, sizeof(raw16));

        audio_loop_time_us = (uint32_t)(esp_timer_get_time() - t0);
    }
}

void audio_init() {
    i2s_config_t cfg = {};
    cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
    cfg.sample_rate = SAMPLE_RATE;
    cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
    cfg.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;
    cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    cfg.intr_alloc_flags = 0;
    cfg.dma_buf_count = 8;
    cfg.dma_buf_len = 256;
    cfg.use_apll = false;

    i2s_pin_config_t pins = {};
    pins.mck_io_num = I2S_PIN_NO_CHANGE;
    pins.bck_io_num = I2S_SCK;
    pins.ws_io_num = I2S_WS;
    pins.data_out_num = I2S_PIN_NO_CHANGE;
    pins.data_in_num = I2S_SD;

    if (i2s_driver_install(I2S_PORT, &cfg, 0, nullptr) != ESP_OK ||
        i2s_set_pin(I2S_PORT, &pins) != ESP_OK) {
        send_log("I2S init FAILED");
        return;
    }
    xTaskCreatePinnedToCore(audio_task, "Audio", 8192, nullptr, 5, nullptr, 1);
}
