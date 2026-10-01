import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from protocol import PHASE_NAMES
from ui.ringbuf import Ring


class KinematicPanel(QWidget):
    def __init__(self, window_s=10.0):
        super().__init__()
        self.window_s = window_s
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.info = QLabel('Knee angle: — | Phase: — | Cycles: 0')
        lay.addWidget(self.info)
        self.plot = pg.PlotWidget(title='Knee angle with flexion / extension phase shading')
        self.plot.setLabel('left', 'angle', units='°')
        self.plot.setLabel('bottom', 'time', units='s')
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        lay.addWidget(self.plot)

        self.flex_fill = pg.PlotDataItem(pen=None, fillLevel=0, brush=pg.mkBrush(166, 227, 161, 50))
        self.ext_fill = pg.PlotDataItem(pen=None, fillLevel=0, brush=pg.mkBrush(250, 179, 135, 50))
        self.plot.addItem(self.flex_fill)
        self.plot.addItem(self.ext_fill)
        self.curve = self.plot.plot(pen=pg.mkPen('#cdd6f4', width=2))
        self.ev = pg.ScatterPlotItem(size=11, brush=pg.mkBrush('#f9e2af'), pen=None)
        self.plot.addItem(self.ev)
        self.cycle_lines = []

        self.r = Ring(int(window_s * 100) + 50, cols=2)   # angle, phase
        self.events = []
        self.cycle_marks = []
        self.n_cycles = 0
        self.now = 0.0
        self.cal = (0, 0, 0, 0)
        self.angle = 0.0
        self.phase = 0

    def clear(self):
        self.r.clear()
        self.events.clear()
        self.cycle_marks.clear()

    def add_data(self, t, d):
        self.r.push(t, np.array([[d['knee_angle'], d['phase']]]))
        self.now = max(self.now, t)
        self.angle, self.phase, self.cal = d['knee_angle'], d['phase'], d['cal']

    def add_event(self, t, angle):
        self.events.append((t, angle))

    def add_cycle(self, t):
        self.cycle_marks.append(t)
        self.n_cycles += 1

    def update_plots(self):
        lo = self.now - self.window_s
        t, v = self.r.view()
        if len(t):
            ang, ph = v[:, 0], v[:, 1]
            top = max(10.0, float(ang.max()) * 1.1)
            self.curve.setData(t, ang)
            self.flex_fill.setData(t, np.where(ph == 1, top, 0.0))
            self.ext_fill.setData(t, np.where(ph == 2, top, 0.0))
        self.events = [e for e in self.events if e[0] > lo]
        self.ev.setData([e[0] for e in self.events], [e[1] for e in self.events])
        self.cycle_marks = [c for c in self.cycle_marks if c > lo]
        for ln in self.cycle_lines:
            self.plot.removeItem(ln)
        self.cycle_lines = []
        for c in self.cycle_marks:
            ln = pg.InfiniteLine(pos=c, angle=90, pen=pg.mkPen('#89b4fa', style=pg.QtCore.Qt.DotLine))
            self.plot.addItem(ln)
            self.cycle_lines.append(ln)
        if self.now > 0:
            self.plot.setXRange(max(0, lo), self.now, padding=0)
        self.info.setText(f'Knee angle: {self.angle:6.1f}° | Phase: {PHASE_NAMES.get(self.phase, "?")} | '
                          f'Cycles: {self.n_cycles} | IMU cal (sys/gyr/acc/mag): '
                          f'{"/".join(str(c) for c in self.cal)}  (green = flexion, orange = extension)')
