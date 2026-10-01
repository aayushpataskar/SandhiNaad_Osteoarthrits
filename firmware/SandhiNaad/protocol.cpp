#include "protocol.h"
#include "config.h"
#include <stdarg.h>
#include <stdio.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

// One mutex guards the UART. Without it, the audio task (core 1) and the
// sensor/status tasks (core 0) interleave bytes and the host sees CRC errors.
static SemaphoreHandle_t tx_mutex = nullptr;
static uint16_t seq = 0;
static uint8_t  frame[17 + 1100];
static uint32_t bytes_this_window = 0;
static uint32_t bytes_per_sec = 0;
static uint64_t window_start = 0;
static uint32_t dropped = 0;

void protocol_init() {
    tx_mutex = xSemaphoreCreateMutex();
    window_start = esp_timer_get_time();
}

uint16_t calculate_crc16(const uint8_t* data, size_t length) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < length; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (uint8_t j = 0; j < 8; j++) {
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

void send_packet(PacketType type, uint64_t ts, const void* payload, uint16_t len) {
    if (len > 1100) { dropped++; return; }
    if (!tx_mutex) return;
    // Wait at most 100 ms; if the link is that congested, drop and count it.
    if (xSemaphoreTake(tx_mutex, pdMS_TO_TICKS(100)) != pdTRUE) { dropped++; return; }

    uint8_t* f = frame;
    f[0] = 0xA5; f[1] = 0x5A; f[2] = (uint8_t)type;
    f[3] = seq & 0xFF; f[4] = (seq >> 8) & 0xFF;
    seq++;
    for (int i = 0; i < 8; i++) f[5 + i] = (ts >> (8 * i)) & 0xFF;
    f[13] = len & 0xFF; f[14] = (len >> 8) & 0xFF;
    if (len && payload) memcpy(f + 15, payload, len);
    uint16_t crc = calculate_crc16(f + 2, 13 + len);
    f[15 + len] = crc & 0xFF;
    f[16 + len] = (crc >> 8) & 0xFF;
    size_t total = 17 + len;
    Serial.write(f, total);

    bytes_this_window += total;
    uint64_t now = esp_timer_get_time();
    if (now - window_start >= 1000000ULL) {
        bytes_per_sec = bytes_this_window;
        bytes_this_window = 0;
        window_start = now;
    }
    xSemaphoreGive(tx_mutex);
}

void send_log(const char* fmt, ...) {
    char buf[200];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n < 0) return;
    if (n > (int)sizeof(buf) - 1) n = sizeof(buf) - 1;
    send_packet(PKT_LOG, esp_timer_get_time(), buf, (uint16_t)(n + 1));
}

uint32_t protocol_tx_bytes_per_sec() { return bytes_per_sec; }
uint32_t protocol_dropped() { return dropped; }
