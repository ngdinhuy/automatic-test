"""Không dùng lịch sử CONNECT hoặc PID cũ để chứng minh camera đang mở."""
import pytest
from tammi_runner.camera_capture import clients


def dump(active):return 'Active Camera Clients:\n['+active+']\nAllowed user IDs: 0\n== Camera service events log ==\nCONNECT com.example.app PID: 20'


def test_idle_ignores_historical_clients():
    assert clients(dump(''),'com.example.app',{20})==[]


def test_active_client_requires_exact_package_and_current_pid():
    text=dump('(Camera ID: 1, Cost: 100, PID: 20, Client Package Name: com.example.app), (Camera ID: 0, PID: 22, Client Package Name: com.example.app.other)')
    assert clients(text,'com.example.app',{20})==[{'camera_id':'1','pid':20}]
    assert clients(text,'com.example.app',{99})==[]


@pytest.mark.parametrize('text',[dump('unknown format'),'Active Camera Clients: missing list'])
def test_unknown_format_cannot_mean_camera_off(text):
    with pytest.raises(ValueError):clients(text,'com.example.app',{20})


def test_open_idle_client_is_not_streaming():
    from tammi_runner.camera_capture import streaming
    text=dump('(Camera ID: 1, PID: 20, Client Package Name: com.example.app)')+'\n== Camera device 1 status -2 dynamic info: ==\n    Device status: IDLE\n'
    rows=clients(text,'com.example.app',{20})
    assert rows and streaming(text,rows)==[]
    assert streaming(text.replace('Device status: IDLE','Device status: ACTIVE'),rows)==rows


def test_streaming_requires_device_status_for_target_camera_not_other_device():
    from tammi_runner.camera_capture import streaming
    rows=[{'camera_id':'1','pid':20}]
    text='== Camera device 0 dynamic info: ==\nDevice status: ACTIVE\n'
    with pytest.raises(ValueError):streaming(text,rows)


def load_adapter(monkeypatch):
    import importlib.util
    from tammi_runner.common import ROOT
    monkeypatch.syspath_prepend(str(ROOT/'scripts/probes'))
    spec=importlib.util.spec_from_file_location('camera_capture_adapter',ROOT/'scripts/probes/camera_capture.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_prepare_does_not_require_app_process_before_opening_it(monkeypatch):
    adapter=load_adapter(monkeypatch)
    monkeypatch.setattr(adapter,'adb',lambda *_:pytest.fail('Prepare không đo trước khi app được mở.'))
    result=adapter.main({'phase':'prepare','marker':'APPIUM-123456789abc','challenge':'fresh'})
    assert result['challenge']=='fresh' and result['measurements']=={}


def test_measure_missing_app_process_cannot_mean_camera_off(monkeypatch,tmp_path):
    import subprocess
    adapter=load_adapter(monkeypatch)
    def missing(*_):raise subprocess.CalledProcessError(1,['adb','pidof'],output='',stderr='')
    monkeypatch.setattr(adapter,'adb',missing)
    payload={'phase':'measure','marker':'APPIUM-123456789abc','challenge':'fresh','report_directory':str(tmp_path),'app_package':'com.example.app'}
    with pytest.raises(AssertionError,match='Không có process staging khi đo camera trên A'):adapter.main(payload)
