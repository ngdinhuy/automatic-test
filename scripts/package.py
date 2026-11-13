#!/usr/bin/env python3
"""Đóng gói source cho máy khác, loại credentials, APK, report và runtime theo whitelist."""
import tarfile
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'dist'/('tammi-test-source-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.tar.gz')
OUTPUT.parent.mkdir(parents=True,exist_ok=True)
items=['PLAN-ADB-AUDIO-SIGNALS.md','HANDOFF-APPIUM-BLOCKED-2026-11-13.md','lab-android','.gitignore','tammi_runner','desktop_app','verification','scripts','catalog','testcases','config/examples','sources','Tammi Test Desktop.app','Launch.command','requirements.lock','package.json','package-lock.json','README.md','RUNBOOK.md','PLAN.md','PLAN-v2.md','VALIDATION.md','KNOWN-ISSUES.md','LAB.md','MEASUREMENT-SETUP.md','FAIL-CASES.md','RESUME-STATUS.md','TESTLAB-STATUS.md','DESKTOP-LAB-CHECK.md','COMPLETION-STATUS.md','STATISTICS-SUMMARY.md']
with tarfile.open(OUTPUT,'w:gz') as archive:
    for item in items:
        path=ROOT/item
        if not path.exists():continue
        paths=sorted(path.rglob('*')) if path.is_dir() else [path]
        for candidate in paths:
            if not candidate.is_file() or candidate.is_symlink() or '__pycache__' in candidate.parts:continue
            archive.add(candidate,arcname=str(Path('automation-desktop')/candidate.relative_to(ROOT)),recursive=False)
print(OUTPUT)
