#!/usr/bin/env python3
"""Đo camera active theo package/PID trên A/B; không đo chất lượng hình hay FPS từ xa."""
import json
import re
import sys
import subprocess
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tammi_runner.camera_capture import clients,streaming
from tammi_runner.common import save_private_json
from media_integrity import adb


def main(payload):
    marker=payload['marker']
    if not re.fullmatch(r'APPIUM-[a-f0-9]{12}',marker):raise ValueError('Marker không hợp lệ.')
    result={'schema':1,'challenge':payload['challenge'],'measurements':{},'scope':'CameraService package/PID và Device status ACTIVE, không đo hình nhận/FPS.'}
    # Prepare chỉ khởi tạo hợp đồng; app có thể chưa mở ở bước này.
    if payload['phase'] in ('prepare','cleanup'):return result
    folder=Path(payload['report_directory'])/('camera-'+marker);folder.mkdir(parents=True,exist_ok=True)
    snapshots={};counts={}
    for role in ('A','B'):
        package=payload['app_package']
        try:raw_pid=adb(payload,role,'shell','pidof',package)
        except subprocess.CalledProcessError as error:
            if error.returncode!=1 or (error.stdout or "").strip() or (error.stderr or "").strip():raise
            raise AssertionError('Không có process staging khi đo camera trên '+role) from error
        pids={int(value) for value in raw_pid.split() if value.isdigit()}
        if not pids:raise AssertionError('Không có process staging trên '+role)
        text=adb(payload,role,'shell','dumpsys','media.camera')
        try:
            opened=clients(text,package,pids)
            active=streaming(text,opened)
        except ValueError as error:
            (folder/(role+'-unsupported.txt')).write_text(text.split('== Camera service events log',1)[0])
            result['blocked']=str(error);return result
        snapshots[role]={'opened':opened,'capturing':active};counts[role+'_active_clients']=len(active)
        counts[role+'_open_clients']=len(opened)
    result['measurements']=counts
    save_private_json(folder/(str(time.time_ns())+'.json'),{'active':snapshots,'measurements':counts})
    return result

if __name__=='__main__':
    try:result=main(json.load(sys.stdin))
    except Exception as error:print(type(error).__name__+': '+str(error),file=sys.stderr);sys.exit(1)
    print(json.dumps(result,ensure_ascii=False))
