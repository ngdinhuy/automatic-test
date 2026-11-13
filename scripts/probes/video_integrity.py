#!/usr/bin/env python3
"""Snapshot video trước test, tải file mới đúng marker rồi giải mã và đối chiếu nội dung."""
import json
import re
import time
from pathlib import Path

from media_integrity import adb,similarity
from tammi_runner.common import ROOT,save_private_json,sha256_file
from tammi_runner.video import decode,sample


def videos(payload,role):
    text=adb(payload,role,'shell','content','query','--uri','content://media/external/video/media',
             '--projection','_id:_data:_display_name:_size','--where','is_pending=0')
    rows=[]
    for line in text.splitlines():
        match=re.search(r'_id=(\d+), _data=(.*?), _display_name=(.*?), _size=(\d+)',line)
        if match:rows.append({'id':int(match[1]),'path':match[2],'name':match[3],'bytes':int(match[4])})
    return rows


def camera_files(payload):
    package=payload['app_package']
    if not re.fullmatch('[A-Za-z0-9_.]+',package):raise AssertionError('Package không hợp lệ.')
    root='/sdcard/Android/data/'+package+'/files/'
    text=adb(payload,'A','shell','find',root,'-maxdepth','1','-type','f','-name','VIDEO_*.mp4')
    return [line for line in text.splitlines() if line.startswith(root+'VIDEO_') and line.endswith('.mp4')]


def compare(source,received,folder,source_info=None):
    source_info=source_info or decode(source)
    same=sha256_file(source)==sha256_file(received)
    received_info=source_info if same else decode(received)
    error=abs(source_info['duration_seconds']-received_info['duration_seconds'])
    assert error<=max(.5,source_info['duration_seconds']*.002),'Video nhận bị cắt/thay đổi thời lượng.'
    assert not source_info['has_audio'] or received_info['has_audio'],'Video nhận mất track audio.'
    proof=[]
    for index,fraction in enumerate((.02,.25,.5,.75,.98)):
        duration=min(source_info['duration_seconds'],received_info['duration_seconds'])
        # Audio padding có thể dài hơn frame video cuối; không seek sau frame cuối ở clip ngắn.
        seconds=min(duration*fraction,max(0,duration-.25))
        first=sample(source,seconds,folder/f'reference-{index}.png')
        second=sample(received,seconds,folder/f'received-{index}.png')
        scores=similarity(first,second)
        assert scores['correlation']>=.90 and scores['mean_absolute_error']<=.10 and scores['aspect_error']<=.025,'Frame video không khớp nguồn.'
        proof.append({'seconds':seconds,**scores})
    return {'source':source_info,'received':received_info,'duration_error_seconds':error,
            'checksum_matches':int(same),'samples':proof,'received_sha256':sha256_file(received)}


def main(payload):
    marker=payload['marker']
    if not re.fullmatch('APPIUM-[a-f0-9]{12}',marker):raise AssertionError('Marker không hợp lệ.')
    folder=Path(payload['report_directory'])/('video-'+marker);folder.mkdir(parents=True,exist_ok=True)
    state_path=folder/'state.json';phase=payload['phase']
    result={'schema':1,'challenge':payload['challenge'],'measurements':{}}
    if not all(payload.get('devices',{}).get(role) for role in ('A','B')):
        result['blocked']='Probe video cần đủ hai thiết bị A/B đã cấu hình.';return result
    if phase=='prepare':
        state={'before_B':[r['id'] for r in videos(payload,'B')],'owned_received':[]}
        if payload.get('fixture')=='camera_video' or payload.get('case_id')=='CHAT-006-CAMERA_VIDEO':
            state['before_camera']=camera_files(payload)
        else:
            path=Path(payload['fixtures']['gallery_video']['path']).expanduser()
            path=path if path.is_absolute() else ROOT/path
            state.update(reference=str(path),reference_info=decode(path))
        save_private_json(state_path,state);return result
    if not state_path.exists():raise AssertionError('Thiếu snapshot video trước gửi.')
    state=json.loads(state_path.read_text())
    if phase=='capture_reference':
        files=set(camera_files(payload))-set(state.get('before_camera',[]))
        if len(files)!=1:raise AssertionError('Không xác định duy nhất file camera video mới.')
        reference=folder/'camera-reference.mp4';adb(payload,'A','pull',next(iter(files)),reference)
        state.update(reference=str(reference),reference_info=decode(reference));save_private_json(state_path,state);return result
    if phase=='cleanup':
        for row in state['owned_received']:
            adb(payload,'B','shell','content','delete','--uri','content://media/external/video/media/'+str(row['id']))
        return result
    deadline=time.monotonic()+180
    while True:
        fresh=[r for r in videos(payload,'B') if r['id'] not in state['before_B'] and r['bytes']>0]
        if fresh or time.monotonic()>=deadline:break
        time.sleep(.5)
    save_private_json(folder/'received-candidates.json',{'new_videos':fresh})
    if len(fresh)!=1:raise AssertionError('Cần đúng 1 video mới lưu ở B, thực tế: '+str(len(fresh)))
    row=fresh[0]
    if not row['path'].startswith(('/storage/emulated/0/','/sdcard/')):raise AssertionError('Video nhận không thuộc media public.')
    local=folder/'received.mp4';adb(payload,'B','pull',row['path'],local)
    proof=compare(Path(state['reference']),local,folder,state['reference_info'])
    state['owned_received'].append(row);save_private_json(state_path,state)
    result['proof']=proof
    result['measurements']={'decodable':1,'received_bytes':local.stat().st_size,
                            'checksum_matches':proof['checksum_matches'],'content_matches':1,
                            'duration_error_seconds':proof['duration_error_seconds'],'decoded_frames':proof['received']['frames']}
    return result
