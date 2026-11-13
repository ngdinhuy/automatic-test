#!/usr/bin/env python3
"""Đọc route và trạng thái thu/phát thoại từ AudioService theo UID."""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tammi_runner.audio_capture import adb
from tammi_runner.audio_devices import call_route_sample, connected, voice_stream_volume
from tammi_runner.common import Blocked, save_private_json
from tammi_runner.probes import ROUTE_STAGES


def main(payload):
    probe, phase = payload['probe'], payload['phase']
    route_probe = probe == 'audio_routes'
    roles = (payload.get('role', 'A'),) if route_probe else ('A', 'B')
    config = {'devices': {role: {'udid': payload['devices'][role]} for role in roles}, 'tools': payload.get('tools', {})}
    package = payload['app_package']
    result = {'schema': 1, 'challenge': payload['challenge'], 'mode': 'adb_signals', 'measurements': {}}
    stage = payload.get('stage')
    if phase == 'cleanup' or (phase == 'prepare' and stage != 'baseline'):
        return result

    uids = {}
    for role in roles:
        output = adb(config, role, 'shell', 'pm', 'list', 'packages', '-U', package)
        match = re.search(r'^package:' + re.escape(package) + r' uid:(\d+)$', output, re.M)
        if not match:
            raise Blocked(f'Không xác minh được UID ứng dụng trên {role}.')
        uids[role] = int(match[1])

    if phase == 'check':
        for role in roles:
            audio = adb(config, role, 'shell', 'dumpsys', 'audio')
            call_route_sample(audio, package, uids[role])
            if route_probe:
                connected(audio)
        return {**result, 'ready': True, 'checks': ['Đọc được UID và thông tin route thoại từ AudioService.']}

    marker = payload['marker']
    if not re.fullmatch(r'APPIUM-[a-f0-9]{12}', marker):
        raise ValueError('Marker audio không hợp lệ.')
    folder = Path(payload['report_directory']) / f'{probe}-{marker}'
    folder.mkdir(parents=True, exist_ok=True)
    baseline = folder / 'baseline.json'
    identity = {role: [payload['devices'][role], uids[role]] for role in roles}
    sample_index = 0

    def sample():
        nonlocal sample_index
        samples = {}
        for role in roles:
            audio = adb(config, role, 'shell', 'dumpsys', 'audio')
            row = call_route_sample(audio, package, uids[role])
            if route_probe:
                row['wired_connected'] = connected(audio)['wired_output']
                if stage == 'volume':
                    row['volume'] = voice_stream_volume(audio, row['route'])
            samples[role] = row
            save_private_json(folder / f"{payload['challenge']}-{sample_index}-{role}.json", {
                'timestamp': time.time(), 'uid': uids[role], 'stage': stage or phase, 'sample': row, 'audio': audio,
            })
        sample_index += 1
        return samples

    if phase == 'prepare':
        rows = sample()
        if not route_probe and any(row['active'] for row in rows.values()):
            raise Blocked('Ứng dụng đã sở hữu route thoại trước cuộc gọi.')
        save_private_json(baseline, identity)
        return result

    if not baseline.is_file() or json.loads(baseline.read_text()) != identity:
        raise Blocked('Thiếu baseline đúng thiết bị và UID của lượt chạy.')
    if route_probe:
        row = sample()[roles[0]]
        if stage in ROUTE_STAGES:
            deadline = time.monotonic() + 4
            while row['active'] and row['route'] not in ROUTE_STAGES[stage] and time.monotonic() < deadline:
                time.sleep(.35)
                row = sample()[roles[0]]
        if not row['active']:
            raise Blocked('Ứng dụng chưa sở hữu audio mode thoại trên máy chuyển route.')
        result['measurements'] = row
        return result

    if phase == 'after_end':
        consecutive = 0
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            consecutive = consecutive + 1 if all(not row['active'] for row in sample().values()) else 0
            if consecutive == 2:
                result['measurements'] = {'call_audio_mode_released': 1}
                return result
            time.sleep(.4)
        raise AssertionError('App vẫn sở hữu audio mode thoại sau khi kết thúc.')
    rows = sample()
    for role, row in rows.items():
        if not row['active'] or row['playback'] is None or row['recording'] is None:
            raise Blocked(f'{role}: AudioService chưa có đủ tín hiệu thu và phát quy được cho UID cuộc gọi.')
        assert row['playback'] and row['recording'], f'{role}: client thoại thiếu hoạt động thu hoặc phát.'
    result['measurements'] = {'active_playback_roles': 2, 'active_recording_roles': 2}
    return result


if __name__ == '__main__':
    payload = json.load(sys.stdin)
    try:
        result = main(payload)
    except (Blocked, ValueError) as error:
        result = {'schema': 1, 'challenge': payload['challenge'], 'blocked': str(error)}
    except Exception as error:
        print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False))
