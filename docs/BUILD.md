# Build & Run Instructions

The complete, current guide is **[HOW_TO_RUN.md](HOW_TO_RUN.md)**. It covers:

- Wiring table (2× INMP441, 2× BNO055, AD8232, HX711)
- Uploading `firmware/SandhiNaad/SandhiNaad.ino` with Arduino IDE (esp32 core 2.0.17, Core Debug Level = None) or PlatformIO
- Running the PySide6 UI (`host/app.py`), including the no-hardware **SIMULATOR** port
- Calibration (IMU zero, load-cell tare/scale), recording sessions, stream modes
- Retraining the model and regenerating `model.h`
- Troubleshooting

Quick version:
```powershell
# firmware (PlatformIO alternative to Arduino IDE)
cd firmware; pio run -t upload
# UI
cd ..\host; pip install -r requirements.txt; python app.py
```
