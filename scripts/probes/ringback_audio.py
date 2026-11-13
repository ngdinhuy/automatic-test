#!/usr/bin/env python3
"""Probe tín hiệu chuông qua ADB, lưu snapshot ba giai đoạn; không cần mic C."""
import json,re,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tammi_runner.common import Blocked,save_private_json
from tammi_runner.audio_capture import adb
from tammi_runner.ringback_signals import snapshot,candidates,stopped


def main(p):
    cfg={'devices':{r:{'udid':u} for r,u in p['devices'].items()},'tools':p.get('tools',{})}
    role=p.get('role','A');package=p['app_package'];phase=p['phase']
    result={'schema':1,'challenge':p['challenge'],'mode':'adb_signals','scope':'Tín hiệu player đúng UID, không đo RMS/SNR hoặc âm vật lý.','measurements':{}}
    info=adb(cfg,role,'shell','pm','list','packages','-U',package)
    uid_match=re.search(r'package:'+re.escape(package)+r' uid:(\d+)',info)
    if not uid_match:raise Blocked('Không xác minh được UID ứng dụng.')
    uid=int(uid_match[1])
    if phase=='check':
        snapshot(adb(cfg,role,'shell','dumpsys','audio'),uid)
        return {**result,'ready':True,'checks':['Đọc được UID và bảng playback ADB; volume/route thiếu sẽ ghi unavailable, không cần mic C.']}
    if phase=='cleanup':return result
    if not re.fullmatch(r'APPIUM-[a-f0-9]{12}',p['marker']):raise ValueError('Marker không hợp lệ.')
    folder=Path(p['report_directory'])/('ringback-'+p['marker']);folder.mkdir(parents=True,exist_ok=True)
    path=folder/'signal-state.json'
    def take(stage,index=0):
        raw=adb(cfg,role,'shell','dumpsys','audio')
        evidence={'time':time.time(),'challenge':p['challenge'],'role':role,'uid':uid,'audio':raw}
        for service in ('media.audio_flinger','media.audio_policy'):
            try:evidence[service]=adb(cfg,role,'shell','dumpsys',service)
            except Exception as error:evidence[service]={'unavailable':str(error)}
        save_private_json(folder/f'{stage}-{index}.json',evidence)
        return snapshot(raw,uid)
    if phase=='prepare':
        if p.get('stage')!='baseline':return result
        before=take('before')
        if any(r['state']=='started' for r in before['players']):raise Blocked('App đã có player active trước gọi; cần baseline yên để quy thuộc chuông.')
        save_private_json(path,{'uid':uid,'role':role,'serial':p['devices'][role],'created':time.time(),'before':before})
        return result
    if not path.exists():raise Blocked('Thiếu baseline của run hiện tại.')
    state=json.loads(path.read_text())
    if (state['uid'],state['role'],state['serial'])!=(uid,role,p['devices'][role]) or time.time()-state['created']>180:
        raise Blocked('Baseline hết hạn hoặc đổi UID/thiết bị.')
    if phase=='measure':
        selected=[]
        for index in range(5):
            selected=candidates(state['before'],take('during',index))
            if selected:break
            time.sleep(.4)
        assert selected,'Không thấy player mới đúng UID/usage chuyển started trong cửa sổ chuông.'
        state['selected']=selected;save_private_json(path,state)
        result['measurements']={'fresh_ringback_players':len(selected),'unmuted_ringback_players':len(selected)}
        result['players']=selected
    elif phase=='after':
        if not state.get('selected'):raise Blocked('Thiếu player đã xác minh trong lúc chuông.')
        consecutive=0
        for index in range(12):
            consecutive=consecutive+1 if stopped(state['selected'],take('after',index)) else 0
            if consecutive>=2:break
            time.sleep(.4)
        assert consecutive>=2,'Player chuông vẫn started sau nhận/kết thúc gọi.'
        result['measurements']={'ringback_players_stopped':1}
    else:raise ValueError('Phase không hỗ trợ.')
    save_private_json(folder/(phase+'-result.json'),result)
    return result


if __name__=='__main__':
    payload=json.load(sys.stdin)
    try:answer=main(payload)
    except Blocked as error:answer={'schema':1,'challenge':payload['challenge'],'blocked':str(error)}
    except Exception as error:print(type(error).__name__+': '+str(error),file=sys.stderr);sys.exit(1)
    print(json.dumps(answer,ensure_ascii=False))
