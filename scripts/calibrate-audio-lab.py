#!/usr/bin/env python3
"""Hiệu chỉnh mic C bằng âm chuẩn phát từ A; thiếu tín hiệu thì BLOCKED, không PASS app."""
import json,math,shutil,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tammi_runner.common import load_config,Reporter,DEFAULT_CONFIG,save_private_json,Blocked
from tammi_runner.audio_capture import begin,stop,adb,REMOTE
from tammi_runner.audio_analysis import samples,rms,similarity
from tammi_runner.audio_devices import connected
from tammi_runner.runtime import RunLock
cfg=load_config();reporter=Reporter(cfg);marker='CAL-'+uuid.uuid4().hex[:12];active={}
with RunLock():
    try:
        folder=ROOT/'fixtures/audio';folder.mkdir(parents=True,exist_ok=True)
        refs=[]
        for name in ('audio_going_out.mp3','audio_connecting.mp3'):
            path=folder/name;shutil.copyfile(ROOT.parent/'ChatCall/src/main/res/raw'/name,path);refs.append(str(path))
        begin(cfg,'C',marker+'-quiet',seconds=12);active['C']=marker+'-quiet';time.sleep(2)
        quiet=stop(cfg,'C',active['C'],reporter.directory);active.pop('C');baseline=rms(samples(quiet))
        adb(cfg,'A','shell','mkdir','-p',REMOTE);adb(cfg,'A','push',refs[0],REMOTE+'audio_going_out.mp3')
        begin(cfg,'A',marker+'-cue',action='play',filename='audio_going_out.mp3',seconds=25);active['A']=marker+'-cue'
        begin(cfg,'C',marker+'-tone',seconds=12);active['C']=marker+'-tone';time.sleep(3)
        path=stop(cfg,'C',active['C'],reporter.directory);active.pop('C');stop(cfg,'A',active['A']);active.pop('A')
        pcm=samples(path);level=rms(pcm);score=similarity(pcm,samples(refs[0]));snr=20*math.log10(max(level,1e-9)/max(baseline,1e-6))
        data={'source':'physical_microphone_C','created_at':time.time(),'baseline_rms':baseline,'tone_rms':level,'correlation':score,'snr_db':snr,'references':refs,'A_devices':connected(adb(cfg,'A','shell','dumpsys','audio')),'C_udid':cfg['devices']['C']['udid'],'ready':score>=.55 and snr>=6 and level>=.001}
        save_private_json(reporter.directory/'audio-calibration.json',data)
        reporter.emit('setup','Đã đo đối chứng âm thật từ A đến mic C.',correlation=score,snr_db=snr,ready=data['ready'])
        if not data['ready']:raise Blocked('Mic C chưa thu được âm chuẩn A đủ rõ; cần đặt mic sát đầu phát hoặc đổi nguồn thu. Không bật probe bằng RMS tiếng phòng.')
        calibration=ROOT/'config/local/audio-calibration.json';save_private_json(calibration,data)
        cfg['lab']['audio_capture']={'source':'physical_microphone','role':'C','calibration':str(calibration),'references':refs}
        command=[sys.executable,str(ROOT/'scripts/probes/ringback_audio.py')]
        cfg['lab']['probes']['ringback']={'command':command,'healthcheck_command':command}
        save_private_json(DEFAULT_CONFIG,cfg)
    except Blocked as error:reporter.emit('blocked',str(error))
    finally:
        for role,owned in active.items():
            try:stop(cfg,role,owned,reporter.directory if role=='C' else None)
            except Exception as error:reporter.emit('warning',str(error))
        for role in ('A','C'):
            try:adb(cfg,role,'shell','am','start','-n',cfg['app_package']+'/'+cfg.get('app_activity','com.vt.platform.MainActivity'))
            except Exception as error:reporter.emit('warning',str(error))
        reporter.finish()
