# SandhiNaad (सन्धिनाद) — Knee Joint-Sound Screening System

## Overview
**SandhiNaad** is a multimodal knee-osteoarthritis screening wearable prototype. It captures and analyzes knee joint sounds (acoustic emissions) synchronized with kinematic data and muscle activity to screen for potential joint degradation.

## System Components
- **ESP32 Firmware:** Handles high-speed data acquisition, real-time digital signal processing (DSP), and streaming via a custom binary protocol.
- **Python Desktop App:** Provides real-time streaming, UI visualization, device control, and recording capabilities.
- **ML Pipeline:** Synthetic data generation, model training, and exporting trained models to C-headers for on-device inference.

## Hardware Setup
- **Microcontroller:** ESP32 DevKit
- **Acoustics:** 2× INMP441 MEMS microphones on one I2S bus (L/R = GND and 3V3)
- **Kinematics:** 2x BNO055 IMU (I2C) for thigh and shank tracking
- **Muscle Activity:** AD8232 ECG front-end (used as an EMG reference)
- **Load (Optional):** HX711 + bar load cell (auto-detected)

## Quick Start
**Full step-by-step guide: [`docs/HOW_TO_RUN.md`](docs/HOW_TO_RUN.md)** (wiring, Arduino IDE upload, UI, retraining).

1. **Firmware:** open `firmware/SandhiNaad/SandhiNaad.ino` in Arduino IDE (board: ESP32 Dev Module) and Upload — or `pio run -t upload` in `firmware/`.
2. **Host App:** `cd host`, `pip install -r requirements.txt`, `python app.py`, pick the COM port (or **SIMULATOR** without hardware), Connect.
3. **ML (Optional):** `ml/synth_data.py` → `ml/train.py` → `ml/export_c_header.py` (writes `firmware/SandhiNaad/model.h`).

## Repository Structure
```
.
├── docs/       # Project documentation
├── firmware/   # SandhiNaad/ Arduino sketch (.ino + modules) + platformio.ini
├── host/       # Python UI and host communication app
└── ml/         # Python machine learning and DSP modeling scripts
```

## Current Status
**Prototype:** The system currently relies on synthetic data only and has **not** been clinically validated.

## License
[License Placeholder]
