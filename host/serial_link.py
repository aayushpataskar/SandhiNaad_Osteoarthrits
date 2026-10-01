"""Serial reader thread: resync, CRC check, global-sequence drop counting."""
import threading
import time
from collections import deque

try:
    import serial
    import serial.tools.list_ports
except ImportError:          # simulator still works without pyserial
    serial = None

from protocol import (SYNC, HEADER_SIZE, CRC_SIZE, MAX_PAYLOAD, decode_header,
                      verify_crc, decode_payload, encode_command)

SIMULATOR_PORT = 'SIMULATOR'


class SerialLink:
    def __init__(self, port=None, baud=921600):
        self.port = port
        self.baud = baud
        self.ser = None
        self._thread = None
        self._running = False
        self._queue = deque(maxlen=20000)
        self._lock = threading.Lock()
        self.last_error = ''
        self.reset_stats()

    def reset_stats(self):
        self.stats = {'packets_rx': 0, 'bytes_rx': 0, 'crc_errors': 0, 'drops': 0,
                      'packets_per_sec': 0, 'bytes_per_sec': 0}
        self._last_seq = None
        self._t_stats = time.monotonic()
        self._n_pkts = 0
        self._n_bytes = 0

    @property
    def connected(self):
        return self._running

    @staticmethod
    def list_ports():
        ports = []
        if serial is not None:
            ports = [p.device for p in serial.tools.list_ports.comports()]
        return ports + [SIMULATOR_PORT]

    def connect(self):
        self.reset_stats()
        if self.port == SIMULATOR_PORT:
            from sim_device import SimulatedSerial
            self.ser = SimulatedSerial()
        else:
            if serial is None:
                raise RuntimeError('pyserial not installed: pip install pyserial')
            self.ser = serial.Serial(self.port, self.baud, timeout=0.05)
            # Opening the port toggles DTR/RTS on most ESP32 boards => board resets.
            # Give it time to boot before the UI sends START.
            self.ser.reset_input_buffer()
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def disconnect(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def send_command(self, cmd: str):
        if self.ser is not None and self.ser.is_open:
            try:
                self.ser.write(encode_command(cmd))
            except Exception as e:
                self.last_error = str(e)

    def get_packets(self, max_count=5000):
        out = []
        with self._lock:
            while self._queue and len(out) < max_count:
                out.append(self._queue.popleft())
        return out

    def _reader(self):
        buf = bytearray()
        while self._running:
            try:
                n = self.ser.in_waiting if self.ser else 0
                if n:
                    chunk = self.ser.read(min(n, 65536))
                    buf.extend(chunk)
                    self.stats['bytes_rx'] += len(chunk)
                    self._n_bytes += len(chunk)
                    self._parse(buf)
                else:
                    time.sleep(0.002)
            except Exception as e:           # e.g. USB cable pulled
                self.last_error = str(e)
                time.sleep(0.05)
            now = time.monotonic()
            dt = now - self._t_stats
            if dt >= 1.0:
                self.stats['packets_per_sec'] = int(self._n_pkts / dt)
                self.stats['bytes_per_sec'] = int(self._n_bytes / dt)
                self._n_pkts = self._n_bytes = 0
                self._t_stats = now

    def _parse(self, buf: bytearray):
        while True:
            idx = buf.find(SYNC)
            if idx < 0:
                if len(buf) > 1:
                    del buf[:-1]            # keep a possible half sync byte
                return
            if idx:
                del buf[:idx]
            if len(buf) < HEADER_SIZE:
                return
            hdr = decode_header(bytes(buf[:HEADER_SIZE]))
            if hdr is None or hdr[3] > MAX_PAYLOAD:
                del buf[:1]
                continue
            ptype, seq, ts, plen = hdr
            total = HEADER_SIZE + plen + CRC_SIZE
            if len(buf) < total:
                return
            pkt = bytes(buf[:total])
            if not verify_crc(pkt):
                self.stats['crc_errors'] += 1
                del buf[:1]                 # resync from the next byte (spec)
                continue
            del buf[:total]

            if self._last_seq is not None:
                gap = (seq - self._last_seq - 1) & 0xFFFF
                if 0 < gap < 5000:
                    self.stats['drops'] += gap
            self._last_seq = seq

            decoded = decode_payload(ptype, pkt[HEADER_SIZE:HEADER_SIZE + plen])
            with self._lock:
                self._queue.append((ptype, seq, ts, decoded))
            self.stats['packets_rx'] += 1
            self._n_pkts += 1
