#!/usr/bin/env python3
"""Bật adapter tín hiệu ADB ringback; không thay tài khoản hoặc chạy testcase."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tammi_runner.common import DEFAULT_CONFIG,load_config,save_private_json
config=load_config()
command=[str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/probes/ringback_audio.py')]
config.setdefault('lab',{}).setdefault('probes',{})['ringback']={'command':command,'healthcheck_command':command,'mode':'adb_signals'}
save_private_json(DEFAULT_CONFIG,config)
print('Đã bật ringback adb_signals; healthcheck thiết bị chưa chạy.')
