# SandhiNaad Binary Protocol Specification

This document details the binary protocol used for communication between the ESP32 device and the Host application.

## Link Layer
- **Transport:** USB serial
- **Baud Rate:** 921600 baud (8N1), optional 2000000 baud
- **Bridge:** On-board USB-UART bridge (CP2102 or CH340)

## Packet Format
All multi-byte fields are transmitted in Little-Endian format. Total overhead per packet is 17 bytes.

| Offset | Size | Field | Description |
|---|---|---|---|
| 0 | 2 | Sync bytes | `0xA5`, `0x5A` |
| 2 | 1 | Packet type | Identifies payload type (see below) |
| 3 | 2 | Sequence number | `uint16`, ONE global counter across all packet types, wraps at 65535 (gaps = dropped packets) |
| 5 | 8 | Timestamp | `uint64`, microseconds from `esp_timer_get_time()` |
| 13 | 2 | Payload length | `uint16`, 0-65535 (N) |
| 15 | N | Payload | Packet-specific data |
| 15+N | 2 | CRC16-CCITT | Polynomial `0x1021`, init `0xFFFF` |

## Packet Types

### 0x01 AUDIO_RAW
- **Direction:** ESP → Host
- **Payload:** `int16[N]` raw audio samples
- **Typical Size:** N=512 (1024 bytes) — approx 32ms at 16kHz
- **Rate:** ~31 packets/s

### 0x02 AUDIO_FILT
- **Direction:** ESP → Host
- **Payload:** `int16[N]` band-passed audio samples
- **Typical Size:** 1024 bytes
- **Rate:** ~31 packets/s

### 0x03 AUDIO_MINMAX
- **Direction:** ESP → Host
- **Payload:** `struct{int16 min, max}[32]` — raw audio decimated ×16 → 1 kHz display pairs
- **Typical Size:** 128 bytes (sent in DEFAULT mode only)
- **Rate:** ~31 packets/s

### 0x04 ENVELOPE
- **Direction:** ESP → Host
- **Payload:** `uint16[32]` envelope (50 Hz follower of |filtered|) decimated to 1 kHz, amplitude × 65535
- **Typical Size:** 64 bytes (all modes)
- **Rate:** ~31 packets/s

### 0x05 EMG
- **Direction:** ESP → Host
- **Payload:** `struct{uint16 raw, int16 baseline_removed, uint16 envelope}[N]`
- **Typical Size:** N=~33 at 1kHz/30fps (198 bytes)
- **Rate:** 30 packets/s (all modes)

### 0x06 IMU
- **Direction:** ESP → Host
- **Payload:** thigh quat(`4×f32`) + shank quat(`4×f32`) + knee_angle(`f32`) + angular_vel(`f32`) + phase(`u8`: 0 hold, 1 flexion, 2 extension) + thigh cal sys/gyro/accel/mag(`4×u8`) + status thigh/shank(`2×u8`)
- **Typical Size:** 47 bytes
- **Rate:** 100 Hz (all modes)

### 0x07 LOAD
- **Direction:** ESP → Host
- **Payload:** force_N(`f32`) + status(`u8`)
- **Typical Size:** 5 bytes
- **Rate:** 80 Hz (when enabled)

### 0x08 EVENT
- **Direction:** ESP → Host
- **Payload:** timestamp(`u64`) + peak_dbfs(`f32`) + margin(`f32`) + duration(`f32`) + angle(`f32`) + phase(`u8`) + snippet(`256×i16`)
- **Typical Size:** 537 bytes
- **Rate:** Sporadic

### 0x09 FEAT_BLOCK
- **Direction:** ESP → Host
- **Payload:** 17 × `f32`
- **Typical Size:** 68 bytes
- **Rate:** ~31/s

### 0x0A FEAT_CYCLE
- **Direction:** ESP → Host
- **Payload:** 11 × `f32` (rom, peak_flex_vel, peak_ext_vel, duration_s, num_events, oa_probability, mean_rms, mean_spectral_centroid, mean_hf_ratio, mean_kurtosis, mean_spectral_entropy) + 22 × `f32` model input vector (order = ACOUSTIC_FEATURES in ml/config.py)
- **Typical Size:** 132 bytes
- **Rate:** Per cycle (~0.3/s)

### 0x0B STATUS
- **Direction:** ESP → Host
- **Payload:** mic1, mic2, imu1, imu2, emg, load status (`6×u8`: 0 ATTACHED, 1 NOT_ATTACHED, 2 FAULT) + stream_mode(`u8`) + free_heap, dropped_packets, tx_bytes_per_sec, loop_time_us (`4×u32`) + mic1_slot(`u8`) + noise_floor_dbfs(`f32`)
- **Typical Size:** 28 bytes (sent even when not streaming)
- **Rate:** 2/s

### 0x0C LOG
- **Direction:** ESP → Host
- **Payload:** Null-terminated string
- **Typical Size:** Variable
- **Rate:** Sporadic

### 0x0D ACK
- **Direction:** ESP → Host
- **Payload:** Null-terminated command echo
- **Typical Size:** Variable
- **Rate:** On command

## Bandwidth Budget Table
Link Capacity at 921600 baud ≈ 92160 bytes/s. Assuming ~70% usable bandwidth = **64500 bytes/s**.

| Mode | Active Streams | Bytes/s (approx) | % of Usable Link |
|---|---|---|---|
| **MODE_FULL** | Raw + Filt + Env + EMG + IMU + Load + Feat + Evt + Stat | ~90,000 | > 100% (may drop at 921600) |
| **MODE_DEFAULT** | Filt + MinMax + Env + EMG + IMU + Load + Feat + Evt + Stat | ~55,000 | ~85% |
| **MODE_FEATURES**| Env + EMG + IMU + Load + Feat + Evt + Stat (no waveforms) | ~15,000 | ~23% |

## Stream Modes
- **FULL:** Transmits everything, including raw and filtered audio at full rate. May approach or exceed link limit.
- **DEFAULT:** Filtered audio full rate, raw audio as min/max decimated pairs, plus all other streams.
- **FEATURES:** No audio waveforms sent. Only processed envelope, EMG, IMU, and features are transmitted.

## Host Commands
Sent from Host to ESP as ASCII, newline-terminated (`\n`).
- `START`: Begin data streaming.
- `STOP`: Halt data streaming.
- `MODE FULL|DEFAULT|FEATURES`: Switch the active stream mode.
- `CAL_ZERO`: Zero-calibrate the IMUs.
- `TARE`: Tare the load cell.
- `SCALE <g>`: Calibrate the load cell with known weight.
- `THRESH <dB>`: Set acoustic event detection threshold.
- `RATE 16000|48000`: Not supported in this build (fixed 16 kHz, model trained at 16 kHz) — replies with a LOG.
- `PING`: Request an ACK.
- `STATUS`: Request an immediate STATUS packet.
- `SELFTEST`: Run model_predict() on the embedded test vector and LOG PASS/FAIL (also runs at boot).
- `VERSION`: LOG firmware version.

Every command is answered with an ACK echoing it (prefixed `ERR ` if rejected).

## CRC16-CCITT Algorithm
The CRC uses polynomial `0x1021` and initial value `0xFFFF`.

```c
uint16_t calculate_crc16(const uint8_t *data, size_t length) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < length; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (uint8_t j = 0; j < 8; j++) {
            if (crc & 0x8000) crc = (crc << 1) ^ 0x1021;
            else crc <<= 1;
        }
    }
    return crc;
}
```

## Resynchronization
If parsing fails or a stream is interrupted (invalid CRC, missing sync bytes):
1. The parser must scan forward byte-by-byte for the sync sequence `0xA5 0x5A`.
2. Once found, attempt to parse the header (type, seq, timestamp, length).
3. Validate the payload against the trailing CRC16-CCITT. If invalid, resume scanning from the byte after the invalid sync byte.

## Concurrency (firmware)
All tasks call `send_packet()`, which builds the whole frame and writes it under one FreeRTOS mutex, so frames from different cores never interleave.
