#!/usr/bin/env python3
"""Chẩn đoán tạo/kết thúc phòng Meet mới, không chạy lại testcase sản phẩm."""
import json
import signal
import sys
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tammi_runner.cases import select_cases
from tammi_runner.cli import Context
from tammi_runner.common import load_config,Reporter,save_private_json
from tammi_runner.full_runner import FullRun
from tammi_runner.rich_flows import meeting_start,end_meeting
from tammi_runner.runtime import RunLock


def main():
    cfg=load_config();reporter=Reporter(cfg);ctx=Context(cfg,reporter,None)
    for signum in (signal.SIGINT,signal.SIGTERM):signal.signal(signum,lambda *_:setattr(ctx,'cancelled',True))
    case=replace(select_cases(['CALL-041-CAMERA_OFF'])[0],id='DIAG-MEETING-CONTROLS',sources=(),obligations=())
    with RunLock():
        try:
            for role in ('A','B'):ctx.page(role).require_idle_call()
            run=FullRun(ctx,case)
            meeting_start(run)
            end_meeting(run)
            save_private_json(reporter.directory/'diagnostic.json',{'ok':True,'scope':'Tạo/join/kết thúc Meet mới chỉ A/B; không chạy bài 15 phút hoặc tính PASS sản phẩm.'})
            reporter.emit('diagnostic','Đã kiểm tra kết thúc phòng Meet mới; không cộng testcase PASS.')

        except BaseException:
            ctx.evidence('DIAG-MEETING-CONTROLS');raise
        finally:ctx.close();reporter.finish()
    return 0

if __name__=='__main__':raise SystemExit(main())
