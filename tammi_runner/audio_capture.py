"""Điều khiển thu mic lab qua ADB; chỉ dừng phiên thuộc marker của run."""
import json,re,subprocess,time
from pathlib import Path
from .common import Blocked,find_adb

PACKAGE='com.tammi.lab.audio'
REMOTE='/sdcard/Android/data/'+PACKAGE+'/files/'


def adb(config,role,*args):
    result=subprocess.run([find_adb(config),'-s',config['devices'][role]['udid'],*map(str,args)],capture_output=True,text=True,timeout=20,check=True)
    return result.stdout


def state(config,role):
    try:return json.loads(adb(config,role,'shell','cat',REMOTE+'state.json'))
    except (subprocess.CalledProcessError,ValueError):return {}


def begin(config,role,marker,action='record',filename=None,seconds=10):
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',marker):raise ValueError('Marker audio không hợp lệ.')
    current=state(config,role)
    if current.get('active'):raise Blocked('Helper audio đang có phiên khác trên '+role+'; không dừng hoặc ghi đè.')
    args=['shell','am','start','-W','-n',PACKAGE+'/.MainActivity','--es','action',action,'--es','marker',marker,'--ei','duration_ms',str(min(30,max(1,seconds))*1000)]
    if filename:
        if not re.fullmatch('[A-Za-z0-9_.-]+',filename):raise ValueError('Tên fixture không hợp lệ.')
        args+=['--es','file',filename]
    adb(config,role,*args)
    end=time.monotonic()+8
    while time.monotonic()<end:
        current=state(config,role)
        if current.get('marker')==marker:
            if current.get('error'):raise Blocked('Helper audio: '+current['error'])
            if current.get('active'):return current
        time.sleep(.2)
    raise Blocked('Helper chưa xác nhận thu/phát âm trên '+role+'.')


def stop(config,role,marker,folder=None):
    current=state(config,role)
    if current.get('marker')!=marker:raise Blocked('Không dừng phiên audio không thuộc run.')
    if current.get('active'):
        adb(config,role,'shell','am','start','-W','-n',PACKAGE+'/.MainActivity','--es','action','stop','--es','marker',marker)
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        current=state(config,role)
        if current.get('marker')==marker and not current.get('active'):break
        time.sleep(.2)
    else:raise Blocked('Helper audio chưa dừng sạch trên '+role)
    if current.get('error'):raise Blocked('Thu âm lỗi: '+current['error'])
    if folder is not None and current.get('mode')=='record':
        path=Path(folder)/(marker+'.m4a');path.parent.mkdir(parents=True,exist_ok=True)
        adb(config,role,'pull',REMOTE+marker+'.m4a',path)
        if not path.is_file() or path.stat().st_size<500:raise Blocked('Chưa lấy được file thu âm thật.')
        return path
