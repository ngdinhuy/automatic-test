#!/usr/bin/env python3
"""Copy video do người dùng chỉ định qua ADB, giải mã thật và cấu hình fixture; không sửa file gốc."""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path,PurePosixPath

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tammi_runner.common import load_config,find_adb,sha256_file,save_private_json,DEFAULT_CONFIG
from tammi_runner.runtime import RunLock
from tammi_runner.video import decode


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role',choices=['A','B'],default='A')
    parser.add_argument('--remote',required=True)
    args=parser.parse_args();remote=PurePosixPath(args.remote)
    if not args.remote.startswith(('/sdcard/','/storage/emulated/0/')) or '..' in remote.parts:
        parser.error('Chỉ nhận đường dẫn media public tuyệt đối trên thiết bị.')
    if remote.suffix.lower() not in ('.mp4','.mov','.mkv','.webm'):parser.error('Cần file video hợp lệ.')
    config=load_config();folder=ROOT/'fixtures/local';folder.mkdir(parents=True,exist_ok=True)
    with RunLock():
        with tempfile.NamedTemporaryFile(dir=folder,suffix=remote.suffix,delete=False) as stream:path=Path(stream.name)
        try:
            subprocess.run([find_adb(config),'-s',config['devices'][args.role]['udid'],'pull',args.remote,str(path)],capture_output=True,text=True,timeout=180,check=True)
            if path.stat().st_size<=100*1024*1024:raise ValueError('Case yêu cầu video nguồn >100 MiB; không tạo padding để đủ dung lượng.')
            info=decode(path);digest=sha256_file(path);target=folder/(digest[:16]+remote.suffix.lower())
            if target.exists():
                if sha256_file(target)!=digest:raise RuntimeError('Tên fixture trùng nhưng nội dung khác; không ghi đè.')
            else:path.rename(target)
            target.chmod(0o600)
            fixture={'path':str(target),'sha256':digest,'source_device':args.role,'source_file':args.remote,'decoded':info}
            config.setdefault('fixtures',{})['gallery_video']=fixture;save_private_json(DEFAULT_CONFIG,config)
            print(json.dumps({'fixture':str(target),'bytes':target.stat().st_size,**info},ensure_ascii=False))
        finally:path.unlink(missing_ok=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
