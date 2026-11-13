"""Đối chiếu player trước–trong–sau; không suy RMS từ trạng thái Android."""
import re
from .common import Blocked

USAGES={'USAGE_NOTIFICATION_RINGTONE','USAGE_VOICE_COMMUNICATION','USAGE_VOICE_COMMUNICATION_SIGNALLING'}


def snapshot(text,uid):
    if 'AudioPlaybackConfiguration' not in text and 'PlaybackActivityMonitor' not in text:
        raise Blocked('AudioService chưa expose bảng playback; không coi thiếu bảng là đã dừng.')
    rows=[]
    for line in text.splitlines():
        if 'AudioPlaybackConfiguration piid:' not in line or not re.search(r'u/pid:'+str(uid)+r'/',line):continue
        key=re.search(r'piid:(\d+)',line);state=re.search(r'\bstate:(\w+)',line);usage=re.search(r'usage=(\w+)',line)
        muted=re.search(r'mutedState:([^\s]+)',line)
        device=re.search(r'\bdeviceId[:=]\s*(\d+)',line)
        if not key or not state:raise Blocked('Định dạng player chưa hỗ trợ.')
        rows.append({'piid':key[1],'state':state[1],'usage':usage[1] if usage else None,
                     'muted':None if not muted else muted[1]!='none','device_id':int(device[1]) if device else None})
    # Chỉ đối chiếu stream ứng với usage; giữ bảng gốc để tránh nhầm volume của thiết bị khác.
    streams={}
    for name,body in re.findall(r'- (STREAM_\w+):(.*?)(?=\n\s*- STREAM_|\Z)',text,re.S):
        current=re.search(r'^\s*Current: (.+)$',body,re.M);mute=re.search(r'^\s*Muted: (true|false)',body,re.M)
        streams[name]={'current':current[1] if current else None,'muted':mute[1]=='true' if mute else None}
    return {'players':rows,'streams':streams}


def candidates(before,during):
    previous={r['piid']:r for r in before['players']}
    found=[]
    for row in during['players']:
        if row['state']!='started' or row['usage'] not in USAGES:continue
        old=previous.get(row['piid'])
        if old and old['state']=='started':continue
        if row['muted'] is None:raise Blocked('Player mới thiếu mutedState; chưa đủ bằng chứng không muted.')
        assert not row['muted'],'Player chuông mới đang muted.'
        stream='STREAM_RING' if row['usage']=='USAGE_NOTIFICATION_RINGTONE' else 'STREAM_VOICE_CALL'
        volume=during['streams'].get(stream,{})
        assert volume.get('muted') is not True,'Stream chuông/thoại đang muted.'
        levels=re.findall(r':\s*(\d+)(?:\s|,|$)',volume.get('current') or '')
        if levels:assert any(int(v)>0 for v in levels),'Mọi mức volume stream được expose đều bằng 0.'
        # Không suy volume theo route nếu dumpsys không liên kết được hai trường.
        found.append({**row,'volume':volume,'route_status':'reported' if row['device_id'] else 'unavailable'})
    return found


def stopped(rows,after):
    active={r['piid'] for r in after['players'] if r['state']=='started'}
    return all(row['piid'] not in active for row in rows)
