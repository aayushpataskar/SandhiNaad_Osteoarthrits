"""
SandhiNaad ML Pipeline — Shared configuration.

All tunable parameters for synthetic data generation, feature names,
and model training are defined here in one place.

DESIGN NOTE on overlap:
  With 22 features, even small per-feature effect sizes compound into
  trivial multivariate separation.  To achieve a realistic AUC of ~0.78–0.85:
  - Only 4–5 features carry a meaningful signal (Cohen's d ≈ 0.4–0.5)
  - ~5 features carry weak signal (d ≈ 0.15–0.2)
  - The remaining ~12 features are noise (d ≈ 0)
  - Subject-level random effects are large (std = 0.7)
"""

# ── Feature name lists (must match firmware and host exactly) ──────────────
ACOUSTIC_FEATURES = [
    'rms', 'peak_dbfs', 'floor_dbfs', 'spectral_centroid', 'peak_freq',
    'subband_250_500', 'subband_500_1k', 'subband_1k_2k', 'subband_2k_4k5',
    'hf_ratio', 'spectral_entropy', 'kurtosis', 'skewness',
    'hjorth_activity', 'hjorth_mobility', 'hjorth_complexity', 'zcr',
    'events_per_cycle', 'rom', 'peak_flex_vel', 'peak_ext_vel', 'cycle_duration',
]

CLINICAL_FEATURES = [
    'age', 'sex', 'bmi', 'occupation_squat', 'koos_pain', 'koos_function',
]

ALL_FEATURES = ACOUSTIC_FEATURES + CLINICAL_FEATURES

# ── Synthetic data generation parameters ───────────────────────────────────
# Each tuple is (mean, std).  Binary features use a single probability.
#
# Effect sizes (Cohen's d) per feature — designed for AUC ~0.78–0.85:
#   STRONG  (d~0.45):  events_per_cycle, rom, kurtosis, spectral_centroid
#   WEAK    (d~0.20):  rms, hf_ratio, peak_dbfs, hjorth_activity, cycle_duration
#   NOISE   (d~0.00):  everything else

SYNTH_CONFIG = {
    'n_subjects': 60,            # 30 OA, 30 control
    'cycles_per_subject': 5,
    'seed': 42,

    # ── Control group ──────────────────────────────────────────────────────
    'control': {
        # --- WEAK signal features (d ≈ 0.20) ---
        'rms':               (0.015, 0.008),
        'peak_dbfs':         (-35.0, 8.0),
        'floor_dbfs':        (-75.0, 6.0),      # noise (d≈0)
        # --- STRONG signal features (d ≈ 0.45) ---
        'spectral_centroid': (1700.0, 400.0),
        'peak_freq':         (1400.0, 500.0),    # noise (d≈0)
        # --- NOISE features (d ≈ 0) ---
        'subband_250_500':   (0.18, 0.07),
        'subband_500_1k':    (0.27, 0.07),
        'subband_1k_2k':     (0.30, 0.08),
        'subband_2k_4k5':    (0.25, 0.07),
        # --- WEAK signal (d ≈ 0.20) ---
        'hf_ratio':          (0.25, 0.09),
        # --- NOISE ---
        'spectral_entropy':  (0.72, 0.10),
        # --- STRONG signal (d ≈ 0.45) ---
        'kurtosis':          (3.5, 1.8),
        # --- NOISE ---
        'skewness':          (0.3, 0.6),
        # --- WEAK (d ≈ 0.20) ---
        'hjorth_activity':   (0.0003, 0.00018),
        # --- NOISE ---
        'hjorth_mobility':   (0.16, 0.06),
        'hjorth_complexity': (1.5, 0.35),
        'zcr':               (0.11, 0.05),
        # --- STRONG signal (d ≈ 0.45) ---
        'events_per_cycle':  (2.5, 2.0),
        'rom':               (105.0, 20.0),
        # --- NOISE ---
        'peak_flex_vel':     (115.0, 35.0),
        'peak_ext_vel':      (95.0, 30.0),
        # --- WEAK (d ≈ 0.20) ---
        'cycle_duration':    (3.2, 1.0),
    },

    # ── OA group (small shifts on select features, big overlap) ────────────
    'oa': {
        # --- WEAK (d ≈ 0.20): Δ = 0.20 × pooled_std ---
        'rms':               (0.0175, 0.009),       # +0.0025 on mean
        'peak_dbfs':         (-33.0, 8.5),           # +2 dB
        'floor_dbfs':        (-74.0, 6.5),           # almost same (d≈0.15)
        # --- STRONG (d ≈ 0.45): Δ ≈ 0.45 × pooled_std ---
        'spectral_centroid': (1510.0, 420.0),        # -190 Hz
        'peak_freq':         (1380.0, 500.0),        # almost same (d≈0.04)
        # --- NOISE (d ≈ 0) ---
        'subband_250_500':   (0.19, 0.07),           # +0.01
        'subband_500_1k':    (0.28, 0.07),           # +0.01
        'subband_1k_2k':     (0.29, 0.08),           # -0.01
        'subband_2k_4k5':    (0.24, 0.07),           # -0.01
        # --- WEAK (d ≈ 0.20) ---
        'hf_ratio':          (0.23, 0.09),           # -0.02
        # --- NOISE ---
        'spectral_entropy':  (0.70, 0.11),           # -0.02 (d≈0.19)
        # --- STRONG (d ≈ 0.45) ---
        'kurtosis':          (4.3, 1.9),             # +0.8
        # --- NOISE ---
        'skewness':          (0.35, 0.65),           # +0.05 (d≈0.08)
        # --- WEAK (d ≈ 0.20) ---
        'hjorth_activity':   (0.00034, 0.00019),     # small shift
        # --- NOISE ---
        'hjorth_mobility':   (0.165, 0.065),         # +0.005 (d≈0.08)
        'hjorth_complexity': (1.52, 0.36),           # +0.02 (d≈0.06)
        'zcr':               (0.108, 0.05),          # -0.002 (d≈0.04)
        # --- STRONG (d ≈ 0.45) ---
        'events_per_cycle':  (3.5, 2.2),             # +1.0
        'rom':               (96.0, 22.0),           # -9.0 deg
        # --- NOISE ---
        'peak_flex_vel':     (110.0, 36.0),          # -5 (d≈0.14)
        'peak_ext_vel':      (92.0, 31.0),           # -3 (d≈0.10)
        # --- WEAK (d ≈ 0.20) ---
        'cycle_duration':    (3.4, 1.1),             # +0.2s
    },

    # ── Clinical feature distributions ─────────────────────────────────────
    # These also have moderate overlap for realism
    'control_clinical': {
        'age':              (40.0, 14.0),
        'sex':              0.5,
        'bmi':              (25.0, 4.0),
        'occupation_squat': 0.25,
        'koos_pain':        (85.0, 12.0),
        'koos_function':    (88.0, 10.0),
    },
    'oa_clinical': {
        'age':              (52.0, 14.0),
        'sex':              0.48,
        'bmi':              (27.5, 4.5),
        'occupation_squat': 0.35,
        'koos_pain':        (62.0, 20.0),
        'koos_function':    (65.0, 18.0),
    },

    # ── Subject-level random effects (LARGE to add correlation + noise) ────
    'subject_random_effect_std': 0.7,

    # ── Confounds ──────────────────────────────────────────────────────────
    'bmi_amplitude_effect': 0.01,
    'noise_floor_outlier_prob': 0.08,
}
