#!/usr/bin/env python3
"""Đo tọa độ đích Maps của card nhận được; không lấy GPS thật của máy B."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tammi_runner.location_lab import navigation_coordinates
from tammi_runner.common import Blocked
from media_integrity import adb


def main(payload):
    result={'schema':1,'challenge':payload['challenge'],'measurements':{},'scope':'Điểm đích do staging truyền sang Google Maps sau mở card mới; không phải GPS B.'}
    if payload['phase']=='check':
        installed=adb(payload,'B','shell','pm','path','com.google.android.apps.maps').strip().startswith('package:')
        return {**result,'ready':installed,'checks':['Google Maps đã cài trên B'] if installed else [],'blocked':None if installed else 'B chưa có Google Maps.'}
    if payload['phase'] in ('prepare','cleanup'):return result
    text=adb(payload,'B','shell','dumpsys','activity','activities')
    if 'com.google.android.apps.maps' not in text:
        result['blocked']='Không thấy activity Google Maps để đọc điểm đích.';return result
    try:lat,lon=navigation_coordinates(text)
    except Blocked as error:result['blocked']=str(error);return result
    result['measurements']={'latitude':lat,'longitude':lon}
    return result


if __name__=='__main__':
    try:result=main(json.load(sys.stdin))
    except Exception as error:print(type(error).__name__+': '+str(error),file=sys.stderr);sys.exit(1)
    print(json.dumps(result,ensure_ascii=False))
