# SandhiNaad DSP Pipeline Documentation

This document describes the Digital Signal Processing (DSP) algorithms implemented in the SandhiNaad ESP32 firmware.

## Audio Acquisition
- **Hardware:** INMP441 I2S MEMS microphone
- **Data Format:** 24-bit audio data, left-aligned in a 32-bit slot.
- **Sample Extraction:** `sample = (raw >> 8)`
- **Normalization:** `x = sample / 8388608.0f` (maps to ±1.0)
- **Initialization:** I2S slot auto-detection runs at boot. The first 100ms of audio is discarded to allow the microphone's DC offset to settle.

## DC Removal
A one-pole high-pass filter is applied to remove residual DC bias.
- **Equation:** `y[n] = x[n] - x[n-1] + α·y[n-1]`
- **Coefficient:** `α = 0.9975` (yielding a ~20 Hz cutoff frequency at 16 kHz sample rate).

## Band-Pass Filter (250 Hz – 4500 Hz)
Filters physiological joint sounds from out-of-band noise. Designed via bilinear transform.
- **High-Pass (250 Hz):** 4th-order Butterworth HPF (2 cascaded biquad sections).
  - Section 1: Q = 0.5412
  - Section 2: Q = 1.3066
- **Low-Pass (4500 Hz):** 2nd-order Butterworth LPF.
  - Q = 0.7071
- **Implementation:** Direct Form II Transposed biquad.
- *Actual coefficient values for 16 kHz are documented in the C++ firmware headers.*

## Envelope Extraction
Extracts the shape of the acoustic signal.
- **Rectification:** Full-wave rectify `|x|`
- **Low-Pass Filter:** One-pole LPF `y[n] = α·|x[n]| + (1-α)·y[n-1]`
- **Coefficient:** `α = 1 - exp(-2π·50/fs)` (50 Hz envelope cutoff).

## Noise Floor Estimation
- Tracks background acoustic noise.
- **Method:** Rolling median of block RMS values over approximately 1 second (30 blocks of 512 samples). Events are not detected until 10 blocks are collected.

## Event (Click) Detection
Detects sharp, sudden acoustic emissions indicating potential joint friction or crepitus.
- **Thresholding:** Detects when block peak > floor × 10^(18/20) (≈ floor × 7.94, representing an 18 dB margin).
- **Refractory Period:** A minimum of 50ms is required between events.
- **Captured Data:** Timestamp, peak dBFS, margin over floor, event duration, current knee angle, gait phase, and a 256-sample audio snippet centered on the event.

## Spectral Analysis
Performed using a 512-point FFT on a Hann-windowed, band-passed block of audio.
- **Spectral Centroid:** Σ(f·\|X(f)\|²) / Σ\|X(f)\|² over 250-4500 Hz.
- **Peak Frequency:** argmax\|X(f)\|² in the 250-4500 Hz range.
- **Sub-band Powers:** Sum of \|X(f)\|² in bins corresponding to [250-500], [500-1k], [1k-2k], and [2k-4.5k] Hz.
- **HF Ratio:** Power above 2kHz / total in-band power.
- **Spectral Entropy:** -Σ(p·log(p)) / log(N) where p = \|X(f)\|²/Σ\|X(f)\|², normalized to 0-1.

## Time-Domain Features
Computed over audio blocks:
- **Kurtosis:** E[(x-μ)⁴] / σ⁴ (Pearson; Gaussian noise = 3 — matches the ML training data)
- **Skewness:** E[(x-μ)³] / σ³
- **Hjorth Activity:** Variance of the signal.
- **Hjorth Mobility:** sqrt(var(dx)/var(x))
- **Hjorth Complexity:** mobility(dx) / mobility(x)
- **Zero-Crossing Rate (ZCR):** Count of sign changes divided by (N-1) — a rate in 0..1.

## EMG Processing
- **Sampling:** 1 kHz via ESP32 ADC.
- **Baseline Removal:** One-pole HPF at 20 Hz, adapted for the 1 kHz rate.
- **Envelope:** Full-wave rectification followed by an LPF at 5 Hz.
- **Saturation Detection:** Flags if >2% of samples in a frame are within 20 counts of the ADC rails (0 or 4095).

## IMU Processing
- **Hardware:** BNO055 operating in NDOF sensor fusion mode at 100 Hz.
- **Kinematics:** Thigh and shank quaternions are combined to compute the relative 1D knee angle.
- **Calibration:** `CAL_ZERO` host command stores the current relative pose as 0°.
- **Derived Metrics:** Angular velocity is derived from smoothed angle derivatives.
- **Gait/Movement Phase:** Phase tagging relies on velocity zero-crossings with applied hysteresis.
- **Cycle Detection:** A cycle runs from one flexion onset to the next (min 0.5 s). ROM = max − min angle in the cycle. Each completed cycle triggers the on-device model with the 17 block features averaged over the cycle + events, ROM, peak velocities, duration.

## Noise Cancellation (NLMS)
- **Where:** Host app (`host/dsp_ref.py`), toggled with "Noise cancel (NLMS)"; the UI shows before (grey) / after (yellow) and the dB reduction.
- **Algorithm:** Normalized Least Mean Squares (NLMS) adaptive filter, 16 taps, μ = 0.05.
- **Purpose:** Subtracts movement/muscle artifact (using EMG or IMU as a reference) from the acoustic signal.
- **Bypass Conditions:** Automatically bypassed if the EMG signal is absent, detached, or saturated.
