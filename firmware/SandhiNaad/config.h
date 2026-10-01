#pragma once
// =============================================================================
// SandhiNaad firmware — central configuration
// Board: ESP32 DevKit V1 (ESP32-WROOM-32). Works in Arduino IDE and PlatformIO.
// =============================================================================
#include <Arduino.h>
#include <driver/i2s.h>

// ---- Feature switches -------------------------------------------------------
// Load cell (HX711) is auto-detected at runtime; set to 0 to compile it out.
#ifndef USE_LOADCELL
#define USE_LOADCELL 1
#endif
// AD8232 lead-off pins (LO+ / LO-) wired? 1 = use them for EMG status.
#ifndef USE_EMG_LEADOFF
#define USE_EMG_LEADOFF 0
#endif

// ---- Pins -------------------------------------------------------------------
// I2S bus shared by both INMP441 mics (mic #1 L/R->GND, mic #2 L/R->3V3)
constexpr int I2S_SCK = 26;
constexpr int I2S_WS  = 25;
constexpr int I2S_SD  = 33;
// AD8232 analog output (ADC1 only — ADC2 is unusable while WiFi/BT is on)
constexpr int EMG_PIN = 34;
constexpr int EMG_LO_PLUS_PIN  = 32;
constexpr int EMG_LO_MINUS_PIN = 35;
// I2C for both BNO055
constexpr int I2C_SDA = 21;
constexpr int I2C_SCL = 22;
// HX711 load-cell amplifier
constexpr int HX711_DOUT = 16;
constexpr int HX711_SCK  = 17;

// ---- Audio ------------------------------------------------------------------
constexpr int SAMPLE_RATE = 16000;
constexpr int BLOCK_SIZE  = 512;                 // 32 ms per block
constexpr int DISPLAY_DECIM = 16;                // 512/16 = 32 values/block = 1 kHz display rate
constexpr int DISPLAY_N = BLOCK_SIZE / DISPLAY_DECIM;
constexpr i2s_port_t I2S_PORT = I2S_NUM_0;

// ---- BNO055 addresses -------------------------------------------------------
constexpr uint8_t BNO055_ADDRESS_THIGH = 0x28;   // ADR -> GND
constexpr uint8_t BNO055_ADDRESS_SHANK = 0x29;   // ADR -> 3V3

// ---- EMG --------------------------------------------------------------------
constexpr int EMG_SAMPLE_RATE = 1000;
constexpr int EMG_SAMPLES_PER_PKT = 33;          // ~30 packets/s

// ---- Serial link ------------------------------------------------------------
constexpr uint32_t BAUD_RATE = 921600;           // host must use the same value

// ---- Event detection (THRESH command changes the threshold at runtime) ------
constexpr float THRESHOLD_DB_DEFAULT = 18.0f;
constexpr int   REFRACTORY_MS = 50;
constexpr int   NOISE_BLOCKS = 30;               // ~1 s rolling median

// ---- DSP --------------------------------------------------------------------
constexpr float DC_ALPHA   = 0.9975f;            // ~20 Hz one-pole HPF @16 kHz
constexpr float BP_LOW     = 250.0f;
constexpr float BP_HIGH    = 4500.0f;
constexpr float ENV_CUTOFF = 50.0f;

// ---- Stream modes -----------------------------------------------------------
constexpr uint8_t MODE_FULL     = 0;
constexpr uint8_t MODE_DEFAULT  = 1;
constexpr uint8_t MODE_FEATURES = 2;

// ---- Sensor status codes ----------------------------------------------------
constexpr uint8_t ST_ATTACHED     = 0;
constexpr uint8_t ST_NOT_ATTACHED = 1;
constexpr uint8_t ST_FAULT        = 2;

// ---- Shared runtime state (defined in SandhiNaad.ino) -----------------------
extern volatile uint8_t stream_mode;
extern volatile bool    streaming;
extern volatile float   threshold_db;
extern volatile uint32_t audio_loop_time_us;
