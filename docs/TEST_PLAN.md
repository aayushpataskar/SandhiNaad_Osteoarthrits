# Acceptance Test Plan

This document outlines the systematic tests to verify the functionality of the SandhiNaad system.

### Test 1: Sensor Status
- **Description:** Verify the firmware properly identifies connected and disconnected sensors.
- **Setup:** Connect all sensors according to the wiring diagram.
- **Steps:** Power on the device and view the host UI. Disconnect the AD8232 and BNO055 sensors sequentially.
- **Expected Result:** STATUS packets should reflect the exact state of the hardware.
- **Pass Criteria:** UI shows green "ATTACHED" badges when connected, and grey "NOT_ATTACHED" badges immediately upon disconnection for all six sensors.

### Test 2: Audio Events
- **Description:** Verify acoustic click detection mechanisms.
- **Setup:** System running in a quiet room, INMP441 connected.
- **Steps:** 
  1. Observe the system in silence.
  2. Tap the table near the microphone.
- **Expected Result:** Silence yields no events. Tapping yields events.
- **Pass Criteria:** No phantom events in a quiet room. Taps trigger EVENT packets with a margin ≥18 dB. The UI correctly reports the noise floor band in dBFS.

### Test 3: IMU Tracking
- **Description:** Validate dual BNO055 IMU angle tracking and phase shading.
- **Setup:** Two BNO055 sensors connected (0x28, 0x29).
- **Steps:** 
  1. Lay sensors flat and send `CAL_ZERO`.
  2. Bend one sensor 90 degrees relative to the other.
  3. Move cyclically.
- **Expected Result:** Angle tracking should reflect the relative bend.
- **Pass Criteria:** Both IMUs answer correctly. `CAL_ZERO` resets angle to 0°. A physical 90° bend reads ~90° (±10° error margin). Phase shading in the UI follows the cyclic movement correctly.

### Test 4: EMG Response
- **Description:** Validate the EMG pipeline via the AD8232.
- **Setup:** AD8232 connected to the user's quadriceps.
- **Steps:** Contract the quadriceps muscle. Induce a rail saturation (e.g., by shorting inputs momentarily).
- **Expected Result:** Envelope responds to muscle activity; saturation flag throws when appropriate.
- **Pass Criteria:** The EMG envelope trace rises clearly during contraction. The saturation flag triggers when the raw signal rails.

### Test 5: Protocol Stability
- **Description:** Ensure binary protocol integrity over a long session.
- **Setup:** System running in `MODE_FULL`.
- **Steps:** Stream data to the host app continuously for 10 minutes.
- **Expected Result:** Continuous plotting with no serial exceptions.
- **Pass Criteria:** Zero CRC errors reported in the host app console. The drop count remains at 0 throughout the test.

### Test 6: UI Alignment
- **Description:** Verify synchronization of multiple modalities in the UI.
- **Setup:** Normal operation.
- **Steps:** Induce an acoustic event while moving the IMUs.
- **Expected Result:** Event markers on the UI are accurately placed.
- **Pass Criteria:** Click markers vertically align with the acoustic envelope peaks, and simultaneously sit perfectly on the angle trace at the correct movement phase.

### Test 7: Noise Cancellation
- **Description:** Verify the NLMS adaptive filter works.
- **Setup:** Standard setup with EMG attached.
- **Steps:** Induce mechanical noise that heavily correlates with movement. Toggle NC in the UI. Disconnect the EMG sensor.
- **Expected Result:** Filter reduces correlated noise. Disconnecting EMG bypasses the filter.
- **Pass Criteria:** Visual before/after plots show noticeable dB reduction of artifact noise. The system automatically bypasses the filter when EMG is absent/detached.

### Test 8: Localization Demo
- **Description:** Demonstrate the capability of the spatial localization UI.
- **Setup:** UI running.
- **Steps:** Open the localization simulation panel.
- **Expected Result:** Simulation output is visible.
- **Pass Criteria:** Displays simulated spatial accuracy alongside a confusion matrix. The panel prominently displays a "SIMULATED" badge.

### Test 9: Machine Learning Pipeline
- **Description:** End-to-end test of the ML flow.
- **Setup:** `ml/` folder scripts.
- **Steps:** Run `synth_data.py`, `train.py`, and `export_c_header.py`. Compare firmware outputs to host python outputs.
- **Expected Result:** Pipeline succeeds and embedded predictions match python exactly.
- **Pass Criteria:** A Leave-One-Subject-Out (LOSO) report is successfully generated. Firmware embedded model predictions match the Python host predictions within `1e-4` tolerance. The contribution chart in the UI updates per cycle based on SHAP/feature weights.
