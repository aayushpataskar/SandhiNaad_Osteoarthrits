#!/usr/bin/env python3
"""
SandhiNaad — calibrate the acoustic model for screening use, then export model.h.

Why: the L2-regularised logistic model (C=0.01) outputs probabilities squeezed
around 0.5, so everyone lands in the "Early Risk" tier (0.3–0.6). This script
  1. clips standardised features to ±Z_CLIP (robust to out-of-range sensors),
  2. Platt-scales the model logit on the cycle-level data (spreads probabilities),
  3. adds a screening-population prior (default prevalence 15 %):
        logit_final = a·logit + b + ln(prev / (1 - prev))
and bakes (1)-(3) into the saved model + firmware header, so the ESP32 and
the host keep producing IDENTICAL numbers.

Always starts from the original (uncalibrated) models kept in models/uncalibrated/,
so it is safe to re-run with a different prevalence.

Usage:
    python calibrate.py                    # prevalence 0.15
    python calibrate.py --prevalence 0.25
Then re-upload the firmware (UPLOAD_FIRMWARE.bat) and restart the UI.
"""
import argparse
import json
import os
import shutil
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from config import ACOUSTIC_FEATURES  # noqa: E402
from export_c_header import export, Z_CLIP  # noqa: E402

MODELS = os.path.join(HERE, 'models')
ORIG = os.path.join(MODELS, 'uncalibrated')


def tiers(p):
    return {'Healthy': float(np.mean(p < 0.3)), 'Early Risk': float(np.mean((p >= 0.3) & (p < 0.6))),
            'High Risk': float(np.mean((p >= 0.6) & (p < 0.8))), 'Referral': float(np.mean(p >= 0.8))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prevalence', type=float, default=0.15)
    ap.add_argument('--data', default=os.path.join(HERE, 'data', 'synthetic_dataset.csv'))
    args = ap.parse_args()

    os.makedirs(ORIG, exist_ok=True)
    for f in ('acoustic_model.joblib', 'acoustic_scaler.joblib', 'model_info.json'):
        if not os.path.exists(os.path.join(ORIG, f)):
            shutil.copy2(os.path.join(MODELS, f), os.path.join(ORIG, f))
    model = joblib.load(os.path.join(ORIG, 'acoustic_model.joblib'))
    scaler = joblib.load(os.path.join(ORIG, 'acoustic_scaler.joblib'))
    with open(os.path.join(ORIG, 'model_info.json')) as f:
        info = json.load(f)

    df = pd.read_csv(args.data)
    z = np.clip(scaler.transform(df[ACOUSTIC_FEATURES].values), -Z_CLIP, Z_CLIP)
    raw = z @ model.coef_[0] + model.intercept_[0]
    platt = LogisticRegression(C=1e6).fit(raw.reshape(-1, 1), df['label'].values)
    a, b = float(platt.coef_[0, 0]), float(platt.intercept_[0])
    shift = float(np.log(args.prevalence / (1 - args.prevalence)))

    model.coef_ = model.coef_ * a
    model.intercept_ = model.intercept_ * a + b + shift
    joblib.dump(model, os.path.join(MODELS, 'acoustic_model.joblib'))
    joblib.dump(scaler, os.path.join(MODELS, 'acoustic_scaler.joblib'))

    final = 1 / (1 + np.exp(-(z @ model.coef_[0] + model.intercept_[0])))
    ctl, oa = tiers(final[df.label == 0]), tiers(final[df.label == 1])
    info.update({'coefficients': model.coef_[0].tolist(), 'intercept': float(model.intercept_[0]),
                 'threshold': 0.3, 'z_clip': Z_CLIP,
                 'calibration': {'platt_a': a, 'platt_b': b, 'prevalence': args.prevalence,
                                 'prior_logit_shift': shift,
                                 'synthetic_tier_rates_control': ctl, 'synthetic_tier_rates_oa': oa}})
    with open(os.path.join(MODELS, 'model_info.json'), 'w') as f:
        json.dump(info, f, indent=2)

    print(f'Platt a={a:.3f} b={b:.3f}, prevalence={args.prevalence:.2f} (logit shift {shift:+.3f})')
    print('Synthetic CONTROL cycles ->', {k: f'{v:.0%}' for k, v in ctl.items()})
    print('Synthetic OA cycles      ->', {k: f'{v:.0%}' for k, v in oa.items()})
    export(os.path.join(MODELS, 'acoustic_model.joblib'), os.path.join(MODELS, 'acoustic_scaler.joblib'),
           os.path.join(HERE, '..', 'firmware', 'SandhiNaad', 'model.h'),
           os.path.join(MODELS, 'model_info.json'))
    print('\nNext: re-upload the firmware (UPLOAD_FIRMWARE.bat) and restart the UI.')


if __name__ == '__main__':
    main()
