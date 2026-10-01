#include "load.h"
#include "config.h"
#include "protocol.h"
#include <Preferences.h>
#include <esp_timer.h>

static uint8_t status = ST_NOT_ATTACHED;
static float force_n = 0;

#if USE_LOADCELL
static Preferences prefs;
static int32_t offset = 0;
static float counts_per_n = 0;         // 0 = not calibrated (force sent as raw counts/1000)
static uint64_t last_ready = 0;
static volatile bool tare_req = false;
static volatile float scale_req_g = 0;
static int avg_n = 0;
static int64_t avg_sum = 0;
static enum { IDLE, TARING, SCALING } avg_mode = IDLE;

static portMUX_TYPE hx_mux = portMUX_INITIALIZER_UNLOCKED;
static int32_t hx_read() {
    // 24 bits MSB first + 1 extra pulse => channel A, gain 128
    uint32_t v = 0;
    portENTER_CRITICAL(&hx_mux);
    for (int i = 0; i < 24; i++) {
        digitalWrite(HX711_SCK, HIGH); delayMicroseconds(1);
        v = (v << 1) | (uint32_t)digitalRead(HX711_DOUT);
        digitalWrite(HX711_SCK, LOW); delayMicroseconds(1);
    }
    digitalWrite(HX711_SCK, HIGH); delayMicroseconds(1);
    digitalWrite(HX711_SCK, LOW);
    portEXIT_CRITICAL(&hx_mux);
    if (v & 0x800000) v |= 0xFF000000;   // sign-extend
    return (int32_t)v;
}
#endif

void load_init() {
#if USE_LOADCELL
    pinMode(HX711_DOUT, INPUT_PULLUP);   // absent module -> pin HIGH -> never ready
    pinMode(HX711_SCK, OUTPUT);
    digitalWrite(HX711_SCK, LOW);
    prefs.begin("sandhinaad", false);
    offset = prefs.getInt("lc_off", 0);
    counts_per_n = prefs.getFloat("lc_cpn", 0.0f);
    last_ready = esp_timer_get_time();
#endif
}

void load_update() {
#if USE_LOADCELL
    uint64_t now = esp_timer_get_time();
    if (digitalRead(HX711_DOUT) != LOW) {
        if (now - last_ready > 500000ULL) status = ST_NOT_ATTACHED;
        return;
    }
    last_ready = now;
    int32_t raw = hx_read();
    status = (raw == 0x7FFFFF || raw == (int32_t)0xFF800000) ? ST_FAULT : ST_ATTACHED;

    if (tare_req) { tare_req = false; avg_mode = TARING; avg_n = 0; avg_sum = 0; }
    if (scale_req_g > 0 && avg_mode == IDLE) { avg_mode = SCALING; avg_n = 0; avg_sum = 0; }
    if (avg_mode != IDLE) {
        avg_sum += raw;
        if (++avg_n >= 16) {
            int32_t avg = (int32_t)(avg_sum / avg_n);
            if (avg_mode == TARING) {
                offset = avg;
                prefs.putInt("lc_off", offset);
                send_log("TARE done: offset=%ld", (long)offset);
            } else {
                float newton = scale_req_g / 1000.0f * 9.80665f;
                if (newton > 0 && avg != offset) {
                    counts_per_n = (float)(avg - offset) / newton;
                    prefs.putFloat("lc_cpn", counts_per_n);
                    send_log("SCALE done: %.1f counts/N", counts_per_n);
                } else {
                    send_log("SCALE failed: put the known weight on the cell and TARE first");
                }
                scale_req_g = 0;
            }
            avg_mode = IDLE;
        }
    }
    force_n = (counts_per_n != 0) ? (raw - offset) / counts_per_n : (raw - offset) / 1000.0f;
    LoadPayload lp{force_n, status};
    send_packet(PKT_LOAD, now, &lp, sizeof(lp));
#endif
}

void load_request_tare() {
#if USE_LOADCELL
    tare_req = true;
#endif
}
void load_request_scale(float g) {
#if USE_LOADCELL
    scale_req_g = g;
#else
    (void)g;
#endif
}
uint8_t load_get_status() { return status; }
float load_get_force_n() { return force_n; }
