"""Python reference of the firmware block features (acoustic_features.cpp).

Used by the simulator and for offline analysis of recorded WAVs. Definitions
match firmware and ml/config.py: Pearson kurtosis, ZCR as a rate.
"""
import numpy as np
from protocol import ACOUSTIC_FEATURE_NAMES

_N = 512
_HANN = 0.5 * (1 - np.cos(2 * np.pi * np.arange(_N) / (_N - 1)))


def block_features(x: np.ndarray, fs: int = 16000, floor_dbfs: float = -90.0) -> dict:
    x = np.asarray(x, dtype=np.float64)[:_N]
    n = len(x)
    f = {}
    f['rms'] = float(np.sqrt(np.mean(x ** 2)))
    f['peak_dbfs'] = float(20 * np.log10(np.max(np.abs(x)) + 1e-9))
    f['floor_dbfs'] = floor_dbfs
    d = x - x.mean()
    m2 = np.mean(d ** 2)
    if m2 > 1e-14:
        f['skewness'] = float(np.mean(d ** 3) / m2 ** 1.5)
        f['kurtosis'] = float(np.mean(d ** 4) / m2 ** 2)
    else:
        f['skewness'], f['kurtosis'] = 0.0, 3.0
    dx = np.diff(x)
    ddx = np.diff(x, 2)
    var_dx = np.sum(dx ** 2) / (n - 1)
    var_ddx = np.sum(ddx ** 2) / (n - 2)
    f['hjorth_activity'] = float(m2)
    if m2 > 1e-14 and var_dx > 1e-14:
        mob = np.sqrt(var_dx / m2)
        f['hjorth_mobility'] = float(mob)
        f['hjorth_complexity'] = float(np.sqrt(var_ddx / var_dx) / mob)
    else:
        f['hjorth_mobility'] = f['hjorth_complexity'] = 0.0
    f['zcr'] = float(np.sum((x[1:] >= 0) != (x[:-1] >= 0)) / (n - 1))

    buf = np.zeros(_N)
    buf[:n] = x * _HANN[:n]
    p = np.abs(np.fft.fft(buf))[:256] ** 2
    fr = np.arange(256) * fs / _N
    band = (fr >= 250) & (fr <= 4500)
    pb, fb = p[band], fr[band]
    tot = pb.sum()
    if tot > 1e-20:
        f['spectral_centroid'] = float((fb * pb).sum() / tot)
        f['peak_freq'] = float(fb[np.argmax(pb)])
        f['subband_250_500'] = float(pb[fb < 500].sum() / tot)
        f['subband_500_1k'] = float(pb[(fb >= 500) & (fb < 1000)].sum() / tot)
        f['subband_1k_2k'] = float(pb[(fb >= 1000) & (fb < 2000)].sum() / tot)
        f['subband_2k_4k5'] = float(pb[fb >= 2000].sum() / tot)
        f['hf_ratio'] = f['subband_2k_4k5']
        q = pb / tot
        q = q[q > 0]
        h = -np.sum(q * np.log(q)) / np.log(len(fb))
        f['spectral_entropy'] = float(np.clip(h, 0, 1))
    else:
        for k in ('spectral_centroid', 'peak_freq', 'subband_250_500', 'subband_500_1k',
                  'subband_1k_2k', 'subband_2k_4k5', 'hf_ratio', 'spectral_entropy'):
            f[k] = 0.0
    return {k: f[k] for k in ACOUSTIC_FEATURE_NAMES}
