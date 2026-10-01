"""Session recording: synchronized CSVs + WAV + a small SQLite index.

Output folder: host/sessions/<name>_<YYYYmmdd_HHMMSS>/
  imu.csv, emg.csv, load.csv, events.csv, features.csv, cycles.csv,
  audio_filt.wav, audio_raw.wav (if streamed), meta.json
All time columns are device time in seconds (same clock for every sensor).
"""
import csv
import json
import os
import sqlite3
from datetime import datetime

import numpy as np

try:
    import scipy.io.wavfile as wavfile
except ImportError:
    wavfile = None

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sessions')


class SessionManager:
    def __init__(self, base_dir=BASE):
        self.base = base_dir
        os.makedirs(self.base, exist_ok=True)
        self.db_path = os.path.join(self.base, 'sessions.db')
        with sqlite3.connect(self.db_path) as c:
            c.execute('CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, name TEXT, '
                      'started TEXT, folder TEXT, clinical TEXT, summary TEXT)')
        self.recording = False
        self.folder = None
        self._files = {}
        self._writers = {}
        self._audio = {'filt': [], 'raw': []}
        self.meta = {}
        self.counts = {}

    def start(self, name, clinical=None, extra=None):
        safe = ''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in (name or 'session'))
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.folder = os.path.join(self.base, f'{safe}_{stamp}')
        os.makedirs(self.folder, exist_ok=True)
        heads = {
            'imu': ['t_s', 'knee_angle_deg', 'angular_vel_dps', 'phase', 'status_thigh', 'status_shank'],
            'emg': ['t_s', 'raw', 'baseline_removed', 'envelope'],
            'load': ['t_s', 'force_N', 'status'],
            'events': ['t_s', 'peak_dbfs', 'margin_db', 'duration_ms', 'knee_angle_deg', 'phase'],
            'features': None,
            'cycles': None,
        }
        for k, h in heads.items():
            f = open(os.path.join(self.folder, f'{k}.csv'), 'w', newline='')
            self._files[k] = f
            self._writers[k] = csv.writer(f)
            if h:
                self._writers[k].writerow(h)
        self._feat_header = None
        self._cyc_header = None
        self._audio = {'filt': [], 'raw': []}
        self.counts = {k: 0 for k in heads}
        self.meta = {'name': name, 'started': datetime.now().isoformat(),
                     'clinical': clinical or {}, 'synthetic_model': True, **(extra or {})}
        self.recording = True
        return self.folder

    def _w(self, k, row):
        if self.recording:
            self._writers[k].writerow(row)
            self.counts[k] += 1

    def log_imu(self, t, d):
        self._w('imu', [f'{t:.4f}', f"{d['knee_angle']:.2f}", f"{d['angular_vel']:.2f}",
                        d['phase'], d['status_thigh'], d['status_shank']])

    def log_emg(self, t0, d, fs=1000.0):
        if not self.recording:
            return
        for i in range(len(d['raw'])):
            self._w('emg', [f'{t0 + i / fs:.4f}', int(d['raw'][i]), int(d['removed'][i]), int(d['envelope'][i])])

    def log_load(self, t, d):
        self._w('load', [f'{t:.4f}', f"{d['force_N']:.3f}", d['status']])

    def log_event(self, t, d):
        self._w('events', [f'{t:.4f}', f"{d['peak_dbfs']:.2f}", f"{d['margin_db']:.2f}",
                           f"{d['duration_ms']:.2f}", f"{d['knee_angle']:.2f}", d['phase']])

    def log_features(self, t, d):
        if not self.recording:
            return
        if self._feat_header is None:
            self._feat_header = list(d.keys())
            self._writers['features'].writerow(['t_s'] + self._feat_header)
        self._w('features', [f'{t:.4f}'] + [f'{d.get(k, 0):.6g}' for k in self._feat_header])

    def log_cycle(self, t, d, host_prob=None, fused_prob=None):
        if not self.recording:
            return
        flat = {k: v for k, v in d.items() if k != 'model_input'}
        flat.update({f'in_{k}': v for k, v in d.get('model_input', {}).items()})
        flat['host_prob'] = host_prob if host_prob is not None else ''
        flat['fused_prob'] = fused_prob if fused_prob is not None else ''
        if self._cyc_header is None:
            self._cyc_header = list(flat.keys())
            self._writers['cycles'].writerow(['t_s'] + self._cyc_header)
        self._w('cycles', [f'{t:.4f}'] + [flat.get(k, '') for k in self._cyc_header])

    def log_audio(self, kind, samples):
        if self.recording:
            self._audio[kind].append(np.asarray(samples, dtype=np.float32))

    def stop(self, summary=None):
        if not self.recording:
            return None
        self.recording = False
        for f in self._files.values():
            f.close()
        self._files, self._writers = {}, {}
        if wavfile is not None:
            for kind, chunks in self._audio.items():
                if chunks:
                    a = np.clip(np.concatenate(chunks), -1, 1)
                    wavfile.write(os.path.join(self.folder, f'audio_{kind}.wav'), 16000,
                                  (a * 32767).astype(np.int16))
        self.meta['stopped'] = datetime.now().isoformat()
        self.meta['rows'] = self.counts
        self.meta['summary'] = summary or {}
        with open(os.path.join(self.folder, 'meta.json'), 'w') as f:
            json.dump(self.meta, f, indent=2, default=str)
        with sqlite3.connect(self.db_path) as c:
            c.execute('INSERT INTO sessions (name, started, folder, clinical, summary) VALUES (?,?,?,?,?)',
                      (self.meta.get('name'), self.meta.get('started'), self.folder,
                       json.dumps(self.meta.get('clinical')), json.dumps(summary or {}, default=str)))
        return self.folder
