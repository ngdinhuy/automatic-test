"""Đọc PCM thật và so đoạn âm chuẩn; không thay âm thu bằng log AudioService."""
import array,math,subprocess,sys
from pathlib import Path
import imageio_ffmpeg


def samples(path,rate=2000):
    data=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(path),'-vn','-ac','1','-ar',str(rate),'-f','s16le','-'],capture_output=True,check=True,timeout=30).stdout
    pcm=array.array('h');pcm.frombytes(data)
    if sys.byteorder!='little':pcm.byteswap()
    if len(pcm)<rate:raise ValueError('File thu chưa có đủ một giây âm thanh giải mã được.')
    return list(pcm)


def rms(pcm):return math.sqrt(sum(x*x for x in pcm)/max(1,len(pcm)))/32768


def similarity(record,reference,window=1000):
    if len(reference)<window or len(record)<window:raise ValueError('Không đủ PCM cho cửa sổ đối chiếu.')
    energy=[sum(x*x for x in reference[i:i+window]) for i in range(0,len(reference)-window+1,window//2)]
    offset=max(range(len(energy)),key=energy.__getitem__)*(window//2)
    ref=reference[offset:offset+window];mean=sum(ref)/window;ref=[x-mean for x in ref]
    ref_energy=sum(x*x for x in ref)
    if ref_energy<=0:raise ValueError('Âm chuẩn không có tín hiệu.')
    prefix=[0.0];squares=[0.0]
    for x in record:prefix.append(prefix[-1]+x);squares.append(squares[-1]+x*x)
    best=0.0
    for pos in range(len(record)-window+1):
        total=prefix[pos+window]-prefix[pos]
        value=squares[pos+window]-squares[pos]-total*total/window
        if value<=0:continue
        dot=sum(x*y for x,y in zip(ref,record[pos:pos+window]))
        best=max(best,dot/math.sqrt(ref_energy*value))
    return min(1.0,max(0.0,best))
