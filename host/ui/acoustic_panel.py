import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui.ringbuf import Ring

FS = 16000
SPEC_N = 256
SPEC_COLS = 320          # ~10 s of 32 ms blocks


class AcousticPanel(QWidget):
    def __init__(self, window_s=10.0):
        super().__init__()
        self.window_s = window_s
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.info = QLabel('Noise floor: — dBFS | Threshold: 18 dB | Events: 0 | NC: off')
        lay.addWidget(self.info)

        self.glw = pg.GraphicsLayoutWidget()
        lay.addWidget(self.glw)
        self.p_raw = self.glw.addPlot(row=0, col=0, title='Raw audio (min/max per ms)')
        self.p_filt = self.glw.addPlot(row=1, col=0, title='Band-passed 250–4500 Hz')
        self.p_env = self.glw.addPlot(row=2, col=0, title='Envelope + click events')
        self.p_spec = self.glw.addPlot(row=3, col=0, title='Spectrogram (filtered)')
        for p in (self.p_filt, self.p_env, self.p_spec):
            p.setXLink(self.p_raw)
        for p in (self.p_raw, self.p_filt, self.p_env):
            p.setDownsampling(auto=True, mode='peak')
            p.setClipToView(True)
            p.showGrid(x=True, y=True, alpha=0.2)
        self.p_spec.setLabel('left', 'Hz')
        self.p_spec.setLabel('bottom', 'time', units='s')

        self.c_raw_hi = self.p_raw.plot(pen='#bac2de')
        self.c_raw_lo = self.p_raw.plot(pen='#bac2de')
        self.c_before = self.p_filt.plot(pen=pg.mkPen('#6c7086', width=1))
        self.c_filt = self.p_filt.plot(pen='#f9e2af')
        self.c_env = self.p_env.plot(pen=pg.mkPen('#89dceb', width=2))
        self.floor_line = pg.InfiniteLine(angle=0, pen=pg.mkPen('#f38ba8', style=pg.QtCore.Qt.DashLine),
                                          label='floor', labelOpts={'position': 0.05, 'color': '#f38ba8'})
        self.thr_line = pg.InfiniteLine(angle=0, pen=pg.mkPen('#a6e3a1', style=pg.QtCore.Qt.DashLine),
                                        label='threshold', labelOpts={'position': 0.15, 'color': '#a6e3a1'})
        self.p_env.addItem(self.floor_line)
        self.p_env.addItem(self.thr_line)
        self.ev_scatter = pg.ScatterPlotItem(size=11, symbol='t', pen=None)
        self.p_env.addItem(self.ev_scatter)

        self.spec_img = pg.ImageItem()
        self.spec_img.setColorMap(pg.colormap.get('inferno'))
        self.p_spec.addItem(self.spec_img)
        self.spec = np.full((SPEC_COLS, SPEC_N // 2), -120.0)
        self.spec_t_end = 0.0
        self._win = np.hanning(SPEC_N)

        self.r_raw = Ring(int(window_s * 1000) + 100, cols=2)
        self.r_filt = Ring(int(window_s * FS) + 1024)
        self.r_before = Ring(int(window_s * FS) + 1024)
        self.r_env = Ring(int(window_s * 1000) + 100)
        self.events = []          # (t, amp, phase)
        self.n_events = 0
        self.floor_dbfs = -90.0
        self.thresh_db = 18.0
        self.nc_on = False
        self.nc_db = 0.0
        self.nc_bypassed = True
        self.now = 0.0

    def clear(self):
        for r in (self.r_raw, self.r_filt, self.r_before, self.r_env):
            r.clear()
        self.events.clear()
        self.spec[:] = -120
        self.n_events = 0

    def add_minmax(self, t0, mn, mx):
        n = len(mn)
        self.r_raw.push(t0 + np.arange(n) / 1000.0, np.stack([mn, mx], 1))
        self.now = max(self.now, t0 + n / 1000.0)

    def add_raw(self, t0, x):
        d = x[: (len(x) // 16) * 16].reshape(-1, 16)
        self.add_minmax(t0, d.min(1), d.max(1))

    def add_filtered(self, t0, x, before=None):
        n = len(x)
        tt = t0 + np.arange(n) / FS
        self.r_filt.push(tt, x)
        if before is not None:
            self.r_before.push(tt, before)
        self.now = max(self.now, t0 + n / FS)
        seg = x[-SPEC_N:]
        if len(seg) == SPEC_N:
            col = 10 * np.log10(np.abs(np.fft.rfft(seg * self._win))[:SPEC_N // 2] ** 2 + 1e-12)
            self.spec = np.roll(self.spec, -1, axis=0)
            self.spec[-1] = col
            self.spec_t_end = t0 + n / FS

    def add_envelope(self, t0, env):
        n = len(env)
        self.r_env.push(t0 + np.arange(n) / 1000.0, env)
        self.now = max(self.now, t0 + n / 1000.0)

    def add_event(self, t, d):
        amp = 10 ** (d['peak_dbfs'] / 20)
        self.events.append((t, amp, d['phase']))
        self.n_events += 1

    def set_floor(self, dbfs):
        self.floor_dbfs = dbfs

    def update_plots(self):
        lo = self.now - self.window_s
        t, v = self.r_raw.view()
        if len(t):
            self.c_raw_lo.setData(t, v[:, 0])
            self.c_raw_hi.setData(t, v[:, 1])
        t, v = self.r_filt.view()
        if len(t):
            self.c_filt.setData(t, v)
        if self.nc_on:
            tb, vb = self.r_before.view()
            self.c_before.setData(tb, vb)
        else:
            self.c_before.setData([], [])
        t, v = self.r_env.view()
        if len(t):
            self.c_env.setData(t, v)
        floor_lin = 10 ** (self.floor_dbfs / 20)
        self.floor_line.setValue(floor_lin)
        self.thr_line.setValue(floor_lin * 10 ** (self.thresh_db / 20))
        self.events = [e for e in self.events if e[0] > lo]
        colors = {0: '#bac2de', 1: '#a6e3a1', 2: '#fab387'}
        self.ev_scatter.setData([{'pos': (e[0], e[1]), 'brush': pg.mkBrush(colors.get(e[2], '#fff'))}
                                 for e in self.events])
        if self.spec_t_end > 0:
            self.spec_img.setImage(self.spec, autoLevels=False, levels=(-100, -20))
            dt = 512 / FS
            self.spec_img.setRect(pg.QtCore.QRectF(self.spec_t_end - SPEC_COLS * dt, 0,
                                                   SPEC_COLS * dt, FS / 2))
        if self.now > 0:
            self.p_raw.setXRange(max(0, lo), self.now, padding=0)
        nc = 'off'
        if self.nc_on:
            nc = 'BYPASSED (EMG absent/saturated)' if self.nc_bypassed else f'{self.nc_db:+.1f} dB reduction'
        self.info.setText(f'Noise floor: {self.floor_dbfs:.1f} dBFS | Threshold: {self.thresh_db:.0f} dB | '
                          f'Events: {self.n_events} (green = flexion, orange = extension) | NC: {nc}')
