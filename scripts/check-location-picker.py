#!/usr/bin/env python3
"""Hiệu chỉnh picker vị trí giả lập, chưa gửi vị trí và không tính PASS sản phẩm."""
import argparse
import signal
import sys
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tammi_runner.cases import select_cases
from tammi_runner.cli import Context
from tammi_runner.common import load_config,Reporter,save_private_json
from tammi_runner.full_runner import FullRun
from tammi_runner.location_lab import FIXTURE,prepare
from tammi_runner.runtime import RunLock

parser=argparse.ArgumentParser();parser.add_argument('--select-current',action='store_true');args=parser.parse_args()
cfg=load_config();cfg.setdefault('lab',{})['location']=dict(FIXTURE)
reporter=Reporter(cfg);ctx=Context(cfg,reporter,None)
for signum in (signal.SIGINT,signal.SIGTERM):signal.signal(signum,lambda *_:setattr(ctx,'cancelled',True))
case=replace(select_cases(['CHAT-031-PEER_CURRENT'])[0],id='DIAG-LOCATION-PICKER',sources=(),obligations=())
with RunLock():
    try:
        for role in ('A','B'):
            page=ctx.page(role);page.require_idle_call();page.allow_test_permission();page.home()
        run=FullRun(ctx,case);a,b=run.pair();prepare(run)
        u=run.ui('A');u.click('attachment');u.click('location')
        def picker_ready():
            a.allow_test_permission()
            return bool(a.elements(a.text_locator('Vị trí hiện tại của bạn')))
        a.wait(picker_ready,'Chưa mở được picker vị trí sau khi cấp quyền.',timeout=25)
        if args.select_current:
            a.click(a.text_locator('Vị trí hiện tại của bạn'),stable_bounds=True)
            a.find(a.text_locator('Chia sẻ vị trí hiện tại'))
        ctx.evidence(case.id)
        save_private_json(reporter.directory/'diagnostic.json',{'scope':'Chỉ mở picker vị trí giả lập; chưa gửi, không PASS sản phẩm.'})
    except BaseException:
        ctx.evidence(case.id);raise
    finally:
        for role in ('A','B'):
            try:
                page=ctx.page(role);page.allow_test_permission();page.home()
            except Exception as error:reporter.emit('warning','Không trở về màn chính: '+str(error))
        ctx.close();reporter.finish()
