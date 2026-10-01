"""Simulated SandhiNaad device — lets you run and demo the UI without hardware.

Choose port "SIMULATOR" in the UI. It speaks the exact binary protocol of the
firmware (same packets, CRC, commands, stream modes), so everything downstream
(parser, panels, recording, ML) is exercised end-to-end. All data is SYNTHETIC.
"""
import json
import os
import struct
import threading
import time
from collections import deque

import numpy as np

import protocol as P
from features import block_features

FS = 16000
BLOCK = 512
BLOCK_S = BLOCK / FS


def _load_model_info():
    for c in (os.path.join(os.path.dirname(__file__), '..', 'ml', 'models', 'model_info.json'),):
        if os.path.exists(c):
            with open(c) as f:
                return json.load(f)
    return None


class SimulatedSerial:
    """Duck-types the parts of pyserial.Serial that SerialLink uses."""

    def __init__(self, seed=1):
        self.rng = np.random.default_rng(seed)
        self.is_open = True
        self._out = bytearray()
        self._lock = threading.Lock()
        self._cmd_buf = b''
        self.seq = 0
        self.streaming = False
        self.mode = 1
        self.thresh_db = 18.0
        self.t0 = time.monotonic()
        self.sim_t = 0.0
        self.angle_zero = 0.0
        self.phase = 0
        self.prev_angle = None
        self.vel_f = 0.0
        self.noise_hist = deque(maxlen=30)
        self.last_event_t = -1.0
        self.cycle_start = 0.0
        self.cycle = self._new_cycle()
        self.cyc_sum = np.zeros(17)
        self.cyc_n = 0
        self.imu_acc = 0.0
        self.load_acc = 0.0
        self.status_acc = 0.0
        self.emg_state = [0.0, 0.0, 0.0]   # hp_y, hp_x, env
        self.load_offset = 0.0
        self.oa_like = self.rng.random() < 0.5
        info = _load_model_info()
        self.model = None
        if info:
            self.model = (np.array(info['means']), np.array(info['stds']),
                          np.array(info['coefficients']), info['intercept'])
        self._running = True
        self._log('SandhiNaad SIMULATOR booting (synthetic data)')
        self._log('SELFTEST model: simulator uses ml/models/model_info.json coefficients')
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ---- pyserial-like API ------------------------------------------------
    @property
    def in_waiting(self):
        with self._lock:
            return len(self._out)

    def read(self, n):
        with self._lock:
            d = bytes(self._out[:n])
            del self._out[:n]
            return d

    def write(self, data):
        self._cmd_buf += data
        while b'\n' in self._cmd_buf:
            line, self._cmd_buf = self._cmd_buf.split(b'\n', 1)
            self._handle(line.decode(errors='ignore').strip())
        return len(data)

    def close(self):
        self._running = False
        self.is_open = False

    # ---- helpers ------------------------------------------------------------
    def _send(self, t, ts_us, payload):
        pkt = P.encode_packet(t, self.seq, int(ts_us), payload)
        self.seq = (self.seq + 1) & 0xFFFF
        with self._lock:
            if len(self._out) < 2_000_000:
                self._out.extend(pkt)

    def _now_us(self):
        return int(self.sim_t * 1e6)

    def _log(self, msg):
        self._send(P.PKT_LOG, self._now_us(), msg.encode() + b'\0')

    def _handle(self, cmd):
        up = cmd.upper()
        ok = True
        if up == 'START':
            self.streaming = True
        elif up == 'STOP':
            self.streaming = False
        elif up.startswith('MODE '):
            m = {'FULL': 0, 'DEFAULT': 1, 'FEATURES': 2}.get(up[5:].strip())
            ok = m is not None
            if ok:
                self.mode = m
        elif up == 'CAL_ZERO':
            self.angle_zero = self._raw_angle(self.sim_t)
        elif up == 'TARE':
            self.load_offset = self._raw_force(self.sim_t)
            self._log('TARE done')
        elif up.startswith('SCALE '):
            self._log('SCALE done (simulated)')
        elif up.startswith('THRESH '):
            try:
                self.thresh_db = float(up[7:])
                self._log(f'Event threshold = {self.thresh_db:.1f} dB')
            except ValueError:
                ok = False
        elif up in ('PING', 'STATUS', 'SELFTEST', 'VERSION') or up.startswith('RATE'):
            if up == 'STATUS':
                self._status()
            if up == 'SELFTEST':
                self._log('SELFTEST model: PASS (simulator)')
        else:
            ok = False
        ack = (cmd if ok else 'ERR ' + cmd).encode() + b'\0'
        self._send(P.PKT_ACK, self._now_us(), ack)

    @staticmethod
    def _new_cycle():
        return {'events': 0, 'flex': 0.0, 'ext': 0.0, 'amin': 1e9, 'amax': -1e9}

    def _raw_angle(self, t):
        period = 3.4 if self.oa_like else 3.0
        rom = 92.0 if self.oa_like else 108.0
        return 5 + rom / 2 * (1 - np.cos(2 * np.pi * t / period))

    def _raw_force(self, t):
        return 250 + 120 * np.sin(2 * np.pi * t / 3.2)

    def _status(self):
        st = struct.pack('<7B4IBf', 0, 1, 0, 0, 0, 0, self.mode,
                         180000, 0, 55000, 4200, 0,
                         float(20 * np.log10(np.median(self.noise_hist) + 1e-9)) if self.noise_hist else -90.0)
        self._send(P.PKT_STATUS, self._now_us(), st)

    # ---- main generator loop -------------------------------------------------
    def _run(self):
        while self._running:
            target = time.monotonic() - self.t0
            if self.sim_t + BLOCK_S > target:
                time.sleep(0.004)
                continue
            self._block()
            self.sim_t += BLOCK_S

    def _block(self):
        t0 = self.sim_t
        ts0 = int(t0 * 1e6)
        rng = self.rng

        # status runs even when not streaming
        self.status_acc += BLOCK_S
        if self.status_acc >= 0.5:
            self.status_acc = 0
            self._status()
        if not self.streaming:
            return

        # ---- IMU @100 Hz (+ phase/cycle logic identical to firmware) ----
        self.imu_acc += BLOCK_S
        while self.imu_acc >= 0.01:
            self.imu_acc -= 0.01
            t = t0 + (BLOCK_S - self.imu_acc)
            ang = abs(self._raw_angle(t) - self.angle_zero) + rng.normal(0, 0.3)
            vel = 0.0 if self.prev_angle is None else (ang - self.prev_angle) / 0.01
            self.prev_angle = ang
            self.vel_f = 0.8 * self.vel_f + 0.2 * vel
            old = self.phase
            v = self.vel_f
            if v > 5 or (old == 1 and v > 3):
                self.phase = 1
            elif v < -5 or (old == 2 and v < -3):
                self.phase = 2
            else:
                self.phase = 0
            if old != 1 and self.phase == 1:
                self._finish_cycle(t)
            c = self.cycle
            if self.phase == 1:
                c['flex'] = max(c['flex'], v)
            if self.phase == 2:
                c['ext'] = min(c['ext'], v)
            c['amin'] = min(c['amin'], ang)
            c['amax'] = max(c['amax'], ang)
            imu = struct.pack('<10f7B', 1, 0, 0, 0, np.cos(np.radians(ang) / 2), np.sin(np.radians(ang) / 2), 0, 0,
                              ang, v, self.phase, 3, 3, 3, 3, 0, 0)
            self._send(P.PKT_IMU, int(t * 1e6), imu)

        # ---- EMG @1 kHz: quadriceps burst during extension + artifact source ----
        n_emg = int(round(BLOCK_S * 1000))
        act = 1.0 if self.phase == 2 else 0.25
        raw = 2048 + rng.normal(0, 60 * act, n_emg) + 30 * np.sin(2 * np.pi * 7 * (t0 + np.arange(n_emg) / 1000))
        raw = np.clip(raw, 0, 4095)
        hp_y, hp_x, env = self.emg_state
        a_hp = np.exp(-2 * np.pi * 20 / 1000)
        a_lp = 1 - np.exp(-2 * np.pi * 5 / 1000)
        rec = np.zeros(n_emg, dtype=P._EMG_DT)
        for i, x in enumerate(raw):
            hp_y = a_hp * (hp_y + x - hp_x)
            hp_x = x
            env = (1 - a_lp) * env + a_lp * abs(hp_y)
            rec[i] = (int(x), int(np.clip(hp_y, -32768, 32767)), int(min(env, 65535)))
        self.emg_state = [hp_y, hp_x, env]
        self._send(P.PKT_EMG, ts0, rec.tobytes())
        emg_ref = np.interp(np.linspace(0, n_emg - 1, BLOCK), np.arange(n_emg), rec['removed'].astype(float))

        # ---- audio block ----
        tt = t0 + np.arange(BLOCK) / FS
        x = rng.normal(0, 0.0012, BLOCK)
        x += 0.00004 * emg_ref                                   # EMG-correlated artifact (for NLMS demo)
        click_p = (0.16 if self.oa_like else 0.06) if self.phase == 1 else 0.01
        if rng.random() < click_p:
            k = rng.integers(40, BLOCK - 120)
            n = np.arange(BLOCK - k)
            fc = rng.uniform(900, 2600)
            x[k:] += rng.uniform(0.03, 0.15) * np.exp(-n / 40) * np.sin(2 * np.pi * fc * n / FS)
        x = np.clip(x, -1, 1)

        rms = float(np.sqrt(np.mean(x ** 2)))
        self.noise_hist.append(rms)
        floor = max(float(np.median(self.noise_hist)), 1e-7)
        floor_db = 20 * np.log10(floor)
        peak_i = int(np.argmax(np.abs(x)))
        peak = abs(x[peak_i])
        thr = floor * 10 ** (self.thresh_db / 20)
        ev_t = t0 + peak_i / FS
        if len(self.noise_hist) >= 10 and peak > thr and ev_t - self.last_event_t > 0.05:
            self.last_event_t = ev_t
            self.cycle['events'] += 1
            above = np.where(np.abs(x) > 0.5 * thr)[0]
            dur = (above[-1] - above[0] + 1) * 1000 / FS if len(above) else 0.0
            snip = np.zeros(256)
            lo = max(0, peak_i - 128)
            seg = x[lo:peak_i + 128]
            snip[128 - (peak_i - lo):128 - (peak_i - lo) + len(seg)] = seg
            pdb = 20 * np.log10(peak + 1e-9)
            payload = struct.pack('<Q4fB', int(ev_t * 1e6), pdb, pdb - floor_db, dur,
                                  self.prev_angle or 0.0, self.phase)
            payload += (np.clip(snip, -1, 1) * 32767).astype('<i2').tobytes()
            self._send(P.PKT_EVENT, int(ev_t * 1e6), payload)

        feats = block_features(x, FS, floor_db)
        vec = np.array([feats[k] for k in P.ACOUSTIC_FEATURE_NAMES])
        self.cyc_sum += vec
        self.cyc_n += 1
        self._send(P.PKT_FEAT_BLOCK, ts0, struct.pack('<17f', *vec))

        # envelope (1 kHz) and display streams
        env_a = np.zeros(BLOCK)
        e = getattr(self, '_env', 0.0)
        a_env = 1 - np.exp(-2 * np.pi * 50 / FS)
        for i, v in enumerate(np.abs(x)):
            e += a_env * (v - e)
            env_a[i] = e
        self._env = e
        env_d = np.clip(env_a[15::16] * 65535, 0, 65535).astype('<u2')
        self._send(P.PKT_ENVELOPE, ts0, env_d.tobytes())
        x16 = (x * 32767).astype('<i2')
        if self.mode == 1:
            mm = np.stack([x16.reshape(-1, 16).min(1), x16.reshape(-1, 16).max(1)], 1).astype('<i2')
            self._send(P.PKT_AUDIO_MINMAX, ts0, mm.tobytes())
        if self.mode in (0, 1):
            self._send(P.PKT_AUDIO_FILT, ts0, x16.tobytes())
        if self.mode == 0:
            self._send(P.PKT_AUDIO_RAW, ts0, x16.tobytes())

        # ---- load @80 Hz ----
        self.load_acc += BLOCK_S
        while self.load_acc >= 1 / 80:
            self.load_acc -= 1 / 80
            t = t0 + BLOCK_S - self.load_acc
            f = self._raw_force(t) - self.load_offset + rng.normal(0, 2)
            self._send(P.PKT_LOAD, int(t * 1e6), struct.pack('<fB', f, 0))

    def _finish_cycle(self, t):
        c = self.cycle
        dur = t - self.cycle_start
        if dur > 0.5 and c['amax'] > c['amin'] and self.cyc_n > 0:
            mi = list(self.cyc_sum / self.cyc_n) + [c['events'], c['amax'] - c['amin'],
                                                     c['flex'], abs(c['ext']), dur]
            prob = 0.5
            if self.model:
                m, s, w, b = self.model
                z = b + np.dot(w, np.clip((np.array(mi) - m) / (s + 1e-8), -3, 3))
                prob = 1 / (1 + np.exp(-z))
            head = [c['amax'] - c['amin'], c['flex'], c['ext'], dur, c['events'], prob,
                    mi[0], mi[3], mi[9], mi[11], mi[10]]
            self._send(P.PKT_FEAT_CYCLE, int(t * 1e6), struct.pack('<11f22f', *head, *mi))
            self.cyc_sum[:] = 0
            self.cyc_n = 0
        self.cycle = self._new_cycle()
        self.cycle_start = t
