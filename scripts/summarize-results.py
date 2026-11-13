#!/usr/bin/env python3
"""Tổng hợp lần thực thi mới nhất theo case, giữ link và lịch sử từng report; không gộp thành một run PASS."""
import html
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tammi_runner.cases import CASES
from tammi_runner.common import save_private_json

known={case.id:case for case in CASES};latest={};preflight={};history={}
for path in sorted((ROOT/'reports').glob('*/summary.json')):
    try:value=json.loads(path.read_text())
    except (ValueError,OSError):continue
    invalid_path=path.parent/'invalidated-results.json'
    invalid=json.loads(invalid_path.read_text()) if invalid_path.exists() else {}
    for original in value.get('results',[]):
        if original['id'] not in known:continue
        row={**original,'run_id':path.parent.name,'report':str(path.parent/'report.html')}
        if row['id'] in invalid:row['status']='INVALIDATED';row['message']=invalid[row['id']]
        history.setdefault(row['id'],[]).append({'run_id':row['run_id'],'status':row['status']})
        if row['status']=='READY':preflight[row['id']]=row;continue
        if row['status'] in ('CANCELLED','INVALIDATED'):continue
        latest[row['id']]=row
# PASS cũ không thay cho việc chạy các assertion mới được bổ sung.
for case_id,row in latest.items():
    missing=set(known[case_id].obligations)-set(row.get('proved_assertions',[]))
    if row['status']=='PASS' and missing:
        row['original_status']='PASS';row['status']='NEEDS_RERUN'
        row['message']='Từng PASS theo assertion cũ; cần chạy lại để chứng minh: '+', '.join(sorted(missing))
rows=[]
for case in CASES:
    row=latest.get(case.id,{'id':case.id,'status':'NOT_RUN','message':'Chưa có lượt thực thi hoàn tất.','run_id':None,'report':None})
    rows.append({**row,'name':case.name,'coverage_level':case.coverage_level,'scope_note':case.note,'sources':list(case.sources),'requirements':list(case.requirements),'expected_assertions':list(case.obligations),'history':history.get(case.id,[])})
counts=dict(Counter(row['status'] for row in rows));folder=ROOT/'reports/latest';folder.mkdir(parents=True,exist_ok=True)
value={'generated_at':datetime.now().isoformat(),'note':'Lịch sử thô, có cả location staging ngoài phạm vi mới; thống kê nghiệm thu staging và location prod xem pair-report.html / COMPLETION-STATUS.md. Snapshot kết quả thực thi mới nhất của từng script qua nhiều run. Không phải một lượt all-pass; PASS cũ vẫn có thể có FAIL/ERROR trong lịch sử. READY/CANCELLED không thay thế kết quả thực thi. Các biến thể và expected chưa được nghiệm thu toàn bộ.','counts':counts,'cases':rows}
save_private_json(folder/'latest-results.json',value)
content='<html><meta charset="utf-8"><title>Tammi · Snapshot</title><style>body{font:15px system-ui;margin:32px}td,th{border:1px solid #ccd;padding:8px;text-align:left}table{border-collapse:collapse;width:100%}</style><h1>Tammi · Snapshot kết quả</h1><p>'+html.escape(value['note'])+'</p><p>'+html.escape(str(counts))+'</p><table><tr><th>Case</th><th>Kết quả mới nhất</th><th>Run</th><th>Chi tiết / điều kiện còn thiếu</th></tr>'
for row in rows:
    link='<a href="../'+html.escape(str(row['run_id']))+'/report.html">'+html.escape(str(row['run_id']))+'</a>' if row['run_id'] else ''
    content+='<tr><td>'+html.escape(row['id']+' · '+row['name'])+'</td><td>'+html.escape(row['status'])+'</td><td>'+link+'</td><td>'+html.escape(row['message'])+'</td></tr>'
(folder/'report.html').write_text(content+'</table></html>')
lines=['# Snapshot kết quả Appium', '',value['note'],'','Cập nhật: '+value['generated_at'],'','Kết quả: '+', '.join(f'{key}: {number}' for key,number in counts.items()),'','| Case | Kết quả | Run |','|---|---|---|']
for row in rows:lines.append('| '+row['id']+' | '+row['status']+' | '+('['+row['run_id']+']('+row['report']+')' if row['run_id'] else '—')+' |')
(ROOT/'CURRENT-RESULTS.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'counts':counts,'report':str(folder/'report.html')},ensure_ascii=False))
