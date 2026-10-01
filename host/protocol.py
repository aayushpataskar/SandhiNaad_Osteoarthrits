"""Binary protocol decoder/encoder for SandhiNaad ESP32 communication.

Frame: A5 5A | type u8 | seq u16 | ts_us u64 | len u16 | payload | crc16  (little-endian)
CRC16-CCITT (poly 0x1021, init 0xFFFF) over type..payload. `seq` is one global
counter across all packet types. Must match firmware/SandhiNaad/protocol.h.
"""
import struct
import numpy as np

SYNC = b'\xA5\x5A'
HEADER_SIZE = 15
CRC_SIZE = 2
MAX_PAYLOAD = 1100

PKT_AUDIO_RAW    = 0x01
PKT_AUDIO_FILT   = 0x02
PKT_AUDIO_MINMAX = 0x03
PKT_ENVELOPE     = 0x04
PKT_EMG          = 0x05
PKT_IMU          = 0x06
PKT_LOAD         = 0x07
PKT_EVENT        = 0x08
PKT_FEAT_BLOCK   = 0x09
PKT_FEAT_CYCLE   = 0x0A
PKT_STATUS       = 0x0B
PKT_LOG          = 0x0C
PKT_ACK          = 0x0D

PKT_NAMES = {
    0x01: 'AUDIO_RAW', 0x02: 'AUDIO_FILT', 0x03: 'AUDIO_MINMAX',
    0x04: 'ENVELOPE', 0x05: 'EMG', 0x06: 'IMU', 0x07: 'LOAD',
    0x08: 'EVENT', 0x09: 'FEAT_BLOCK', 0x0A: 'FEAT_CYCLE',
    0x0B: 'STATUS', 0x0C: 'LOG', 0x0D: 'ACK',
}

STATUS_NAMES = {0: 'ATTACHED', 1: 'NOT_ATTACHED', 2: 'FAULT', 3: 'SIMULATED'}   # 3 = host-side demo fill-in only
PHASE_NAMES = {0: 'HOLD', 1: 'FLEXION', 2: 'EXTENSION'}
MODE_NAMES = {0: 'FULL', 1: 'DEFAULT', 2: 'FEATURES'}

# First 17 = FEAT_BLOCK payload order; all 22 = model input order (ml/config.py)
ACOUSTIC_FEATURE_NAMES = [
    'rms', 'peak_dbfs', 'floor_dbfs', 'spectral_centroid', 'peak_freq',
    'subband_250_500', 'subband_500_1k', 'subband_1k_2k', 'subband_2k_4k5',
    'hf_ratio', 'spectral_entropy', 'kurtosis', 'skewness',
    'hjorth_activity', 'hjorth_mobility', 'hjorth_complexity', 'zcr',
]
MODEL_FEATURE_NAMES = ACOUSTIC_FEATURE_NAMES + [
    'events_per_cycle', 'rom', 'peak_flex_vel', 'peak_ext_vel', 'cycle_duration',
]
CYCLE_NAMES = ['rom', 'peak_flex_vel', 'peak_ext_vel', 'duration_s',
               'num_events', 'oa_probability', 'mean_rms',
               'mean_spectral_centroid', 'mean_hf_ratio',
               'mean_kurtosis', 'mean_spectral_entropy']

_EMG_DT = np.dtype([('raw', '<u2'), ('removed', '<i2'), ('envelope', '<u2')])


def crc16_ccitt(data: bytes, init: int = 0xFFFF) -> int:
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return crc


# Table-driven version (the bitwise one is too slow for ~60 kB/s in Python)
_CRC_TABLE = []
for _i in range(256):
    _c = _i << 8
    for _ in range(8):
        _c = ((_c << 1) ^ 0x1021) if (_c & 0x8000) else (_c << 1)
    _CRC_TABLE.append(_c & 0xFFFF)


def crc16_fast(data) -> int:
    crc = 0xFFFF
    tbl = _CRC_TABLE
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ tbl[((crc >> 8) ^ b) & 0xFF]
    return crc


def decode_header(data: bytes):
    if len(data) < HEADER_SIZE or data[0:2] != SYNC:
        return None
    pkt_type = data[2]
    seq, ts, plen = struct.unpack_from('<HQH', data, 3)
    return pkt_type, seq, ts, plen


def verify_crc(pkt: bytes) -> bool:
    if len(pkt) < HEADER_SIZE + CRC_SIZE:
        return False
    end = len(pkt) - CRC_SIZE
    return crc16_fast(pkt[2:end]) == struct.unpack_from('<H', pkt, end)[0]


def encode_packet(pkt_type: int, seq: int, ts_us: int, payload: bytes) -> bytes:
    """Build a frame exactly like the firmware does (used by simulator + tests)."""
    body = struct.pack('<BHQH', pkt_type, seq & 0xFFFF, ts_us, len(payload)) + payload
    return SYNC + body + struct.pack('<H', crc16_fast(body))


def decode_payload(pkt_type: int, p: bytes) -> dict:
    if pkt_type in (PKT_AUDIO_RAW, PKT_AUDIO_FILT):
        return {'samples': np.frombuffer(p, dtype='<i2').astype(np.float32) / 32768.0}

    if pkt_type == PKT_AUDIO_MINMAX:
        d = np.frombuffer(p, dtype='<i2').reshape(-1, 2).astype(np.float32) / 32768.0
        return {'min': d[:, 0], 'max': d[:, 1]}

    if pkt_type == PKT_ENVELOPE:
        return {'envelope': np.frombuffer(p, dtype='<u2').astype(np.float32) / 65535.0}

    if pkt_type == PKT_EMG:
        a = np.frombuffer(p[: (len(p) // 6) * 6], dtype=_EMG_DT)
        return {'raw': a['raw'].astype(np.float32),
                'removed': a['removed'].astype(np.float32),
                'envelope': a['envelope'].astype(np.float32)}

    if pkt_type == PKT_IMU:
        if len(p) < 47:
            return {}
        v = struct.unpack_from('<10f', p, 0)
        return {'q_thigh': v[0:4], 'q_shank': v[4:8],
                'knee_angle': v[8], 'angular_vel': v[9], 'phase': p[40],
                'cal': tuple(p[41:45]), 'status_thigh': p[45], 'status_shank': p[46]}

    if pkt_type == PKT_LOAD:
        if len(p) < 5:
            return {}
        return {'force_N': struct.unpack_from('<f', p, 0)[0], 'status': p[4]}

    if pkt_type == PKT_EVENT:
        if len(p) < 25:
            return {}
        ts = struct.unpack_from('<Q', p, 0)[0]
        peak, margin, dur, ang = struct.unpack_from('<4f', p, 8)
        snip = np.frombuffer(p[25:25 + 512], dtype='<i2').astype(np.float32) / 32768.0
        return {'event_time_us': ts, 'peak_dbfs': peak, 'margin_db': margin,
                'duration_ms': dur, 'knee_angle': ang, 'phase': p[24], 'snippet': snip}

    if pkt_type == PKT_FEAT_BLOCK:
        if len(p) < 68:
            return {}
        return dict(zip(ACOUSTIC_FEATURE_NAMES, struct.unpack_from('<17f', p, 0)))

    if pkt_type == PKT_FEAT_CYCLE:
        if len(p) < 44:
            return {}
        d = dict(zip(CYCLE_NAMES, struct.unpack_from('<11f', p, 0)))
        if len(p) >= 44 + 22 * 4:
            d['model_input'] = dict(zip(MODEL_FEATURE_NAMES, struct.unpack_from('<22f', p, 44)))
        return d

    if pkt_type == PKT_STATUS:
        if len(p) < 24:
            return {}
        s = {'mic1_status': p[0], 'mic2_status': p[1], 'imu1_status': p[2],
             'imu2_status': p[3], 'emg_status': p[4], 'load_status': p[5],
             'stream_mode': p[6]}
        (s['free_heap'], s['dropped_packets'],
         s['tx_bytes_per_sec'], s['loop_time_us']) = struct.unpack_from('<4I', p, 7)
        s['mic1_slot'] = p[23]
        if len(p) >= 28:
            s['noise_floor_dbfs'] = struct.unpack_from('<f', p, 24)[0]
        return s

    if pkt_type in (PKT_LOG, PKT_ACK):
        return {'msg': p.decode('utf-8', errors='replace').rstrip('\x00')}

    return {}


def encode_command(cmd: str) -> bytes:
    return (cmd.strip() + '\n').encode('ascii', errors='ignore')
