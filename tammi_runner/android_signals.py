"""Đọc sự kiện Android có quy thuộc UID; không đổi số đo hệ thống thành RMS âm thanh."""
import re
from datetime import datetime


def after_snapshot(key,since):
    baseline=datetime.strptime(since,'%Y-%m-%dT%H:%M:%S%z')
    candidates=[]
    for year in (baseline.year-1,baseline.year,baseline.year+1):
        try:candidates.append(datetime.strptime(str(year)+'-'+key,'%Y-%m-%d %H:%M:%S.%f').replace(tzinfo=baseline.tzinfo))
        except ValueError:continue
    if not candidates:return False
    event=min(candidates,key=lambda value:abs((value-baseline).total_seconds()))
    return event>=baseline


def vibrations(text,package,uid):
    rows={}
    for line in text.splitlines():
        if not re.search(r'\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}\s*\|',line):continue
        fields=[part.strip() for part in line.split('|')]
        if len(fields)<8:continue
        belongs=(f'{package} (uid={uid},' in line or f'Notification ({package} {uid})' in line)
        usage=next((part for part in fields if part.startswith('usage:')),'')
        if not belongs or not any(key in usage for key in ('RINGTONE','NOTIFICATION','COMMUNICATION_REQUEST')):continue
        started=next((part.split('start:',1)[1].strip() for part in fields if part.startswith('start:')),'')
        status=fields[2]
        rows[fields[0]]={'status':status,'started':bool(started),'accepted':not status.lower().startswith('ignored') and bool(started)}
    return rows


def players(text,uid):
    rows=[]
    for line in text.splitlines():
        if 'AudioPlaybackConfiguration piid:' not in line:continue
        if not re.search(r'u/pid:'+str(uid)+r'/',line) or 'state:started' not in line:continue
        match=re.search(r'piid:(\d+)',line)
        usage=re.search(r'usage=(\w+)',line)
        rows.append({'piid':match.group(1),'usage':usage.group(1) if usage else 'UNKNOWN',
                     'ringtone_candidate':('RINGTONE' in line or ('type:android.media.MediaPlayer' in line and 'USAGE_VOICE_COMMUNICATION' in line)),
                     'muted':not ('mutedState:none' in line)})
    return rows
