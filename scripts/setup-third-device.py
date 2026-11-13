#!/usr/bin/env python3
"""Xác minh C; tùy chọn gửi marker hiệu chỉnh row, không thực hiện cuộc gọi."""
import argparse,sys,time,signal,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tammi_runner.common import DEFAULT_CONFIG,load_config,save_private_json,Reporter,Blocked
from tammi_runner.pages import literal
from tammi_runner.cli import Context
from tammi_runner.runtime import RunLock

parser=argparse.ArgumentParser()
parser.add_argument('--seed-peer-rows',action='store_true')
parser.add_argument('--verify-outgoing-peers',action='store_true',help='Mở hội thoại A và B trên C theo số đã cấu hình, không gửi tin.')
args=parser.parse_args()
cfg=load_config();reporter=Reporter(cfg);ctx=Context(cfg,reporter,None)
for signum in (signal.SIGINT,signal.SIGTERM):signal.signal(signum,lambda *_:setattr(ctx,'cancelled',True))
with RunLock():
    try:
        page=ctx.page('C');page.require_idle_call();page.login_and_verify()
        start=time.monotonic();page.driver.page_source;latency=time.monotonic()-start
        names={}
        for role in ('A','B'):
            peer=ctx.page(role);peer.require_idle_call();peer.login_and_verify();peer.open_peer(peer_role='C')
            names[role]=peer.peer_name
            if args.seed_peer_rows:
                marker='APPIUM-'+uuid.uuid4().hex[:12]+'-setup-C'
                page.home();peer.send(marker)
                locator='//*[@clickable="true" and contains(@content-desc,'+literal(marker)+')]'
                row=page.find(locator,timeout=40);label=row.get_attribute('content-desc')
                title,separator,_=label.partition(', '+marker)
                if not title or not separator:raise Blocked('Chưa đọc được tên row C theo marker đối chứng.')
                page.click(locator,stable_bounds=True);page.message_received(marker)
                cfg['lab'].setdefault('verified_peer_rows',{}).setdefault('C',{})[role]={'name':title,'peer_phone':cfg['devices'][role]['account']['phone'],'viewer_phone':cfg['devices']['C']['account']['phone']}
                page.home()
            peer.home()
        if args.verify_outgoing_peers:
            for role in ('A','B'):
                page.home()
                page.open_peer(peer_role=role)
                reporter.emit('setup',f'C mở được hội thoại {role} theo số tài khoản staging.')
        cfg['lab'].setdefault('member_names',{})['C']=names['A']
        for role,name in names.items():cfg['lab'].setdefault('member_names_by_viewer',{}).setdefault(role,{})['C']=name
        save_private_json(DEFAULT_CONFIG,cfg)
        save_private_json(reporter.directory/'third-device-setup.json',{'account_verified':True,'source_seconds':latency,'caller_names':names,'scope':'C phụ; A/B là cặp chính. Chỉ setup, chưa chạy testcase.'})
        reporter.emit('setup','Đã xác minh C và tên hiển thị trên A/B.',source_seconds=latency,caller_names=names)
    except BaseException:
        ctx.evidence('SETUP-C');raise
    finally:
        try:
            for page in ctx.pages.values():
                try:page.home()
                except Exception as error:reporter.emit('warning','Không trở về home: '+str(error))
        finally:ctx.close();reporter.finish()
