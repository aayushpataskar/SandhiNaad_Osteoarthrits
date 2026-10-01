import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QGroupBox
from PySide6.QtCore import Qt

from model import TIER_COLORS, _risk_tier
from ui.styles import SYNTH_BADGE
from i18n import tr

TIER_BANDS = [(0.0, 0.3, 'Healthy'), (0.3, 0.6, 'Early Risk'), (0.6, 0.8, 'High Risk'), (0.8, 1.0, 'Referral')]
SESSION_N = 5          # session risk = median of the last N valid cycles


def _rgba(hex_color, a):
    h = hex_color.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


class MLPanel(QWidget):
    """Session OA-risk (median of recent valid cycles), per-cycle trend with tier bands,
    and per-feature contributions of the latest cycle."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        badge = QLabel('⚠ Model trained on SYNTHETIC data — demonstration only, '
                       'not clinically validated, not a diagnostic device.')
        badge.setWordWrap(True)
        badge.setStyleSheet(SYNTH_BADGE)
        badge.setAlignment(Qt.AlignCenter)
        lay.addWidget(badge)

        g = QGroupBox(f'Session OA risk (median of last {SESSION_N} valid flex–extend cycles)')
        gl = QVBoxLayout(g)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setFormat('%p %')
        self.tier = QLabel('Tier: waiting for a full, slow flex–extend cycle…')
        self.tier.setAlignment(Qt.AlignCenter)
        self.tier.setStyleSheet('font-size: 16pt; font-weight: bold;')
        self.detail = QLabel('')
        self.detail.setWordWrap(True)
        gl.addWidget(self.bar)
        gl.addWidget(self.tier)
        gl.addWidget(self.detail)
        lay.addWidget(g)

        row = QHBoxLayout()
        # --- risk trend with tier bands ---
        self.hist_plot = pg.PlotWidget(title='Risk per cycle (dots) and session risk (line)')
        self.hist_plot.setLabel('left', 'OA risk', units='%')
        self.hist_plot.setLabel('bottom', 'cycle #')
        self.hist_plot.setYRange(0, 100, padding=0)
        self.hist_plot.setXRange(0.5, 10.5, padding=0)
        self.hist_plot.setMouseEnabled(x=False, y=False)
        self.hist_plot.showGrid(x=True, y=True, alpha=0.15)
        for lo, hi, name in TIER_BANDS:
            band = pg.LinearRegionItem(values=(lo * 100, hi * 100), orientation='horizontal', movable=False,
                                       brush=pg.mkBrush(*_rgba(TIER_COLORS[name], 45)), pen=pg.mkPen(None))
            band.setZValue(-10)
            self.hist_plot.addItem(band)
            txt = pg.TextItem(name, color=TIER_COLORS[name], anchor=(0, 0.5))
            txt.setPos(0.6, (lo + hi) * 50)
            self.hist_plot.addItem(txt)
            self._band_labels = getattr(self, '_band_labels', []) + [txt]
        self.session_curve = self.hist_plot.plot(pen=pg.mkPen('#cdd6f4', width=2))
        self.dots = pg.ScatterPlotItem(size=11, pen=pg.mkPen('#11111b', width=1))
        self.hist_plot.addItem(self.dots)

        # --- contributions ---
        self.contrib_plot = pg.PlotWidget(title='Why? Feature contributions, latest cycle (top 8)')
        self.contrib_plot.setLabel('bottom', 'log-odds  (red → towards OA, green → towards healthy)')

        row.addWidget(self.hist_plot, 3)
        row.addWidget(self.contrib_plot, 2)
        lay.addLayout(row, 1)
        self.lang = 'en'
        self.last_session = None
        self.history = []          # (cycle_no, prob)
        self.session = []          # (cycle_no, session prob)
        self.n = 0

    def set_lang(self, lang):
        self.lang = lang
        if getattr(self, 'last_session', None):
            s, st = self.last_session
            self.tier.setText(f"{tr('sn.ml.tier', lang)}: {tr('sn.tiers.' + st, lang)}")
        else:
            self.tier.setText(f"{tr('sn.ml.tier', lang)}: {tr('sn.ml.waiting', lang)}")

    def clear(self):
        self.history.clear()
        self.session.clear()
        self.n = 0
        self.lowq = set()
        self.last_session = None
        self.dots.setData([])
        self.session_curve.setData([], [])

    def skipped(self, reason):
        self.detail.setText(f'<span style="color:#f9e2af">Last movement not scored: {reason}. '
                            'Do one slow, full bend (straighten fully, then lower) in 2–8 s.</span>')

    def update_cycle(self, device_prob, host_prob, fused_prob, tier, contributions, cycle, low_quality=None):
        p = fused_prob if fused_prob is not None else (host_prob if host_prob is not None else device_prob)
        self.n += 1
        self.history.append((self.n, p))
        self.lowq = getattr(self, 'lowq', set())
        if low_quality:
            self.lowq.add(self.n)
        recent = [q for _, q in self.history[-SESSION_N:]]
        sess = float(np.median(recent))
        self.session.append((self.n, sess))
        stier = _risk_tier(sess)

        self.last_session = (sess, stier)
        self.bar.setValue(int(round(sess * 100)))
        color = TIER_COLORS.get(stier, '#cdd6f4')
        self.bar.setStyleSheet(f'QProgressBar::chunk {{ background: {color}; }}')
        self.tier.setText(f"{tr('sn.ml.tier', self.lang)}: {tr('sn.tiers.' + stier, self.lang)}")
        self.tier.setStyleSheet(f'font-size: 16pt; font-weight: bold; color: {color};')
        parts = [f'latest cycle p = {p:.3f} ({_risk_tier(p)})', f'on-device p = {device_prob:.4f}']
        if host_prob is not None:
            parts.append('host re-check ' + ('match ✓' if abs(host_prob - device_prob) < 1e-3 else 'MISMATCH ✗'))
        if fused_prob is not None:
            parts.append('clinical prior applied')
        parts.append(f"ROM {cycle.get('rom', 0):.0f}°, {int(cycle.get('num_events', 0))} clicks, "
                     f"{cycle.get('duration_s', 0):.1f} s, based on {len(recent)} cycle(s)")
        if low_quality:
            parts.append(f'<span style="color:#f9e2af">low-quality movement ({low_quality}) — hollow dot</span>')
        self.detail.setText(' | '.join(parts))

        xs = [c for c, _ in self.history]
        self.dots.setData([{'pos': (c, q * 100),
                            'brush': pg.mkBrush(None) if c in self.lowq else pg.mkBrush(TIER_COLORS[_risk_tier(q)]),
                            'pen': pg.mkPen(TIER_COLORS[_risk_tier(q)], width=2) if c in self.lowq else pg.mkPen('#11111b')}
                           for c, q in self.history])
        self.session_curve.setData([c for c, _ in self.session], [s * 100 for _, s in self.session])
        hi = max(10.5, self.n + 0.5)
        self.hist_plot.setXRange(max(0.5, hi - 20), hi, padding=0)
        for t in self._band_labels:
            t.setPos(max(0.6, hi - 20 + 0.1), t.pos().y())

        self.contrib_plot.clear()
        top = contributions[:8][::-1]
        if top:
            y = np.arange(len(top))
            w = np.array([c[1] for c in top])
            brushes = [pg.mkBrush('#f38ba8' if v > 0 else '#a6e3a1') for v in w]
            self.contrib_plot.addItem(pg.BarGraphItem(x0=np.minimum(w, 0), y=y, width=np.abs(w),
                                                      height=0.6, brushes=brushes))
            self.contrib_plot.getAxis('left').setTicks([list(zip(y, [c[0] for c in top]))])
