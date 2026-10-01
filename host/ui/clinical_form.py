from PySide6.QtWidgets import (QWidget, QFormLayout, QSpinBox, QDoubleSpinBox, QComboBox,
                               QCheckBox, QPushButton, QHBoxLayout, QLabel)
from PySide6.QtCore import Signal


class ClinicalForm(QWidget):
    """Clinical prior inputs. Encoding matches ml/config.py CLINICAL_FEATURES."""
    changed = Signal(dict)

    def __init__(self):
        super().__init__()
        f = QFormLayout(self)
        self.age = QSpinBox(); self.age.setRange(0, 110); self.age.setSpecialValueText('— (not entered)')
        self.sex = QComboBox(); self.sex.addItems(['Male', 'Female'])
        self.bmi = QDoubleSpinBox(); self.bmi.setRange(10, 60); self.bmi.setValue(24.0); self.bmi.setDecimals(1)
        self.squat = QCheckBox('Occupation involves frequent squatting / kneeling')
        self.koos_pain = QSpinBox(); self.koos_pain.setRange(0, 100); self.koos_pain.setValue(100)
        self.koos_func = QSpinBox(); self.koos_func.setRange(0, 100); self.koos_func.setValue(100)
        f.addRow('Age (years):', self.age)
        f.addRow('Sex:', self.sex)
        f.addRow('BMI (kg/m²):', self.bmi)
        f.addRow('', self.squat)
        f.addRow('KOOS Pain (0 worst – 100 best):', self.koos_pain)
        f.addRow('KOOS Function/ADL (0–100):', self.koos_func)
        btns = QHBoxLayout()
        self.btn_apply = QPushButton('Apply as prior')
        self.btn_clear = QPushButton('Clear')
        btns.addWidget(self.btn_apply)
        btns.addWidget(self.btn_clear)
        f.addRow(btns)
        self.state = QLabel('Prior: not applied (acoustic model only)')
        f.addRow(self.state)
        self.btn_apply.clicked.connect(self._apply)
        self.btn_clear.clicked.connect(self._clear)
        self.applied = {}

    def get_data(self):
        if self.age.value() <= 0:
            return {}
        return {'age': float(self.age.value()),
                'sex': 1.0 if self.sex.currentText() == 'Female' else 0.0,
                'bmi': float(self.bmi.value()),
                'occupation_squat': 1.0 if self.squat.isChecked() else 0.0,
                'koos_pain': float(self.koos_pain.value()),
                'koos_function': float(self.koos_func.value())}

    def _apply(self):
        self.applied = self.get_data()
        self.state.setText('Prior: APPLIED (late fusion: acoustic log-odds + clinical log-odds)'
                           if self.applied else 'Enter age first')
        self.changed.emit(self.applied)

    def _clear(self):
        self.age.setValue(0)
        self.applied = {}
        self.state.setText('Prior: not applied (acoustic model only)')
        self.changed.emit({})
