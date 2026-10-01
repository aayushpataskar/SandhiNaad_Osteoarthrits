import numpy as np
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QHeaderView)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from localization import LocalizationSystem
from ui.styles import SYNTH_BADGE


class LocalizationPanel(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        b = QLabel('SIMULATED — source localization uses a simulated 4-mic geometry, '
                   'not live microphone data.')
        b.setStyleSheet(SYNTH_BADGE)
        b.setAlignment(Qt.AlignCenter)
        b.setWordWrap(True)
        lay.addWidget(b)
        lay.addWidget(QLabel('Idea: time-difference + amplitude fingerprints across mics around the patella '
                             'classify where a click originates (medial/lateral joint line, supra/infra-patellar).'))
        self.btn = QPushButton('Run simulated demo (40 events)')
        self.btn.clicked.connect(self.run)
        lay.addWidget(self.btn)
        self.acc = QLabel('Accuracy: —')
        self.acc.setStyleSheet('font-size: 14pt; font-weight: bold;')
        lay.addWidget(self.acc)
        self.table = QTableWidget()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self.table)
        self.sys = LocalizationSystem()

    def run(self):
        acc, results = self.sys.run_simulated_demo()
        names = list(self.sys.mic_positions.keys())
        cm = np.zeros((len(names), len(names)), dtype=int)
        for true, pred in results:
            if pred in names:
                cm[names.index(true), names.index(pred)] += 1
        self.acc.setText(f'Simulated accuracy: {acc * 100:.1f}% (rows = true, columns = predicted)')
        self.table.setRowCount(len(names))
        self.table.setColumnCount(len(names))
        self.table.setHorizontalHeaderLabels(names)
        self.table.setVerticalHeaderLabels(names)
        mx = max(1, cm.max())
        for i in range(len(names)):
            for j in range(len(names)):
                it = QTableWidgetItem(str(cm[i, j]))
                it.setTextAlignment(Qt.AlignCenter)
                a = int(40 + 180 * cm[i, j] / mx)
                it.setBackground(QColor(137, 180, 250, a) if i == j else QColor(243, 139, 168, a if cm[i, j] else 0))
                self.table.setItem(i, j, it)
