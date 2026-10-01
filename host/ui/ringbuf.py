import numpy as np


class Ring:
    """Fixed-size time/value ring buffer; view() returns chronologically ordered copies."""

    def __init__(self, size, cols=1):
        self.size = size
        self.t = np.zeros(size)
        self.v = np.zeros((size, cols)) if cols > 1 else np.zeros(size)
        self.n = 0
        self.i = 0

    def clear(self):
        self.n = 0
        self.i = 0

    def push(self, t, v):
        t = np.atleast_1d(np.asarray(t, dtype=float))
        v = np.asarray(v, dtype=float)
        if v.ndim == 0:
            v = v.reshape(1)
        m = len(t)
        if m >= self.size:
            t, v, m = t[-self.size:], v[-self.size:], self.size
        end = self.i + m
        if end <= self.size:
            self.t[self.i:end] = t
            self.v[self.i:end] = v
        else:
            k = self.size - self.i
            self.t[self.i:] = t[:k]
            self.v[self.i:] = v[:k]
            self.t[:m - k] = t[k:]
            self.v[:m - k] = v[k:]
        self.i = end % self.size
        self.n = min(self.size, self.n + m)

    def view(self):
        if self.n < self.size:
            return self.t[:self.n].copy(), self.v[:self.n].copy()
        idx = np.r_[self.i:self.size, 0:self.i]
        return self.t[idx], self.v[idx]

    def last(self, k):
        t, v = self.view()
        return t[-k:], v[-k:]
