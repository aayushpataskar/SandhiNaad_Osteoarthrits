"""SandhiNaad host app.  Run:  python app.py   (from the host/ folder)

Pick the ESP32's COM port (or SIMULATOR to try it without hardware) and Connect.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from ui.styles import DARK_THEME


def main():
    app = QApplication(sys.argv)
    pg.setConfigOptions(antialias=False, background='#181825', foreground='#cdd6f4')
    app.setStyleSheet(DARK_THEME)
    from ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
