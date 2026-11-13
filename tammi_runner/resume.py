"""Chọn phần còn dở từ report đã hoàn tất, giữ nguyên các case đã PASS đủ assertion."""
import json
from pathlib import Path

from .common import Blocked


def pending_cases(cases, reports, *, skip_passed=True, skip_failed=False):
    wanted={case.id for case in cases};failed_ids=set();passed={}
    for path in sorted(Path(reports).glob('*/summary.json')):
        try:
            rows=json.loads(path.read_text()).get('results',[])
            invalid_path=path.parent/'invalidated-results.json'
            invalid=json.loads(invalid_path.read_text()) if invalid_path.exists() else {}
        except (OSError,ValueError) as error:
            raise Blocked('Không đọc được lịch sử để tránh chạy lặp: '+str(path)) from error
        for row in rows:
            case_id=row.get('id')
            if case_id not in wanted or case_id in invalid:continue
            if row.get('status') in ('READY','CANCELLED','INVALIDATED'):continue
            if row.get("status") in ("FAIL","ERROR"):failed_ids.add(case_id)
            if row.get("status")=="PASS":passed.setdefault(case_id,[]).append(set(row.get("proved_assertions",[])))
    pending=[];skipped=[]
    for case in cases:
        complete=any(set(case.obligations)<=proof for proof in passed.get(case.id,[]))
        failed=skip_failed and case.id in failed_ids
        (skipped if (skip_passed and complete) or failed else pending).append(case)
    return pending,skipped
