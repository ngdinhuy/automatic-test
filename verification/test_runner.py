"""Kiểm chứng bộ điều phối bằng dữ liệu giả, không chạm thiết bị Android."""
import json
import signal
from argparse import Namespace

import pytest

from tammi_runner import cli, runtime
from tammi_runner.cases import select_cases
from tammi_runner.common import Blocked, Reporter, validate_devices


def test_wait_heartbeat_keeps_both_sessions_alive_without_switching_apps(config,tmp_path,monkeypatch):
    class Driver:
        def __init__(self):self.reads=0
        @property
        def current_package(self):self.reads+=1;return config['app_package']
    ctx=cli.Context(config,Reporter(config,tmp_path),None)
    ctx.drivers={'A':Driver(),'B':Driver()};ctx._last_keepalive=0
    monkeypatch.setattr(cli.time,'monotonic',lambda:40)
    ctx.check();ctx.check()
    assert [driver.reads for driver in ctx.drivers.values()]==[1,1]


def test_auth_route_returns_from_message_settings_before_identity_check(config):
    from unittest.mock import Mock
    from tammi_runner.pages import AppPage
    driver=Mock();page=AppPage(driver,config,"A",lambda:None)
    state={"settings":True}
    page.allow_test_permission=lambda:False
    page.dismiss_optional_setup=lambda:False
    def elements(xpath):
        if state["settings"]:
            return [object()] if xpath in ('//*[@text="Tự động lưu ảnh/video đã chụp"]',
                                           '//*[@content-desc="Quay lại"]') else []
        return [object()] if xpath=='//*[@content-desc="Tin nhắn"]' else []
    page.elements=elements
    def click(xpath):
        assert xpath=='//*[@content-desc="Quay lại"]'
        state["settings"]=False
    page.click=Mock(side_effect=click)
    page.prepare_auth_route()
    page.click.assert_called_once()
    driver.back.assert_not_called()


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch, tmp_path):
    # Unit test không đọc journal của lượt Appium đang chạy thật.
    monkeypatch.setattr(cli,"ROOT",tmp_path)
    monkeypatch.setattr(runtime,"ROOT",tmp_path)


@pytest.fixture
def config():
    return {"environment": "staging", "platform": "Android",
            "app_package": "com.viettel.appviettel.staging",
            "devices": {"A": {"udid": "device-A", "system_port": 8201,
                              "account": {"phone": "0700000001", "otp": "123456"}},
                        "B": {"udid": None, "system_port": 8202,
                              "account": {"phone": "0700000002", "otp": "123456"}}}}


def test_two_device_case_rejects_missing_and_duplicate_mapping(config):
    available = [{"udid": "device-A", "state": "device"}]
    with pytest.raises(Blocked, match="Chưa chọn đủ"):
        validate_devices(config, available, ("A", "B"))
    config["devices"]["B"]["udid"] = "device-A"
    with pytest.raises(Blocked, match="khác nhau"):
        validate_devices(config, available, ("A", "B"))


def test_offline_device_and_same_account_are_not_allowed(config):
    config["devices"]["B"]["udid"] = "device-B"
    with pytest.raises(Blocked, match="chưa kết nối"):
        validate_devices(config, [{"udid": "device-A", "state": "unauthorized"}], ("A",))
    config["devices"]["B"]["account"] = config["devices"]["A"]["account"].copy()
    with pytest.raises(Blocked, match="tài khoản staging khác nhau"):
        validate_devices(config, [{"udid": name, "state": "device"} for name in ("device-A", "device-B")], ("A", "B"))


def test_report_redacts_credentials_without_corrupting_numeric_events(config, tmp_path):
    reporter = Reporter(config, tmp_path)
    reporter.emit("appium", "OTP 123456, phone 0700000001, Bearer fake-token")
    reporter.emit("case_result", "ok", seconds=0.123456, count=123456)
    reporter.results = [{"id": "x", "status": "BLOCKED", "message": "0700000001 <script>", "seconds": 0}]
    reporter.finish()
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert events[1]["seconds"] == 0.123456
    assert events[1]["count"] == 123456
    assert "0700000001" not in (tmp_path / "appium.log").read_text()
    assert "OTP 123456" not in (tmp_path / "appium.log").read_text()
    assert "fake-token" not in (tmp_path / "appium.log").read_text()
    report = (tmp_path / "report.html").read_text()
    assert "<script>" not in report and "&lt;script&gt;" in report
    assert "<skipped" in (tmp_path / "junit.xml").read_text()


def test_missing_device_produces_blocked_report_without_starting_appium(config, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "list_devices", lambda _: [])
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(signal, "signal", lambda *_: None)
    monkeypatch.setattr(runtime.ManagedAppium, "start", lambda _: pytest.fail("Không được mở Appium nếu thiếu thiết bị"))
    args = Namespace(case=["APP-OPEN", "CHAT-TEXT-PAIR"], output=str(tmp_path / "report"), stop_file=None)
    assert cli.run(args, config) == 2
    result = json.loads((tmp_path / "report/summary.json").read_text())
    assert [r["status"] for r in result["results"]] == ["BLOCKED", "BLOCKED"]
    assert not (tmp_path / ".runtime/run.lock").exists()


def test_stop_request_cancels_before_session_creation(config, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(signal, "signal", lambda *_: None)
    stop = tmp_path / "stop"
    stop.touch()
    args = Namespace(case=["APP-OPEN", "CHAT-DRAFT"], output=str(tmp_path / "report"), stop_file=str(stop))
    assert cli.run(args, config) == 130
    assert [r["status"] for r in json.loads((tmp_path / "report/summary.json").read_text())["results"]] == ["CANCELLED", "CANCELLED"]


def test_cleanup_happens_while_run_lock_is_held(config, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(signal, "signal", lambda *_: None)
    monkeypatch.setattr(cli, "execute_case", lambda *_: "fake orchestration pass")
    original = cli.Context.close
    def close(ctx):
        assert (tmp_path / ".runtime/run.lock").exists()
        original(ctx)
    monkeypatch.setattr(cli.Context, "close", close)
    args = Namespace(case=["APP-OPEN"], output=str(tmp_path / "report"), stop_file=None)
    assert cli.run(args, config) == 0


def test_unknown_catalog_case_cannot_be_claimed_as_executable():
    with pytest.raises(ValueError, match="chưa có script"):
        select_cases(["CHAT-SRC-033"])


def test_second_job_is_blocked_by_live_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    with runtime.RunLock():
        with pytest.raises(Blocked, match="job đang chạy"):
            with runtime.RunLock():
                pytest.fail("Không được lấy lock hai lần")


def test_call_without_locator_stops_before_phone_is_controlled(config, tmp_path, monkeypatch):
    config["devices"]["B"]["udid"] = "device-B"
    monkeypatch.setattr(cli, "list_devices", lambda _: [{"udid": n, "state": "device"} for n in ("device-A", "device-B")])
    ctx = cli.Context(config, Reporter(config, tmp_path), None)
    monkeypatch.setattr(ctx, "page", lambda _: pytest.fail("Không được chạm máy khi thiếu locator"))
    with pytest.raises(Blocked, match="locator call"):
        cli.execute_case(ctx, select_cases(["CALL-RECALL-A"])[0])


def test_install_rejects_prod_apk_before_adb_install(config, tmp_path, monkeypatch):
    from types import SimpleNamespace
    sdk = tmp_path / "sdk/build-tools/36.0.0"
    sdk.mkdir(parents=True)
    (sdk / "aapt").touch()
    apk = tmp_path / "prod.apk"
    apk.touch()
    config["tools"] = {"android_home": str(tmp_path / "sdk")}
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "list_devices", lambda _: [{"udid": "device-A", "state": "device"}])
    calls = []
    def command(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout="package: name='com.viettel.appviettel' versionCode='1'")
    monkeypatch.setattr(cli.subprocess, "run", command)
    args = Namespace(role=["A"], apk=str(apk), output=str(tmp_path / "report"), stop_file=None)
    assert cli.install(args, config) == 2
    assert all("install" not in call for call in calls)
    assert json.loads((tmp_path / "report/summary.json").read_text())["results"][0]["status"] == "BLOCKED"


def test_invalid_build_host_produces_report_without_running_gradle(config, tmp_path, monkeypatch):
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("Không được chạy build khi host sai"))
    args = Namespace(host=str(tmp_path / "missing"), environment="staging", output=str(tmp_path / "report"), stop_file=None)
    assert cli.build(args, config) == 2
    assert (tmp_path / "report/report.html").is_file()


def test_phone_matching_accepts_profile_formatting_but_not_query_or_wrong_account():
    from tammi_runner.pages import phone_nodes
    source = '<hierarchy><node class="android.widget.EditText" text="0700000001"/><node class="android.widget.TextView" text="0700 000 002"/><node class="android.widget.TextView" text="+84 700 000 001"/></hierarchy>'
    assert phone_nodes(source, "0700000001") == [("text", "+84 700 000 001")]
    assert phone_nodes(source, "0700000003") == []


def test_formatted_phone_and_key_arrays_are_redacted(config, tmp_path):
    reporter = Reporter(config, tmp_path)
    line = reporter.redact('phone 0700 000 001 {"value":["1","2","3","4","5","6"]}')
    assert "0700 000 001" not in line
    assert '"1","2","3"' not in line
    assert '"keycode":8' not in reporter.redact('{"keycode":8}')


def test_source_coverage_never_claims_full_source_pass_from_partial_script(config, tmp_path):
    from tammi_runner.coverage import write_coverage
    reporter = Reporter(config, tmp_path)
    reporter.results = [{"id": "CHAT-TEXT-PAIR", "status": "PASS", "seconds": 1, "message": "text only"}]
    reporter.finish()
    write_coverage(reporter)
    data = json.loads((tmp_path / "source-coverage.json").read_text())
    assert len(data["cases"]) == 76
    text_case = next(row for row in data["cases"] if row["source_id"] == "CHAT-SRC-003")
    assert text_case["status"] == "SCRIPT_DEFINED_NOT_ACCEPTED"
    assert text_case["scripts"][0]["status"] == "PASS"
    assert data["counts"]["EXCLUDED"] == 3
    assert "SCRIPT_DEFINED_NOT_ACCEPTED" in (tmp_path / "report.html").read_text()


@pytest.mark.parametrize("password_reminder", [True, False])
def test_logout_handles_password_reminder_without_setting_password(config, password_reminder):
    from types import SimpleNamespace
    from tammi_runner.pages import AppPage
    actions = []
    driver = SimpleNamespace(execute_script=lambda command, args: actions.append(args["elementId"]))
    page = AppPage(driver, config, "A", lambda: None)
    page.elements = lambda xpath: [SimpleNamespace(id="logout")] if 'Đăng xuất' in xpath else ([True] if password_reminder and 'Thiết lập mật khẩu' in xpath else [])
    def find(xpath, **kwargs):
        actions.append(xpath)
        return SimpleNamespace(id="defer" if 'Để sau' in xpath else "confirm")
    page.find = find
    page.wait = lambda *_args, **_kwargs: True
    page.login_and_verify = lambda allow_switch: actions.append(("login", allow_switch))
    page.logout_for_test_account()
    assert ("defer" if password_reminder else "confirm") in actions
    assert not any("Thiết lập ngay" in str(action) for action in actions)
    assert actions[-1] == ("login", False)


def test_profile_avatar_is_selected_next_to_search_not_unrelated_explore_button():
    from tammi_runner.pages import avatar_locator
    source = '<hierarchy><node clickable="true" bounds="[0,1413][1080,1557]" text="Xem tất cả"/><node clickable="true" bounds="[36,132][180,276]"><node text="VM"/></node><node clickable="true" bounds="[198,132][882,276]"><node text="Tìm kiếm tính năng" bounds="[312,182][792,226]"/></node></hierarchy>'
    assert "[36,132][180,276]" in avatar_locator(source)
    assert "[0,1413][1080,1557]" not in avatar_locator(source)


def test_contact_search_requires_full_query_and_single_contact_result():
    from tammi_runner.pages import unique_contact_result
    source = '<hierarchy><node class="android.widget.EditText" text="0700000002"/><node class="android.widget.TextView" text="Liên hệ (1)"/><node clickable="true" bounds="[0,200][600,350]"><node class="android.widget.TextView" text="Test B"/><node content-desc="Gọi"/><node content-desc="Gọi video"/></node></hierarchy>'
    locator, name = unique_contact_result(source, "0700000002")
    assert name == "Test B" and "[0,200][600,350]" in locator
    assert unique_contact_result(source, "0700000001") is None
    assert unique_contact_result(source.replace('Liên hệ (1)', 'Liên hệ (2)'), "0700000002") is None


def test_sending_never_overwrites_an_existing_draft(config, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tammi_runner import pages
    monkeypatch.setattr(pages, "ROOT", tmp_path)
    page = pages.AppPage(None, config, "A", lambda: None)
    page.composer = lambda: SimpleNamespace(get_attribute=lambda _: "Nháp của người dùng",
                                            send_keys=lambda _: pytest.fail("Không được ghi đè nháp"))
    with pytest.raises(Blocked, match="nháp sẵn"):
        page.send("APPIUM-new-test-message")


def test_draft_ownership_is_bound_to_device_and_account(config, tmp_path, monkeypatch):
    from tammi_runner import pages
    monkeypatch.setattr(pages, "ROOT", tmp_path)
    page = pages.AppPage(None, config, "A", lambda: None)
    page.draft_journal(["APPIUM-owned"])
    assert page.draft_journal() == ["APPIUM-owned"]
    config["devices"]["A"]["account"]["phone"] = "0700000009"
    assert page.draft_journal() == []


def test_call_header_placeholder_escapes_contact_names(config):
    from tammi_runner.pages import AppPage
    config["locators"] = {"call_audio": '//*[@text={peer_name}]/following-sibling::android.widget.Button[1]'}
    page = AppPage(None, config, "A", lambda: None)
    with pytest.raises(Blocked, match="Chưa xác minh tên"):
        page.named("call_audio")
    page.peer_name = "Test 'B'"
    assert '//*[@text="Test \'B\'"]' in page.named("call_audio")


def test_click_reacquires_stale_control_but_never_repeats_uncertain_dispatch(config, monkeypatch):
    from types import SimpleNamespace
    from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
    from tammi_runner import pages
    monkeypatch.setattr(pages.time, "sleep", lambda _: None)
    attempts, dispatched = [], []
    def gesture(_command, data):
        attempts.append(data["elementId"])
        if len(attempts) == 1:
            raise StaleElementReferenceException("Control đã bị Compose thay trước khi gesture chạy")
        dispatched.append(data["elementId"])
    driver = SimpleNamespace(execute_script=gesture)
    page = pages.AppPage(driver, config, "A", lambda: None)
    page.elements = lambda _: [SimpleNamespace(id="old" if not attempts else "new", is_displayed=lambda: True)]
    page.click('//*[@content-desc="Send"]')
    assert attempts == ["old", "new"] and dispatched == ["new"]
    attempts.clear()
    def uncertain(_command, data):
        attempts.append(data["elementId"])
        raise WebDriverException("Mất phản hồi sau khi gửi lệnh; không được tự bấm lại")
    driver.execute_script = uncertain
    with pytest.raises(WebDriverException):
        page.click('//*[@content-desc="Send"]')
    assert len(attempts) == 1


def test_probe_measurements_report_preserves_failed_case_and_escapes_text(config,tmp_path):
    reporter=Reporter(config,tmp_path)
    reporter.emit('case_start','start',case_id='VIDEO-TEST')
    reporter.emit('assertion','Probe <bad>',measurements={'decoded_frames':120})
    reporter.results=[{'id':'VIDEO-TEST','status':'FAIL','message':'missing assertion'}]
    reporter.finish()
    from tammi_runner.common import append_probe_summary
    append_probe_summary(tmp_path)
    content=(tmp_path/'report.html').read_text()
    assert content.count('id="probe-measurements"')==1
    assert 'Probe &lt;bad&gt;' in content and 'decoded_frames' in content
    assert json.loads((tmp_path/'summary.json').read_text())['results'][0]['status']=='FAIL'


def test_room_cleanup_can_end_owned_room_before_generic_call_cleanup(config,tmp_path):
    from types import SimpleNamespace
    ctx=cli.Context(config,Reporter(config,tmp_path),None)
    ctx.owned_call_roles.add('A');closed=[]
    def close_room():
        closed.append('new-test-room');ctx.owned_call_roles.clear()
    ctx.call_cleanup.append(close_room)
    ctx.pages={'A':SimpleNamespace(owned_draft=None,clear_owned_draft=lambda:None,end_owned_call=lambda:pytest.fail('Phòng đã kết thúc; không gọi cleanup generic.'))}
    assert ctx.cleanup()==[] and closed==['new-test-room']


def test_video_avatar_without_texture_can_reveal_controls_when_service_active(config,monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from tammi_runner.pages import AppPage
    config['locators']={'call_end':'END'}
    visible=[False];root=SimpleNamespace(id='compose-call',rect={'x':0,'y':0,'width':720,'height':1600})
    driver=Mock();driver.current_activity='com.tammi.call.host.presentation.CallActivity'
    page=AppPage(driver,config,'A',lambda:None)
    page.call_service_active=lambda:True
    def elements(xpath):
        if xpath=='END':return [object()] if visible[0] else []
        if xpath=='//androidx.compose.ui.platform.ComposeView':return [root]
        return []
    page.elements=elements
    tap=Mock(side_effect=lambda *args,**kwargs:visible.__setitem__(0,True))
    monkeypatch.setattr('tammi_runner.pages.find_adb',lambda _: 'adb')
    monkeypatch.setattr('tammi_runner.pages.subprocess.run',tap)
    page.reveal_call_controls()
    assert tap.call_args.args[0][-7:]==['input','swipe','180','880','180','880','100']
    driver.update_settings.assert_any_call({'waitForIdleTimeout':0})


def test_connected_timer_can_progress_when_controls_auto_hide_after_first_read():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from tammi_runner.pages import AppPage
    page=object.__new__(AppPage);page.role='A';page.emit=Mock()
    page.named=lambda key:'TIMER';page.allow_test_permission=lambda:False
    visible=[False];restores=[0]
    def restore():restores[0]+=1;visible[0]=True
    page.restore_owned_call_view=restore
    def value(key):
        text='00:01' if restores[0]==1 else '00:02';visible[0]=False;return text
    timer=SimpleNamespace(get_attribute=value,is_displayed=lambda:True)
    page.elements=lambda xpath:[timer] if visible[0] else []
    def wait(condition,message,timeout):
        result=condition()
        assert result,message
        return result
    page.wait=wait;page.wait_connected()
    assert restores[0]>=2


def test_setup_unlocks_only_explicitly_unsecured_lab_device(config):
    from unittest.mock import Mock
    from tammi_runner.pages import AppPage
    driver=Mock();page=AppPage(driver,config,'B',lambda:None)
    page.wake_for_interaction();driver.is_locked.assert_not_called()
    config['lab']={'unsecured_devices':True};driver.is_locked.side_effect=[True,True,False]
    page.wake_for_interaction();driver.unlock.assert_called_once()


def test_camera_control_hidden_before_click_is_revealed_without_duplicate_toggle(config,monkeypatch):
    from unittest.mock import Mock
    from types import SimpleNamespace
    from tammi_runner.pages import AppPage
    driver=Mock();page=AppPage(driver,config,'A',lambda:None)
    visible=[False];target=SimpleNamespace(id='camera',rect={'x':100,'y':200,'width':80,'height':80},is_displayed=lambda:True)
    page.elements=lambda xpath:[target] if visible[0] else []
    def reveal():visible[0]=True
    page.reveal_call_controls=Mock(side_effect=reveal)
    tap=Mock()
    monkeypatch.setattr('tammi_runner.pages.find_adb',lambda _: 'adb')
    monkeypatch.setattr('tammi_runner.pages.subprocess.run',tap)
    page.click('CAMERA',call_controls=True)
    page.reveal_call_controls.assert_called_once()
    assert tap.call_count==1
    assert tap.call_args.args[0][-4:]==['input','tap','140','240']
    driver.execute_script.assert_not_called()


def test_auth_dismisses_delayed_optional_setup_before_services_click(config):
    from unittest.mock import Mock
    from types import SimpleNamespace
    from tammi_runner.pages import AppPage
    driver=Mock();page=AppPage(driver,config,'B',lambda:None)
    visible=[False];target=SimpleNamespace(id='services',is_displayed=lambda:True)
    page.elements=lambda xpath:[target] if visible[0] else []
    page.dismiss_optional_setup=Mock(side_effect=lambda:visible.__setitem__(0,True))
    page.click('SERVICES',dismiss_setup=True)
    page.dismiss_optional_setup.assert_called_once()
    driver.execute_script.assert_called_once_with('mobile: clickGesture',{'elementId':'services'})


def test_live_call_service_does_not_allow_tapping_main_activity(config,monkeypatch):
    from unittest.mock import Mock
    from tammi_runner.pages import AppPage
    driver=Mock();driver.current_activity='com.example.MainActivity'
    config['locators']={'call_end':'END'}
    page=AppPage(driver,config,'A',lambda:None);page.elements=lambda _:[]
    page.call_service_active=lambda:True
    tap=Mock();monkeypatch.setattr('tammi_runner.pages.subprocess.run',tap)
    page.reveal_call_controls()
    tap.assert_not_called()


def test_meeting_end_keeps_foreground_call_instead_of_activating_launcher(config):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from tammi_runner.rich_flows import end_meeting
    state=[True];driver=Mock();driver.current_package=config['app_package']
    page=SimpleNamespace(driver=driver,call_active=lambda:state[0],elements=lambda _:[],wait=lambda condition,*args,**kwargs:condition())
    ui=SimpleNamespace(exists=lambda _:True,click=lambda _:state.__setitem__(0,False))
    ctx=SimpleNamespace(config=config,owned_call_roles={'A','B'})
    run=SimpleNamespace(meeting_owned=True,ctx=ctx,page=lambda _:page,ui=lambda _:ui,ended=Mock())
    end_meeting(run)
    driver.activate_app.assert_not_called()
    assert not run.meeting_owned and not ctx.owned_call_roles


def test_auth_returns_from_unjoined_meeting_lobby_before_identity_check(config):
    from unittest.mock import Mock
    from tammi_runner.pages import AppPage
    driver=Mock();driver.current_activity='com.tammi.call.meeting.presentation.prepare.MeetingPrepareActivity'
    page=AppPage(driver,config,'B',lambda:None);lobby=[True]
    page.allow_test_permission=lambda:False;page.dismiss_optional_setup=lambda:False
    page.home=Mock(side_effect=lambda:lobby.__setitem__(0,False))
    def elements(xpath):
        if xpath==page.text_locator('Tham gia') and lobby[0]:return [object()]
        if xpath=='//*[@content-desc="Tin nhắn"]' and not lobby[0]:return [object()]
        return []
    page.elements=elements
    page.prepare_auth_route()
    page.home.assert_called_once()
    driver.execute_script.assert_not_called()


def test_open_peer_never_reuses_group_name_as_cached_peer(config):
    from unittest.mock import Mock
    from tammi_runner.pages import AppPage
    config['locators']={'conversation_search':'PHONE_SEARCH'}
    page=AppPage(Mock(),config,'B',lambda:None)
    page.login_and_verify=lambda:None
    page.peer_role='A';page.peer_name='Test refactor';page.conversation_name='Test refactor'
    page.elements=lambda _:[object()]
    def click(xpath,**kwargs):
        if xpath=='PHONE_SEARCH':raise RuntimeError('correct-phone-search')
        pytest.fail('Không được mở row nhóm như peer đã cache.')
    page.click=click
    with pytest.raises(RuntimeError,match='correct-phone-search'):page.open_peer(peer_role='A')
