#!/usr/bin/env python3
"""Đối chiếu ảnh tải từ máy nhận với fixture/ảnh camera gốc; không suy từ icon hoặc screenshot."""
import hashlib
import json
import math
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QImageReader
from tammi_runner.cases import CASES
from tammi_runner.common import find_adb, save_private_json, sha256_file


def adb(payload,role,*args):
    if args[0]=='shell':args=('shell',shlex.join(map(str,args[1:])))
    result=subprocess.run([find_adb({'tools':payload.get('tools',{})}),'-s',payload['devices'][role],*map(str,args)],capture_output=True,text=True,timeout=30,check=True)
    return result.stdout


def images(payload,role):
    output=adb(payload,role,'shell','content','query','--uri','content://media/external/images/media','--projection','_id:_data:_display_name:_size')
    rows=[]
    for line in output.splitlines():
        match=re.search(r'_id=(\d+), _data=(.*?), _display_name=(.*?), _size=(\d+)',line)
        if match:rows.append({'id':int(match[1]),'path':match[2],'name':match[3],'bytes':int(match[4])})
    return rows


def camera_files(payload):
    package=payload.get('app_package','com.viettel.appviettel.staging')
    if not re.fullmatch(r'[A-Za-z0-9_.]+',package):raise AssertionError('Package camera không hợp lệ.')
    root='/sdcard/Android/data/'+package+'/files/'
    try:output=adb(payload,'A','shell','find',root,'-maxdepth','1','-type','f','-name','IMG_*.jpg')
    except subprocess.CalledProcessError as error:
        if 'No such file or directory' in (error.stderr or ''):return []
        raise
    return [line for line in output.splitlines() if line.startswith(root+'IMG_') and line.endswith('.jpg')]


def decode(path):
    reader=QImageReader(str(path));reader.setAutoTransform(True);image=reader.read()
    if image.isNull():raise AssertionError('File nhận không giải mã được thành ảnh: '+path.name)
    return image


def pixel_digest(image):
    rgba=image.convertToFormat(QImage.Format.Format_RGBA8888)
    return hashlib.sha256(bytes(rgba.constBits())).hexdigest()


def similarity(first,second):
    def pixels(image):
        result=image.scaled(64,64,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation).convertToFormat(QImage.Format.Format_RGB888)
        return bytes(result.constBits())
    a,b=pixels(first),pixels(second);ma,mb=sum(a)/len(a),sum(b)/len(b)
    covariance=sum((x-ma)*(y-mb) for x,y in zip(a,b))
    variance=math.sqrt(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))
    correlation=covariance/variance if variance else float(a==b)
    error=sum(abs(x-y) for x,y in zip(a,b))/(len(a)*255)
    aspect_error=abs(first.width()/first.height()-second.width()/second.height())
    return {'correlation':correlation,'mean_absolute_error':error,'aspect_error':aspect_error}


def original_paths(payload,case,state,folder):
    kind=case.params.get('media');fixture=payload.get('fixtures',{}).get(kind,{})
    if kind=='camera_photo':
        if state.get('camera_reference'):
            return [Path(state['camera_reference'])]
        candidates=[row for row in images(payload,'A') if row['id'] not in state['before_A'] and row['bytes']>0]
        if len(candidates)!=1:raise AssertionError('Không xác định duy nhất ảnh camera mới lưu ở A để đối chiếu.')
        path=folder/'camera-reference.jpg';adb(payload,'A','pull',candidates[0]['path'],path)
        return [path]
    paths=[Path(fixture['path']).expanduser()]
    if kind=='multiple_images':paths.append(Path(fixture['second_path']).expanduser())
    return [path if path.is_absolute() else ROOT/path for path in paths]


def main(payload):
    if payload.get('case_id') in ('CHAT-006-CAMERA_VIDEO','VIDEO-FILE-OVER-100MB'):
        from video_integrity import main as video_main
        return video_main(payload)
    marker=payload['marker']
    if not re.fullmatch(r'APPIUM-[a-f0-9]{12}',marker):raise AssertionError('Marker probe không hợp lệ.')
    case=next(case for case in CASES if case.id==payload['case_id'])
    phase=payload['phase'];folder=Path(payload['report_directory'])/('media-'+marker);folder.mkdir(parents=True,exist_ok=True)
    state_path=folder/'state.json';result={'schema':1,'challenge':payload['challenge'],'measurements':{}}
    if phase=='prepare':
        if case.params.get('media') in ('camera_video','video_over_1000mb'):
            result['blocked']='Adapter tích hợp hiện chỉ giải mã ảnh; video cần adapter giải mã/đối chiếu riêng.';return result
        kind=case.params.get('media')
        if kind!='camera_photo':
            fixture=payload.get('fixtures',{}).get(kind,{})
            candidates=[fixture.get('path')]+([fixture.get('second_path')] if kind=='multiple_images' else [])
            for value in candidates:
                if not value:
                    result['blocked']='Thiếu đường dẫn fixture ảnh.';return result
                path=Path(value).expanduser();path=path if path.is_absolute() else ROOT/path
                try:decode(path)
                except Exception:
                    result['blocked']='Fixture không phải ảnh giải mã được: '+path.name;return result
        save_private_json(state_path,{'before_A':[r['id'] for r in images(payload,'A')],'before_B':[r['id'] for r in images(payload,'B')],'owned_received':[],'before_camera_files':camera_files(payload) if kind=='camera_photo' else []})
        return result
    if not state_path.exists():raise AssertionError('Thiếu snapshot trước gửi ảnh.')
    state=json.loads(state_path.read_text())
    if phase=='capture_reference':
        fresh=set(camera_files(payload))-set(state.get('before_camera_files',[]))
        if len(fresh)!=1:
            result['blocked']='Không xác định duy nhất file camera tạm mới của staging để lấy reference.';return result
        reference=folder/'camera-reference.jpg';source=next(iter(fresh))
        adb(payload,'A','pull',source,reference);decode(reference)
        state['camera_reference']=str(reference);state['camera_source']=source;save_private_json(state_path,state)
        return result
    if phase=='cleanup':
        warnings=[]
        for row in state['owned_received']:
            # Chỉ xóa ID đã xác nhận khớp ảnh test; không xóa theo thời gian hoặc wildcard.
            try:adb(payload,'B','shell','content','delete','--uri','content://media/external/images/media/'+str(row['id']))
            except Exception as error:warnings.append('Giữ ảnh test đã tải ở B vì không dọn được ID '+str(row['id']))
        result['cleanup_warnings']=warnings;return result
    paths=original_paths(payload,case,state,folder)
    deadline=time.monotonic()+40;received=[]
    while time.monotonic()<deadline:
        received=[r for r in images(payload,'B') if r['id'] not in state['before_B'] and r['bytes']>0]
        if len(received)>=len(paths):break
        time.sleep(.5)
    if len(received)!=len(paths):raise AssertionError('Số ảnh mới tải ở B khác số fixture; không đoán file để PASS.')
    references=[decode(path) for path in paths];unused=set(range(len(paths)));proof=[];all_checksums=True;all_pixels=True;total=0
    for row in received:
        if not row['path'].startswith(('/storage/emulated/0/','/sdcard/')):raise AssertionError('File nhận không nằm trong bộ nhớ media public.')
        path=folder/('received-'+str(row['id'])+Path(row['path']).suffix);adb(payload,'B','pull',row['path'],path)
        image=decode(path);matches=[(index,similarity(references[index],image)) for index in unused]
        index,metrics=max(matches,key=lambda item:item[1]['correlation'])
        assert metrics['correlation']>=.95 and metrics['mean_absolute_error']<=.08 and metrics['aspect_error']<=.01,'Nội dung ảnh nhận không khớp fixture.'
        unused.remove(index);state['owned_received'].append(row);save_private_json(state_path,state)
        digest=sha256_file(path);expected=sha256_file(paths[index])
        decoded=pixel_digest(image);reference_decoded=pixel_digest(references[index])
        pixels_equal=(image.width(),image.height(),decoded)==(references[index].width(),references[index].height(),reference_decoded)
        all_pixels=all_pixels and pixels_equal
        all_checksums=all_checksums and digest==expected;total+=path.stat().st_size
        proof.append({'decoded_sha256':decoded,'reference_decoded_sha256':reference_decoded,'file':path.name,'bytes':path.stat().st_size,'sha256':digest,'reference_sha256':expected,'width':image.width(),'height':image.height(),**metrics})
    result['measurements']={'decodable':1,'received_bytes':total,'checksum_matches':int(all_checksums),'exact_pixels_match':int(all_pixels),'content_matches':int(not unused)}
    if case.params.get('media')=='camera_photo':
        saved=False;until=time.monotonic()+(10 if case.params.get('save_camera') else 0)
        while True:
            public=[row for row in images(payload,'A') if row['id'] not in state['before_A'] and row['bytes']>0]
            for row in public:
                path=folder/('camera-public-'+str(row['id'])+'.jpg')
                adb(payload,'A','pull',row['path'],path)
                metrics=similarity(references[0],decode(path))
                if metrics['correlation']>=.95 and metrics['mean_absolute_error']<=.08 and metrics['aspect_error']<=.01:saved=True;break
            if saved or time.monotonic()>=until:break
            time.sleep(.5)
        result['measurements']['camera_public_saved']=int(saved)
    result['files']=proof;return result


if __name__=='__main__':
    data=json.load(sys.stdin)
    try:answer=main(data)
    except Exception as error:
        print(type(error).__name__+': '+str(error),file=sys.stderr);sys.exit(1)
    print(json.dumps(answer,ensure_ascii=False))
