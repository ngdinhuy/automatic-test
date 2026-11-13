"""Không PASS nhờ player cũ/UID khác, muted hoặc bằng chứng sau gọi thiếu."""
import pytest
from tammi_runner.ringback_signals import snapshot,candidates,stopped
from tammi_runner.common import Blocked


def raw(uid=12,state='started',usage='USAGE_VOICE_COMMUNICATION',mute='none',key=7):
    return f'PlaybackActivityMonitor\n AudioPlaybackConfiguration piid:{key} u/pid:{uid}/100 state:{state} usage={usage} mutedState:{mute} deviceId:2\n'


def test_transition_and_stop_tracks_same_player_not_other_audio():
    before=snapshot(raw(state='paused'),12)
    during=snapshot(raw(),12)
    selected=candidates(before,during)
    assert len(selected)==1 and selected[0]['device_id']==2
    assert not candidates(during,during)
    assert not candidates(before,snapshot(raw(uid=13),12))
    assert not candidates(before,snapshot(raw(usage='USAGE_MEDIA'),12))
    assert not stopped(selected,during)
    assert stopped(selected,snapshot(raw(state='paused'),12))
    assert stopped(selected,snapshot(raw(key=8),12))


def test_missing_table_and_muted_are_not_success():
    before=snapshot('PlaybackActivityMonitor',12)
    with pytest.raises(Blocked):snapshot('Permission Denial',12)
    with pytest.raises(AssertionError,match='muted'):candidates(before,snapshot(raw(mute='user'),12))
    with pytest.raises(Blocked,match='mutedState'):candidates(before,snapshot(raw().replace('mutedState:none',''),12))
    zero=raw()+'- STREAM_VOICE_CALL:\n Muted: false\n Current: 2 (speaker): 0, 4 (headset): 0\n'
    with pytest.raises(AssertionError,match='volume'):candidates(before,snapshot(zero,12))


def test_ringback_catalog_requires_both_phases_and_partial_scope():
    from tammi_runner.cases import CASES
    for case in CASES:
        if 'probe:ringback' in case.requirements:
            assert case.coverage_level=='partial'
            assert {'ringback_signal_started','ringback_signal_stopped'}<=set(case.obligations)


def test_adapter_persists_three_phases_and_rejects_changed_identity(tmp_path,monkeypatch):
    import importlib.util,json
    from tammi_runner.common import ROOT
    spec=importlib.util.spec_from_file_location('ringback_under_test',ROOT/'scripts/probes/ringback_audio.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    current={'text':'PlaybackActivityMonitor','uid':12}
    def command(cfg,role,*args):
        if 'packages' in args:return 'package:test.app uid:'+str(current['uid'])
        if args[-1]=='audio':return current['text']
        return 'Diagnostic output'
    monkeypatch.setattr(module,'adb',command);monkeypatch.setattr(module.time,'sleep',lambda _:None)
    p={'devices':{'A':'device-a'},'tools':{},'app_package':'test.app','challenge':'nonce','marker':'APPIUM-123456abcdef','report_directory':str(tmp_path),'role':'A'}
    assert module.main({**p,'phase':'check'})['ready']
    module.main({**p,'phase':'prepare','stage':'baseline'})
    current['text']=raw()
    assert module.main({**p,'phase':'measure'})['measurements']['fresh_ringback_players']==1
    with pytest.raises(AssertionError,match='vẫn started'):module.main({**p,'phase':'after'})
    current['text']=raw(state='paused')
    assert module.main({**p,'phase':'after'})['measurements']['ringback_players_stopped']==1
    folder=tmp_path/('ringback-'+p['marker'])
    for phase in ('before','during','after'):
        evidence=json.loads((folder/(phase+'-0.json')).read_text())
        assert evidence['uid']==12 and evidence['challenge']=='nonce' and 'audio' in evidence
    current['uid']=13
    with pytest.raises(Blocked,match='UID'):module.main({**p,'phase':'after'})
