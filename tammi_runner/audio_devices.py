"""Đọc thiết bị âm thanh đang nối, loại bảng volume và log kết nối cũ."""
import re
import subprocess
from .common import find_adb

BT_OUTPUT={0x10,0x20,0x40,0x80,0x100,0x200,0x20000000,0x20000001,0x20000002}
BT_INPUT={0x80000008,0xA0000000}
WIRED_OUTPUT={4,8,0x2000,0x4000,0x4000000}
WIRED_INPUT={0x80000010,0x80000800,0x80001000,0x82000000}


def communication_route(text):
    route = re.search(r'^\s*Active communication device: AudioDeviceAttributes: role:output type:([\w-]+)\b', text, re.M)
    if not route:
        raise ValueError('AudioService chưa expose route thoại đang được chọn.')
    return route[1]


def call_route_sample(text, package, uid):
    route = communication_route(text)
    owner = re.search(r'^- Mode owner:[ \t]*\n(?P<fields>(?:  - [^\n]+\n)+)', text, re.M)
    mode = re.search(r'^- Actual mode = (\w+)', text, re.M)
    if not mode:
        raise ValueError('AudioService chưa expose audio mode.')
    if mode[1] != 'MODE_IN_COMMUNICATION':
        return {'active': False, 'route': route}
    if not owner:
        raise ValueError('AudioService chưa expose thông tin chủ audio mode thoại.')
    fields = dict(re.findall(r'^  - (\w+): (.+)$', owner['fields'], re.M))
    if not fields.get('Uid') or not fields.get('Package'):
        raise ValueError('Thiếu UID hoặc package của chủ audio mode thoại.')
    if fields.get('Uid') != str(uid) or fields.get('Package') != package:
        return {'active': False, 'route': route}
    client_block = re.search(r'^[ \t]*Communication route clients:[^\n]*\n((?:[ \t]+\[CommunicationRouteClient:[^\n]*\n)*)', text, re.M)
    binder = fields.get('Binder')
    client = next((line for line in client_block[1].splitlines() if binder and f'mCb: {binder} ' in line), '') if client_block else ''
    return {'active': True, 'route': route,
            'playback': 'mPlaybackActive: true' in client if 'mPlaybackActive:' in client else None,
            'recording': 'mRecordingActive: true' in client if 'mRecordingActive:' in client else None}


def voice_stream_volume(text, route):
    stream = re.search(r'^- STREAM_VOICE_CALL:\s*\n(.*?)(?=^\s*- STREAM_|\Z)', text, re.M | re.S)
    if stream:
        levels = re.search(r'^\s*Current: ([^\n]+)', stream[1], re.M)
        devices = re.search(r'^\s*Devices: ([^\n]+)', stream[1], re.M)
        if levels and devices and re.fullmatch(re.escape(route) + r'(?:\([\da-fA-Fx]+\))?', devices[1].strip()):
            volume = re.search(r'\(' + re.escape(route) + r'\):\s*(\d+)\b', levels[1])
            if volume:
                return int(volume[1])
    raise ValueError('Không ghép được mức âm lượng thoại với route đang chọn.')


def connected(text):
    lines=text.splitlines();start=next((i for i,line in enumerate(lines) if line.strip()=='Connected devices:'),None)
    if start is None:raise ValueError('AudioService không expose mục Connected devices theo parser hiện tại.')
    indent=len(lines[start])-len(lines[start].lstrip());devices=[]
    for line in lines[start+1:]:
        if line.strip() and len(line)-len(line.lstrip())<=indent:break
        match=re.search(r'\[DeviceInfo: type:0x([0-9a-fA-F]+) \(([^)]+)\)',line)
        if 'DeviceInfo' in line and not match:raise ValueError('Định dạng DeviceInfo chưa được hỗ trợ; không suy ra tai nghe đã ngắt.')
        if match:
            value=int(match[1],16)
            name=re.search(r'\bname:(.*?)\s+addr:',line)
            devices.append({'type':match[2],'name':name[1].strip() if name else '',
                            'direction':'input' if value & 0x80000000 else 'output','code':value})
    codes={d['code'] for d in devices}
    return {'types':[d['type'] for d in devices],'devices':devices,
            'wired_or_usb':bool(codes & (WIRED_OUTPUT|WIRED_INPUT)),
            'wired_output':bool(codes & WIRED_OUTPUT),'wired_input':bool(codes & WIRED_INPUT),
            'bluetooth':bool(codes & (BT_OUTPUT|BT_INPUT)),
            'bluetooth_output':bool(codes & BT_OUTPUT),'bluetooth_input':bool(codes & BT_INPUT),
            'bluetooth_call_profiles':bool(codes & {0x10,0x20,0x40,0x20000000,0x20000001,0x20000002}) and bool(codes & BT_INPUT)}


def route_requirements(case,hardware):
    """Chỉ kiểm tra tai nghe trên máy thực hiện chuyển route; không đòi B đeo tai nghe."""
    if 'probe:audio_routes' not in case.requirements:return []
    role=case.params.get('caller','A')
    row=next((r for r in hardware if r.get('role')==role),None)
    if not row or 'observed' not in row:return [f'Chưa đọc được kết nối tai nghe hiện tại trên máy {role}.']
    observed=row['observed'];issues=[]
    if not observed.get('wired_output'):issues.append(f'Máy {role} chưa nối tai nghe dây/USB để kiểm tra cắm/rút.')
    if not observed.get('bluetooth_output'):issues.append(f'Máy {role} chưa nối đầu ra tai nghe Bluetooth.')
    elif not observed.get('bluetooth_call_profiles'):issues.append(f'Máy {role} có Bluetooth nhưng chưa thấy đủ profile thoại và micro; A2DP đơn thuần chưa đủ.')
    return issues


def inventory(config,available):
    rows=[];online={d['udid'] for d in available if d['state']=='device'}
    for role in ('A','B'):
        serial=config.get('devices',{}).get(role,{}).get('udid')
        if serial not in online:continue
        try:
            text=subprocess.check_output([find_adb(config),'-s',serial,'shell','dumpsys','audio'],text=True,timeout=10)
            values=connected(text)
            names=list(dict.fromkeys(d['name'] for d in values['devices'] if d['name']))
            detail='Thiết bị: '+(', '.join(names) or 'không có tên ngoài được liệt kê')+'. Profile: '+(', '.join(values['types']) or 'không có')+'. Dây/USB: '+('có' if values['wired_output'] else 'chưa nối')+'; Bluetooth: '+('có' if values['bluetooth_output'] else 'chưa nối')+'; profile thoại + micro BT: '+('có' if values['bluetooth_call_profiles'] else 'chưa đủ')+'.'
            rows.append({'name':role+' · thiết bị âm thanh','role':role,'status':'OBSERVED','detail':detail,'needs':'Kết nối/profile chưa chứng minh route đang được cuộc gọi sử dụng hoặc âm thanh/rung vật lý.','observed':values})
        except (OSError,ValueError,subprocess.SubprocessError) as error:
            rows.append({'name':role+' · thiết bị âm thanh','role':role,'status':'UNVERIFIED','detail':str(error),'needs':'Cần Android expose trạng thái thiết bị đang nối; không suy từ log lịch sử.'})
    return rows
