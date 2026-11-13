#!/usr/bin/env python3
"""Dọn cuộc gọi test còn treo, chỉ với thiết bị và case có bằng chứng trong report chỉ định."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tammi_runner.cli import Context
from tammi_runner.common import Blocked, Reporter, load_config, list_devices, validate_devices
from tammi_runner.runtime import RunLock


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report',required=True);parser.add_argument('--case',required=True)
    args=parser.parse_args();folder=Path(args.report).resolve();cfg=load_config()
    row=next((r for r in json.loads((folder/'summary.json').read_text())['results'] if r['id']==args.case),None)
    if not row or not args.case.startswith('CALL-') or row['status'] not in ('FAIL','ERROR','CANCELLED'):
        raise Blocked('Cần một case Call lỗi/chưa hoàn tất có report của chính runner.')
    log=(folder/'appium.log').read_text()
    if any(cfg['devices'][role]['udid'] not in log for role in ('A','B')):raise Blocked('Thiết bị hiện tại khác report, không dọn call.')
    validate_devices(cfg,list_devices(cfg),('A','B'))
    reporter=Reporter(cfg);ctx=Context(cfg,reporter,None)
    with RunLock():
        try:
            # Phiên trước đã xác minh A/B và tạo call này; dọn trước để có thể mở hồ sơ xác minh lại.
            ctx.owned_call_roles.update(('A','B'))
            for role in ('A','B'):ctx.page(role).end_owned_call()
            for role in ('A','B'):ctx.page(role).login_and_verify()
            ctx.owned_call_roles.clear()
            reporter.emit('step','Đã dọn cuộc gọi của report, xác minh lại tài khoản; không tính PASS testcase.')
        finally:ctx.close();reporter.finish()

if __name__=='__main__':main()
