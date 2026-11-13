"""Kiểm tra điều kiện lab thật; trạng thái cấu hình không phải PASS testcase."""
import json
import re
import subprocess
import sys
from pathlib import Path

from .common import ROOT, find_adb, list_devices, save_private_json
from .probes import REQUIRED, command


NEEDS = {
    "location_destination":"ADB + Google Maps trên B; đọc điểm đích của card vị trí mới, không dùng GPS B.",
    "camera_capture":"CameraService active clients trên A/B theo package/PID; không đo FPS/hình bên nhận.",
    "android_signals":"ADB trên máy nhận; đọc UID playback và sự kiện rung mới, chưa đo âm thanh/rung vật lý.",
    "audio_duplex": "ADB trên A/B để đọc tín hiệu thu và phát của client thoại theo UID.",
    "voice_playback": "File âm thanh chuẩn, đường thu playback thật để đối chiếu tương quan/thời lượng.",
    "voice_playback_signal": "ADB trên B đọc player media theo UID trước, trong và sau phát lại tin thoại.",
    "video_duplex": "Nguồn hình chuẩn và thu hình hai đầu, đo FPS và độ tương đồng khuôn mặt.",
    "ringback": "ADB máy gọi: UID/player trước–trong–sau, muted, volume/route nếu expose; không cần mic C, không đo RMS/SNR.",
    "incoming_alert": "Đường thu âm máy nhận và cảm biến rung; đo theo từng chế độ chuông.",
    "notification_alert": "ADB máy B đọc event âm thanh và rung theo key của thông báo staging mới.",
    "audio_routes": "Tai nghe dây/USB và Bluetooth trên máy gọi. ADB xác minh route thoại và mức âm lượng theo route.",
    "launcher_badge": "Adapter đọc badge của launcher đúng thiết bị; không thay bằng số notification.",
    "media_audio_focus": "Nguồn media và đường thu riêng để đo ducking cùng âm thanh cuộc gọi.",
    "location_live": "Nguồn vị trí thay đổi và adapter kiểm chứng cập nhật ở máy nhận.",
    "whatsapp_call": "Tài khoản WhatsApp test và adapter xác minh cuộc gọi đang hoạt động.",
    "zero_data_sim": "SIM hết quota và nguồn xác minh quota thực tế từ nhà mạng.",
    "meeting_web": "Trình duyệt/tài khoản web test, adapter xác minh thành viên và frame chia sẻ.",
    "meeting_media": "Adapter thu âm/hình cuộc họp và đối chiếu trạng thái mic/camera.",
}


def security(policy, fingerprint, face):
    matches=re.findall(r"^\s*secure=(true|false)\s*$",policy,re.M)
    def enrolled(text):
        if "Can't find service" in text or "not found" in text.lower():return None
        counts=re.findall(r'"count"\s*:\s*(\d+)',text)
        return sum(map(int,counts)) if counts else None
    return {"secure":matches[-1]=="true" if matches else None,
            "fingerprints":enrolled(fingerprint),"faces":enrolled(face)}


def probe_inventory(config):
    rows=[]
    for name in REQUIRED:
        row={"name":name,"status":"NOT_CONFIGURED","measurements":list(REQUIRED[name]),
             "needs":NEEDS.get(name,"Fixture ảnh thật và MediaStore trên A/B.")}
        try:
            argv=command(config,name)
            if not Path(argv[0]).is_absolute():raise ValueError("Executable phải là đường dẫn tuyệt đối.")
            # Adapter Python phải còn tồn tại sau khi chuyển folder sang máy khác.
            if Path(argv[0]).name.startswith('python'):
                if len(argv)<2 or not Path(argv[1]).is_file():raise ValueError("Thiếu file adapter Python.")
            row["status"]="CONFIGURED_NOT_MEASURED"
            row["command"]=argv
            if name=="media_integrity":
                row["supported_media"]=config['lab']['probes'][name].get('supported_media',[])
        except Exception as error:row['reason']=str(error)
        rows.append(row)
    return rows


def configure(config, group=None):
    if group:
        config.setdefault('groups',{})['primary']=group
    probes=config.setdefault('lab',{}).setdefault('probes',{})
    probes.setdefault('media_integrity',{'command':[sys.executable,str(ROOT/'scripts/probes/media_integrity.py')],
                                       'supported_media':['camera_photo','multiple_images','image_under_100mb','camera_video','gallery_video']})
    media=probes['media_integrity']
    if media.get('command')==[sys.executable,str(ROOT/'scripts/probes/media_integrity.py')]:
        media['supported_media']=list(dict.fromkeys(media.get('supported_media',[])+['camera_photo','multiple_images','image_under_100mb','camera_video','gallery_video']))
    probes.setdefault('android_signals',{'command':[sys.executable,str(ROOT/'scripts/probes/android_signals.py')]})
    configure_call_audio(config)
    configure_notification_alert(config)
    voice=[sys.executable,str(ROOT/'scripts/probes/voice_playback_signal.py')]
    probes.setdefault('voice_playback_signal',{'command':voice,'healthcheck_command':voice})
    probes.setdefault('location_destination',{'command':[sys.executable,str(ROOT/'scripts/probes/location_destination.py')],'healthcheck_command':[sys.executable,str(ROOT/'scripts/probes/location_destination.py')]})
    probes.setdefault('camera_capture',{'command':[sys.executable,str(ROOT/'scripts/probes/camera_capture.py')]})
    return config


def configure_notification_alert(config):
    probes = config.setdefault('lab', {}).setdefault('probes', {})
    command = [sys.executable, str(ROOT/'scripts/probes/notification_alert.py')]
    probes.setdefault('notification_alert', {'command': command, 'healthcheck_command': command})


def configure_call_audio(config):
    probes = config.setdefault('lab', {}).setdefault('probes', {})
    command = [sys.executable, str(ROOT/'scripts/probes/call_audio_signals.py')]
    for name in ('audio_duplex', 'audio_routes'):
        probes.setdefault(name, {'command': command, 'healthcheck_command': command})


def inspect(config):
    states={d['udid']:d['state'] for d in list_devices(config)}
    devices={}
    for role in ('A','B'):
        serial=config.get('devices',{}).get(role,{}).get('udid')
        row={'state':states.get(serial,'DISCONNECTED')}
        if row['state']=='device':
            outputs=[]
            try:
                for args in [('window','policy'),('fingerprint',),('face',)]:
                    result=subprocess.run([find_adb(config),'-s',serial,'shell','dumpsys',*args],
                                          capture_output=True,text=True,timeout=20,check=True)
                    outputs.append(result.stdout)
                row.update(security(*outputs))
                row['no_credentials_verified']=(row['secure'] is False and row['fingerprints']==0 and row['faces']==0)
            except Exception as error:row['error']=type(error).__name__
        devices[role]=row
    return {'schema':1,'note':'Kiểm tra lab, không phải kết quả testcase sản phẩm.',
            'devices':devices,'groups':config.get('groups',{}),'probes':probe_inventory(config)}


def verify_group(config,reporter,available_roles,discover_members=False):
    from .cli import Context
    from .suite_ui import UI
    from .pages import literal
    ctx=Context(config,reporter,None)
    result={}
    try:
        for role in available_roles:
            try:
                page=ctx.page(role);page.require_idle_call();page.login_and_verify()
                peer=None
                if discover_members:
                    other='B' if role=='A' else 'A'
                    page.open_peer(peer_role=other)
                    peer={'role':other,'name':page.peer_name}
                name=config['groups']['primary']
                UI(page).open_named(name)
                page.composer()
                page.find('//*[@text='+literal(name)+' or @content-desc='+literal(name)+']')
                result[role]={'status':'OPENED','group':name,'note':'Chỉ xác minh mở đúng hội thoại; chưa chứng minh đủ thành viên hoặc chạy testcase.'}
                if peer:result[role]['verified_peer']=peer
                page.home()
            except Exception as error:result[role]={'status':'BLOCKED','reason':reporter.redact(error)}
    finally:ctx.close()
    return result
