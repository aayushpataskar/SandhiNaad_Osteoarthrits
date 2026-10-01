#pragma once
#include <stdint.h>
#include <stddef.h>

// Packet: A5 5A | type u8 | seq u16 | ts_us u64 | len u16 | payload | crc16 (LE)
// CRC16-CCITT (poly 0x1021, init 0xFFFF) over type..payload (sync excluded).
// seq is ONE global counter across all packet types (host uses it for drop count).

enum PacketType : uint8_t {
    PKT_AUDIO_RAW    = 0x01,
    PKT_AUDIO_FILT   = 0x02,
    PKT_AUDIO_MINMAX = 0x03,
    PKT_ENVELOPE     = 0x04,
    PKT_EMG          = 0x05,
    PKT_IMU          = 0x06,
    PKT_LOAD         = 0x07,
    PKT_EVENT        = 0x08,
    PKT_FEAT_BLOCK   = 0x09,
    PKT_FEAT_CYCLE   = 0x0A,
    PKT_STATUS       = 0x0B,
    PKT_LOG          = 0x0C,
    PKT_ACK          = 0x0D
};

struct __attribute__((packed)) ImuPayload {          // 47 bytes
    float qw_thigh, qx_thigh, qy_thigh, qz_thigh;
    float qw_shank, qx_shank, qy_shank, qz_shank;
    float knee_angle;        // deg
    float angular_vel;       // deg/s (+ = flexion)
    uint8_t phase;           // 0 HOLD, 1 FLEXION, 2 EXTENSION
    uint8_t cal_sys, cal_gyro, cal_accel, cal_mag;   // thigh BNO055 calibration 0..3
    uint8_t status_thigh;
    uint8_t status_shank;
};

struct __attribute__((packed)) EmgSample {           // 6 bytes
    uint16_t raw;
    int16_t  baseline_removed;
    uint16_t envelope;
};

struct __attribute__((packed)) LoadPayload {         // 5 bytes
    float   force_n;
    uint8_t status;
};

struct __attribute__((packed)) EventPayload {        // 537 bytes
    uint64_t event_time_us;
    float peak_dbfs;
    float margin_db;
    float duration_ms;
    float knee_angle;
    uint8_t phase;
    int16_t snippet[256];
};

// Order == first 17 entries of ACOUSTIC_FEATURES in ml/config.py
struct __attribute__((packed)) FeatBlockPayload {    // 68 bytes
    float rms;
    float peak_dbfs;
    float floor_dbfs;
    float spectral_centroid;
    float peak_freq;
    float subband_250_500;
    float subband_500_1k;
    float subband_1k_2k;
    float subband_2k_4k5;
    float hf_ratio;
    float spectral_entropy;
    float kurtosis;          // Pearson (normal = 3)
    float skewness;
    float hjorth_activity;
    float hjorth_mobility;
    float hjorth_complexity;
    float zcr;               // sign changes / sample
};

struct __attribute__((packed)) FeatCyclePayload {    // 132 bytes
    float rom;
    float peak_flex_vel;
    float peak_ext_vel;
    float duration_s;
    float num_events;
    float oa_probability;    // on-device model output
    float mean_rms;
    float mean_spectral_centroid;
    float mean_hf_ratio;
    float mean_kurtosis;
    float mean_spectral_entropy;
    float model_input[22];   // exact vector fed to model_predict() (host re-checks it)
};

struct __attribute__((packed)) StatusPayload {       // 28 bytes
    uint8_t mic1_status;
    uint8_t mic2_status;
    uint8_t imu1_status;
    uint8_t imu2_status;
    uint8_t emg_status;
    uint8_t load_status;
    uint8_t stream_mode;
    uint32_t free_heap;
    uint32_t dropped_packets;
    uint32_t tx_bytes_per_sec;
    uint32_t loop_time_us;
    uint8_t mic1_slot;
    float noise_floor_dbfs;
};

void protocol_init();
uint16_t calculate_crc16(const uint8_t* data, size_t length);
// Thread-safe: may be called from any task on either core.
void send_packet(PacketType type, uint64_t timestamp_us, const void* payload, uint16_t len);
void send_log(const char* fmt, ...);
uint32_t protocol_tx_bytes_per_sec();
uint32_t protocol_dropped();
