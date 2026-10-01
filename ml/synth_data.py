#!/usr/bin/env python3
"""
SandhiNaad — Synthetic dataset generator for knee-OA screening.

Generates feature-level synthetic data for N subjects (half OA, half control),
each with multiple flexion–extension cycles.  Distributions are tuned for
substantial class overlap so the downstream model achieves a realistic AUC
(~0.78–0.85), NOT a trivially separable task.

Usage:
    python synth_data.py --output ml/data/synthetic_dataset.csv
    python synth_data.py --n_subjects 100 --seed 123 --output ml/data/custom.csv
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

# Allow running from repo root or from ml/
sys.path.insert(0, os.path.dirname(__file__))
from config import ACOUSTIC_FEATURES, CLINICAL_FEATURES, SYNTH_CONFIG


def _draw_clinical(rng: np.random.Generator, cfg: dict, n: int) -> dict:
    """Draw clinical features for *n* subjects from one group config."""
    out = {}
    for feat in CLINICAL_FEATURES:
        spec = cfg[feat]
        if isinstance(spec, (int, float)):
            # Binary feature — spec is P(1)
            out[feat] = rng.binomial(1, spec, size=n).astype(float)
        else:
            mean, std = spec
            vals = rng.normal(mean, std, size=n)
            # Clamp to sensible ranges
            if feat == 'age':
                vals = np.clip(vals, 18, 95)
            elif feat == 'bmi':
                vals = np.clip(vals, 15, 50)
            elif feat in ('koos_pain', 'koos_function'):
                vals = np.clip(vals, 0, 100)
            out[feat] = vals
    return out


def generate_dataset(
    n_subjects: int | None = None,
    cycles_per_subject: int | None = None,
    seed: int | None = None,
    config: dict | None = None,
) -> pd.DataFrame:
    """Return a DataFrame of synthetic cycle-level features.

    Parameters
    ----------
    n_subjects : int, optional
        Total subjects (split 50/50 OA vs control).  Default from config.
    cycles_per_subject : int, optional
        Cycles per subject.  Default from config.
    seed : int, optional
        RNG seed for reproducibility.  Default from config.
    config : dict, optional
        Override SYNTH_CONFIG.

    Returns
    -------
    pd.DataFrame
        One row per cycle, with columns:
        subject_id, cycle_num, label (0=control, 1=OA), synthetic, seed,
        + all acoustic features + all clinical features.
    """
    cfg = config or SYNTH_CONFIG
    n_subjects = n_subjects or cfg['n_subjects']
    cycles = cycles_per_subject or cfg['cycles_per_subject']
    seed = seed if seed is not None else cfg['seed']
    rng = np.random.default_rng(seed)

    n_oa = n_subjects // 2
    n_ctrl = n_subjects - n_oa

    # ── Subject-level clinical features ────────────────────────────────────
    ctrl_clin = _draw_clinical(rng, cfg['control_clinical'], n_ctrl)
    oa_clin = _draw_clinical(rng, cfg['oa_clinical'], n_oa)

    rows: list[dict] = []
    subject_id = 0

    for label, n_grp, grp_cfg, clin in [
        (0, n_ctrl, cfg['control'], ctrl_clin),
        (1, n_oa, cfg['oa'], oa_clin),
    ]:
        for s in range(n_grp):
            subject_id += 1

            # Subject-level random effect (shifts all acoustic features)
            subj_effect = rng.normal(0, cfg['subject_random_effect_std'],
                                     size=len(ACOUSTIC_FEATURES))

            # Clinical features are constant per subject
            subj_clinical = {f: clin[f][s] for f in CLINICAL_FEATURES}
            bmi = subj_clinical['bmi']

            for c in range(cycles):
                row: dict = {
                    'subject_id': subject_id,
                    'cycle_num': c + 1,
                    'label': label,
                    'synthetic': True,
                    'seed': seed,
                }

                # ── Acoustic features ──────────────────────────────────────
                for i, feat in enumerate(ACOUSTIC_FEATURES):
                    mean, std = grp_cfg[feat]
                    # Base sample + subject effect (scaled by std)
                    val = rng.normal(mean, std) + subj_effect[i] * std

                    # ── BMI confound ───────────────────────────────────────
                    bmi_excess = max(0.0, bmi - 25.0)
                    if feat in ('rms', 'hjorth_activity'):
                        val += bmi_excess * cfg['bmi_amplitude_effect'] * std
                    elif feat == 'rom':
                        val -= bmi_excess * 0.5  # higher BMI → slightly less ROM

                    # ── Noise-floor outlier ────────────────────────────────
                    if feat == 'floor_dbfs' and rng.random() < cfg['noise_floor_outlier_prob']:
                        val += rng.uniform(5, 15)  # elevated floor

                    # ── Clamp to physically plausible ranges ───────────────
                    if feat == 'rms':
                        val = max(val, 1e-5)
                    elif feat in ('subband_250_500', 'subband_500_1k',
                                  'subband_1k_2k', 'subband_2k_4k5',
                                  'hf_ratio'):
                        val = np.clip(val, 0.0, 1.0)
                    elif feat == 'spectral_entropy':
                        val = np.clip(val, 0.0, 1.0)
                    elif feat == 'events_per_cycle':
                        val = max(0.0, round(val))
                    elif feat == 'rom':
                        val = np.clip(val, 5.0, 160.0)
                    elif feat in ('peak_flex_vel', 'peak_ext_vel'):
                        val = max(val, 5.0)
                    elif feat == 'cycle_duration':
                        val = max(val, 0.5)
                    elif feat == 'zcr':
                        val = np.clip(val, 0.0, 0.5)
                    elif feat == 'spectral_centroid':
                        val = np.clip(val, 250.0, 4500.0)
                    elif feat == 'peak_freq':
                        val = np.clip(val, 250.0, 4500.0)
                    elif feat == 'kurtosis':
                        val = max(val, 1.5)  # excess kurtosis can be negative, but not for joint sounds
                    elif feat == 'hjorth_activity':
                        val = max(val, 1e-7)
                    elif feat == 'hjorth_mobility':
                        val = max(val, 0.01)
                    elif feat == 'hjorth_complexity':
                        val = max(val, 1.0)

                    row[feat] = float(val)

                # ── Clinical features (constant per subject) ───────────────
                row.update(subj_clinical)
                rows.append(row)

    df = pd.DataFrame(rows)

    # Shuffle by subject to avoid ordering bias
    subj_order = rng.permutation(df['subject_id'].unique())
    df['_sort'] = df['subject_id'].map({s: i for i, s in enumerate(subj_order)})
    df = df.sort_values(['_sort', 'cycle_num']).drop(columns='_sort').reset_index(drop=True)

    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Generate synthetic knee-OA screening dataset (feature-level).')
    parser.add_argument('--n_subjects', type=int, default=None,
                        help='Total subjects (default: from config)')
    parser.add_argument('--cycles', type=int, default=None,
                        help='Cycles per subject (default: from config)')
    parser.add_argument('--seed', type=int, default=None,
                        help='Random seed (default: from config)')
    parser.add_argument('--output', type=str,
                        default=os.path.join(os.path.dirname(__file__),
                                             'data', 'synthetic_dataset.csv'),
                        help='Output CSV path')
    args = parser.parse_args()

    print(f'Generating synthetic dataset (seed={args.seed or SYNTH_CONFIG["seed"]})…')
    df = generate_dataset(
        n_subjects=args.n_subjects,
        cycles_per_subject=args.cycles,
        seed=args.seed,
    )

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    df.to_csv(args.output, index=False)

    n_oa = (df.groupby('subject_id')['label'].first() == 1).sum()
    n_ctrl = (df.groupby('subject_id')['label'].first() == 0).sum()
    print(f'Saved {len(df)} cycles from {df["subject_id"].nunique()} subjects '
          f'({n_ctrl} control, {n_oa} OA) to {args.output}')

    # Quick sanity — per-class feature means
    print('\nPer-class means for key features:')
    key_feats = ['rms', 'spectral_centroid', 'kurtosis', 'events_per_cycle', 'rom']
    for feat in key_feats:
        ctrl_m = df.loc[df['label'] == 0, feat].mean()
        oa_m = df.loc[df['label'] == 1, feat].mean()
        print(f'  {feat:>22s}:  control={ctrl_m:.4f}  OA={oa_m:.4f}')


if __name__ == '__main__':
    main()
