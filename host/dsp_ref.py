"""Host-side NLMS noise cancellation (EMG as the artifact reference).

Streaming: call NoiseCanceller.process(audio_block, emg_block) per 512-sample
audio block. The EMG block (1 kHz) is linearly resampled to the audio length.
Bypassed automatically if EMG is absent, detached, or saturated.
"""
import numpy as np


class NoiseCanceller:
    def __init__(self, taps=16, mu=0.05, eps=1e-6):
        self.taps = taps
        self.mu = mu
        self.eps = eps
        self.reset()

    def reset(self):
        self.w = np.zeros(self.taps)
        self.x_hist = np.zeros(self.taps - 1)
        self.last_db = 0.0
        self.bypassed = True

    def process(self, d, emg, emg_ok=True):
        d = np.asarray(d, dtype=np.float64)
        if (not emg_ok) or emg is None or len(emg) < 2:
            self.bypassed = True
            self.last_db = 0.0
            return d
        self.bypassed = False
        ref = np.interp(np.linspace(0, len(emg) - 1, len(d)), np.arange(len(emg)),
                        np.asarray(emg, dtype=np.float64))
        ref = ref / (np.std(ref) + 1e-9) * 1e-3          # scale-free reference
        x = np.concatenate([self.x_hist, ref])
        e = np.empty_like(d)
        w = self.w
        L = self.taps
        for n in range(len(d)):
            xv = x[n:n + L][::-1]
            y = w @ xv
            e[n] = d[n] - y
            w += (self.mu / (self.eps + xv @ xv)) * e[n] * xv
        self.w = w
        self.x_hist = x[-(L - 1):]
        vd, ve = np.var(d), np.var(e)
        self.last_db = float(10 * np.log10(vd / ve)) if ve > 0 and vd > 0 else 0.0
        return e
