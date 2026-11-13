#!/usr/bin/env python3
"""Đo cửa sổ sự kiện rung/phát âm thanh Android của app; không đo âm thanh vật lý."""
import json
import re
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tammi_runner.common import Blocked,save_private_json
from tammi_runner.android_signals import players,vibrations,after_snapshot
from tammi_runner.ringback_signals import snapshot
from media_integrity import adb


def app_uid(payload,role,package):
    info=adb(payload,role,'shell','pm','list','packages','-U',package)
    match=re.search(r'^package:'+re.escape(package)+r' uid:(\d+)$',info,re.M)
    if not match:
        raise Blocked('Không xác minh được UID ứng dụng trên máy nhận.')
    return int(match[1])


def main(payload):
    marker=payload['marker']
    if not re.fullmatch('APPIUM-[a-f0-9]{12}',marker):raise AssertionError('Marker probe không hợp lệ.')
    folder=Path(payload['report_directory'])/('android-signals-'+marker);folder.mkdir(parents=True,exist_ok=True)
    path=folder/'state.json';role=payload.get('role','B');package=payload['app_package']
    result={'schema':1,'challenge':payload['challenge'],'measurements':{},
            'scope':'Android UID playback/vibration dispatch, không đo RMS hoặc cảm nhận âm thanh/rung vật lý.'}
    if payload['phase']=='prepare':
        uid=app_uid(payload,role,package)
        audio=adb(payload,role,'shell','dumpsys','audio')
        snapshot(audio,uid)
        active_before=[row['piid'] for row in players(audio,uid)]
        baseline=vibrations(adb(payload,role,'shell','dumpsys','vibrator_manager'),package,uid)
        since=adb(payload,role,'shell','date','+%Y-%m-%dT%H:%M:%S%z').strip()
        save_private_json(path,{'uid':uid,'before':list(baseline),'role':role,'since':since,
                                'serial':payload['devices'][role],'active_before':active_before,'audio_before':audio})
        return result
    if payload['phase']=='cleanup':return result
    state=json.loads(path.read_text());uid=state['uid'];role=state['role']
    if state['serial']!=payload['devices'][role] or app_uid(payload,role,package)!=uid:
        raise Blocked('Thiết bị hoặc UID nhận đã đổi sau baseline.')
    snapshots=[];start=time.monotonic();fresh={};active={};ringtone={}
    while time.monotonic()-start<5:
        vib=adb(payload,role,'shell','dumpsys','vibrator_manager')
        audio=adb(payload,role,'shell','dumpsys','audio')
        snapshot(audio,uid)
        events={k:v for k,v in vibrations(vib,package,uid).items() if k not in state['before'] and after_snapshot(k,state['since'])}
        fresh.update(events)
        records=players(audio,uid)
        for record in records:
            active[record['piid']]=record
            if record['ringtone_candidate'] and not record['muted'] and record['piid'] not in state['active_before']:
                ringtone[record['piid']]=record
        index=len(snapshots)
        save_private_json(folder/f'{index}-uid-signals.json',{'events':events,'active_players':records,'audio':audio})
        snapshots.append({'seconds':time.monotonic()-start,'events':events,'active_players':records})
        time.sleep(.5)
    result['measurements']={'observed_seconds':time.monotonic()-start,
                            'fresh_vibration_events':sum(v['accepted'] for v in fresh.values()),
                            'active_audio_clients':len(active),'active_ringtone_clients':len(ringtone)}
    result['vibration_events']=fresh;result['snapshots']=snapshots
    return result


if __name__=='__main__':
    payload=json.load(sys.stdin)
    try:answer=main(payload)
    except Blocked as error:answer={'schema':1,'challenge':payload['challenge'],'blocked':str(error)}
    except Exception as error:
        print(type(error).__name__+': '+str(error),file=sys.stderr);sys.exit(1)
    print(json.dumps(answer,ensure_ascii=False))
