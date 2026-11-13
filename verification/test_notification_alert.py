import importlib.util

from tammi_runner.common import ROOT


def test_probe_matches_fresh_alert_to_marker_key(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("notification_alert", ROOT / "scripts/probes/notification_alert.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    package = "test.app"
    key = "0|test.app|7|null|10123"
    marker = "APPIUM-123456abcdef"
    data = {
        "date": "100.000",
        "dumpsys": (
            f"NotificationRecord(0x10: pkg={package} channel={probe.CHANNEL} key={key}:\n"
            f"  mUpdateTimeMs=101000\n  android.text={marker}-0\n"
        ),
        "logcat": (
            f"99.000 123 456 I notification_alert: [{key},1,1,0,0,0]\n"
            f"100.500 123 456 I notification_alert: [{key},1,1,0,0,0]\n"
            "101.100 123 456 I notification_alert: [0|test.app|8|null|10123,1,1,0,0,0]\n"
            f"101.200 123 456 I notification_alert: [{key},1,0,0,0,0]\n"
        ),
    }
    monkeypatch.setattr(probe, "adb", lambda _config, _role, _shell, command, *_: data[command])
    payload = {"probe": "notification_alert", "challenge": "test", "stage": "baseline",
               "devices": {"B": "test-b"}, "app_package": package,
               "marker": marker, "report_directory": str(tmp_path)}
    probe.main({**payload, "phase": "prepare"})
    assert probe.main({**payload, "phase": "measure"})["measurements"] == {
        "sound_dispatched": 0, "vibration_dispatched": 1,
    }
