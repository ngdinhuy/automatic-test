#!/usr/bin/env python3
"""Chuẩn bị fixture/probe tích hợp khi setup máy mới, giữ các cấu hình người dùng đã có."""
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tammi_runner.common import DEFAULT_CONFIG, load_config, save_private_json
from tammi_runner.lab_setup import configure_call_audio, configure_notification_alert

if not DEFAULT_CONFIG.exists():save_private_json(DEFAULT_CONFIG,json.loads((ROOT/'config/examples/staging.json').read_text()))
config=load_config();manifest=ROOT/'fixtures/generated/manifest.json'
if not manifest.exists():subprocess.run([sys.executable,str(ROOT/'scripts/prepare-fixtures.py'),'--large-image'],check=True)
for key,value in json.loads(manifest.read_text()).items():config.setdefault('fixtures',{}).setdefault(key,value)
for kind in ('camera_photo','camera_video'):config['fixtures'].setdefault(kind,{})
config.setdefault('lab',{}).setdefault('probes',{}).setdefault('media_integrity',{'command':[sys.executable,str(ROOT/'scripts/probes/media_integrity.py')],'supported_media':['camera_photo','multiple_images','image_under_100mb','camera_video','gallery_video']})
probe=config['lab']['probes']['media_integrity']
if probe.get('command')==[sys.executable,str(ROOT/'scripts/probes/media_integrity.py')]:
    probe['supported_media']=list(dict.fromkeys(probe.get('supported_media',[])+['camera_photo','multiple_images','image_under_100mb','camera_video','gallery_video']))
config['lab']['probes'].setdefault('android_signals',{'command':[sys.executable,str(ROOT/'scripts/probes/android_signals.py')]})
config['lab']['probes'].setdefault('camera_capture',{'command':[sys.executable,str(ROOT/'scripts/probes/camera_capture.py')]})
configure_call_audio(config)
configure_notification_alert(config)
save_private_json(DEFAULT_CONFIG,config)
print('Đã chuẩn bị fixture/probe ảnh tích hợp. Tài khoản và tool paths kiểm tra trong Desktop.')
