from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel

from protocol import STATUS_NAMES, MODE_NAMES
from ui.styles import STATUS_COLORS

# Badge key -> (label, status keys it summarises). The knee IMU badge is ATTACHED
# if either BNO055 answers (single-IMU mode is supported by firmware >= 1.2).
BADGES = [('mic1', 'Mic #1 (INMP441)', ('mic1_status',)),
          ('mic2', 'Mic #2 (INMP441)', ('mic2_status',)),
          ('imu', 'Knee IMU (BNO055)', ('imu1_status', 'imu2_status')),
          ('emg', 'EMG (AD8232)', ('emg_status',)),
          ('load', 'Load cell (HX711)', ('load_status',))]


class StatusStrip(QWidget):
    """Shows only the sensors installed on this build.

    A badge appears once its sensor has reported ATTACHED at least once in this
    session (so an unplugged cable later still shows NOT_ATTACHED / FAULT).
    Sensors that were never detected stay hidden unless show_all is set.
    """

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        self.badges = {}
        for key, label, _ in BADGES:
            b = QLabel(f'{label}: —')
            self._paint(b, 1)
            b.setVisible(False)
            self.badges[key] = b
            lay.addWidget(b)
        lay.addStretch()
        self.info = QLabel('')
        lay.addWidget(self.info)
        self.last = {}
        self.seen = set()
        self.show_all = False

    @staticmethod
    def _paint(lbl, code):
        lbl.setStyleSheet(f'background:{STATUS_COLORS.get(code, "#6c7086")}; color:#11111b;'
                          'padding:3px 8px; border-radius:4px; font-weight:bold;')

    def installed(self, key):
        return key in self.seen

    def update_status(self, s, simulated=()):
        """Returns a list of human-readable changes (for the log panel)."""
        changes = []
        for key, label, skeys in BADGES:
            codes = [s.get(k, 1) for k in skeys]
            code = 0 if 0 in codes else max(codes)
            if code == 0:
                self.seen.add(key)
            lbl = self.badges[key]
            lbl.setText(f'{label}: {STATUS_NAMES.get(code, "?")}')
            self._paint(lbl, code)
            lbl.setVisible(self.show_all or key in self.seen)
            if key in self.last and self.last[key] != code and key in self.seen:
                changes.append(f'{label} → {STATUS_NAMES.get(code, "?")}')
            self.last[key] = code
        self.info.setText(
            f"mode {MODE_NAMES.get(s.get('stream_mode'), '?')} | floor {s.get('noise_floor_dbfs', -90):.1f} dBFS | "
            f"heap {s.get('free_heap', 0) // 1024} kB | dsp {s.get('loop_time_us', 0) / 1000:.1f} ms/blk")
        return changes
