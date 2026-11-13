#!/usr/bin/env python3
"""Thu semantics banner đối chứng để kiểm tra absence; không chạy lại testcase PASS."""
import sys
import signal
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tammi_runner.cases import select_cases
from tammi_runner.cli import Context
from tammi_runner.common import load_config,Reporter,save_private_json
from tammi_runner.full_runner import FullRun
from tammi_runner.runtime import RunLock
cfg=load_config();reporter=Reporter(cfg);ctx=Context(cfg,reporter,None)
for signum in (signal.SIGINT,signal.SIGTERM):signal.signal(signum,lambda *_:setattr(ctx,'cancelled',True))
case=replace(select_cases(['CHAT-023-SAME_CONVERSATION'])[0],id='DIAG-NOTIFICATION-CONTAINER',sources=(),obligations=())
with RunLock():
    try:
        run=FullRun(ctx,case);a,b=run.pair();run.ui('B').open_named(cfg['groups']['primary'])
        def capture():
            b.find(b.text_locator(run.marker),timeout=35)
            return b.driver.page_source
        with ThreadPoolExecutor(max_workers=1) as worker:
            waiting=worker.submit(capture);a.send(run.marker);source=waiting.result()
        save_private_json(reporter.directory/'banner-source.json',{'marker':run.marker,'source':source})
        reporter.emit('diagnostic','Đã thu semantics banner đối chứng; không tính PASS sản phẩm.')
    except BaseException:
        ctx.evidence(case.id);raise
    finally:ctx.close();reporter.finish()
