#!/usr/bin/env python3
"""Thu mic C ngắn bằng ADB, phân tích file thật; không tính PASS testcase app."""
import sys,time,uuid,subprocess,wave,audioop
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tammi_runner.common import load_config,Reporter,save_private_json
from tammi_runner.audio_capture import begin,stop,adb,PACKAGE
from tammi_runner.runtime import RunLock
import imageio_ffmpeg
cfg=load_config();reporter=Reporter(cfg);marker='MIC-'+uuid.uuid4().hex[:12];started=False
with RunLock():
    try:
        begin(cfg,'C',marker,seconds=8);started=True;time.sleep(2)
        path=stop(cfg,'C',marker,reporter.directory);started=False
        pcm=reporter.directory/(marker+'.wav')
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-i',str(path),'-ac','1','-ar','8000','-c:a','pcm_s16le',str(pcm)],check=True,capture_output=True)
        with wave.open(str(pcm),'rb') as f:
            duration=f.getnframes()/f.getframerate();rms=audioop.rms(f.readframes(f.getnframes()),2)/32768
        save_private_json(reporter.directory/'audio-capture-check.json',{'source':'physical_microphone_C','duration_seconds':duration,'rms':rms,'file':path.name,'scope':'Chỉ xác minh công cụ thu; không phải số đo chuông/call hoặc PASS sản phẩm.'})
        reporter.emit('setup','Đã thu và giải mã file mic C qua ADB.',duration_seconds=duration,rms=rms)
    finally:
        try:
            if started:stop(cfg,'C',marker,reporter.directory)
        finally:
            adb(cfg,'C','shell','am','start','-n',cfg['app_package']+'/'+cfg.get('app_activity','com.vt.platform.MainActivity'))
            reporter.finish()
