# SandhiNaad Demonstration Script

This document provides a step-by-step script for conducting a live or recorded demonstration of the SandhiNaad system. It is designed to be easily followed by anyone unfamiliar with the setup.

### Preparation
- Ensure all hardware (ESP32, INMP441, BNO055s, AD8232) is properly wired on a breadboard or custom PCB.
- Ensure the ESP32 is plugged into the host computer via USB.

### Demo Steps

1. **Hardware Introduction:**
   - On camera, point out the ESP32 microcontroller, the I2S microphone (INMP441), the two IMUs (BNO055), and the EMG front-end (AD8232). Briefly explain the role of each.

2. **Booting Up:**
   - In your terminal, flash the firmware (or show that it's already flashed): `cd firmware && pio run -t upload`.
   - Open the host app: `cd host && python app.py`.

3. **Connecting:**
   - In the Python UI, select the correct COM port (baud 921600) and click **Connect**.
   - Show the stream starting up.

4. **Sensor Status Inspection:**
   - Direct attention to the status bar/panel.
   - Point out the green "ATTACHED" badges for all connected sensors. (Optionally unplug one sensor momentarily to show it dynamically turn grey).

5. **Acoustic Events:**
   - Direct attention to the Acoustic panel.
   - Tap the table near the microphone.
   - Show the detected clicks appearing as markers on the waveform/envelope graph. Explain that the system thresholds these automatically.

6. **Kinematic Tracking:**
   - Pick up the two IMUs (thigh and shank). Send a `CAL_ZERO` command via the UI.
   - Flex and extend the "knee" (bend one IMU relative to the other).
   - Show the real-time angle tracking in the Kinematics panel. Point out the phase shading (e.g., flexion vs. extension) and cycle detection boundaries.

7. **Muscle Activity (EMG):**
   - Direct attention to the EMG panel.
   - Simulate or perform a quadriceps contraction (if electrodes are worn).
   - Show the signal amplitude/envelope rising in real-time.

8. **Noise Cancellation:**
   - Enable Noise Cancellation (NLMS) in the UI.
   - Induce some artifact noise. Show the before/after traces if available in the UI to highlight the dB reduction.

9. **Feature Extraction:**
   - Direct attention to the DSP/Feature panel.
   - Show the real-time calculated features (Spectral Centroid, Entropy, Hjorth parameters, etc.) updating continuously or per-cycle.

10. **Machine Learning & Risk Gauge:**
    - Show the ML panel.
    - Point out the Risk Gauge (Osteoarthritis likelihood) and the feature contribution chart (which features drove the prediction).
    - **Crucial:** Explicitly point out the "SYNTHETIC" badge, explaining that the current models are trained on simulated data for prototyping purposes.

11. **Localization Simulation:**
    - Open the Localization Demo tab.
    - Explain the concept of spatial source localization. Show the confusion matrix and simulated accuracy metric. Reiterate that this module is heavily SIMULATED.

12. **Clinical Data Entry:**
    - Navigate to the Session/Patient tab.
    - Enter mock clinical data (e.g., Age, BMI, WOMAC score).
    - Explain how this data acts as a prior for the ML model (prior head effect).

13. **Data Export:**
    - Click **Save Session**.
    - Open the output directory to show the exported `.csv` file containing the synchronized time-series and event data, ready for offline analysis.

14. **Streaming Modes:**
    - In the UI (or via command interface), switch the stream from `MODE_FULL` to `MODE_DEFAULT`, and then to `MODE_FEATURES`.
    - Note how the bandwidth usage drops (explain the bandwidth limits of serial vs. the data density of raw audio).
