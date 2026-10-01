"""
SandhiNaad — ML model loader and interpreter for the host app.

Loads the trained acoustic + prior models and provides:
  - predict(features_dict) → (probability, risk_tier, contributions)
  - Risk tiers: Healthy / Early Risk / High Risk / Referral
  - Per-feature contribution bar chart data

Feature order MUST match ACOUSTIC_FEATURES in ml/config.py and firmware model.h.
"""
import os
import json
import numpy as np

try:
    import joblib
except ImportError:
    joblib = None

# Canonical feature order — MUST match firmware/ML exactly
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

# Risk tiers
def _risk_tier(prob):
    if prob >= 0.8:
        return 'Referral'
    elif prob >= 0.6:
        return 'High Risk'
    elif prob >= 0.3:
        return 'Early Risk'
    return 'Healthy'

TIER_COLORS = {
    'Healthy': '#a6e3a1',
    'Early Risk': '#f9e2af',
    'High Risk': '#fab387',
    'Referral': '#f38ba8',
}


class OAScreeningModel:
    """Loads trained acoustic + prior models for OA risk prediction."""

    def __init__(self, models_dir=None):
        self.acoustic_model = None
        self.acoustic_scaler = None
        self.prior_model = None
        self.prior_scaler = None
        self.threshold = 0.5
        self.is_synthetic = True
        self.z_clip = 3.0

        if models_dir is None:
            # Try standard locations relative to host/
            candidates = [
                os.path.join(os.path.dirname(__file__), '..', 'ml', 'models'),
                os.path.join(os.path.dirname(__file__), 'ml', 'models'),
            ]
            for c in candidates:
                if os.path.isdir(c):
                    models_dir = c
                    break

        if models_dir and joblib:
            self._load(models_dir)

    def _load(self, d):
        try:
            model_path = os.path.join(d, 'acoustic_model.joblib')
            scaler_path = os.path.join(d, 'acoustic_scaler.joblib')
            if os.path.exists(model_path) and os.path.exists(scaler_path):
                self.acoustic_model = joblib.load(model_path)
                self.acoustic_scaler = joblib.load(scaler_path)

            prior_model_path = os.path.join(d, 'prior_model.joblib')
            prior_scaler_path = os.path.join(d, 'prior_scaler.joblib')
            if os.path.exists(prior_model_path) and os.path.exists(prior_scaler_path):
                self.prior_model = joblib.load(prior_model_path)
                self.prior_scaler = joblib.load(prior_scaler_path)

            info_path = os.path.join(d, 'model_info.json')
            if os.path.exists(info_path):
                with open(info_path) as f:
                    info = json.load(f)
                self.threshold = info.get('threshold', 0.5)
                self.is_synthetic = info.get('synthetic', True)
                self.z_clip = float(info.get('z_clip', 3.0))
        except Exception as e:
            print(f'[model] Warning: failed to load models: {e}')

    @property
    def loaded(self):
        return self.acoustic_model is not None

    def predict_acoustic(self, features_dict):
        """Predict OA probability from acoustic features.

        Parameters
        ----------
        features_dict : dict
            Must contain keys matching ACOUSTIC_FEATURES.

        Returns
        -------
        prob : float
        tier : str
        contributions : list of (name, value) sorted by |value| descending
        """
        if not self.loaded or not features_dict:
            return None, 'Unknown', []

        # Build feature vector in canonical order
        x = np.array([features_dict.get(f, 0.0) for f in ACOUSTIC_FEATURES],
                      dtype=np.float64).reshape(1, -1)

        # clip to +-3 SD exactly like firmware model_predict() (MODEL_Z_CLIP)
        x_scaled = np.clip(self.acoustic_scaler.transform(x), -self.z_clip, self.z_clip)
        self.last_z = dict(zip(ACOUSTIC_FEATURES, x_scaled[0].tolist()))   # used for report explanations
        prob = float(self.acoustic_model.predict_proba(x_scaled)[0, 1])
        # (identical to firmware model_predict(): sigmoid(b + w . (x-mean)/std))
        tier = _risk_tier(prob)

        # Per-feature contributions: coefficient × standardised value
        contributions = []
        if hasattr(self.acoustic_model, 'coef_'):
            coefs = self.acoustic_model.coef_[0]
            for i, fname in enumerate(ACOUSTIC_FEATURES):
                contrib = float(coefs[i] * x_scaled[0, i])
                contributions.append((fname, contrib))
            contributions.sort(key=lambda t: abs(t[1]), reverse=True)

        return prob, tier, contributions

    def predict_prior(self, clinical_dict):
        """Predict OA probability from clinical features only."""
        if self.prior_model is None or not clinical_dict:
            return None

        x = np.array([clinical_dict.get(f, 0.0) for f in CLINICAL_FEATURES],
                      dtype=np.float64).reshape(1, -1)
        x_scaled = self.prior_scaler.transform(x)
        return float(self.prior_model.predict_proba(x_scaled)[0, 1])

    def predict_fused(self, features_dict, clinical_dict=None):
        """Late fusion of acoustic + prior heads.

        Returns (prob, tier, contributions) where prob is the fused probability.
        """
        acoustic_prob, tier, contribs = self.predict_acoustic(features_dict)
        if acoustic_prob is None:
            return None, tier, contribs

        if clinical_dict and self.prior_model is not None and clinical_dict.get('age', 0) > 0:
            prior_prob = self.predict_prior(clinical_dict)
            if prior_prob is not None:
                eps = 1e-7
                a_logit = np.log(np.clip(acoustic_prob, eps, 1-eps) /
                                 (1 - np.clip(acoustic_prob, eps, 1-eps)))
                p_logit = np.log(np.clip(prior_prob, eps, 1-eps) /
                                 (1 - np.clip(prior_prob, eps, 1-eps)))
                fused = 1.0 / (1.0 + np.exp(-(a_logit + p_logit)))
                acoustic_prob = float(fused)
                tier = _risk_tier(acoustic_prob)

        return acoustic_prob, tier, contribs
