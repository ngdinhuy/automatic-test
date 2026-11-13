#!/usr/bin/env python3
"""Setup nhóm/probe và kiểm tra Android; không tự tạo số đo hoặc thay đổi khóa máy."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tammi_runner.common import DEFAULT_CONFIG, Reporter, load_config, save_private_json
from tammi_runner.lab_setup import configure,inspect,verify_group
from tammi_runner.runtime import RunLock


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default=str(DEFAULT_CONFIG))
    parser.add_argument('--group')
    parser.add_argument('--verify-group',action='store_true')
    parser.add_argument('--discover-member-names',action='store_true',help='Đọc tên peer A/B từ hội thoại đã xác minh tài khoản; dùng cùng --verify-group.')
    args=parser.parse_args()
    with RunLock():
        config=configure(load_config(args.config),args.group)
        report=inspect(config)
        # Không tự khẳng định máy mất kết nối đã tắt sinh trắc học.
        checked=[r for r in report['devices'].values() if r['state']=='device']
        if checked and any(r.get('secure') is True or (r.get('fingerprints') or 0)>0 or (r.get('faces') or 0)>0 for r in checked):
            config['lab']['unsecured_devices']=False
        elif all(r.get('no_credentials_verified') for r in report['devices'].values()):
            config['lab']['unsecured_devices']=True
        save_private_json(args.config,config)
        reporter=Reporter(config)
        if args.verify_group:
            if not config.get('groups',{}).get('primary'):parser.error('Cần --group hoặc groups.primary.')
            roles=[role for role,row in report['devices'].items() if row['state']=='device']
            report['group_access']=verify_group(config,reporter,roles,args.discover_member_names)
            peers=[row.get('verified_peer',{}) for row in report['group_access'].values() if row['status']=='OPENED']
            if args.discover_member_names and {peer.get('role') for peer in peers}=={'A','B'}:
                config['lab'].setdefault('member_names',{}).update({peer['role']:peer['name'] for peer in peers})
                save_private_json(args.config,config)
        report['cleanup_errors']=reporter.cleanup_errors
        report['complete']=(all(row.get('no_credentials_verified') for row in report['devices'].values())
                            and not reporter.cleanup_errors
                            and all(row['status']=='CONFIGURED_NOT_MEASURED' for row in report['probes'])
                            and (not args.verify_group or all(row['status']=='OPENED' for row in report.get('group_access',{}).values())))
        path=reporter.directory/'lab-setup.json'
        save_private_json(path,reporter.sanitize(report))
        lines=['# Trạng thái setup lab','',report['note'],'','## Thiết bị','']
        for role,row in report['devices'].items():
            lines.append(f"- {role}: {row['state']}; secure={row.get('secure','chưa kiểm tra')}; vân tay={row.get('fingerprints','chưa kiểm tra')}; khuôn mặt={row.get('faces','chưa kiểm tra')}.")
        lines.extend(['','## Nhóm','',f"Nhóm chính: {config.get('groups',{}).get('primary','chưa chọn')}. Nhóm phụ được giữ nguyên; cần nhóm khác để test liên nhóm."])
        for role,row in report.get('group_access',{}).items():lines.append(f"- {role}: {row['status']} — {row.get('reason',row.get('note',''))}")
        lines.extend(['','## Probe','','CONFIGURED_NOT_MEASURED chỉ xác minh cấu hình, chưa phải kết quả đo hoặc PASS.','','| Probe | Trạng thái | Điều kiện đo |','|---|---|---|'])
        for row in report['probes']:lines.append(f"| {row['name']} | {row['status']} | {row['needs']} |")
        (reporter.directory/'lab-setup.md').write_text(reporter.redact('\n'.join(lines)+'\n'))
        reporter.finish()
        print(path)
        print(json.dumps({'devices':report['devices'],'group_access':report.get('group_access',{}),'complete':report['complete']},ensure_ascii=False))
        return 0 if report['complete'] else 2


if __name__=='__main__':raise SystemExit(main())
