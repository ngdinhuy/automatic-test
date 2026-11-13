"""Cổng điều kiện không biến command hoặc history cũ thành bằng chứng đo lab."""
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock
from tammi_runner import readiness
from tammi_runner.cases import Case


def test_missing_probe_and_configured_external_probe_are_not_ready(monkeypatch):
    monkeypatch.setattr(readiness,'preflight',lambda *args:None)
    cfg={'devices':{},'lab':{'probes':{'ringback':{'command':[sys.executable]}}}}
    cases=[Case('pending','test',('A','B'),'suite',requirements=('probe:ringback',))]
    value=readiness.inspect(cfg,cases,[])
    assert value['blocked']==1 and value['ready']==0
    assert value['probes'][0]['status']=='UNVERIFIED'
    cfg['lab']['probes'].clear()
    value=readiness.inspect(cfg,cases,[])
    assert value['probes'][0]['status']=='MISSING'


def test_history_skip_does_not_require_probe_or_claim_ready(monkeypatch):
    monkeypatch.setattr(readiness,'preflight',Mock(side_effect=AssertionError('Không kiểm tra case đã bỏ qua')))
    case=Case('done','old',('A','B'),'suite',requirements=('probe:ringback',))
    value=readiness.inspect({},[case],[],skipped=['done'])
    assert value['cases'][0]['status']=='SKIPPED'
    assert value['probes']==[] and value['ready']==value['blocked']==0


def test_healthcheck_requires_matching_challenge_and_actual_check_list(monkeypatch):
    cfg={'devices':{},'tools':{},'app_package':'staging','lab':{'probes':{'ringback':{'command':[sys.executable],'healthcheck_command':[sys.executable,'check.py']}}}}
    def execute(*args,**kwargs):
        payload=json.loads(kwargs['input'])
        return SimpleNamespace(stdout=json.dumps({'schema':1,'challenge':payload['challenge'],'ready':True,'checks':['Đã kết nối nguồn thu A']}))
    monkeypatch.setattr(readiness.subprocess,'run',execute)
    assert readiness.probe_check(cfg,'ringback',[])['status']=='READY'
    monkeypatch.setattr(readiness.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(stdout='{"schema":1,"challenge":"old","ready":true,"checks":["stale"]}'))
    assert readiness.probe_check(cfg,'ringback',[])['status']=='UNVERIFIED'


def test_cancel_stops_before_checking_next_external_probe(monkeypatch):
    import pytest
    from tammi_runner.common import Cancelled
    probe=Mock();monkeypatch.setattr(readiness,'probe_check',probe)
    case=Case('pending','test',('A','B'),'suite',requirements=('probe:ringback',))
    def cancel():raise Cancelled('stop')
    with pytest.raises(Cancelled):readiness.inspect({},[case],[],check_cancel=cancel)
    probe.assert_not_called()


def test_connected_bluetooth_cannot_bypass_missing_wired_hardware(monkeypatch):
    monkeypatch.setattr(readiness,'preflight',lambda *args:None)
    monkeypatch.setattr(readiness,'probe_check',lambda *args:{'name':'audio_routes','status':'READY','detail':'adapter checked','needs':'headsets'})
    case=Case('routes','routes',('A','B'),'suite',requirements=('probe:audio_routes',))
    hardware=[{'role':'A','observed':{'wired_output':False,'bluetooth_output':True,'bluetooth_call_profiles':True}}]
    value=readiness.inspect({},[case],[],hardware=hardware)
    assert value['blocked']==1 and 'dây/USB' in value['cases'][0]['detail']
    hardware[0]['observed']['wired_output']=True
    assert readiness.inspect({},[case],[],hardware=hardware)['ready']==1
