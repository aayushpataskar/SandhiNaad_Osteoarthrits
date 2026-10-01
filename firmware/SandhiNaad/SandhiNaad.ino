// =============================================================================
// SandhiNaad (सन्धिनाद) — knee joint-sound screening wearable, ESP32 firmware
//
// Open THIS file in Arduino IDE (the folder name must stay "SandhiNaad").
// Board: "ESP32 Dev Module". Libraries: "Adafruit BNO055" (+ Adafruit Unified
// Sensor, Adafruit BusIO — the IDE offers to install them together).
// No other libraries are needed (HX711 driver is built in).
//
// The board streams a BINARY protocol at 921600 baud — the Arduino Serial
// Monitor will show garbage. Use the Python host app (host/app.py) instead.
//
// Tasks:  core 1: Audio (I2S 16 kHz, DSP, events, features, on-device model)
//         core 0: EMG (1 kHz), Sensor (IMU + load @100 Hz), Status (2 Hz)
//         loop(): serial command parser
// =============================================================================
#include <Arduino.h>
#include <esp_timer.h>
#include "config.h"
#include "protocol.h"
#include "audio.h"
#include "imu.h"
#include "emg.h"
#include "load.h"
#include "model.h"

#define FW_VERSION "1.3.0"

volatile uint8_t  stream_mode = MODE_DEFAULT;
volatile bool     streaming = false;
volatile float    threshold_db = THRESHOLD_DB_DEFAULT;
volatile uint32_t audio_loop_time_us = 0;
static volatile bool status_now = false;

static void run_model_selftest() {
    float p = model_predict(MODEL_TEST_VECTOR);
    float d = fabsf(p - MODEL_TEST_EXPECTED_PROB);
    send_log("SELFTEST model: prob=%.7f expected=%.7f diff=%.2e %s%s",
             p, MODEL_TEST_EXPECTED_PROB, d, d < 1e-4f ? "PASS" : "FAIL",
             MODEL_SYNTHETIC ? " (SYNTHETIC model)" : "");
}

static void sensor_task(void*) {
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        imu_update();       // 100 Hz, sends PKT_IMU
        load_update();      // sends PKT_LOAD whenever the HX711 has a sample
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(10));
    }
}

static void send_status() {
    StatusPayload st = {};
    ImuPayload ip = imu_get_payload();
    st.mic1_status = audio_get_mic_status(0);
    st.mic2_status = audio_get_mic_status(1);
    st.imu1_status = ip.status_thigh;
    st.imu2_status = ip.status_shank;
    st.emg_status = emg_get_status();
    st.load_status = load_get_status();
    st.stream_mode = stream_mode;
    st.free_heap = ESP.getFreeHeap();
    st.dropped_packets = protocol_dropped();
    st.tx_bytes_per_sec = protocol_tx_bytes_per_sec();
    st.loop_time_us = audio_loop_time_us;
    st.mic1_slot = (uint8_t)audio_get_live_slot();
    st.noise_floor_dbfs = audio_get_noise_floor_dbfs();
    send_packet(PKT_STATUS, esp_timer_get_time(), &st, sizeof(st));
}

static void status_task(void*) {
    uint32_t elapsed = 0;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(50));
        elapsed += 50;
        if (elapsed >= 500 || status_now) {   // STATUS is sent even when not streaming
            elapsed = 0;
            status_now = false;
            send_status();
        }
    }
}

static void handle_command(String cmd) {
    cmd.trim();
    String up = cmd; up.toUpperCase();
    bool ok = true;

    if (up == "START") streaming = true;
    else if (up == "STOP") streaming = false;
    else if (up.startsWith("MODE ")) {
        String m = up.substring(5); m.trim();
        if (m == "FULL") stream_mode = MODE_FULL;
        else if (m == "DEFAULT") stream_mode = MODE_DEFAULT;
        else if (m == "FEATURES") stream_mode = MODE_FEATURES;
        else ok = false;
    }
    else if (up == "CAL_ZERO") imu_request_cal_zero();
    else if (up == "TARE") load_request_tare();
    else if (up.startsWith("SCALE ")) {
        float g = up.substring(6).toFloat();
        if (g > 0) load_request_scale(g); else ok = false;
    }
    else if (up.startsWith("THRESH ")) {
        float db = up.substring(7).toFloat();
        if (db >= 3 && db <= 60) { threshold_db = db; send_log("Event threshold = %.1f dB", db); }
        else ok = false;
    }
    else if (up.startsWith("RATE ")) {
        send_log("RATE: this build is fixed at %d Hz (model trained at 16 kHz)", SAMPLE_RATE);
    }
    else if (up == "PING") { /* ACK only */ }
    else if (up == "STATUS") status_now = true;
    else if (up == "SELFTEST") run_model_selftest();
    else if (up == "VERSION") send_log("SandhiNaad FW %s, %d Hz, %lu baud", FW_VERSION, SAMPLE_RATE, (unsigned long)BAUD_RATE);
    else ok = false;

    String ack = ok ? cmd : String("ERR ") + cmd;
    send_packet(PKT_ACK, esp_timer_get_time(), ack.c_str(), (uint16_t)(ack.length() + 1));
}

void setup() {
    Serial.setTxBufferSize(8192);   // must be before begin(); smooths bursts
    Serial.setRxBufferSize(512);
    Serial.begin(BAUD_RATE);
    delay(200);
    protocol_init();

    send_log("SandhiNaad FW %s booting", FW_VERSION);
    imu_init();
    load_init();
    emg_init();
    audio_init();

    xTaskCreatePinnedToCore(sensor_task, "Sensor", 6144, nullptr, 3, nullptr, 0);
    xTaskCreatePinnedToCore(status_task, "Status", 3072, nullptr, 1, nullptr, 0);

    ImuPayload ip = imu_get_payload();
    send_log("Boot: IMU thigh=%s shank=%s | load=%s | waiting for START",
             ip.status_thigh == 0 ? "OK" : "missing",
             ip.status_shank == 0 ? "OK" : "missing",
             USE_LOADCELL ? "enabled" : "disabled");
    run_model_selftest();
}

void loop() {
    static String line;
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            if (line.length()) handle_command(line);
            line = "";
        } else if (line.length() < 64) {
            line += c;
        }
    }
    delay(5);
}
