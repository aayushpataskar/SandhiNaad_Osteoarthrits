import sys
import time
from serial_link import SerialLink
from protocol import PKT_LOG, PKT_ACK, PKT_STATUS, PKT_NAMES

print('Opening SerialLink on COM17...')
link = SerialLink('COM17', 921600)
link.connect()

print('Waiting 3s for reboot...')
time.sleep(3)

print('Sending START...')
link.send_command('START')

print('Reading packets for 10s...')
time.sleep(10)

packets = link.get_packets(100000)
link.disconnect()

print('\n--- RESULTS ---')

logs = []
latest_status = None
counts = {}

for pkt_type, seq, ts, payload in packets:
    counts[pkt_type] = counts.get(pkt_type, 0) + 1
    if pkt_type in (PKT_LOG, PKT_ACK):
        logs.append(payload.get('msg', ''))
    elif pkt_type == PKT_STATUS:
        latest_status = payload

print('LOG/ACK Messages:')
for msg in logs:
    print(f'  {msg}')

print('\nLatest STATUS:')
if latest_status:
    print(f'  mic1_status: {latest_status.get("mic1_status")}')
    print(f'  mic2_status: {latest_status.get("mic2_status")}')
    print(f'  imu1_status: {latest_status.get("imu1_status")}')
    print(f'  imu2_status: {latest_status.get("imu2_status")}')
    print(f'  emg_status:  {latest_status.get("emg_status")}')
    print(f'  load_status: {latest_status.get("load_status")}')
else:
    print('  No STATUS packet received!')

print('\nPacket counts per type:')
for pt, count in sorted(counts.items()):
    name = PKT_NAMES.get(pt, f'UNKNOWN_{pt}')
    print(f'  {name}: {count}')

print(f'\nStats: {link.stats}')
