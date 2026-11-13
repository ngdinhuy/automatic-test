"""Giải mã video thật bằng FFmpeg; checksum không thay thế kiểm tra khả năng giải mã."""
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PySide6.QtGui import QImageReader


def binary():return imageio_ffmpeg.get_ffmpeg_exe()


def decode(path):
    result=subprocess.run([binary(),'-hide_banner','-xerror','-err_detect','explode','-i',str(path),
                           '-map','0:v:0','-map','0:a?','-f','null','-','-progress','pipe:1','-nostats'],
                          capture_output=True,text=True,timeout=100,check=False)
    if result.returncode:raise AssertionError('Video không giải mã hết: '+result.stderr[-1200:])
    frames=re.findall(r'^frame=(\d+)$',result.stdout,re.M)
    times=re.findall(r'^out_time_us=(\d+)$',result.stdout,re.M)
    if not frames or not times or 'progress=end' not in result.stdout:
        raise AssertionError('Decoder chưa xác nhận đọc hết video.')
    duration=int(times[-1])/1_000_000
    if int(frames[-1])<2 or duration<=0:raise AssertionError('Video không có đủ frame/thời lượng.')
    return {'frames':int(frames[-1]),'duration_seconds':duration,
            'has_audio':bool(re.search(r'Stream #.*Audio:',result.stderr)),
            'decoder':'FFmpeg '+imageio_ffmpeg.get_ffmpeg_version()}


def sample(path,seconds,output):
    result=subprocess.run([binary(),'-v','error','-ss',str(seconds),'-i',str(path),'-frames:v','1',
                           '-vf','scale=160:160:force_original_aspect_ratio=decrease','-y',str(output)],
                          capture_output=True,text=True,timeout=20,check=False)
    if result.returncode:raise AssertionError('Không giải mã được frame mẫu: '+result.stderr[-500:])
    image=QImageReader(str(output)).read()
    if image.isNull():raise AssertionError('Frame mẫu không phải ảnh hợp lệ.')
    return image
