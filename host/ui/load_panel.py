import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui.ringbuf import Ring


class LoadPanel(QWidget):
    def __init__(self, window_s=10.0):
        super().__init__()
        self.window_s = window_s
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.info = QLabel('Load: — N')
        lay.addWidget(self.info)
        self.plot = pg.PlotWidget(title='Load cell (HX711)')
        self.plot.setLabel('left', 'force', units='N')
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        lay.addWidget(self.plot)
        self.curve = self.plot.plot(pen=pg.mkPen('#89dceb', width=2))
        self.r = Ring(int(window_s * 100) + 50)
        self.now = 0.0
        self.value = None
        self.simulated = False

    def clear(self):
        self.r.clear()

    def add(self, t, force):
        self.r.push(t, force)
        self.now = max(self.now, t)
        self.value = force

    def set_simulated(self, on):
        self.simulated = on
        self.plot.setTitle('Load cell (HX711) — SIMULATED demo values' if on else 'Load cell (HX711)')

    def update_plots(self):
        t, v = self.r.view()
        if len(t):
            self.curve.setData(t, v)
            self.plot.setXRange(max(0, self.now - self.window_s), self.now, padding=0)
        if self.value is not None:
            tail = ('<b style="color:#89b4fa">SIMULATED (no load cell wired)</b>' if self.simulated
                    else 'uncalibrated until TARE + SCALE')
            self.info.setText(f'Load: {self.value:7.1f} N  ({self.value / 9.80665:5.2f} kgf)  — ' + tail)
