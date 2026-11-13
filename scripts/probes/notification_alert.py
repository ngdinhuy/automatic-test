#!/usr/bin/env python3
"""Đối chiếu notification_alert với key và marker của tin staging mới."""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tammi_runner.audio_capture import adb
from tammi_runner.common import Blocked, save_private_json


CHANNEL = 'appviettel_sms_channel_v2'
ALERT = re.compile(r'^\s*(\d+\.\d+)\s+\d+\s+\d+\s+[A-Z]\s+notification_alert:\s*\[(.+?),([\d, -]+)\]\s*$', re.M)


def main(payload):
    result = {'schema': 1, 'challenge': payload['challenge'], 'mode': 'adb_signals', 'measurements': {}}
    phase = payload['phase']
    if phase == 'cleanup' or (phase == 'prepare' and payload.get('stage') != 'baseline'):
        return result
    role = 'B'
    serial = payload['devices'][role]
    config = {'devices': {role: {'udid': serial}}, 'tools': payload.get('tools', {})}
    package = payload['app_package']

    def read(*args):
        return adb(config, role, 'shell', *args)

    def alerts():
        return read('logcat', '-d', '-b', 'events', '-v', 'epoch', '-t', '8000', 'notification_alert:I', "'*:S'")

    if phase == 'check':
        if not ALERT.search(alerts()):
            raise Blocked('Chưa xác minh được định dạng event notification_alert trên máy B.')
        return {**result, 'ready': True, 'checks': ['Đọc được event notification_alert theo key trên B.']}

    marker = payload['marker']
    if not re.fullmatch(r'APPIUM-[a-f0-9]{12}', marker):
        raise ValueError('Marker notification không hợp lệ.')
    folder = Path(payload['report_directory']) / ('notification-alert-' + marker)
    folder.mkdir(parents=True, exist_ok=True)
    baseline = folder / 'baseline.json'
    if phase == 'prepare':
        since = float(read('date', '+%s.%N').strip())
        save_private_json(baseline, {'serial': serial, 'package': package, 'since': since})
        return result

    if not baseline.is_file():
        raise Blocked('Thiếu baseline trước khi gửi tin notification.')
    state = json.loads(baseline.read_text())
    if (state['serial'], state['package']) != (serial, package):
        raise Blocked('Thiết bị hoặc package đã đổi sau baseline notification.')
    notification = read('dumpsys', 'notification', '--noredact')
    keys = {}
    for block in re.split(r'(?=NotificationRecord\()', notification):
        header = block.split('\n', 1)[0]
        if f'pkg={package} ' not in header or not re.search(r'\bchannel=' + re.escape(CHANNEL) + r'(?=[\s,)])', header):
            continue
        key = re.search(r'\bkey=(\S+)', header)
        updated = re.search(r'\bmUpdateTimeMs=(\d+)', block)
        if key and updated and int(updated[1]) >= int(state['since'] * 1000) and marker + '-0' in block:
            # Dấu hai chấm cuối thuộc dòng tiêu đề NotificationRecord trên Samsung.
            value = key[1].removesuffix(':')
            keys[value] = max(keys.get(value, 0), int(updated[1]))
    if len(keys) != 1:
        raise Blocked('Chưa xác định duy nhất key thông báo mới chứa marker của testcase.')
    key, updated_ms = next(iter(keys.items()))
    events = []
    for event in ALERT.finditer(alerts()):
        if event[2] != key or float(event[1]) < max(state['since'], updated_ms / 1000):
            continue
        values = [int(value) for value in event[3].split(',')]
        if len(values) >= 3:
            events.append({'time': float(event[1]), 'buzz': values[0], 'beep': values[1], 'blink': values[2]})
    save_private_json(folder / 'matched-alert.json', {'key': key, 'events': events, 'channel': CHANNEL})
    if not events:
        raise Blocked('Thông báo có marker nhưng thiếu event Android cùng key trong cửa sổ đo.')
    if any(row['buzz'] not in (0, 1) or row['beep'] not in (0, 1) for row in events):
        raise Blocked('ROM trả giá trị buzz/beep ngoài định dạng 0/1 cho thông báo test.')
    result['measurements'] = {
        'sound_dispatched': int(any(row['beep'] == 1 for row in events)),
        'vibration_dispatched': int(any(row['buzz'] == 1 for row in events)),
    }
    return result


if __name__ == '__main__':
    payload = json.load(sys.stdin)
    try:
        answer = main(payload)
    except Blocked as error:
        answer = {'schema': 1, 'challenge': payload['challenge'], 'blocked': str(error)}
    print(json.dumps(answer, ensure_ascii=False))
