#!/usr/bin/env python3
"""
SandhiNaad — Model training pipeline with Leave-One-Subject-Out validation.

Trains three models:
  1. Acoustic head   — logistic regression on acoustic features
  2. Prior head      — logistic regression on clinical features
  3. Fusion          — late fusion (sum of log-odds) vs stacking, chosen by CV

Validation uses LOSO with nested CV for the regularisation parameter C.
Cycles are aggregated to subject level (median) before the final decision.

Usage:
    python train.py --data ml/data/synthetic_dataset.csv
    python train.py --data ml/data/synthetic_dataset.csv --output-dir ml/models/ --report-dir ml/reports/
"""

import argparse
import json
import os
import sys
import warnings

import joblib
import matplotlib
matplotlib.use('Agg')  # non-interactive backend for server/CI
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.special import expit, logit
from sklearn.calibration import calibration_curve
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, auc, confusion_matrix, roc_auc_score, roc_curve,
)
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(__file__))
from config import ACOUSTIC_FEATURES, CLINICAL_FEATURES

warnings.filterwarnings('ignore', category=UserWarning)

# ── Hyperparameter grid ────────────────────────────────────────────────────
C_VALUES = [0.01, 0.1, 1.0, 10.0, 100.0]


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _aggregate_to_subject(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """Median-aggregate cycle-level features to one row per subject."""
    agg = {f: 'median' for f in feature_cols}
    agg['label'] = 'first'
    return df.groupby('subject_id').agg(agg).reset_index()


def _bootstrap_auc_ci(y_true: np.ndarray, y_score: np.ndarray,
                       n_boot: int = 1000, alpha: float = 0.05,
                       seed: int = 42) -> tuple[float, float, float]:
    """Bootstrap 95 % CI for AUC."""
    rng = np.random.default_rng(seed)
    aucs = []
    for _ in range(n_boot):
        idx = rng.choice(len(y_true), size=len(y_true), replace=True)
        if len(np.unique(y_true[idx])) < 2:
            continue
        aucs.append(roc_auc_score(y_true[idx], y_score[idx]))
    aucs = np.array(aucs)
    lo = np.percentile(aucs, 100 * alpha / 2)
    hi = np.percentile(aucs, 100 * (1 - alpha / 2))
    return float(np.median(aucs)), float(lo), float(hi)


def _pick_threshold_high_sensitivity(y_true: np.ndarray, y_score: np.ndarray,
                                      target_sens: float = 0.90) -> float:
    """Choose the operating threshold for ≥target_sens sensitivity.

    Picks the *highest* threshold (best specificity) where TPR ≥ target.
    sklearn's roc_curve returns thresholds in *decreasing* order, so the
    first valid entry is the most conservative one that still meets the
    sensitivity target.
    """
    fpr, tpr, thresholds = roc_curve(y_true, y_score)
    valid = tpr >= target_sens
    if valid.any():
        # First valid = highest threshold with sufficient sensitivity
        return float(thresholds[valid][0])
    # Fallback: lowest threshold (everything positive)
    return float(thresholds[-1])


# ─────────────────────────────────────────────────────────────────────────────
# LOSO cross-validation
# ─────────────────────────────────────────────────────────────────────────────

def loso_cv(df: pd.DataFrame, feature_cols: list[str],
            model_name: str = 'acoustic') -> dict:
    """Run Leave-One-Subject-Out CV with nested C selection.

    Returns dict with subject-level predictions, best C per fold, etc.
    """
    subjects = df['subject_id'].unique()
    preds = {}       # subject_id → predicted probability
    labels = {}      # subject_id → true label
    best_cs = []

    for test_subj in subjects:
        train_df = df[df['subject_id'] != test_subj]
        test_df = df[df['subject_id'] == test_subj]

        # Aggregate train to subject level
        train_agg = _aggregate_to_subject(train_df, feature_cols)
        X_train = train_agg[feature_cols].values.astype(np.float64)
        y_train = train_agg['label'].values.astype(int)

        # ── Nested CV for C (leave-one-out inside training fold) ───────────
        inner_subjects = train_agg['subject_id'].unique()
        best_c, best_inner_auc = C_VALUES[0], -1.0

        if len(np.unique(y_train)) > 1 and len(inner_subjects) > 4:
            for c_val in C_VALUES:
                inner_aucs = []
                for val_subj in inner_subjects:
                    i_train = train_agg['subject_id'] != val_subj
                    i_val = train_agg['subject_id'] == val_subj

                    Xi_tr = X_train[i_train]
                    yi_tr = y_train[i_train]
                    Xi_val = X_train[i_val]
                    yi_val = y_train[i_val]

                    if len(np.unique(yi_tr)) < 2:
                        continue

                    sc = StandardScaler().fit(Xi_tr)
                    lr = LogisticRegression(
                        C=c_val, l1_ratio=0, class_weight='balanced',
                        solver='lbfgs', max_iter=2000,
                    ).fit(sc.transform(Xi_tr), yi_tr)

                    prob = lr.predict_proba(sc.transform(Xi_val))[:, 1]
                    # Single-sample AUC not meaningful → skip
                    if len(np.unique(yi_val)) < 2:
                        inner_aucs.append(0.5)
                    else:
                        inner_aucs.append(roc_auc_score(yi_val, prob))

                mean_auc = np.mean(inner_aucs) if inner_aucs else 0.5
                if mean_auc > best_inner_auc:
                    best_inner_auc = mean_auc
                    best_c = c_val

        best_cs.append(best_c)

        # ── Fit on full training fold with best C ──────────────────────────
        scaler = StandardScaler().fit(X_train)
        model = LogisticRegression(
            C=best_c, l1_ratio=0, class_weight='balanced',
            solver='lbfgs', max_iter=2000,
        ).fit(scaler.transform(X_train), y_train)

        # ── Predict on test subject (aggregate test cycles to median) ──────
        test_agg = _aggregate_to_subject(test_df, feature_cols)
        X_test = test_agg[feature_cols].values.astype(np.float64)
        prob = model.predict_proba(scaler.transform(X_test))[:, 1]
        subj_prob = float(np.median(prob))

        preds[int(test_subj)] = subj_prob
        labels[int(test_subj)] = int(test_agg['label'].values[0])

    y_true = np.array([labels[s] for s in sorted(labels)])
    y_score = np.array([preds[s] for s in sorted(preds)])

    return {
        'model_name': model_name,
        'y_true': y_true,
        'y_score': y_score,
        'best_cs': best_cs,
        'subjects': sorted(labels.keys()),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fusion
# ─────────────────────────────────────────────────────────────────────────────

def late_fusion(acoustic_scores: np.ndarray, prior_scores: np.ndarray) -> np.ndarray:
    """Late fusion by summing log-odds, then back to probability."""
    eps = 1e-7
    a_logit = logit(np.clip(acoustic_scores, eps, 1 - eps))
    p_logit = logit(np.clip(prior_scores, eps, 1 - eps))
    return expit(a_logit + p_logit)


def stacking_fusion(y_true: np.ndarray,
                    acoustic_scores: np.ndarray,
                    prior_scores: np.ndarray) -> np.ndarray:
    """Stacking fusion: fit LR on [acoustic_prob, prior_prob] via LOO."""
    n = len(y_true)
    fused = np.zeros(n)
    X = np.column_stack([acoustic_scores, prior_scores])
    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        if len(np.unique(y_true[mask])) < 2:
            fused[i] = (acoustic_scores[i] + prior_scores[i]) / 2
            continue
        lr = LogisticRegression(
            C=1.0, l1_ratio=0, solver='lbfgs', max_iter=2000,
        ).fit(X[mask], y_true[mask])
        fused[i] = lr.predict_proba(X[i:i+1])[:, 1][0]
    return fused


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────

def _plot_roc(y_true, y_score, auc_val, ci_lo, ci_hi, title, path):
    fpr, tpr, _ = roc_curve(y_true, y_score)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot(fpr, tpr, lw=2, color='#89b4fa',
            label=f'AUC = {auc_val:.3f} [{ci_lo:.3f}–{ci_hi:.3f}]')
    ax.plot([0, 1], [0, 1], '--', color='grey', lw=1)
    ax.set_xlabel('False Positive Rate')
    ax.set_ylabel('True Positive Rate (Sensitivity)')
    ax.set_title(f'{title}\n[SYNTHETIC DATA]')
    ax.legend(loc='lower right')
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f'  Saved ROC → {path}')


def _plot_calibration(y_true, y_score, title, path):
    fig, ax = plt.subplots(figsize=(6, 6))
    try:
        frac_pos, mean_pred = calibration_curve(y_true, y_score, n_bins=8,
                                                 strategy='uniform')
        ax.plot(mean_pred, frac_pos, 's-', color='#a6e3a1', label='Model')
    except ValueError:
        pass
    ax.plot([0, 1], [0, 1], '--', color='grey')
    ax.set_xlabel('Mean predicted probability')
    ax.set_ylabel('Fraction of positives')
    ax.set_title(f'{title}\n[SYNTHETIC DATA]')
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f'  Saved calibration → {path}')


def _plot_confusion(y_true, y_pred, title, path):
    cm = confusion_matrix(y_true, y_pred)
    fig, ax = plt.subplots(figsize=(5, 5))
    im = ax.imshow(cm, cmap='Blues')
    for i in range(2):
        for j in range(2):
            ax.text(j, i, str(cm[i, j]), ha='center', va='center',
                    fontsize=20, color='white' if cm[i, j] > cm.max() / 2 else 'black')
    ax.set_xticks([0, 1])
    ax.set_yticks([0, 1])
    ax.set_xticklabels(['Control', 'OA'])
    ax.set_yticklabels(['Control', 'OA'])
    ax.set_xlabel('Predicted')
    ax.set_ylabel('True')
    ax.set_title(f'{title}\n[SYNTHETIC DATA]')
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f'  Saved confusion → {path}')


def generate_report(result: dict, threshold: float,
                    report_dir: str, prefix: str = '') -> dict:
    """Generate plots and metrics JSON for a LOSO result."""
    y_true = result['y_true']
    y_score = result['y_score']
    name = result['model_name']
    tag = f'{prefix}{name}' if prefix else name

    os.makedirs(report_dir, exist_ok=True)

    # AUC with bootstrap CI
    auc_med, ci_lo, ci_hi = _bootstrap_auc_ci(y_true, y_score)
    _plot_roc(y_true, y_score, auc_med, ci_lo, ci_hi,
              f'{name.title()} Head — LOSO ROC',
              os.path.join(report_dir, f'{tag}_roc.png'))

    _plot_calibration(y_true, y_score,
                      f'{name.title()} Head — Calibration',
                      os.path.join(report_dir, f'{tag}_calibration.png'))

    y_pred = (y_score >= threshold).astype(int)
    _plot_confusion(y_true, y_pred,
                    f'{name.title()} Head — Confusion (thresh={threshold:.2f})',
                    os.path.join(report_dir, f'{tag}_confusion.png'))

    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
    sens = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    spec = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    acc = accuracy_score(y_true, y_pred)

    metrics = {
        'model': name,
        'synthetic': True,
        'auc': round(auc_med, 4),
        'auc_ci_low': round(ci_lo, 4),
        'auc_ci_high': round(ci_hi, 4),
        'sensitivity': round(sens, 4),
        'specificity': round(spec, 4),
        'accuracy': round(acc, 4),
        'threshold': round(threshold, 4),
        'n_subjects': len(y_true),
        'n_positive': int(y_true.sum()),
        'n_negative': int((1 - y_true).sum()),
        'confusion_matrix': {'tn': int(tn), 'fp': int(fp),
                             'fn': int(fn), 'tp': int(tp)},
    }

    json_path = os.path.join(report_dir, f'{tag}_metrics.json')
    with open(json_path, 'w') as f:
        json.dump(metrics, f, indent=2)
    print(f'  Saved metrics → {json_path}')

    return metrics


# ─────────────────────────────────────────────────────────────────────────────
# Final model training (on ALL data)
# ─────────────────────────────────────────────────────────────────────────────

def train_final_model(df: pd.DataFrame, feature_cols: list[str],
                      best_c: float, output_dir: str,
                      name: str = 'acoustic') -> tuple:
    """Retrain on all data with the given C.  Save scaler + model."""
    agg = _aggregate_to_subject(df, feature_cols)
    X = agg[feature_cols].values.astype(np.float64)
    y = agg['label'].values.astype(int)

    scaler = StandardScaler().fit(X)
    model = LogisticRegression(
        C=best_c, l1_ratio=0, class_weight='balanced',
        solver='lbfgs', max_iter=2000,
    ).fit(scaler.transform(X), y)

    os.makedirs(output_dir, exist_ok=True)
    scaler_path = os.path.join(output_dir, f'{name}_scaler.joblib')
    model_path = os.path.join(output_dir, f'{name}_model.joblib')
    joblib.dump(scaler, scaler_path)
    joblib.dump(model, model_path)
    print(f'  Saved scaler → {scaler_path}')
    print(f'  Saved model  → {model_path}')

    return scaler, model


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description='Train knee-OA screening models (LOSO).')
    parser.add_argument('--data', type=str, required=True,
                        help='Path to synthetic CSV dataset')
    parser.add_argument('--output-dir', type=str,
                        default=os.path.join(os.path.dirname(__file__), 'models'),
                        help='Directory for saved models')
    parser.add_argument('--report-dir', type=str,
                        default=os.path.join(os.path.dirname(__file__), 'reports'),
                        help='Directory for report PNGs and JSON')
    args = parser.parse_args()

    df = pd.read_csv(args.data)
    print(f'Loaded {len(df)} cycles from {df["subject_id"].nunique()} subjects.')
    print(f'Label distribution: {dict(df.groupby("subject_id")["label"].first().value_counts())}')

    # ── 1. Acoustic head LOSO ──────────────────────────────────────────────
    print('\n═══ Acoustic Head (LOSO) ═══')
    acoustic_result = loso_cv(df, ACOUSTIC_FEATURES, 'acoustic')
    acoustic_thresh = _pick_threshold_high_sensitivity(
        acoustic_result['y_true'], acoustic_result['y_score'], target_sens=0.90)
    acoustic_metrics = generate_report(acoustic_result, acoustic_thresh,
                                        args.report_dir, prefix='')
    print(f'  AUC = {acoustic_metrics["auc"]:.3f} '
          f'[{acoustic_metrics["auc_ci_low"]:.3f}–{acoustic_metrics["auc_ci_high"]:.3f}]')
    print(f'  Sensitivity = {acoustic_metrics["sensitivity"]:.3f}  '
          f'Specificity = {acoustic_metrics["specificity"]:.3f}  '
          f'(threshold = {acoustic_thresh:.3f})')

    # ── 2. Prior (clinical) head LOSO ──────────────────────────────────────
    print('\n═══ Prior (Clinical) Head (LOSO) ═══')
    prior_result = loso_cv(df, CLINICAL_FEATURES, 'prior')
    prior_thresh = _pick_threshold_high_sensitivity(
        prior_result['y_true'], prior_result['y_score'], target_sens=0.90)
    prior_metrics = generate_report(prior_result, prior_thresh,
                                     args.report_dir, prefix='')
    print(f'  AUC = {prior_metrics["auc"]:.3f} '
          f'[{prior_metrics["auc_ci_low"]:.3f}–{prior_metrics["auc_ci_high"]:.3f}]')
    print(f'  Sensitivity = {prior_metrics["sensitivity"]:.3f}  '
          f'Specificity = {prior_metrics["specificity"]:.3f}')

    # ── 3. Fusion ──────────────────────────────────────────────────────────
    print('\n═══ Fusion ═══')
    a_scores = acoustic_result['y_score']
    p_scores = prior_result['y_score']
    y_true = acoustic_result['y_true']

    late_scores = late_fusion(a_scores, p_scores)
    stack_scores = stacking_fusion(y_true, a_scores, p_scores)

    late_auc = roc_auc_score(y_true, late_scores) if len(np.unique(y_true)) > 1 else 0.5
    stack_auc = roc_auc_score(y_true, stack_scores) if len(np.unique(y_true)) > 1 else 0.5
    print(f'  Late fusion  AUC = {late_auc:.3f}')
    print(f'  Stacking     AUC = {stack_auc:.3f}')

    if late_auc >= stack_auc:
        fusion_name, fusion_scores = 'late_fusion', late_scores
        print('  → Using late fusion.')
    else:
        fusion_name, fusion_scores = 'stacking_fusion', stack_scores
        print('  → Using stacking fusion.')

    fusion_result = {
        'model_name': fusion_name,
        'y_true': y_true,
        'y_score': fusion_scores,
        'best_cs': [],
        'subjects': acoustic_result['subjects'],
    }
    fusion_thresh = _pick_threshold_high_sensitivity(y_true, fusion_scores, 0.90)
    fusion_metrics = generate_report(fusion_result, fusion_thresh,
                                      args.report_dir, prefix='')
    print(f'  AUC = {fusion_metrics["auc"]:.3f}  '
          f'Sens = {fusion_metrics["sensitivity"]:.3f}  '
          f'Spec = {fusion_metrics["specificity"]:.3f}')

    # ── 4. Train final models on ALL data ──────────────────────────────────
    print('\n═══ Final Model Training (all data) ═══')

    # Pick the most common best-C from LOSO folds
    from collections import Counter
    best_c_acoustic = Counter(acoustic_result['best_cs']).most_common(1)[0][0]
    best_c_prior = Counter(prior_result['best_cs']).most_common(1)[0][0]
    print(f'  Best C (acoustic): {best_c_acoustic}')
    print(f'  Best C (prior):    {best_c_prior}')

    acoustic_scaler, acoustic_model = train_final_model(
        df, ACOUSTIC_FEATURES, best_c_acoustic, args.output_dir, 'acoustic')
    prior_scaler, prior_model = train_final_model(
        df, CLINICAL_FEATURES, best_c_prior, args.output_dir, 'prior')

    # ── 5. Save model info ─────────────────────────────────────────────────
    info = {
        'feature_names': ACOUSTIC_FEATURES,
        'clinical_feature_names': CLINICAL_FEATURES,
        'means': acoustic_scaler.mean_.tolist(),
        'stds': acoustic_scaler.scale_.tolist(),
        'coefficients': acoustic_model.coef_[0].tolist(),
        'intercept': float(acoustic_model.intercept_[0]),
        'threshold': round(acoustic_thresh, 6),
        'best_c': best_c_acoustic,
        'training_auc': acoustic_metrics['auc'],
        'training_sensitivity': acoustic_metrics['sensitivity'],
        'training_specificity': acoustic_metrics['specificity'],
        'fusion_method': fusion_name,
        'fusion_auc': fusion_metrics['auc'],
        'synthetic': True,
    }
    info_path = os.path.join(args.output_dir, 'model_info.json')
    with open(info_path, 'w') as f:
        json.dump(info, f, indent=2)
    print(f'  Saved model info → {info_path}')

    # ── 6. Questionnaire-only baseline ─────────────────────────────────────
    print('\n═══ Questionnaire-only baseline ═══')
    print(f'  AUC = {prior_metrics["auc"]:.3f}  '
          f'(vs acoustic {acoustic_metrics["auc"]:.3f}, '
          f'fusion {fusion_metrics["auc"]:.3f})')

    print('\n✓ Training complete.  All reports saved to', args.report_dir)
    print('  Run export_c_header.py to generate firmware model.h')


if __name__ == '__main__':
    main()
