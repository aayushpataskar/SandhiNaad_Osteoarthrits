import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui.ringbuf import Ring


class EMGPanel(QWidget):
    def __init__(self, window_s=10.0):
        super().__init__()
        self.window_s = window_s
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.info = QLabel('EMG (AD8232, quadriceps) — saturation: no')
        lay.addWidget(self.info)
        self.plot = pg.PlotWidget(title='EMG: baseline-removed (pink) and envelope (white)')
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.setDownsampling(auto=True, mode='peak')
        self.plot.setClipToView(True)
        lay.addWidget(self.plot)
        self.c_sig = self.plot.plot(pen='#f38ba8')
        self.c_env = self.plot.plot(pen=pg.mkPen('#ffffff', width=2))
        self.r = Ring(int(window_s * 1000) + 100, cols=3)
        self.now = 0.0
        self.saturated = False

    def clear(self):
        self.r.clear()

    def add(self, t0, d):
        n = len(d['raw'])
        if n == 0:
            return
        self.r.push(t0 + np.arange(n) / 1000.0, np.stack([d['raw'], d['removed'], d['envelope']], 1))
        self.now = max(self.now, t0 + n / 1000.0)
        rails = np.sum((d['raw'] <= 20) | (d['raw'] >= 4075))
        self.saturated = rails > 0.02 * n

    def recent_removed(self, k=33):
        _, v = self.r.last(k)
        return v[:, 1] if len(v) else None

    def update_plots(self):
        t, v = self.r.view()
        if len(t):
            self.c_sig.setData(t, v[:, 1])
            self.c_env.setData(t, v[:, 2])
            self.plot.setXRange(max(0, self.now - self.window_s), self.now, padding=0)
        self.info.setText('EMG (AD8232, quadriceps) — saturation: ' +
                          ('<b style="color:#f38ba8">YES (rails)</b>' if self.saturated else 'no'))
