#!/usr/bin/env python3
"""Xuất từng nhóm nguồn và biến thể Android để mang riêng folder test sang máy khác."""
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tammi_runner.cases import DISPLAY_CASES

for source in json.loads((ROOT/'catalog/source-cases.json').read_text())['cases']:
    sheet=source['source_id'].split('-')[0].lower()
    folder=ROOT/'testcases'/sheet;folder.mkdir(parents=True,exist_ok=True)
    value={'source':source,'platform':'Android–Android','variants':[asdict(case) for case in DISPLAY_CASES if source['source_id'] in case.sources]}
    (folder/(source['source_id']+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
print(ROOT/'testcases')
folder=ROOT/'testcases/custom';folder.mkdir(parents=True,exist_ok=True)
for case in DISPLAY_CASES:
    if not case.sources and case.action=='suite':
        (folder/(case.id+'.json')).write_text(json.dumps(asdict(case),ensure_ascii=False,indent=2)+'\n')
