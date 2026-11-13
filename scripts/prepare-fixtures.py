#!/usr/bin/env python3
"""Tạo ảnh PNG thật và rich text cục bộ; không tạo file video giả bằng padding."""
import argparse
import hashlib
import json
import os
import struct
import sys
import zlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tammi_runner.common import sha256_file

def png(path,width,height,noise=False,pattern=False):
    def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    with path.open('wb') as stream:
        stream.write(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0)))
        compressor=zlib.compressobj(0 if noise else 6)
        for row in range(height):
            if pattern:
                # Gradient và ô màu giữ đặc trưng khi nén; nhiễu nhỏ vẫn tạo dữ liệu ảnh thực đủ lớn.
                random=os.urandom(width*3);pixels=bytearray(width*3)
                for x in range(width):
                    i=x*3
                    pixels[i]=x*224//width+(random[i]&31)
                    pixels[i+1]=row*224//height+(random[i+1]&31)
                    pixels[i+2]=32+((x//100+row//100)%2)*160+(random[i+2]&31)
            else:
                pixels=os.urandom(width*3) if noise else bytes((row%256,64,192))*width
            block=compressor.compress(b'\0'+pixels)
            if block:stream.write(chunk(b'IDAT',block))
        stream.write(chunk(b'IDAT',compressor.flush())+chunk(b'IEND',b''))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--large-image',action='store_true');args=parser.parse_args()
    folder=ROOT/'fixtures/generated';folder.mkdir(parents=True,exist_ok=True)
    for name,color in [('image.png',False),('image-2.png',True)]:png(folder/name,640,480,color,pattern=color)
    png(folder/'image-large.png',2000,2000,True,pattern=True)
    text=folder/'rich-text.md';text.write_text('**Đậm** _Nghiêng_ ~~Gạch bỏ~~\n[Trang kiểm thử](https://example.com/)\n`mã kiểm thử`\n',encoding='utf-8')
    manifest={'image_under_100mb':{'path':str(folder/'image-large.png')},'multiple_images':{'path':str(folder/'image.png'),'second_path':str(folder/'image-2.png')},'rich_text':{'path':str(text),'expected_text':['Đậm','Nghiêng','Trang kiểm thử'],'url':'https://example.com/'}}
    if args.large_image:
        path=folder/'image-over-20mb.png';png(path,3000,3000,True);manifest['image_over_20mb']={'path':str(path)}
    for fixture in manifest.values():fixture['sha256']=sha256_file(fixture['path'])
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(folder/'manifest.json')

if __name__=='__main__':main()
