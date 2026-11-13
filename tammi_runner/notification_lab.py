"""Nhận diện banner native bằng đối chứng thật; không dùng bubble để chứng minh absence."""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree as ET
from .common import Blocked,save_private_json


def containers(source,width,height,peer):
    found=[]
    for node in ET.fromstring(source).iter():
        if node.get('class')!='android.view.View' or node.get('clickable')!='true' or node.get('long-clickable')!='true':continue
        rect=list(map(int,re.findall(r'\d+',node.get('bounds',''))))
        if len(rect)!=4:continue
        x,y,right,bottom=rect
        texts=[child.get('text','') for child in node.iter() if child.get('class')=='android.widget.TextView']
        # Banner overlay sát đỉnh, gần tràn chiều ngang; bubble chat không có hình học này.
        if x<=width*.05 and right>=width*.95 and 0<=y<height*.2 and bottom<=height*.25 and peer in texts and len(texts)>=2:
            found.append(node)
    return found


def same_conversation(run,a,b):
    peer=b.peer_name;size=b.driver.get_window_size();width,height=size['width'],size['height']
    group=run.ctx.config.get('groups',{}).get('primary')
    if not group or group==peer:raise Blocked('Cần nhóm đối chứng khác hội thoại peer.')
    control=run.marker+'-control';run.ui('B').open_named(group)
    def positive():
        b.find(b.text_locator(control),timeout=35)
        return b.driver.page_source
    with ThreadPoolExecutor(max_workers=1) as worker:
        waiting=worker.submit(positive);a.send(control);source=waiting.result()
    positive_rows=containers(source,width,height,peer)
    if len(positive_rows)!=1 or control not in ET.tostring(positive_rows[0],encoding='unicode'):
        raise Blocked('Chưa nhận diện duy nhất banner đối chứng; không kiểm tra absence bằng locator chưa xác minh.')
    save_private_json(run.ctx.reporter.directory/'notification-positive.json',{'marker':control,'source':source,'scope':'Đối chứng của case same-conversation, không phải testcase PASS riêng.'})
    b.open_peer(peer_role='A')
    if b.peer_name!=peer or b.conversation_name:
        raise Blocked('Chưa xác minh đã rời nhóm đối chứng để vào đúng hội thoại peer A.')
    b.wait(lambda:not containers(b.driver.page_source,width,height,peer),'Banner đối chứng chưa đóng.',timeout=10)
    ready=threading.Event()
    def observe():
        samples=[];received=None;start=time.monotonic()
        while time.monotonic()-start<45:
            run.ctx.check();current=b.driver.page_source;now=time.monotonic()
            banners=containers(current,width,height,peer)
            assert not banners,'Có banner thông báo khi đang mở chính hội thoại gửi tin.'
            samples.append(now);ready.set()
            nodes=ET.fromstring(current).iter()
            if received is None and any(n.get('class')!='android.widget.EditText' and run.marker in (n.get('text','')+' '+n.get('content-desc','')) and control not in (n.get('text','')+' '+n.get('content-desc','')) for n in nodes):received=now
            if received is not None and now-received>=5:
                gap=max((y-x for x,y in zip(samples,samples[1:])),default=99)
                if gap>2.5:raise Blocked('Khoảng trống lấy mẫu quá dài để chứng minh không có banner.')
                return {'samples':len(samples),'observed_seconds':now-start,'after_received_seconds':now-received,'maximum_gap_seconds':gap,'banner_count':0}
            time.sleep(.1)
        raise AssertionError('Chưa nhận tin test trong cửa sổ theo dõi banner.')
    with ThreadPoolExecutor(max_workers=1) as worker:
        waiting=worker.submit(observe)
        if not ready.wait(10):
            if waiting.done():waiting.result()
            raise Blocked('Watcher chưa sẵn sàng trước khi gửi tin.')
        a.send(run.marker);values=waiting.result()
    save_private_json(run.ctx.reporter.directory/'notification-absence.json',values)
    run.ctx.reporter.emit('step','Đã theo dõi banner liên tục trước gửi đến sau nhận 5 giây.',measurements=values)
