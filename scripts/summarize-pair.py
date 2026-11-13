#!/usr/bin/env python3
"""Tổng hợp staging A/B và kết quả các script cần C."""
import html
import json
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tammi_runner.cases import CASES,uses_only_pair
from tammi_runner.common import save_private_json
from tammi_runner.report_scope import split_location_prod

snapshot=json.loads((ROOT/'reports/latest/latest-results.json').read_text())
allowed={case.id for case in CASES if uses_only_pair(case)}
history_rows=[row for row in snapshot['cases'] if row['id'] in allowed]
rows,prod_pending=split_location_prod(history_rows)
third_device=[row for row in snapshot['cases'] if row['id'] not in allowed]
third_counts=dict(Counter(row['status'] for row in third_device))
counts=dict(Counter(row['status'] for row in rows))
note='Samsung và OPPO là cặp staging chính. C hỗ trợ các case cần ba tài khoản hoặc thiết bị. Bốn case location chỉ nghiệm thu trên prod và hiện chưa chạy trên prod. PASS theo assertion hiện có. Coverage partial ghi nhận các expected đã kiểm tra.'
value={'generated_at':snapshot['generated_at'],'scope':'staging A/B','prod_pending':prod_pending,'staging_history_counts':dict(Counter(row['status'] for row in history_rows)),'counts':counts,'pass_by_coverage':dict(Counter(row.get('coverage_level','partial') for row in rows if row['status']=='PASS')),'third_device_cases':third_device,'third_device_counts':third_counts,'note':note,'cases':rows}
folder=ROOT/'reports/latest';save_private_json(folder/'pair-results.json',value)
lines=['# Kết quả testcase staging','',note,'','Cập nhật: '+value['generated_at'],'','## Cặp A/B','','Kết quả: '+', '.join(f'{k}: {v}' for k,v in counts.items()),'','| Case | Nội dung | Kết quả gần nhất | Report |','|---|---|---|---|']
page='<html><meta charset="utf-8"><title>Tammi · A/B</title><style>body{font:15px system-ui;margin:32px}table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #ccd;text-align:left}</style><h1>Kết quả A/B</h1><p>'+html.escape(note)+'</p><p>'+html.escape(str(counts))+'</p><p>PASS theo phạm vi: '+html.escape(str(value['pass_by_coverage']))+'. partial chỉ chứng minh một phần expected; probe Android chưa đo RMS/âm thanh hoặc rung vật lý.</p><table><tr><th>Case</th><th>Nội dung</th><th>Phạm vi</th><th>Kết quả</th><th>Chi tiết</th></tr>'
for row in rows:
    link='['+str(row['run_id'])+']('+str(row['report'])+')' if row.get('report') else '—'
    lines.append('| '+row['id']+' | '+row['name']+' | '+row['status']+' | '+link+' |')
    target='../'+str(row.get('run_id'))+'/report.html'
    page+='<tr><td>'+html.escape(row['id'])+'</td><td>'+html.escape(row['name'])+'</td><td>'+html.escape(row.get('coverage_level','partial'))+'</td><td><a href="'+html.escape(target)+'">'+html.escape(row['status'])+'</a></td><td>'+html.escape(row.get('message',''))+'</td></tr>'
lines+=['','## Location trên prod: chưa chạy','','| Case | Trạng thái prod | Lịch sử staging (chỉ tra cứu) |','|---|---|---|']
for row in prod_pending:
    lines.append('| '+row['id']+' | NOT_RUN | '+row['staging_history_status']+' |')
page+='</table><h2>Location trên prod: chưa chạy</h2><p>4 case location không tính vào kết quả staging hiện tại. Các kết quả staging cũ được giữ nguyên, không phải kết quả prod.</p><ul>'+''.join('<li>'+html.escape(row['id'])+': NOT_RUN</li>' for row in prod_pending)+'</ul>'
lines+=['','## Script cần C','','| Case | Kết quả gần nhất | Report |','|---|---|---|']
page+='<h2>Script cần C</h2><p>'+html.escape(str(third_counts))+'</p><table><tr><th>Case</th><th>Kết quả gần nhất</th><th>Chi tiết</th></tr>'
for row in third_device:
    link=f"[{row['run_id']}]({row['report']})" if row.get('report') else '—'
    lines.append(f"| {row['id']} | {row['status']} | {link} |")
    status=html.escape(row['status'])
    if row.get('report'):
        status='<a href="../'+html.escape(row['run_id'])+'/report.html">'+status+'</a>'
    page+='<tr><td>'+html.escape(row['id'])+'</td><td>'+status+'</td><td>'+html.escape(row.get('message',''))+'</td></tr>'
(ROOT/'PAIR-RESULTS.md').write_text('\n'.join(lines)+'\n')
(folder/'pair-report.html').write_text(page+'</table></html>')
print(json.dumps({'counts':counts,'eligible':len(rows),'third_device_counts':third_counts,'report':str(folder/'pair-report.html')},ensure_ascii=False))
