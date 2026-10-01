from datetime import datetime

from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QLabel


class FlagsPanel(QWidget):
    """Device log (LOG/ACK), sensor status changes, events and warnings."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel('Device log & flags (newest first)'))
        self.list = QListWidget()
        lay.addWidget(self.list)

    def add_flag(self, text):
        self.list.insertItem(0, f"[{datetime.now().strftime('%H:%M:%S')}] {text}")
        while self.list.count() > 500:
            self.list.takeItem(self.list.count() - 1)
