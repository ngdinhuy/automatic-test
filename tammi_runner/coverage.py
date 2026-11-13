"""Đối chiếu từng dòng nguồn với kết quả script, không suy rộng PASS một phần."""
import html
import json
from collections import Counter

from .cases import CASES
from .common import ROOT, save_private_json


def write_coverage(reporter):
    catalog = json.loads((ROOT / "catalog/source-cases.json").read_text())
    executed = {row["id"]: row for row in reporter.results}
    rows = []
    for source in catalog["cases"]:
        linked = [case for case in CASES if source["source_id"] in case.sources]
        evidence = [{"script": case.id, "status": executed.get(case.id, {}).get("status", "NOT_RUN"),
                     "coverage": case.note} for case in linked]
        reason = source.get("exclusion_reason")
        full = [case for case in linked if case.coverage_level == "functional"]
        if reason:status = "EXCLUDED"
        elif full:
            verified = all(executed.get(case.id, {}).get("status") == "PASS" and
                           set(case.obligations).issubset(executed.get(case.id, {}).get("proved_assertions", [])) for case in full)
            status = "SCRIPT_VARIANTS_PASS" if verified else "SCRIPT_DEFINED_NOT_ACCEPTED"
        else:status = "PARTIAL_SCRIPT" if linked else "NOT_IMPLEMENTED"
        rows.append({"source_id": source["source_id"], "description": source.get("description") or source.get("expected"),
                     "expected":source.get("expected"), "status": status, "reason": reason, "scripts": evidence})
    data = {"source_sha256": catalog["source_sha256"], "counts": dict(Counter(row["status"] for row in rows)),
            "note": "SCRIPT_DEFINED_NOT_ACCEPTED: có mã hành động/assertion, chưa nghiệm thu đủ mọi biến thể. READY chỉ là preflight. SCRIPT_VARIANTS_PASS yêu cầu mọi biến thể chức năng PASS đủ assertion trong cùng run; đây là kết quả các assertion đã định nghĩa, chưa thay thế nghiệm thu toàn bộ expected Excel. Không đánh giá giao diện theo phạm vi người dùng.",
            "cases": rows}
    save_private_json(reporter.directory / "source-coverage.json", data)
    content = '<h2>Đối chiếu toàn bộ Excel</h2><p>' + html.escape(data["note"]) + '</p>'
    content += '<p>' + html.escape(str(data["counts"])) + '</p><table><tr><th>ID nguồn</th><th>Testcase</th><th>Coverage</th><th>Script đã chạy</th></tr>'
    for row in rows:
        values = (row["source_id"], row["description"], row["status"],
                  row["reason"] or "; ".join(item["script"] + ": " + item["status"] for item in row["scripts"]))
        content += '<tr>' + ''.join('<td>' + html.escape(str(value or '')) + '</td>' for value in values) + '</tr>'
    content += '</table>'
    with (reporter.directory / "report.html").open("a", encoding="utf-8") as stream:
        stream.write(content)
