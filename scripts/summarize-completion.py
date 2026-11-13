#!/usr/bin/env python3
"""Thống kê phần đã chạy thành công từ snapshot A/B, không cộng READY hoặc unit test."""
import json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
data=json.loads((ROOT/'reports/latest/pair-results.json').read_text());rows=data['cases']
clean=lambda value:str(value).replace('|','\\|').replace('\n',' ')
counts=Counter(row['status'] for row in rows)
scope=Counter(row.get('coverage_level','partial') for row in rows if row['status']=='PASS')
lines=['# Thống kê phần đã hoàn thành','', 'Cập nhật: '+data['generated_at'],'',
       'Location gồm 4 script chỉ test trên prod, hiện chưa chạy prod; lịch sử location staging không được tính vào bảng staging bên dưới. Snapshot kết quả gần nhất của từng script qua nhiều run, không phải một lượt all-pass. Partial chỉ chứng minh một phần expected; chưa nghiệm thu toàn bộ Excel. READY và kiểm tra nội bộ runner không được cộng vào số testcase app PASS.','',
       '| Phần | PASS | FAIL | ERROR | BLOCKED |','|---|---:|---:|---:|---:|']
for name,prefix in [('Setup/đăng nhập',('APP-','AUTH-')),('Chat',('CHAT-',)),('Call',('CALL-',)),('Video lớn bổ sung',('VIDEO-',))]:
    c=Counter(row['status'] for row in rows if row['id'].startswith(prefix))
    lines.append('| '+name+' | '+' | '.join(str(c[key]) for key in ('PASS','FAIL','ERROR','BLOCKED'))+' |')
lines+=['','Tổng staging A/B (không gồm location): '+str(len(rows))+' script; '+', '.join(key+': '+str(value) for key,value in counts.items())+'.',
        'PASS theo phạm vi: '+', '.join(key+': '+str(value) for key,value in scope.items())+'.',
        'Staging cần C: '+str(len(data['third_device_cases']))+' script. '+', '.join(key+': '+str(value) for key,value in data['third_device_counts'].items())+'.','',
        '## Công cụ đã có','',
        '- Desktop và CLI dùng chung script Appium cho staging, chọn thiết bị/testcase, xem log và mở report. Prod hiện chỉ có lựa chọn build APK; 4 case location prod chưa cấu hình/chưa chạy.',
        '- Một Appium Server local quản lý A/B với UDID/systemPort riêng. Không cần AI điều khiển điện thoại khi chạy test.',
        '- Folder automation-desktop riêng, Git ignore, export case và đóng gói source để chuyển máy.',
        '- Fixture/adapter media giải mã file thật, Android signals theo UID và CameraService theo package/PID + Device status ACTIVE. Hai adapter Android không thay phép đo RMS/SNR, rung vật lý, FPS hay hình bên nhận.','',
        '## Từng script đã PASS','', '| Case | Nội dung | Phạm vi | Report |','|---|---|---|---|']
for row in rows:
    if row['status']=='PASS':lines.append('| '+clean(row['id'])+' | '+clean(row['name'])+' | '+clean(row.get('coverage_level','partial'))+' | [run '+row['run_id']+']('+row['report']+') |')
lines+=['','## FAIL/ERROR chưa giải quyết','', '| Case | Kết quả | Chi tiết gần nhất | Report |','|---|---|---|---|']
for row in rows:
    if row['status'] in ('FAIL','ERROR'):lines.append('| '+clean(row['id'])+' | '+row['status']+' | '+clean(row.get('message',''))+' | [report]('+row['report']+') |')
lines+=['','## Các phần còn BLOCKED','', 'Nguyên nhân dưới đây thuộc lần chạy gần nhất, không thay cho kiểm tra điều kiện hiện tại. Nguồn đo thật/fixture/locator chưa đủ không được tự bỏ để tăng PASS.','', '| Case | Lý do gần nhất |','|---|---|']
for row in rows:
    if row['status']=='BLOCKED':lines.append('| '+row['id']+' | '+clean(row.get('message',''))+' |')
lines+=['','## Location chuyển sang prod: chưa chạy','','4 script location được tách khỏi thống kê staging. Giữ nguyên log staging để tra cứu; không coi FAIL/ERROR/BLOCKED trên staging là kết luận prod.','','| Case | Prod | Lịch sử staging |','|---|---|---|']
for row in data.get('prod_pending',[]):lines.append('| '+row['id']+' | NOT_RUN | '+row['staging_history_status']+' |')
lines+=['','[Report tổng A/B]('+str(ROOT/'reports/latest/pair-report.html')+') · [Hướng dẫn nguồn đo]('+str(ROOT/'MEASUREMENT-SETUP.md')+')')
(ROOT/'COMPLETION-STATUS.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'statistics':str(ROOT/'COMPLETION-STATUS.md'),'counts':dict(counts)},ensure_ascii=False))
