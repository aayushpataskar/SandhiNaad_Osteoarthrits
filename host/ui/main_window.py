import numpy as np
import json
import os

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QTabWidget, QSplitter, QMessageBox, QGroupBox, QComboBox, QFrame)
from PySide6.QtCore import QTimer, Qt

import protocol as P
from serial_link import SerialLink, SIMULATOR_PORT
from session import SessionManager
from model import OAScreeningModel, _risk_tier
from dsp_ref import NoiseCanceller
from ui.toolbar import Toolbar
from ui.status_strip import StatusStrip
from ui.acoustic_panel import AcousticPanel
from ui.kinematic_panel import KinematicPanel
from ui.emg_panel import EMGPanel
from ui.load_panel import LoadPanel
from ui.ml_panel import MLPanel
from ui.features_panel import FeaturesPanel
from ui.clinical_form import ClinicalForm
from ui.localization_panel import LocalizationPanel
from ui.flags_panel import FlagsPanel
from ui.questionnaire_panel import QuestionnairePanel
from ui.report_panel import ReportPanel
from i18n import tr, LANGS
from report_builder import build_context
from reports.render import load_i18n


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('SandhiNaad — Knee Joint-Sound Screening (prototype)')
        self.resize(1500, 950)

        self.link = SerialLink()
        self.sessions = SessionManager()
        self.model = OAScreeningModel()
        self.nc = NoiseCanceller()
        self.nc_on = False
        self.clinical = {}
        self.t_origin = None
        self.last_ts = 0
        self.last_status = {}
        self.last_crc = 0
        self.n_cycles = 0
        self.sim_fill = False
        self.sim_load_t = None
        self.sim_rng = np.random.default_rng()
        self.lang = 'en'
        self.fw = ''
        self._reset_session_stats()

        self._build_ui()
        if not self.model.loaded:
            self.log.add_flag('WARNING: ml/models/*.joblib not found — host re-check/fusion disabled')

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        c = QWidget()
        self.setCentralWidget(c)
        v = QVBoxLayout(c)
        v.setContentsMargins(4, 4, 4, 4)

        head = QFrame()
        head.setStyleSheet('QFrame { background:#181825; border:1px solid #313244; border-radius:6px; }'
                           'QLabel { border:none; }')
        hl = QHBoxLayout(head)
        hl.setContentsMargins(10, 4, 10, 4)
        title = QLabel('<span style="font-size:14pt; font-weight:bold; color:#89b4fa;">SandhiNaad</span>'
                       '<span style="color:#a6adc8;">  ·  সন্ধিনাদ  ·  knee joint-sound OA screening</span>')
        self.patient_chip = QLabel('')
        self.patient_chip.setStyleSheet('background:#313244; padding:3px 10px; border-radius:10px;')
        self.lbl_lang = QLabel()
        self.lang_combo = QComboBox()
        for code, name in LANGS.items():
            self.lang_combo.addItem(name, code)
        self.lang_combo.currentIndexChanged.connect(lambda _: self._set_lang(self.lang_combo.currentData()))
        hl.addWidget(title)
        hl.addStretch()
        hl.addWidget(self.patient_chip)
        hl.addSpacing(16)
        hl.addWidget(self.lbl_lang)
        hl.addWidget(self.lang_combo)
        v.addWidget(head)

        self.toolbar = Toolbar()
        self.toolbar.connect_requested.connect(self._connect)
        self.toolbar.disconnect_requested.connect(self._disconnect)
        self.toolbar.command_requested.connect(self._command)
        self.toolbar.record_toggled.connect(self._record)
        self.toolbar.nc_toggled.connect(self._nc)
        self.toolbar.sim_toggled.connect(self._sim)
        self.toolbar.chk_sim.setVisible(False)     # simulated fill-in disabled: UI shows installed sensors only
        v.addWidget(self.toolbar)
        self.status = StatusStrip()
        v.addWidget(self.status)

        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)

        # Live tab
        self.acoustic = AcousticPanel()
        self.kin = KinematicPanel()
        self.emg = EMGPanel()
        self.load = LoadPanel()
        right = QSplitter(Qt.Vertical)
        for w in (self.kin, self.emg, self.load):
            right.addWidget(w)
        self.load.setVisible(False)
        live = QSplitter(Qt.Horizontal)
        live.addWidget(self.acoustic)
        live.addWidget(right)
        live.setSizes([900, 600])
        self.tabs.addTab(live, 'Live signals')
        self.tab_live = live

        # Screening tab
        self.ml = MLPanel()
        self.features = FeaturesPanel()
        self.form = ClinicalForm()
        self.form.changed.connect(self._clinical_changed)
        side = QSplitter(Qt.Vertical)
        g = QGroupBox('Patient / clinical prior')
        QVBoxLayout(g).addWidget(self.form)
        side.addWidget(g)
        side.addWidget(self.features)
        scr = QSplitter(Qt.Horizontal)
        scr.addWidget(self.ml)
        scr.addWidget(side)
        scr.setSizes([900, 500])
        self.tabs.addTab(scr, 'Screening (ML)')
        self.tab_screening = scr

        # Patient & questionnaire tab (bilingual, ported from the OA-NER web app)
        self.quest = QuestionnairePanel()
        self.quest.changed.connect(self._update_patient_chip)
        self.quest.apply_prior.connect(self._apply_q_prior)
        self.tabs.addTab(self.quest, 'Patient & Questionnaire')

        # Clinical report tab (multilingual PDF)
        self.report = ReportPanel(self._report_context)
        self.report.live_knee = self._live_knee
        self.report.on_saved = self._after_knee_saved
        self.tabs.addTab(self.report, 'Clinical Report (PDF)')
        self.tabs.currentChanged.connect(self._tab_changed)

        self.loc = LocalizationPanel()
        self.tabs.addTab(self.loc, 'Localization (SIMULATED)')
        self.log = FlagsPanel()
        self.tabs.addTab(self.log, 'Log')
        self._set_lang('en')

        foot = QLabel('Screening-aid prototype — not a diagnostic device. ML models are trained on SYNTHETIC data.')
        foot.setAlignment(Qt.AlignCenter)
        foot.setStyleSheet('color:#7f849c; font-style:italic;')
        v.addWidget(foot)

    # ------------------------------------------------------------- actions
    def _connect(self, port, baud):
        if not port:
            self.toolbar.btn_connect.setChecked(False)
            return
        self.link.port, self.link.baud = port, baud
        try:
            self.link.connect()
        except Exception as e:
            QMessageBox.critical(self, 'Connection failed',
                                 f'Could not open {port}:\n{e}\n\nClose Arduino Serial Monitor / other apps '
                                 'using the port, check the USB cable, and pick the right COM port.')
            self.toolbar.btn_connect.blockSignals(True)
            self.toolbar.btn_connect.setChecked(False)
            self.toolbar.btn_connect.setText('Connect')
            self.toolbar.btn_connect.blockSignals(False)
            return
        self.toolbar.set_connected(True)
        self._reset_views()
        self.log.add_flag(f'Connected to {port} @ {baud}')
        # Opening the COM port resets most ESP32 boards; wait for boot, then start streaming.
        QTimer.singleShot(300 if port == SIMULATOR_PORT else 2500, self._start_stream)

    def _start_stream(self):
        if not self.link.connected:
            return
        self._command(f'MODE {self.toolbar.mode_combo.currentText()}')
        self._command(f'THRESH {self.toolbar.thresh.value():.1f}')
        self._command('START')
        self._command('STATUS')

    def _disconnect(self):
        if self.sessions.recording:
            self.toolbar.btn_rec.setChecked(False)
        self._command('STOP')
        self.link.disconnect()
        self.toolbar.set_connected(False)
        self.log.add_flag('Disconnected')

    def _command(self, cmd):
        if self.link.connected:
            self.link.send_command(cmd)
            if cmd.startswith('THRESH'):
                try:
                    self.acoustic.thresh_db = float(cmd.split()[1])
                except (IndexError, ValueError):
                    pass

    def _record(self, on, name):
        if on:
            folder = self.sessions.start(name, self.clinical,
                                         extra={'port': self.link.port, 'mode': self.toolbar.mode_combo.currentText(),
                                                'questionnaire': self.quest.get_state(),
                                                'simulated_sensors': list(self._sim_keys())})
            self.log.add_flag(f'Recording → {folder}')
        else:
            folder = self.sessions.stop({'cycles_seen': self.n_cycles})
            if folder:
                self.log.add_flag(f'Saved session: {folder}')
                QMessageBox.information(self, 'Session saved', f'Saved CSV + WAV files to:\n{folder}')

    def _nc(self, on):
        self.nc_on = on
        self.nc.reset()
        self.acoustic.nc_on = on

    def _sim(self, on):
        self.sim_fill = on
        self.sim_load_t = None
        self.load.set_simulated(False)
        self.log.add_flag('Demo fill-in ON: missing mic #2 / load cell shown as SIMULATED (blue)' if on
                          else 'Demo fill-in OFF')
        if self.last_status:
            self.status.update_status(self.last_status, self._sim_keys())

    def _sim_keys(self):
        if not self.sim_fill:
            return ()
        return tuple(k for k in ('mic2_status', 'load_status') if self.last_status.get(k, 1) != 0)

    def _sim_load(self):
        """80 Hz synthetic force that follows the knee angle (more flexion -> less load)."""
        if not (self.sim_fill and self.link.connected and self.last_status.get('load_status', 1) != 0):
            self.load.set_simulated(False) if self.load.simulated else None
            return
        now = self.kin.now
        if now <= 0:
            return
        if self.sim_load_t is None or self.sim_load_t > now:
            self.sim_load_t = now
            self.load.set_simulated(True)
            return
        n = int((now - self.sim_load_t) * 80)
        for i in range(n):
            t = self.sim_load_t + (i + 1) / 80.0
            f = 320.0 - 1.6 * self.kin.angle + self.sim_rng.normal(0, 4)
            self.load.add(t, f)
            self.sessions.log_load(t, {'force_N': f, 'status': 3})
        self.sim_load_t += n / 80.0

    def _clinical_changed(self, d):
        self.clinical = d
        if d and self.model.prior_model is not None:
            p = self.model.predict_prior(d)
            self.log.add_flag(f'Clinical prior applied: prior-only p(OA) = {p:.3f}')

    def _reset_views(self):
        self.t_origin = None
        for p in (self.acoustic, self.kin, self.emg, self.load, self.ml):
            p.clear()
        self._reset_session_stats()

    # ------------------------------------------------ report / questionnaire
    def _reset_session_stats(self):
        self.sess_stats = {'probs': [], 'contribs': [], 'clicks': 0, 'duration_s': 0.0, 'low_quality': 0,
                           'crc_start': self.link.stats.get('crc_errors', 0) if hasattr(self, 'link') else 0}
        self._new_window()

    def _live_knee(self):
        st = self.sess_stats
        side = self.quest.get_state()['exam']['tested_knee']
        return {'side': side, 'probs': list(st['probs']), 'contribs': list(st['contribs']),
                'clicks': st['clicks'], 'duration_s': st['duration_s'], 'low_quality': st['low_quality'],
                'crc_errors': self.link.stats.get('crc_errors', 0) - st['crc_start']}

    def _after_knee_saved(self, side):
        self.log.add_flag(f'Result saved for {side} knee ({len(self.report.saved[side]["probs"])} cycles). '
                          'Session statistics reset for the next knee.')
        self.ml.clear()
        self._reset_session_stats()

    def _model_info(self):
        info = {'name': 'SandhiNaad acoustic–kinematic LR', 'version': '', 'synthetic': True}
        try:
            with open(os.path.join(os.path.dirname(__file__), '..', '..', 'ml', 'models', 'model_info.json')) as f:
                mi = json.load(f)
            cal = mi.get('calibration', {})
            info['version'] = (f"(Platt-calibrated, prevalence {cal['prevalence']:.0%})" if cal else '')
            info['synthetic'] = mi.get('synthetic', True)
        except (OSError, ValueError, KeyError):
            pass
        if self.fw:
            info['version'] = f"{info['version']} · firmware {self.fw}".strip(' ·')
        return info

    def _report_context(self, lang, knees):
        if not self.quest.registered():
            return None, tr('sn.report.need_patient', self.lang)
        state = self.quest.get_state()
        sim = self.link.port == SIMULATOR_PORT
        device = {'device_id': 'SIMULATOR' if sim else f"SandhiNaad ESP32{(' FW ' + self.fw) if self.fw else ''}",
                  'fw': self.fw, 'data_source': 'simulated' if sim else 'hardware'}
        prior = self.model.predict_prior(self.clinical) if self.clinical and self.model.prior_model is not None else None
        ctx = build_context(state, knees, device, lang, load_i18n(lang), clinical_prior=prior,
                            model_info=self._model_info())
        n = min((len(k['probs']) for k in knees), default=0)
        msg = tr('sn.report.few_cycles', self.lang, n=n) if n < 3 else ''
        return ctx, msg

    def _apply_q_prior(self, d):
        if not d:
            QMessageBox.information(self, 'Prior', tr('patient.estimatedAge', self.lang) + ' ?')
            return
        f = self.form           # mirror the values in the Screening tab's clinical form
        f.age.setValue(int(d['age']))
        f.sex.setCurrentIndex(1 if d['sex'] == 1.0 else 0)
        f.bmi.setValue(d['bmi'])
        f.squat.setChecked(bool(d['occupation_squat']))
        f.koos_pain.setValue(int(round(d['koos_pain'])))
        f.koos_func.setValue(int(round(d['koos_function'])))
        f.applied = d
        f.state.setText(tr('sn.q.prior_applied', self.lang,
                           p=f"{self.model.predict_prior(d):.3f}" if self.model.prior_model is not None else '—'))
        self._clinical_changed(d)

    def _update_patient_chip(self):
        pt = self.quest.get_state()['patient']
        if pt['name']:
            self.patient_chip.setText(f"{tr('sn.patient_chip', self.lang)}: {pt['name']}  ·  {pt['id']}")
        else:
            self.patient_chip.setText(tr('sn.no_patient', self.lang))

    def _tab_changed(self, _):
        if self.tabs.currentWidget() is self.report:
            self.report.refresh()

    def _set_lang(self, code):
        self.lang = code
        i = self.lang_combo.findData(code)
        if i >= 0 and self.lang_combo.currentIndex() != i:
            self.lang_combo.blockSignals(True)
            self.lang_combo.setCurrentIndex(i)
            self.lang_combo.blockSignals(False)
        self.lbl_lang.setText(tr('sn.language', code) + ':')
        for w, key in ((self.tab_live, 'live'), (self.tab_screening, 'screening'), (self.quest, 'patient'),
                       (self.report, 'report'), (self.loc, 'localization'), (self.log, 'log')):
            self.tabs.setTabText(self.tabs.indexOf(w), tr('sn.tabs.' + key, code))
        self.quest.retranslate(code)
        self.report.retranslate(code)
        self.ml.set_lang(code)
        self._update_patient_chip()

    # ----------------------------------------------------------- data flow
    def _t(self, ts):
        if self.t_origin is None or ts + 2_000_000 < self.last_ts:   # first packet or device reboot
            if self.t_origin is not None:
                self.log.add_flag('Device clock restarted (board reset) — views cleared')
                self._reset_views()
            self.t_origin = ts
        self.last_ts = ts
        return (ts - self.t_origin) / 1e6

    def _tick(self):
        for ptype, seq, ts, d in self.link.get_packets():
            if not d:
                continue
            try:
                self._dispatch(ptype, ts, d)
            except Exception as e:     # never let one bad packet kill the UI
                self.log.add_flag(f'Error handling {P.PKT_NAMES.get(ptype, ptype)}: {e}')

        self._sim_load()
        s = self.link.stats
        self.toolbar.update_stats(s)
        if s['crc_errors'] > self.last_crc:
            self.log.add_flag(f"CRC errors: {s['crc_errors']} (link noise or baud mismatch)")
            self.last_crc = s['crc_errors']
        if self.link.last_error:
            self.log.add_flag(f'Serial error: {self.link.last_error}')
            self.link.last_error = ''

        cur = self.tabs.currentWidget()
        if cur is self.tab_live:
            self.acoustic.update_plots()
            self.kin.update_plots()
            self.emg.update_plots()
            self.load.update_plots()
        elif cur is self.tab_screening:
            self.features.refresh()

    def _dispatch(self, ptype, ts, d):
        rec = self.sessions
        if ptype in (P.PKT_LOG, P.PKT_ACK):
            self.log.add_flag(('ACK ' if ptype == P.PKT_ACK else 'DEV ') + d['msg'])
            if 'FW ' in d['msg'] and 'booting' in d['msg']:
                self.fw = d['msg'].split('FW ', 1)[1].split()[0]
            return
        if ptype == P.PKT_STATUS:
            for ch in self.status.update_status(d):
                self.log.add_flag(ch)
            self.last_status = d
            self.load.setVisible(self.status.installed('load'))   # hide panel if no load cell
            if 'noise_floor_dbfs' in d:
                self.acoustic.set_floor(d['noise_floor_dbfs'])
            return

        t = self._t(ts)
        if ptype == P.PKT_IMU:
            self.kin.add_data(t, d)
            rec.log_imu(t, d)
            self.win['imu'].append((t, d['knee_angle'], d['angular_vel']))
        elif ptype == P.PKT_AUDIO_MINMAX:
            self.acoustic.add_minmax(t, d['min'], d['max'])
        elif ptype == P.PKT_AUDIO_RAW:
            self.acoustic.add_raw(t, d['samples'])
            rec.log_audio('raw', d['samples'])
        elif ptype == P.PKT_AUDIO_FILT:
            x = d['samples']
            if self.nc_on:
                emg_ok = (self.last_status.get('emg_status', 1) == 0) and not self.emg.saturated
                y = self.nc.process(x, self.emg.recent_removed(33), emg_ok)
                self.acoustic.nc_db, self.acoustic.nc_bypassed = self.nc.last_db, self.nc.bypassed
                self.acoustic.add_filtered(t, y, before=x)
            else:
                self.acoustic.add_filtered(t, x)
            rec.log_audio('filt', x)
        elif ptype == P.PKT_ENVELOPE:
            self.acoustic.add_envelope(t, d['envelope'])
        elif ptype == P.PKT_EMG:
            self.emg.add(t, d)
            rec.log_emg(t, d)
        elif ptype == P.PKT_LOAD:
            self.load.add(t, d['force_N'])
            rec.log_load(t, d)
        elif ptype == P.PKT_EVENT:
            te = self._t(d['event_time_us'])
            self.acoustic.add_event(te, d)
            self.kin.add_event(te, d['knee_angle'])
            rec.log_event(te, d)
            self.win['events'] += 1
        elif ptype == P.PKT_FEAT_BLOCK:
            self.features.update_features(d)
            self.acoustic.set_floor(d['floor_dbfs'])
            rec.log_features(t, d)
            self.win['blocks'].append([d[k] for k in P.ACOUSTIC_FEATURE_NAMES])
            if self.win['t0'] is None:
                self.win['t0'] = t
            elif t - self.win['t0'] >= self.WINDOW_S:
                self._score_window(t)
        elif ptype == P.PKT_FEAT_CYCLE:
            self._on_cycle(t, d)

    # A scored cycle must be a real flex-extend movement, like the training data
    # (ROM ~60-150 deg, ~1.5-6 s). Twitches, pauses and half-bends are not scored.
    CYCLE_ROM = (30.0, 170.0)
    CYCLE_DUR = (1.0, 10.0)

    # ---- time-window fallback -------------------------------------------------
    # If no complete flex-extend cycle is detected (IMU barely moving, pauses...),
    # the model still scores the REAL measured data every WINDOW_S seconds:
    # acoustic features averaged over the window + ROM / velocities / clicks from
    # the same window. Shown as hollow (low-quality) dots.
    WINDOW_S = 5.0

    def _new_window(self, t=None):
        self.win = {'t0': t, 'blocks': [], 'imu': [], 'events': 0}

    def _score_window(self, t):
        w = self.win
        self._new_window(t)
        if len(w['blocks']) < 20 or not self.model.loaded:
            return
        feats = dict(zip(P.ACOUSTIC_FEATURE_NAMES, np.mean(np.array(w['blocks']), axis=0).tolist()))
        ang = np.array([a for _, a, _ in w['imu']]) if w['imu'] else np.zeros(1)
        vel = np.array([v for _, _, v in w['imu']]) if w['imu'] else np.zeros(1)
        feats.update({'events_per_cycle': float(w['events']), 'rom': float(ang.max() - ang.min()),
                      'peak_flex_vel': float(max(vel.max(), 0.0)), 'peak_ext_vel': float(abs(min(vel.min(), 0.0))),
                      'cycle_duration': float(t - w['t0'])})
        p, _, _ = self.model.predict_acoustic(feats)
        d = {'rom': feats['rom'], 'peak_flex_vel': feats['peak_flex_vel'], 'peak_ext_vel': -feats['peak_ext_vel'],
             'duration_s': feats['cycle_duration'], 'num_events': float(w['events']), 'oa_probability': p,
             'model_input': feats, 'window': True}
        self._on_cycle(t, d)

    def _on_cycle(self, t, d):
        if not d.get('window'):
            self._new_window(t)          # a real cycle arrived: restart the fallback window
        self.kin.add_cycle(t)
        rom, dur = d.get('rom', 0.0), d.get('duration_s', 0.0)
        reason = None
        if rom < self.CYCLE_ROM[0]:
            reason = f'range of motion only {rom:.0f}° (need ≥ {self.CYCLE_ROM[0]:.0f}°)'
        elif rom > self.CYCLE_ROM[1]:
            reason = f'range of motion {rom:.0f}° is implausible (IMU not calibrated?)'
        elif dur < self.CYCLE_DUR[0]:
            reason = f'movement too fast ({dur:.1f} s)'
        elif dur > self.CYCLE_DUR[1]:
            reason = f'movement took {dur:.1f} s (pause/hold, not one bend)'
        # Every movement is scored; movements outside the protocol are flagged as
        # low-quality (hollow dots, lower confidence and QC remark in the report).
        if d.get('window'):
            reason = 'no full bend detected — scored over a 5 s window'
        low_q = bool(reason)
        if low_q:
            self.log.add_flag(f'Low-quality cycle (still scored): {reason}')
        self.n_cycles += 1
        dev_p = float(d['oa_probability'])
        host_p, fused_p, contribs = None, None, []
        tier = _risk_tier(dev_p)
        feats = d.get('model_input')
        if feats and self.model.loaded:
            host_p, tier, contribs = self.model.predict_acoustic(feats)
            if self.clinical:
                fused_p, tier, _ = self.model.predict_fused(feats, self.clinical)
        self.ml.update_cycle(dev_p, host_p, fused_p, tier, contribs, d, low_quality=reason)
        self.sessions.log_cycle(t, d, host_p, fused_p)
        # per-knee session statistics for the clinical report (acoustic model only;
        # the clinical prior is reported separately)
        st = self.sess_stats
        st['probs'].append(host_p if host_p is not None else dev_p)
        z = getattr(self.model, 'last_z', {}) or {}
        st['contribs'] = [(n, c, z.get(n, 0.0)) for n, c in contribs]
        st['clicks'] += int(d.get('num_events', 0))
        st['low_quality'] = st.get('low_quality', 0) + (1 if low_q else 0)
        st['duration_s'] += float(d.get('duration_s', 0.0))
        msg = f"Cycle {self.n_cycles}: ROM {d['rom']:.0f}°, {int(d['num_events'])} clicks, device p={dev_p:.3f}"
        if host_p is not None:
            msg += f', host p={host_p:.3f} (Δ={abs(host_p - dev_p):.1e})'
        self.log.add_flag(msg)

    def closeEvent(self, e):
        if self.sessions.recording:
            self.sessions.stop({'cycles_seen': self.n_cycles})
        self.link.disconnect()
        super().closeEvent(e)
