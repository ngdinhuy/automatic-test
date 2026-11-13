"""Đọc danh sách camera client đang hoạt động; không dùng CONNECT trong log lịch sử."""
import re


def clients(text,package,pids):
    match=re.search(r'Active Camera Clients:\s*\[(.*?)\]\s*Allowed user IDs:',text,re.S)
    if not match:raise ValueError('CameraService không expose danh sách active clients theo định dạng đã hỗ trợ.')
    active=match.group(1).strip()
    if not active:return []
    entries=re.findall(r'\(([^()]*)\)',active,re.S)
    if not entries:raise ValueError('Không phân tích được active camera clients; không suy ra camera đã tắt.')
    rows=[]
    for entry in entries:
        name=re.search(r'Client Package Name:\s*([A-Za-z0-9_.]+)',entry)
        pid=re.search(r'\bPID:\s*(\d+)',entry)
        camera=re.search(r'Camera ID:\s*([^,\n]+)',entry)
        if not name or not pid:raise ValueError('Active camera client thiếu package/PID.')
        if name.group(1)==package and int(pid.group(1)) in pids:
            rows.append({'camera_id':camera.group(1).strip() if camera else '?','pid':int(pid.group(1))})
    return rows


def streaming(text,rows):
    """Client có thể còn mở khi IDLE; chỉ Device status ACTIVE chứng minh capture hoạt động."""
    result=[]
    for row in rows:
        pattern=r'^== Camera device '+re.escape(row['camera_id'])+r'(?: status -?\d+)? dynamic info: ==\s*\n(.*?)(?=^==|\Z)'
        sections=re.findall(pattern,text,re.M|re.S)
        states=[state for part in sections for state in re.findall(r'Device status:\s*(\w+)',part)]
        if not states or any(state not in ('ACTIVE','IDLE','UNCONFIGURED') for state in states):
            raise ValueError('Không xác định được Device status của active client '+row['camera_id'])
        if 'ACTIVE' in states:result.append(row)
    return result
