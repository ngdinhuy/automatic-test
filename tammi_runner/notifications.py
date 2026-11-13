"""Đọc phiên bản notification để không nhận thông báo cũ thành kết quả testcase mới."""
import re


def missed_versions(source, package, peer):
    versions={}
    for block in re.split(r'(?=NotificationRecord\()',source):
        header=block.splitlines()[0] if block.splitlines() else ''
        if f'pkg={package} ' not in header or 'channel=appviettel_missed_call_channel' not in header:
            continue
        if peer and peer not in block:
            continue
        key=re.search(r'\bkey=(\S+)',header)
        updated=re.search(r'\bmUpdateTimeMs=(\d+)',block)
        if key and updated:
            versions[key.group(1)]=int(updated.group(1))
    return versions
