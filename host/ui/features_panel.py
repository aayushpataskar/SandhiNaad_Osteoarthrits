from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QLabel, QHeaderView


class FeaturesPanel(QWidget):
    """Live block features (every 32 ms, shown smoothed) + last cycle summary."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel('DSP features (block = 512 samples @ 16 kHz, EMA-smoothed for display)'))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['Feature', 'Value'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table)
        self.smooth = {}

    def update_features(self, d, alpha=0.2):
        for k, v in d.items():
            self.smooth[k] = v if k not in self.smooth else (1 - alpha) * self.smooth[k] + alpha * v

    def refresh(self):
        items = list(self.smooth.items())
        if self.table.rowCount() != len(items):
            self.table.setRowCount(len(items))
        for i, (k, v) in enumerate(items):
            self.table.setItem(i, 0, QTableWidgetItem(k))
            self.table.setItem(i, 1, QTableWidgetItem(f'{v:.5g}'))
