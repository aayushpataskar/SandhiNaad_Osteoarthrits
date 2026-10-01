#include "emg.h"
#include "config.h"
#include <math.h>
#include <esp_timer.h>

// AD8232 used as a single-channel surface-EMG front end on the quadriceps.
// 1 kHz sampling in a dedicated task (uniform spacing, not bursts).

static volatile uint8_t emg_status = ST_NOT_ATTACHED;
static volatile float   env_value = 0;
static volatile bool    saturated = false;

static void emg_task(void*) {
    const float a_hp = expf(-2.0f * (float)M_PI * 20.0f / EMG_SAMPLE_RATE);      // 20 Hz HPF
    const float a_lp = 1.0f - expf(-2.0f * (float)M_PI * 5.0f / EMG_SAMPLE_RATE); // 5 Hz envelope
    float hp_y = 0, hp_x = 0, env = 0;

    EmgSample pkt[EMG_SAMPLES_PER_PKT];
    int idx = 0;
    uint64_t pkt_ts = 0;

    // status window (1 s) and saturation window (per packet frame)
    float s = 0, ss = 0; int n = 0, rail_win = 0, leadoff_win = 0;
    int rail_frame = 0;

    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        vTaskDelayUntil(&wake, 1);    // 1 tick = 1 ms (Arduino-ESP32 uses 1000 Hz tick)
        if (!streaming) { idx = 0; continue; }

        uint16_t raw = analogRead(EMG_PIN);
        float x = (float)raw;
        hp_y = a_hp * (hp_y + x - hp_x);
        hp_x = x;
        env = (1.0f - a_lp) * env + a_lp * fabsf(hp_y);
        env_value = env;

        bool rail = (raw <= 20 || raw >= 4075);
        if (rail) { rail_frame++; rail_win++; }
#if USE_EMG_LEADOFF
        if (digitalRead(EMG_LO_PLUS_PIN) || digitalRead(EMG_LO_MINUS_PIN)) leadoff_win++;
#endif
        s += x; ss += x * x; n++;

        if (idx == 0) pkt_ts = esp_timer_get_time();
        pkt[idx].raw = raw;
        float b = hp_y; if (b > 32767) b = 32767; if (b < -32768) b = -32768;
        pkt[idx].baseline_removed = (int16_t)b;
        pkt[idx].envelope = (uint16_t)(env > 65535 ? 65535 : env);
        if (++idx >= EMG_SAMPLES_PER_PKT) {
            send_packet(PKT_EMG, pkt_ts, pkt, sizeof(pkt));   // EMG sent in every mode
            saturated = rail_frame > (EMG_SAMPLES_PER_PKT * 2) / 100;  // >2% of frame at rails
            rail_frame = 0;
            idx = 0;
        }

        if (n >= EMG_SAMPLE_RATE) {
            float mean = s / n;
            float var = ss / n - mean * mean;
            float sd = sqrtf(var > 0 ? var : 0);
            if (leadoff_win > n / 2)            emg_status = ST_FAULT;         // electrodes off
            else if (sd < 5.0f)                 emg_status = ST_NOT_ATTACHED;  // flat line
            else if (rail_win > n / 2)          emg_status = ST_FAULT;         // stuck at rail
            else                                emg_status = ST_ATTACHED;
            s = ss = 0; n = rail_win = leadoff_win = 0;
        }
    }
}

void emg_init() {
    analogReadResolution(12);
    pinMode(EMG_PIN, INPUT);
#if USE_EMG_LEADOFF
    pinMode(EMG_LO_PLUS_PIN, INPUT);
    pinMode(EMG_LO_MINUS_PIN, INPUT);
#endif
    xTaskCreatePinnedToCore(emg_task, "EMG", 4096, nullptr, 4, nullptr, 0);
}

uint8_t emg_get_status() { return emg_status; }
float emg_get_envelope() { return env_value; }
bool emg_is_saturated() { return saturated; }
