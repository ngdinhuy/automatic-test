"""Kiểm tra setup lab không coi cấu hình/thiết bị mất kết nối là số đo thành công."""
from pathlib import Path

import pytest

from tammi_runner.lab_setup import configure,probe_inventory,security


@pytest.mark.parametrize('policy,expected', [('secure=false',False),('  secure=true',True),('',None)])
def test_security_requires_explicit_android_policy(policy,expected):
    result=security(policy,'{"prints":[{"count":0}]}','{"prints":[{"count":2}]}')
    assert result=={'secure':expected,'fingerprints':0,'faces':2}


def test_missing_biometric_service_is_unknown_not_zero():
    result=security('secure=false',"Can't find service: fingerprint",'unrecognized output')
    assert result['fingerprints'] is None and result['faces'] is None


def test_group_and_default_probe_preserve_external_adapter_and_secondary():
    custom={'command':['/custom/adapter','--device','lab']}
    config={'groups':{'secondary':'Other test group'},'lab':{'probes':{'media_integrity':custom,'audio_routes':custom}}}
    configure(config,'Test refactor')
    assert config['groups']=={'primary':'Test refactor','secondary':'Other test group'}
    assert config['lab']['probes']['media_integrity']==custom
    assert config['lab']['probes']['audio_routes']==custom
    duplex=config['lab']['probes']['audio_duplex']
    assert duplex['command']==duplex['healthcheck_command']
    assert duplex['command'][1].endswith('/scripts/probes/call_audio_signals.py')


def test_inventory_does_not_treat_configured_adapter_as_measured(tmp_path):
    adapter=tmp_path/'python-adapter';adapter.touch()
    script=tmp_path/'measure.py';script.touch()
    rows=probe_inventory({'lab':{'probes':{'audio_duplex':{'command':[str(adapter),str(script)]}}}})
    assert next(row for row in rows if row['name']=='audio_duplex')['status']=='CONFIGURED_NOT_MEASURED'
    assert next(row for row in rows if row['name']=='video_duplex')['status']=='NOT_CONFIGURED'
    script.unlink()
    rows=probe_inventory({'lab':{'probes':{'audio_duplex':{'command':[str(adapter),str(script)]}}}})
    assert next(row for row in rows if row['name']=='audio_duplex')['status']=='NOT_CONFIGURED'


def test_offline_b_never_counts_as_verified(monkeypatch):
    from tammi_runner import lab_setup
    monkeypatch.setattr(lab_setup,'list_devices',lambda config:[])
    report=lab_setup.inspect({'devices':{'A':{'udid':'a'},'B':{'udid':'b'}}})
    assert all(row['state']=='DISCONNECTED' and not row.get('no_credentials_verified') for row in report['devices'].values())


def test_existing_builtin_media_probe_gains_video_support_without_losing_options():
    config=configure({})
    media=config['lab']['probes']['media_integrity']
    media['supported_media']=['camera_photo'];media['custom_option']='keep'
    configure(config)
    assert 'camera_video' in media['supported_media'] and 'gallery_video' in media['supported_media']
    assert media['custom_option']=='keep'
