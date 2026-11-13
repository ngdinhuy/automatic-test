#!/usr/bin/env python3
"""Chẩn đoán control khi video tắt hai camera, không tính PASS cho bài gọi 15 phút."""
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
from tammi_runner.runtime import RunLock


def main():
    cfg=load_config();reporter=Reporter(cfg);ctx=Context(cfg,reporter,None)
    for signum in (signal.SIGINT,signal.SIGTERM):signal.signal(signum,lambda *_:setattr(ctx,'cancelled',True))
    case=replace(select_cases(['CALL-040-CAMERA_OFF'])[0],id='DIAG-CAMERA-OFF-CONTROLS',sources=(),obligations=())
    with RunLock():
        try:
            for role in ('A','B'):ctx.page(role).require_idle_call()
            run=FullRun(ctx,case);a,b=run.start_call(kind='video');run.answer(a,b)
            def active(value):
                measured=run.probe('camera_capture')
                return all((measured[role+'_active_clients']>=1 if value else measured[role+'_active_clients']==0) for role in ('A','B'))
            a.wait(lambda:active(True),'Camera chưa active ở cả hai máy.')
            for role in ('A','B'):run.page(role).reveal_call_controls();run.ui(role).click('camera_toggle')
            a.wait(lambda:active(False),'Camera chưa tắt ở cả hai máy.')
            run.devices.wait_seconds(8,'Chẩn đoán: chờ control tự ẩn; không phải bài 15 phút.')
            for page in (a,b):page.wait_connected()
            run.stop_call(a,b)
            save_private_json(reporter.directory/'diagnostic.json',{'ok':True,'scope':'Chỉ kiểm tra hiện lại control/timer và kết thúc khi camera off; không tính PASS sản phẩm.'})
            reporter.emit('diagnostic','Đã kiểm tra control camera off; không cộng vào số case PASS.')
        except BaseException:
            ctx.evidence('DIAG-CAMERA-OFF-CONTROLS');raise
        finally:ctx.close();reporter.finish()
    return 0

if __name__=='__main__':raise SystemExit(main())
