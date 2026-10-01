from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QComboBox, QPushButton,
                               QLineEdit, QLabel, QDoubleSpinBox, QCheckBox)
from PySide6.QtCore import Signal

from serial_link import SerialLink


class Toolbar(QWidget):
    connect_requested = Signal(str, int)
    disconnect_requested = Signal()
    command_requested = Signal(str)
    record_toggled = Signal(bool, str)
    nc_toggled = Signal(bool)
    sim_toggled = Signal(bool)

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 0)
        row1, row2 = QHBoxLayout(), QHBoxLayout()
        outer.addLayout(row1)
        outer.addLayout(row2)

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(130)
        self.btn_refresh = QPushButton('↻')
        self.btn_refresh.setFixedWidth(30)
        self.btn_refresh.clicked.connect(self.refresh_ports)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(['921600', '2000000'])
        self.btn_connect = QPushButton('Connect')
        self.btn_connect.setCheckable(True)
        self.btn_connect.toggled.connect(self._on_connect)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(['DEFAULT', 'FULL', 'FEATURES'])
        self.mode_combo.currentTextChanged.connect(lambda m: self.command_requested.emit(f'MODE {m}'))
        self.btn_start = QPushButton('▶ Start')
        self.btn_start.clicked.connect(lambda: self.command_requested.emit('START'))
        self.btn_stop = QPushButton('■ Stop')
        self.btn_stop.clicked.connect(lambda: self.command_requested.emit('STOP'))

        row1.addWidget(QLabel('Port:'))
        row1.addWidget(self.port_combo)
        row1.addWidget(self.btn_refresh)
        row1.addWidget(self.baud_combo)
        row1.addWidget(self.btn_connect)
        row1.addSpacing(12)
        row1.addWidget(QLabel('Mode:'))
        row1.addWidget(self.mode_combo)
        row1.addWidget(self.btn_start)
        row1.addWidget(self.btn_stop)
        row1.addStretch()
        self.stats_label = QLabel('Pkts/s: 0 | kB/s: 0 | Drops: 0 | CRC: 0')
        row1.addWidget(self.stats_label)

        self.btn_cal = QPushButton('Calibrate zero (IMU)')
        self.btn_cal.clicked.connect(lambda: self.command_requested.emit('CAL_ZERO'))
        self.btn_tare = QPushButton('Tare load')
        self.btn_tare.clicked.connect(lambda: self.command_requested.emit('TARE'))
        self.scale_g = QDoubleSpinBox()
        self.scale_g.setRange(1, 20000)
        self.scale_g.setValue(1000)
        self.scale_g.setSuffix(' g')
        self.btn_scale = QPushButton('Scale')
        self.btn_scale.setToolTip('Put this known mass on the load cell, then click')
        self.btn_scale.clicked.connect(lambda: self.command_requested.emit(f'SCALE {self.scale_g.value():.1f}'))
        self.thresh = QDoubleSpinBox()
        self.thresh.setRange(3, 60)
        self.thresh.setValue(18)
        self.thresh.setSuffix(' dB')
        self.thresh.setToolTip('Click-detection margin above the noise floor')
        self.thresh.editingFinished.connect(lambda: self.command_requested.emit(f'THRESH {self.thresh.value():.1f}'))
        self.chk_nc = QCheckBox('Noise cancel (NLMS)')
        self.chk_nc.toggled.connect(self.nc_toggled.emit)
        self.chk_sim = QCheckBox('Demo: fill missing mic #2 + load (SIMULATED)')
        self.chk_sim.setToolTip('Host generates labelled synthetic values for sensors that are not wired. Badges turn BLUE, never green.')
        self.chk_sim.toggled.connect(self.sim_toggled.emit)

        self.session_name = QLineEdit()
        self.session_name.setPlaceholderText('Session / subject ID')
        self.session_name.setMaximumWidth(180)
        self.btn_rec = QPushButton('⏺ Record')
        self.btn_rec.setCheckable(True)
        self.btn_rec.toggled.connect(self._on_rec)

        for w in (self.btn_cal, self.btn_tare, self.scale_g, self.btn_scale, QLabel('Threshold:'),
                  self.thresh, self.chk_nc, self.chk_sim):
            row2.addWidget(w)
        row2.addStretch()
        row2.addWidget(self.session_name)
        row2.addWidget(self.btn_rec)

        self.refresh_ports()
        self.set_connected(False)

    def refresh_ports(self):
        cur = self.port_combo.currentText()
        self.port_combo.clear()
        self.port_combo.addItems(SerialLink.list_ports())
        i = self.port_combo.findText(cur)
        if i >= 0:
            self.port_combo.setCurrentIndex(i)

    def set_connected(self, on):
        for w in (self.btn_start, self.btn_stop, self.btn_cal, self.btn_tare, self.btn_scale,
                  self.mode_combo, self.thresh, self.btn_rec):
            w.setEnabled(on)
        self.port_combo.setEnabled(not on)
        self.baud_combo.setEnabled(not on)

    def _on_connect(self, checked):
        self.btn_connect.setText('Disconnect' if checked else 'Connect')
        if checked:
            self.connect_requested.emit(self.port_combo.currentText(), int(self.baud_combo.currentText()))
        else:
            self.disconnect_requested.emit()

    def _on_rec(self, checked):
        self.btn_rec.setText('⏹ Stop recording' if checked else '⏺ Record')
        self.btn_rec.setStyleSheet('background:#f38ba8; color:#11111b;' if checked else '')
        self.record_toggled.emit(checked, self.session_name.text().strip() or 'session')

    def update_stats(self, s):
        self.stats_label.setText(
            f"Pkts/s: {s['packets_per_sec']} | kB/s: {s['bytes_per_sec'] / 1000:.1f} | "
            f"Drops: {s['drops']} | CRC: {s['crc_errors']}")
