"""Lịch sử PASS không bị chạy lại từ các lượt preflight/diagnostic."""
import json
from dataclasses import replace

from tammi_runner.cases import select_cases
from tammi_runner.resume import pending_cases


def report(root,name,rows):
    folder=root/name;folder.mkdir()
    (folder/'summary.json').write_text(json.dumps({'results':rows}))


def case():return select_cases(['CALL-040-CAMERA_OFF'])[0]


def test_skip_proven_pass_but_keep_fail_and_unseen(tmp_path):
    first=case();second=replace(first,id='NEW');third=replace(first,id='FAILED')
    report(tmp_path,'001',[{'id':first.id,'status':'PASS','proved_assertions':list(first.obligations)},{'id':third.id,'status':'FAIL'}])
    pending,skipped=pending_cases([first,second,third],tmp_path)
    assert pending==[second,third] and skipped==[first]


def test_preflight_cancelled_and_diagnostic_cannot_replace_pass(tmp_path):
    item=case()
    report(tmp_path,'001',[{'id':item.id,'status':'PASS','proved_assertions':list(item.obligations)}])
    report(tmp_path,'002',[{'id':item.id,'status':'READY'},{'id':item.id,'status':'CANCELLED'}])
    report(tmp_path,'003',[])
    assert pending_cases([item],tmp_path)==([],[item])


def test_new_assertions_require_rerun_but_existing_proven_pass_is_retained(tmp_path):
    item=case()
    report(tmp_path,'001',[{'id':item.id,'status':'PASS','proved_assertions':[]}])
    assert pending_cases([item],tmp_path)==([item],[])
    report(tmp_path,'002',[{'id':item.id,'status':'PASS','proved_assertions':list(item.obligations)}])
    report(tmp_path,'003',[{'id':item.id,'status':'ERROR'}])
    assert pending_cases([item],tmp_path)==([],[item])


def test_invalidated_pass_is_not_skipped(tmp_path):
    item=case()
    report(tmp_path,'001',[{'id':item.id,'status':'PASS','proved_assertions':list(item.obligations)}])
    (tmp_path/'001/invalidated-results.json').write_text(json.dumps({item.id:'Kết quả cũ không hợp lệ.'}))
    assert pending_cases([item],tmp_path)==([item],[])


def test_skip_fail_and_error_but_allow_blocked_and_new(tmp_path):
    items=[replace(case(),id=name) for name in ('FAIL','ERROR','BLOCKED','NEW')]
    report(tmp_path,'001',[{'id':item.id,'status':item.id} for item in items[:3]])
    assert pending_cases(items,tmp_path,skip_failed=True)==(items[2:],items[:2])


def test_skip_failed_alone_does_not_silently_skip_pass(tmp_path):
    item=case()
    report(tmp_path,'001',[{'id':item.id,'status':'PASS','proved_assertions':list(item.obligations)}])
    assert pending_cases([item],tmp_path,skip_passed=False,skip_failed=True)==([item],[])


def test_skip_failed_keeps_old_failure_even_when_newer_run_is_blocked(tmp_path):
    item=case()
    report(tmp_path,'001',[{'id':item.id,'status':'FAIL'}])
    report(tmp_path,'002',[{'id':item.id,'status':'BLOCKED'}])
    assert pending_cases([item],tmp_path,skip_failed=True)==([],[item])


def test_newer_blocked_cannot_cause_previously_proven_pass_to_run_again(tmp_path):
    item=case()
    report(tmp_path,'001',[{'id':item.id,'status':'PASS','proved_assertions':list(item.obligations)}])
    report(tmp_path,'002',[{'id':item.id,'status':'BLOCKED'}])
    assert pending_cases([item],tmp_path)==([],[item])
