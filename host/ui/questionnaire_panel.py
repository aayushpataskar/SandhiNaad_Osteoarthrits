"""Bilingual patient registration + OA screening questionnaire (ported from the
OA-NER web app: PatientRegistrationScreen / ScreeningScreen / clinicalConfig.js).

Unanswered items stay 'not_assessed' (never silently 'No'), as in clinicalConfig.js.
Red flags: any 'yes' shows a referral banner and forces a priority referral in the report.
"""
import json
import os
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QGroupBox,
                               QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox,
                               QPushButton, QScrollArea, QTextEdit)

from i18n import tr

SETTINGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'sessions', 'worker.json')

TRI = [('yes', 'options.yes'), ('no', 'options.no'), ('not_assessed', 'options.notAssessed')]
TRI_DK = [('yes', 'options.yes'), ('no', 'options.no'), ('dont_know', 'options.dontKnow')]
OCCUPATIONS = [('farmer', 'occupations.farmer'), ('tea_garden_worker', 'occupations.teaGardenWorker'),
               ('homemaker', 'occupations.homemaker'), ('laborer', 'occupations.laborer'),
               ('office_desk', 'occupations.officeDesk'), ('student', 'occupations.student'),
               ('retired', 'occupations.retired'), ('other', 'occupations.other')]
SEXES = [('male', 'patient.male'), ('female', 'patient.female'), ('other', 'patient.other')]
KNEES = [('right', 'complaint.right'), ('left', 'complaint.left'), ('both', 'complaint.both')]
SIDES = [('right', 'complaint.right'), ('left', 'complaint.left')]
UNITS = [('weeks', 'units.weeks'), ('months', 'units.months'), ('years', 'units.years')]
ALIGN = [('not_assessed', 'options.notAssessed'), ('normal', 'clinicalCheck.alignmentNormal'),
         ('varus', 'clinicalCheck.alignmentVarus'), ('valgus', 'clinicalCheck.alignmentValgus')]
HISTORY = [('injury_left', 'history.leftInjury', TRI_DK), ('injury_right', 'history.rightInjury', TRI_DK),
           ('family_history', 'history.familyHistory', TRI_DK), ('diabetes', 'history.diabetes', TRI_DK),
           ('inflammatory_arthritis', 'history.inflammatoryArthritis', TRI_DK), ('gout', 'history.gout', TRI_DK),
           ('pain_medicine', 'history.painMedicine', TRI), ('walking_aid', 'history.walkingAid', TRI)]
FUNCTIONAL = [('pain_movement', 'complaint.painMovement'), ('stairs', 'complaint.stairs'),
              ('squatting', 'complaint.squatting'), ('kneeling', 'complaint.kneeling'),
              ('standing_chair', 'complaint.standingChair'), ('swelling', 'complaint.swelling'),
              ('locking', 'complaint.locking'), ('giving_way', 'complaint.givingWay'),
              ('night_pain', 'complaint.nightPain')]
RED_FLAGS = [('fever_hot_knee', 'redFlags.feverHotKnee'), ('sudden_severe_swelling', 'redFlags.suddenSevereSwelling'),
             ('recent_significant_injury', 'redFlags.recentSignificantInjury'),
             ('unable_bear_weight', 'redFlags.unableBearWeight'),
             ('unexplained_weight_loss_bone_pain', 'redFlags.unexplainedWeightLossBonePain')]
EXAM = [('effusion', 'clinicalCheck.effusion'), ('tenderness', 'clinicalCheck.jointLineTenderness'),
        ('bony_enlargement', 'clinicalCheck.bonyEnlargement'), ('warmth', 'clinicalCheck.warmth'),
        ('crepitus', 'clinicalCheck.crepitus')]


class OptCombo(QComboBox):
    """Combo whose items are (value, i18n-key); texts re-translate in place."""

    def __init__(self, options, default=None):
        super().__init__()
        self.options = options
        for v, _ in options:
            self.addItem(v, v)
        if default is not None:
            self.set_value(default)

    def retranslate(self, lang):
        for i, (_, key) in enumerate(self.options):
            self.setItemText(i, tr(key, lang))

    def value(self):
        return self.currentData()

    def set_value(self, v):
        i = self.findData(v)
        if i >= 0:
            self.setCurrentIndex(i)


class QuestionnairePanel(QWidget):
    changed = Signal()
    apply_prior = Signal(dict)

    def __init__(self):
        super().__init__()
        self.lang = 'en'
        self._labels = []          # (QLabel|QGroupBox|QCheckBox|QPushButton, key)
        self._combos = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.banner = QLabel('')
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet('background:#f38ba8; color:#11111b; font-weight:bold; padding:8px; border-radius:6px;')
        self.banner.setVisible(False)
        outer.addWidget(self.banner)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        grid = QGridLayout(body)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        grid.addWidget(self._patient_box(), 0, 0)
        grid.addWidget(self._worker_box(), 1, 0)
        grid.addWidget(self._history_box(), 2, 0)
        grid.addWidget(self._redflag_box(), 3, 0)
        grid.addWidget(self._complaint_box(), 0, 1, 2, 1)
        grid.addWidget(self._exam_box(), 2, 1, 2, 1)

        row = QHBoxLayout()
        self.btn_prior = self._btn('sn.q.apply_prior')
        self.btn_prior.clicked.connect(self._emit_prior)
        self.note = self._lbl('sn.q.prior_note')
        self.note.setWordWrap(True)
        self.note.setStyleSheet('color:#a6adc8; font-style:italic;')
        row.addWidget(self.btn_prior)
        row.addWidget(self.note, 1)
        outer.addLayout(row)
        self._load_worker()
        self.new_patient_id()
        self.retranslate('en')

    # ------------------------------------------------------------ helpers
    def _lbl(self, key):
        w = QLabel(key)
        self._labels.append((w, key))
        return w

    def _btn(self, key):
        w = QPushButton(key)
        self._labels.append((w, key))
        return w

    def _box(self, key):
        g = QGroupBox(key)
        self._labels.append((g, key))
        return g

    def _combo(self, options, default=None):
        c = OptCombo(options, default)
        c.currentIndexChanged.connect(self._on_change)
        self._combos.append(c)
        return c

    def _spin(self, lo, hi, val=0, dec=None, suffix=''):
        w = QDoubleSpinBox() if dec is not None else QSpinBox()
        if dec is not None:
            w.setDecimals(dec)
        w.setRange(lo, hi)
        w.setValue(val)
        if suffix:
            w.setSuffix(suffix)
        w.valueChanged.connect(self._on_change)
        return w

    # ------------------------------------------------------------ sections
    def _patient_box(self):
        g = self._box('sn.patient_extra.title')
        f = QFormLayout(g)
        self.p_name = QLineEdit()
        self.p_name.textChanged.connect(self._on_change)
        idrow = QHBoxLayout()
        self.p_id = QLineEdit()
        self.p_id.setReadOnly(True)
        b = self._btn('sn.patient_extra.new_id')
        b.clicked.connect(self.new_patient_id)
        idrow.addWidget(self.p_id, 1)
        idrow.addWidget(b)
        self.p_age = self._spin(0, 110, 0, suffix='')
        self.p_sex = self._combo(SEXES)
        self.p_h = self._spin(100, 220, 160, dec=0, suffix=' cm')
        self.p_w = self._spin(20, 200, 60, dec=1, suffix=' kg')
        self.p_bmi = QLabel('—')
        self.p_h.valueChanged.connect(self._bmi)
        self.p_w.valueChanged.connect(self._bmi)
        self.p_occ = self._combo(OCCUPATIONS, 'farmer')
        self.p_kneel = self._spin(0, 24, 0, suffix=' h')
        self.p_village = QLineEdit()
        self.p_block = QLineEdit()
        self.p_district = QLineEdit()
        self.p_consent = QCheckBox()
        self._labels.append((self.p_consent, 'patient.consentCheckbox'))
        self.p_consent.toggled.connect(self._on_change)
        for key, w in [('patient.name', self.p_name), ('patient.patientId', idrow), ('patient.estimatedAge', self.p_age),
                       ('patient.gender', self.p_sex), ('patient.height', self.p_h), ('patient.weight', self.p_w),
                       ('patient.bmi', self.p_bmi), ('patient.occupation', self.p_occ),
                       ('patient.kneelingSquattingHours', self.p_kneel), ('patient.village', self.p_village),
                       ('patient.block', self.p_block), ('patient.district', self.p_district)]:
            f.addRow(self._lbl(key), w)
        f.addRow(self.p_consent)
        self._bmi()
        return g

    def _worker_box(self):
        g = self._box('sn.worker.title')
        f = QFormLayout(g)
        self.w_name, self.w_role, self.w_id, self.w_fac = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        for key, w in [('sn.worker.name', self.w_name), ('sn.worker.role', self.w_role),
                       ('sn.worker.id', self.w_id), ('sn.worker.facility', self.w_fac)]:
            w.editingFinished.connect(self._save_worker)
            f.addRow(self._lbl(key), w)
        return g

    def _history_box(self):
        g = self._box('history.title')
        f = QFormLayout(g)
        self.hist = {}
        for k, key, opts in HISTORY:
            self.hist[k] = self._combo(opts, 'dont_know' if opts is TRI_DK else 'not_assessed')
            f.addRow(self._lbl(key), self.hist[k])
        return g

    def _redflag_box(self):
        g = self._box('redFlags.title')
        v = QVBoxLayout(g)
        self.rf = {}
        for k, key in RED_FLAGS:
            c = QCheckBox()
            self._labels.append((c, key))
            c.toggled.connect(self._on_change)
            self.rf[k] = c
            v.addWidget(c)
        return g

    def _complaint_box(self):
        g = self._box('complaint.title')
        f = QFormLayout(g)
        self.c_knee = self._combo(KNEES, 'right')
        dur = QHBoxLayout()
        self.c_dur = self._spin(0, 99, 0)
        self.c_unit = self._combo(UNITS, 'months')
        dur.addWidget(self.c_dur)
        dur.addWidget(self.c_unit)
        self.c_stiff = self._spin(0, 480, 0, suffix=' min')
        f.addRow(self._lbl('complaint.affectedKnee'), self.c_knee)
        f.addRow(self._lbl('complaint.symptomDuration'), dur)
        f.addRow(self._lbl('complaint.morningStiffnessMin'), self.c_stiff)
        f.addRow(self._lbl('complaint.painScoreTitle'))
        self.pain = {}
        for k, key in [('pain_rest_left', 'complaint.painRestLeft'), ('pain_activity_left', 'complaint.painActivityLeft'),
                       ('pain_rest_right', 'complaint.painRestRight'), ('pain_activity_right', 'complaint.painActivityRight')]:
            self.pain[k] = self._spin(0, 10, 0, suffix=' / 10')
            f.addRow(self._lbl(key), self.pain[k])
        f.addRow(self._lbl('complaint.functionalTitle'))
        self.func = {}
        for k, key in FUNCTIONAL:
            self.func[k] = self._combo(TRI, 'not_assessed')
            f.addRow(self._lbl(key), self.func[k])
        return g

    def _exam_box(self):
        g = self._box('clinicalCheck.title')
        f = QFormLayout(g)
        self.exam = {}
        for k, key in EXAM:
            self.exam[k] = self._combo(TRI, 'not_assessed')
            f.addRow(self._lbl(key), self.exam[k])
        self.e_flex = self._spin(0, 160, 0, suffix='°')
        self.e_align = self._combo(ALIGN, 'not_assessed')
        self.e_gait = QTextEdit()
        self.e_gait.setMaximumHeight(60)
        self.e_knee = self._combo(SIDES, 'right')
        f.addRow(self._lbl('clinicalCheck.flexionRange'), self.e_flex)
        f.addRow(self._lbl('clinicalCheck.alignment'), self.e_align)
        f.addRow(self._lbl('clinicalCheck.gaitNote'), self.e_gait)
        f.addRow(self._lbl('sn.exam_extra.tested_knee'), self.e_knee)
        return g

    # ------------------------------------------------------------ behaviour
    def new_patient_id(self):
        self.p_id.setText(datetime.now().strftime('PT-%Y%m%d-%H%M%S'))
        self._on_change()

    def _bmi(self):
        h = self.p_h.value() / 100
        self.p_bmi.setText(f'{self.p_w.value() / (h * h):.1f} kg/m²' if h > 0 else '—')

    def _on_change(self, *_):
        red = [k for k, c in self.rf.items() if c.isChecked()] if hasattr(self, 'rf') else []
        if hasattr(self, 'banner'):
            self.banner.setVisible(bool(red))
            self.banner.setText('⚠ ' + tr('sn.q.red_flag_active', self.lang))
        self.changed.emit()

    def _emit_prior(self):
        from report_builder import prior_inputs
        self.apply_prior.emit(prior_inputs(self.get_state()))

    def retranslate(self, lang):
        self.lang = lang
        for w, key in self._labels:
            text = tr(key, lang)
            if isinstance(w, QGroupBox):
                w.setTitle(text)
            else:
                w.setText(text)
        for c in self._combos:
            c.retranslate(lang)
        self._on_change()

    def _load_worker(self):
        try:
            with open(SETTINGS, encoding='utf-8') as f:
                d = json.load(f)
            self.w_name.setText(d.get('name', ''))
            self.w_role.setText(d.get('role', ''))
            self.w_id.setText(d.get('id', ''))
            self.w_fac.setText(d.get('facility', ''))
        except (OSError, ValueError):
            pass

    def _save_worker(self):
        try:
            os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
            with open(SETTINGS, 'w', encoding='utf-8') as f:
                json.dump(self.get_state()['worker'], f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    def registered(self):
        return bool(self.p_name.text().strip()) and self.p_consent.isChecked()

    def get_state(self):
        h = self.p_h.value() / 100
        q = {k: c.value() for k, c in self.hist.items()}
        q.update({k: c.value() for k, c in self.func.items()})
        q.update({k: s.value() for k, s in self.pain.items()})
        q.update({'affected_knee': self.c_knee.value(), 'duration_value': self.c_dur.value(),
                  'duration_unit': self.c_unit.value(), 'morning_stiffness_min': self.c_stiff.value(),
                  'red_flags': {k: c.isChecked() for k, c in self.rf.items()}})
        return {
            'patient': {'id': self.p_id.text(), 'name': self.p_name.text().strip(), 'age': self.p_age.value(),
                        'sex': self.p_sex.value(), 'height_cm': int(self.p_h.value()), 'weight_kg': self.p_w.value(),
                        'bmi': round(self.p_w.value() / (h * h), 1) if h > 0 else 0, 'occupation': self.p_occ.value(),
                        'kneel_hours': self.p_kneel.value(), 'village': self.p_village.text(),
                        'block': self.p_block.text(), 'district': self.p_district.text(),
                        'consent': self.p_consent.isChecked()},
            'worker': {'name': self.w_name.text(), 'role': self.w_role.text(), 'id': self.w_id.text(),
                       'facility': self.w_fac.text()},
            'q': q,
            'exam': {**{k: c.value() for k, c in self.exam.items()}, 'flexion_deg': self.e_flex.value(),
                     'alignment': self.e_align.value(), 'gait_note': self.e_gait.toPlainText().strip(),
                     'tested_knee': self.e_knee.value()},
        }
