"""Giao thức đo lab có challenge theo run; không dùng checkbox 'đã nghe thấy' để PASS."""
import json
import math
import subprocess
import uuid
from pathlib import Path

from .common import Blocked, save_private_json


REQUIRED = {
    "location_destination":{"latitude":(-90,90),"longitude":(-180,180)},
    "camera_capture":{"A_active_clients":(0,None),"B_active_clients":(0,None)},
    "android_signals":{"observed_seconds":(5,None),"fresh_vibration_events":(0,None),"active_audio_clients":(0,None),"active_ringtone_clients":(0,None)},
    "media_integrity": {"decodable":(1,1),"received_bytes":(1,None),"checksum_matches":(0,1),"content_matches":(1,1)},
    "location_live": {"distinct_positions":(2,None),"receiver_updates":(2,None)},
    "audio_duplex": {"active_playback_roles":(2,2),"active_recording_roles":(2,2)},
    "voice_playback": {"correlation":(.8,1),"duration_error_ms":(0,300)},
    "voice_playback_signal": {"fresh_voice_players":(1,None),"voice_players_stopped":(1,1)},
    "video_duplex": {"a_to_b_fps":(10,None),"b_to_a_fps":(10,None),"face_similarity":(.8,1)},
    "ringback": {"fresh_ringback_players":(1,None),"unmuted_ringback_players":(1,None)},
    "incoming_alert": {"vibration_events":(0,None),"ringer_rms":(0,None)},
    "notification_alert": {"sound_dispatched":(0,1),"vibration_dispatched":(0,1)},
    "audio_routes": {},
    "launcher_badge": {"count":(0,None)},
    "media_audio_focus": {"media_rms_before":(.001,None),"media_duck_ratio":(0,.5),"call_rms":(.001,None)},
    "whatsapp_call": {"call_active":(1,1)},
    "zero_data_sim": {"quota_bytes":(0,0),"wifi_enabled":(0,0),"cellular_connected":(1,1)},
    "meeting_web": {"joined":(1,1),"member_identity_matches":(1,1),"remote_screen_frames":(1,None)},
    "meeting_media": {"audio_paths_ok":(1,1),"video_paths_ok":(1,1),"mic_state_matches":(1,1),"camera_state_matches":(1,1)},
}

ROUTE_STAGES = {
    'speaker': {'speaker'},
    'earpiece': {'earpiece'},
    'bluetooth': {'bt_sco', 'bt_sco_hs', 'bt_sco_carkit', 'ble_headset'},
    'wired': {'headset', 'headphone', 'wired_headset', 'wired_headphone', 'usb_device', 'usb_headset'},
}


def command(config, name):
    spec=config.get("lab",{}).get("probes",{}).get(name,{})
    args=spec.get("command")
    if not isinstance(args,list) or not args or not all(isinstance(v,str) for v in args):
        raise Blocked(f"Chưa cấu hình probe lab {name} (command dạng mảng argv).")
    if not Path(args[0]).expanduser().is_file():raise Blocked(f"Không tìm thấy executable của probe {name}.")
    return [str(Path(args[0]).expanduser()),*args[1:]]


def measure(ctx, name, phase="measure", **context):
    args=command(ctx.config,name);nonce=uuid.uuid4().hex
    payload={"schema":1,"challenge":nonce,"probe":name,"phase":phase,
             "devices":{r:d["udid"] for r,d in ctx.config["devices"].items() if d.get("udid")},
             "audio_capture":ctx.config.get("lab",{}).get("audio_capture",{}),"app_package":ctx.config["app_package"],"report_directory":str(ctx.reporter.directory),"fixtures":ctx.config.get("fixtures",{}),"tools":ctx.config.get("tools",{}),**context}
    timeout=300 if name=='media_integrity' and context.get('case_id') in ('VIDEO-FILE-OVER-100MB','CHAT-006-CAMERA_VIDEO') else 120
    result=subprocess.run(args,input=json.dumps(payload),capture_output=True,text=True,timeout=timeout,check=False)
    if getattr(result,"returncode",0):
        details={"probe":name,"phase":phase,"returncode":result.returncode,"stderr":result.stderr,"stdout":result.stdout}
        save_private_json(ctx.reporter.directory/f"probe-{name}-{nonce}-failure.json",ctx.reporter.sanitize(details))
        message=f"Probe {name} lỗi: "+(result.stderr.strip() or f"exit {result.returncode}")[:1600]
        if result.stderr.lstrip().startswith("AssertionError:"):raise AssertionError(message)
        raise RuntimeError(message)
    try:data=json.loads(result.stdout)
    except ValueError as error:raise AssertionError(f"Probe {name} không trả JSON hợp lệ.") from error
    assert data.get("schema")==1 and data.get("challenge")==nonce, "Probe trả kết quả cũ hoặc sai schema/challenge."
    if data.get("blocked"):raise Blocked(str(data["blocked"]))
    values=data.get("measurements",{})
    if name in ("ringback","voice_playback_signal","audio_duplex","audio_routes","notification_alert"):
        assert data.get("mode")=="adb_signals", "Probe phải trả bằng chứng tín hiệu ADB."
    if phase=="measure" or (name,phase) in (("ringback","after"),("audio_duplex","after_end")):
        bounds={"ringback_players_stopped":(1,1)} if name=="ringback" and phase=="after" else dict(REQUIRED[name])
        if name=="audio_duplex" and phase=="after_end":bounds={"call_audio_mode_released":(1,1)}
        if name=="audio_routes":
            assert values.get("active") is True and isinstance(values.get("route"),str), "Thiếu route thoại đang hoạt động."
            stage=context.get("stage")
            if stage in ROUTE_STAGES:
                assert values["route"] in ROUTE_STAGES[stage], "Route thoại khác route được yêu cầu."
            elif stage=="wired_removed":
                assert values.get("wired_connected") is False and values["route"] not in ROUTE_STAGES["wired"], "Thiếu xác nhận đã rút tai nghe dây."
            elif stage=="volume":
                assert values["route"] in ROUTE_STAGES["wired"], "Route đã đổi trong lúc đo âm lượng tai nghe dây."
                bounds={"volume":(0,None)}
            else:
                raise ValueError("Giai đoạn đo route không hợp lệ.")
        if name=="media_integrity":
            for field in ("exact_pixels_match","camera_public_saved"):
                if field in values:bounds[field]=(0,1)
        for key,(minimum,maximum) in bounds.items():
            value=values.get(key)
            assert isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value), f"Probe thiếu số đo {name}.{key}"
            assert (minimum is None or value>=minimum) and (maximum is None or value<=maximum), f"Số đo {name}.{key} ngoài ngưỡng."
    save_private_json(ctx.reporter.directory/f"probe-{name}-{nonce}.json",ctx.reporter.sanitize(data))
    ctx.reporter.emit("assertion",f"Probe {name}: {phase}",measurements=values)
    return values
