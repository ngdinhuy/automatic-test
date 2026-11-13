"""Không báo đã nối tai nghe từ cấu hình volume hoặc log cũ."""
import pytest
from tammi_runner.audio_devices import connected


def test_only_current_connected_section_counts():
    text='Current: 4 (headset): 15, 80 (bt_a2dp): 10\n  Connected devices:\n    [DeviceInfo: type:0x2 (speaker) name:speaker addr:]\n  APM Connected device (A2DP sink only):\nEvents log:\n    [DeviceInfo: type:0x80 (bt_a2dp) name:old headset]\n'
    data=connected(text)
    assert data['types']==['speaker'] and not data['wired_or_usb'] and not data['bluetooth']
    live=text.replace('type:0x2 (speaker)','type:0x4000000 (usb_headset)').replace('  APM Connected device','    [DeviceInfo: type:0x80 (bt_a2dp) name:test]\n  APM Connected device')
    assert connected(live)['wired_or_usb'] and connected(live)['bluetooth']
    with pytest.raises(ValueError):connected('Events log: headset connected yesterday')


def test_oppo_bluetooth_profiles_include_microphone_and_name_without_addresses():
    text='  Connected devices:\n    [DeviceInfo: type:0x10 (bt_sco) name: addr:MASKED]\n    [DeviceInfo: type:0x80000008 (bt_sco_hs) name: addr:MASKED]\n    [DeviceInfo: type:0x80 (bt_a2dp) name:Space Travel 2 addr:MASKED]\n\n  APM Connected device (A2DP sink only):\n'
    data=connected(text)
    assert data['bluetooth_call_profiles'] and data['bluetooth_input'] and data['bluetooth_output']
    assert data['devices'][-1]['name']=='Space Travel 2'
    assert data['devices'][1]['direction']=='input'
    assert 'MASKED' not in str(data)
    a2dp=connected('  Connected devices:\n    [DeviceInfo: type:0x80 (bt_a2dp) name:test addr:x]\n  End:\n')
    assert a2dp['bluetooth'] and not a2dp['bluetooth_call_profiles']


def test_route_prerequisite_checks_caller_device_and_keeps_missing_wired_blocked():
    from tammi_runner.audio_devices import route_requirements
    from tammi_runner.cases import Case
    case=Case('routes','route',('A','B'),'suite',requirements=('probe:audio_routes',))
    hardware=[{'role':'A','observed':{'wired_output':False,'bluetooth_output':True,'bluetooth_call_profiles':True}}]
    assert route_requirements(case,hardware)==['Máy A chưa nối tai nghe dây/USB để kiểm tra cắm/rút.']
    hardware[0]['observed']['wired_output']=True
    assert route_requirements(case,hardware)==[]
    assert route_requirements(Case('other','other',('A','B'),'suite'),[])==[]


def test_unrecognized_device_record_is_unknown_not_disconnected():
    with pytest.raises(ValueError):connected('  Connected devices:\n    [DeviceInfo: new format]\n  End:\n')


def test_live_call_route_requires_matching_uid_and_bound_client():
    from tammi_runner.audio_devices import call_route_sample, voice_stream_volume

    audio = """- STREAM_VOICE_CALL:
   Current: 1 (earpiece): 8, 10 (bt_sco): 14
   Devices: bt_sco(10)
- STREAM_MUSIC:
- Actual mode = MODE_IN_COMMUNICATION
- Mode owner:
  - Mode: MODE_IN_COMMUNICATION
  - Binder: android.os.BinderProxy@call
  - Uid: 10968
  - Package: staging.app
  Communication route clients:
    [CommunicationRouteClient: mCb: android.os.BinderProxy@other mPlaybackActive: true mRecordingActive: true]
    [CommunicationRouteClient: mCb: android.os.BinderProxy@call mPlaybackActive: true mRecordingActive: false]
  Active communication device: AudioDeviceAttributes: role:output type:bt_sco addr:null
"""
    assert call_route_sample(audio, 'staging.app', 10968) == {
        'active': True, 'route': 'bt_sco', 'playback': True, 'recording': False,
    }
    assert not call_route_sample(audio, 'staging.app', 10969)['active']
    assert voice_stream_volume(audio, 'bt_sco') == 14
    with pytest.raises(ValueError):
        voice_stream_volume(audio, 'earpiece')
