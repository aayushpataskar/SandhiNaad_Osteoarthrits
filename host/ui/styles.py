DARK_THEME = """
QMainWindow, QWidget { background-color: #1e1e2e; color: #cdd6f4;
    font-family: 'Segoe UI', Arial, sans-serif; font-size: 10pt; }
QComboBox, QLineEdit, QPushButton, QSpinBox, QDoubleSpinBox {
    background-color: #313244; border: 1px solid #45475a; padding: 4px; border-radius: 4px; }
QPushButton:hover { background-color: #45475a; }
QPushButton:pressed, QPushButton:checked { background-color: #585b70; }
QTabWidget::pane { border: 1px solid #313244; }
QTabBar::tab { background: #313244; padding: 6px 14px; margin-right: 2px; }
QTabBar::tab:selected { background: #45475a; }
QTableWidget { background-color: #181825; gridline-color: #313244; }
QHeaderView::section { background-color: #313244; padding: 4px; border: 1px solid #45475a; }
QListWidget { background-color: #181825; border: 1px solid #313244; }
QProgressBar { border: 1px solid #45475a; border-radius: 4px; text-align: center; height: 22px; }
QGroupBox { border: 1px solid #45475a; border-radius: 6px; margin-top: 10px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
"""

STATUS_COLORS = {0: '#a6e3a1', 1: '#6c7086', 2: '#f38ba8', 3: '#89b4fa'}   # ATTACHED / NOT_ATTACHED / FAULT / SIMULATED
SYNTH_BADGE = ("background:#f9e2af; color:#11111b; font-weight:bold; padding:6px;"
               "border:2px solid #df8e1d; border-radius:5px;")
