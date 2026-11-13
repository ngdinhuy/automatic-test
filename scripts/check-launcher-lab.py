#!/usr/bin/env python3
"""Chỉ đọc launcher phục vụ probe badge, không gửi tin hoặc tính PASS sản phẩm."""
import argparse
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tammi_runner.common import Reporter,load_config,save_private_json,find_adb
from tammi_runner.cli import Context
from tammi_runner.runtime import RunLock

parser=argparse.ArgumentParser();parser.add_argument('--drawer-only',action='store_true');args=parser.parse_args()
cfg=load_config();reporter=Reporter(cfg);ctx=Context(cfg,reporter,None)
with RunLock():
    try:
        b=ctx.page('B');b.require_idle_call();b.driver.press_keycode(3)
        save_private_json(reporter.directory/'launcher-home.json',{'source':b.driver.page_source,'scope':'Nguồn launcher native; chưa chạy testcase unread.'})
        size=b.driver.get_window_size()
        b.driver.execute_script('mobile: swipeGesture',{'left':int(size['width']*.1),'top':int(size['height']*.3),'width':int(size['width']*.8),'height':int(size['height']*.6),'direction':'up','percent':.8})
        save_private_json(reporter.directory/'launcher-drawer.json',{'source':b.driver.page_source})
        b.driver.execute_script('mobile: swipeGesture',{'left':int(size['width']*.05),'top':int(size['height']*.25),'width':int(size['width']*.9),'height':int(size['height']*.4),'direction':'left','percent':.8})
        save_private_json(reporter.directory/'launcher-page2.json',{'source':b.driver.page_source})
        if not args.drawer_only:
            b.click('//*[@resource-id="com.sec.android.app.launcher:id/app_search_edit_text"]',stable_bounds=True)
            b.wait(lambda:b.driver.is_keyboard_shown(),'Chưa focus ô tìm kiếm launcher.')
            if b.driver.current_package not in ('com.sec.android.app.launcher','com.samsung.android.app.galaxyfinder'):raise RuntimeError('Không nhập query ngoài launcher test.')
            subprocess.run([find_adb(cfg),'-s',cfg['devices']['B']['udid'],'shell','input','text','Tammi'],check=True,timeout=10)
            b.wait(lambda:'Tammi' in b.driver.page_source,'Chưa có kết quả launcher cho Tammi.',timeout=10)
            save_private_json(reporter.directory/'launcher-search.json',{'source':b.driver.page_source})
            field=b.elements('//*[@resource-id="com.sec.android.app.launcher:id/search_src_text"]')
            if len(field)==1 and field[0].get_attribute('text')=='Tammi':
                b.click('//*[@resource-id="com.sec.android.app.launcher:id/search_close_btn"]')

    finally:
        try:
            if 'B' in ctx.pages:
                b=ctx.pages['B'];b.driver.press_keycode(3);b.driver.activate_app(cfg['app_package'])
        except Exception as error:reporter.emit('warning','Không trở về staging: '+str(error))
        finally:ctx.close();reporter.finish()
