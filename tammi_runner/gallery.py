"""Chọn media fixture theo MediaStore và bounds ô camera; không chạm ảnh khác của người dùng."""
import re
from xml.etree import ElementTree as ET

from .common import Blocked


def cell_after_camera(camera,screen_width,index):
    x,y,w,h=(camera[key] for key in ('x','y','width','height'))
    gap=(screen_width-2*x-4*w)/3
    if index not in (1,2) or abs(w-h)>4 or not 0<=gap<=20 or w<40:
        raise Blocked('Grid media không còn cấu trúc 4 cột đã đối chiếu source; cần hiệu chỉnh selector.')
    return {'x':round(x+(w+gap)*index+w/2),'y':round(y+h/2)}


def select(run,paths):
    a=run.page('A');u=run.ui('A');names=[]
    for index,path in enumerate(paths):
        name=run.marker+f'-{index}'+path.suffix.lower();remote='/sdcard/Pictures/'+name
        run.devices.remember('A','shell','rm','-f',remote)
        run.devices.adb('A','push',path,remote)
        run.devices.adb('A','shell','am','broadcast','-a','android.intent.action.MEDIA_SCANNER_SCAN_FILE','-d','file://'+remote)
        names.append(name)
    def owned_first():
        output=run.devices.adb('A','shell','content','query','--uri','content://media/external/file','--projection','_display_name:date_added','--where','media_type=1 OR media_type=3','--sort','date_added DESC')
        first=re.findall(r'_display_name=([^,\n]+)',output)[:len(names)]
        return len(first)==len(names) and set(first)==set(names)
    a.wait(owned_first,'Fixture chưa là media mới nhất; không chọn theo index khi có thể chạm ảnh khác.',timeout=25)
    u.click('attachment');u.click('image');a.allow_test_permission()
    camera=a.find('//*[@content-desc="Mở camera"]/ancestor::*[@clickable="true"][1]')
    box=camera.rect;width=a.driver.get_window_size()['width']
    for index in range(1,len(names)+1):
        if not owned_first():raise Blocked('Thứ tự media đổi khi đang chọn; dừng để không chọn file ngoài run.')
        point=cell_after_camera(box,width,index)
        a.driver.execute_script('mobile: clickGesture',point)
        # Số thứ tự chọn phải nằm đúng trong ô vừa chạm, không nhận badge ở chỗ khác.
        def selected():
            if run.p.get("reject") and u.exists("media_limit_error"):return True
            for node in ET.fromstring(a.driver.page_source).iter():
                if node.get('text')!=str(index):continue
                bounds=list(map(int,re.findall(r'\d+',node.get('bounds',''))))
                if len(bounds)==4 and abs((bounds[0]+bounds[2])/2-point['x'])<=box['width']/2 and abs((bounds[1]+bounds[3])/2-point['y'])<=box['height']/2:return True
            return False
        a.wait(selected,'Không xác minh được thứ tự chọn fixture trên đúng ô media.',timeout=8)
    return names
