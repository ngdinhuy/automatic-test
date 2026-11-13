"""Kiểm tra điều kiện lab trước run; không ghi PASS/FAIL testcase sản phẩm."""
import html
import json
import subprocess
import uuid
from pathlib import Path

from .common import ROOT,Blocked,Cancelled,Reporter,list_devices,save_private_json,validate_devices
from .full_runner import preflight
from .lab_setup import NEEDS
from .probes import command
from .resume import pending_cases


def probe_check(config,name,available):
    detail=NEEDS.get(name,'Fixture và nguồn đo thật của testcase.')
    try:args=command(config,name)
    except Blocked as error:return {'name':name,'status':'MISSING','detail':str(error),'needs':detail}
    for arg in args[1:]:
        if arg.endswith('.py') and not Path(arg).is_file():return {'name':name,'status':'MISSING','detail':'Không tìm thấy adapter '+arg,'needs':detail}
    # Adapter tích hợp dùng ADB; đây chỉ là kiểm tra khả năng truy cập, chưa đo sản phẩm.
    builtin={str(ROOT/'scripts/probes'/f'{item}.py') for item in ('media_integrity','camera_capture','android_signals')}
    if len(args)>1 and str(Path(args[1]).resolve()) in builtin:
        return {'name':name,'status':'CONFIGURED','detail':'Adapter tích hợp tồn tại; máy/fixture được kiểm tra theo từng case. Số đo lấy trong run.','needs':detail}
    spec=config['lab']['probes'][name]
    check=spec.get('healthcheck_command')
    if not isinstance(check,list) or not check or not all(isinstance(item,str) for item in check) or not Path(check[0]).is_absolute():
        return {'name':name,'status':'UNVERIFIED','detail':'Đã có command nhưng chưa có healthcheck_command để kiểm tra nguồn đo/thiết bị ngoài.','needs':detail}
    nonce=uuid.uuid4().hex
    payload={'schema':1,'challenge':nonce,'phase':'check','probe':name,'devices':{r:d['udid'] for r,d in config['devices'].items() if d.get('udid')},'tools':config.get('tools',{}),'app_package':config['app_package'],'audio_capture':config.get('lab',{}).get('audio_capture',{})}
    try:
        result=subprocess.run(check,input=json.dumps(payload),text=True,capture_output=True,timeout=20,check=True)
        data=json.loads(result.stdout)
        if data.get('schema')!=1 or data.get('challenge')!=nonce:raise ValueError('Sai schema/challenge healthcheck.')
        if data.get('ready') is not True or not isinstance(data.get('checks'),list) or not data['checks']:raise ValueError(data.get('blocked','Nguồn đo chưa được healthcheck xác nhận.'))
        return {'name':name,'status':'READY','detail':str(data['checks']),'needs':detail}
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        return {'name':name,'status':'UNVERIFIED','detail':str(error),'needs':detail}


def inspect(config,cases,available,*,skipped=(),hardware=None,check_cancel=lambda:None):
    skipped=set(skipped)
    names=sorted({req.split(':',1)[1] for case in cases if case.id not in skipped for req in case.requirements if req.startswith('probe:')})
    probes=[]
    for name in names:
        check_cancel();probes.append(probe_check(config,name,available))
    indexed={row['name']:row for row in probes};rows=[]
    for case in cases:
        check_cancel()
        if case.id in skipped:
            rows.append({'id':case.id,'name':case.name,'status':'SKIPPED','detail':'Giữ kết quả PASS/FAIL hợp lệ trong lịch sử.','needs':''});continue
        issues=[]
        try:
            if case.action=='suite':preflight(config,case,available)
            else:validate_devices(config,available,case.roles)
        except Blocked as error:issues.append(str(error))
        for req in case.requirements:
            if req.startswith('probe:'):
                item=indexed[req.split(':',1)[1]]
                if item['status'] not in ('READY','CONFIGURED') and not (item['status']=='MISSING' and any(item['name'] in issue for issue in issues)):issues.append(item['name']+': '+item['detail'])
        if hardware is not None:
            from .audio_devices import route_requirements
            issues.extend(route_requirements(case,hardware))
        needs=[NEEDS.get(req.split(':',1)[1],'') for req in case.requirements if req.startswith('probe:')]
        rows.append({'id':case.id,'name':case.name,'status':'BLOCKED' if issues else 'READY','detail':' '.join(dict.fromkeys(issues)) if issues else 'Đủ điều kiện cấu hình/thiết bị để chạy; chưa phải kết quả test.','needs':' '.join(dict.fromkeys(needs))})
    return {'cases':rows,'probes':probes,'devices':available,'not_product_results':True,'ready':sum(r['status']=='READY' for r in rows),'blocked':sum(r['status']=='BLOCKED' for r in rows),'skipped':len(skipped)}


def report(args,config,cases):
    reporter=Reporter(config,args.output)
    try:
        def check_cancel():
            if args.stop_file and Path(args.stop_file).exists():raise Cancelled('Đã dừng kiểm tra điều kiện lab; chưa chạy testcase.')
        check_cancel()
        available=list_devices(config)
        _,skipped=pending_cases(cases,ROOT/'reports',skip_passed=args.skip_passed,skip_failed=args.skip_failed)
        from .audio_devices import inventory
        hardware=inventory(config,available)
        check_cancel()
        data=inspect(config,cases,available,skipped=[c.id for c in skipped],hardware=hardware,check_cancel=check_cancel)
        data['hardware']=hardware
        check_cancel()
        save_private_json(reporter.directory/'lab-readiness.json',data)
        safe=reporter.sanitize(data)
        def esc(value):return html.escape(str(value))
        body=''.join('<tr>'+''.join('<td>'+esc(row[key])+'</td>' for key in ('id','name','status','detail','needs'))+'</tr>' for row in safe['cases'])
        probes=''.join('<tr>'+''.join('<td>'+esc(row[key])+'</td>' for key in ('name','status','detail','needs'))+'</tr>' for row in safe['probes']+safe.get('hardware',[]))
        target=reporter.directory/'lab-readiness.html'
        target.write_text('<meta charset="utf-8"><title>Điều kiện test lab</title><style>body{font:15px system-ui;margin:32px;color:#172234}table{border-collapse:collapse;width:100%;margin:20px 0}td,th{border:1px solid #ddd;padding:10px;text-align:left}th{background:#edf1f6}</style><h1>Điều kiện test lab</h1><p>Đủ điều kiện: '+str(data['ready'])+' · BLOCKED: '+str(data['blocked'])+' · Giữ lịch sử: '+str(data['skipped'])+'. Kiểm tra này không tính PASS sản phẩm.</p><table><tr><th>Case</th><th>Nội dung</th><th>Điều kiện</th><th>Kết quả kiểm tra</th><th>Cần chuẩn bị</th></tr>'+body+'</table><h2>Probe / nguồn đo</h2><p>CONFIGURED: có adapter; số đo chỉ được xác minh trong run. UNVERIFIED: cần kiểm tra nguồn đo thật.</p><table><tr><th>Probe</th><th>Trạng thái</th><th>Kết quả kiểm tra</th><th>Nguồn đo cần có</th></tr>'+probes+'</table>')
        reporter.finish()
        reporter.emit('lab_readiness','Đã kiểm tra điều kiện lab; chưa chạy testcase.',**safe,report=str(target))
        return 2 if data['blocked'] else 0
    except Cancelled as error:
        reporter.emit('cancelled',str(error));reporter.finish();return 130
    except Exception:
        reporter.finish();raise
