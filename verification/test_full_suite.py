"""Kiểm tra hợp đồng coverage, tiền điều kiện và khôi phục; không mô phỏng PASS sản phẩm."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tammi_runner.cases import CASES
from tammi_runner.common import ROOT, Blocked, Reporter
from tammi_runner.full_runner import FullRun, preflight
from tammi_runner import device, probes


def test_every_in_scope_source_has_functional_scripts_and_assertions():
    source=json.loads((ROOT/'catalog/source-cases.json').read_text())['cases']
    included={row['source_id'] for row in source if not row.get('exclusion_reason')}
    excluded={row['source_id'] for row in source if row.get('exclusion_reason')}
    full=[case for case in CASES if case.action=='suite']
    assert len(included)==73 and len(excluded)==3
    assert {item for case in full for item in case.sources}==included
    assert not excluded.intersection(item for case in full for item in case.sources)
    assert len({case.id for case in CASES})==len(CASES)
    assert all(case.obligations and case.params.get('flow') for case in full)


def test_handler_cannot_pass_by_returning_without_all_assertions():
    case=next(case for case in CASES if case.id=='CHAT-018-FUNCTIONAL')
    run=object.__new__(FullRun);run.case=case;run.done={'received'}
    with pytest.raises(RuntimeError,match='conversation_preview'):run.finish()


def test_group_title_cannot_be_used_as_member_identity():
    run=object.__new__(FullRun)
    page=SimpleNamespace(peer_name='Test refactor',peer_role='B',conversation_name='Test refactor')
    run.ctx=SimpleNamespace(config={},page=lambda role:page)
    with pytest.raises(Blocked,match='member_names.B'):run.member_name('B')
    page.conversation_name=None;page.peer_name='Verified B'
    assert run.member_name('B')=='Verified B'
    run.ctx.config={'lab':{'member_names':{'B':'Configured B'}}}
    assert run.member_name('B')=='Configured B'


def test_group_call_clears_default_recipients_before_selecting_b_and_c():
    run=object.__new__(FullRun);page=Mock();ui=Mock()
    page.text_locator=lambda text:'TEXT:'+text
    page.elements.return_value=[Mock(is_displayed=lambda:True)]
    run.page=lambda role:page;run.ui=lambda role:ui
    run.ctx=SimpleNamespace(config={'lab':{'member_names':{'B':'Verified B','C':'Verified C'}}},reporter=Mock(),evidence=Mock())
    run.start_group_call('A',('B','C'),'audio')
    clicks=page.click.call_args_list
    assert clicks[0].args==('TEXT:Bỏ chọn tất cả',)
    assert clicks[1].args==('TEXT:Verified B',)
    assert clicks[2].args==('TEXT:Verified C',)
    assert 'Gửi lời mời' in clicks[3].args[0]
    assert any('Đã chọn: 2/' in call.args[0] for call in page.find.call_args_list)


def test_mention_scrolls_popup_and_selects_member_after_last_page():
    from tammi_runner.suite_ui import UI
    member=Mock(id='verified-member');member.is_displayed.return_value=True
    panel=Mock(id='mention-popup');panel.get_attribute.return_value='[0,400][800,900]'
    driver=Mock();driver.execute_script.return_value=False
    page=SimpleNamespace(find=Mock(return_value=panel),elements=Mock(side_effect=[[],[member]]),driver=driver,check_cancel=lambda:None)
    UI(page).choose_mention('Verified B')
    calls=driver.execute_script.call_args_list
    assert calls[0].args==('mobile: scrollGesture',{'elementId':'mention-popup','direction':'down','percent':.65})
    assert calls[1].args==('mobile: clickGesture',{'elementId':'verified-member'})


@pytest.mark.parametrize('matches',[[],[Mock(),Mock()]])
def test_mention_does_not_choose_unknown_or_ambiguous_member(matches):
    from tammi_runner.suite_ui import UI
    panel=Mock(id='popup');panel.get_attribute.return_value='[0,400][800,900]'
    driver=Mock();driver.execute_script.return_value=False
    page=SimpleNamespace(find=lambda xpath:panel,elements=lambda xpath:matches,driver=driver,check_cancel=lambda:None)
    with pytest.raises(Blocked):UI(page).choose_mention('Verified B')
    assert not any(call.args[0]=='mobile: clickGesture' for call in driver.execute_script.call_args_list)


@pytest.mark.parametrize('incoming_observed',[True,False])
def test_sleep_records_incoming_only_after_observing_receiver(incoming_observed):
    run=object.__new__(FullRun)
    run.case=next(case for case in CASES if case.id=='CALL-034-SLEEP')
    run.p=run.case.params;run.record=Mock()
    caller,receiver=Mock(),Mock()
    if not incoming_observed:
        receiver.wait_incoming.side_effect=AssertionError('Không có incoming')
        with pytest.raises(AssertionError):run.answer(caller,receiver)
        run.record.assert_not_called();receiver.call_control.assert_not_called()
    else:
        run.answer(caller,receiver)
        run.record.assert_called_once_with('incoming')
        receiver.call_control.assert_called_once_with('call_accept')
        caller.wait_connected.assert_called_once();receiver.wait_connected.assert_called_once()


def pair_config():
    return {'environment':'staging','platform':'Android','app_package':'com.viettel.appviettel.staging',
            'devices':{role:{'udid':'device-'+role,'system_port':8201+i,'account':{'phone':'070000000'+str(i+1),'otp':'123456'}} for i,role in enumerate(('A','B'))}}


def test_probe_prerequisite_blocks_before_any_session_or_device_mutation(tmp_path,monkeypatch):
    monkeypatch.setattr("tammi_runner.full_runner.ROOT",tmp_path)
    config=pair_config();case=next(case for case in CASES if case.id=='CALL-042-VIDEO_MEDIA')
    with pytest.raises(Blocked,match='audio_duplex'):
        preflight(config,case,[{'udid':'device-'+r,'state':'device'} for r in ('A','B')])


@pytest.mark.parametrize('case_id',['CALL-009-SERVICE','CALL-011-SERVICE'])
def test_group_call_blocks_pair_before_starting_sessions(tmp_path,monkeypatch,case_id):
    monkeypatch.setattr('tammi_runner.full_runner.ROOT',tmp_path)
    config=pair_config();config['groups']={'primary':'Test refactor'}
    case=next(case for case in CASES if case.id==case_id)
    with pytest.raises(Blocked,match='Chưa chọn đủ thiết bị A, B, C'):
        preflight(config,case,[{'udid':'device-'+r,'state':'device'} for r in ('A','B')])


@pytest.mark.parametrize('measurement',[{}, {'count':True},{'count':float('nan')},{'count':-1}])
def test_probe_rejects_missing_boolean_nonfinite_and_out_of_range(tmp_path,monkeypatch,measurement):
    config=pair_config();config['lab']={'probes':{'launcher_badge':{'command':['/bin/echo']}}}
    ctx=SimpleNamespace(config=config,reporter=Reporter(config,tmp_path))
    def response(args,**kwargs):
        payload=json.loads(kwargs['input'])
        return SimpleNamespace(stdout=json.dumps({'schema':1,'challenge':payload['challenge'],'measurements':measurement}))
    monkeypatch.setattr(probes.subprocess,'run',response)
    with pytest.raises(AssertionError):probes.measure(ctx,'launcher_badge')


def test_probe_rejects_replayed_result(tmp_path,monkeypatch):
    config=pair_config();config['lab']={'probes':{'launcher_badge':{'command':['/bin/echo']}}}
    ctx=SimpleNamespace(config=config,reporter=Reporter(config,tmp_path))
    monkeypatch.setattr(probes.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps({'schema':1,'challenge':'old','measurements':{'count':0}})))
    with pytest.raises(AssertionError,match='challenge'):probes.measure(ctx,'launcher_badge')


def test_restore_runs_reverse_and_retains_failed_undo(tmp_path,monkeypatch):
    monkeypatch.setattr(device,'ROOT',tmp_path)
    control=device.Devices(SimpleNamespace(config=pair_config()))
    control.remember('A','shell','svc','wifi','enable');control.remember('B','shell','svc','data','disable')
    calls=[]
    def adb(role,*args):
        calls.append(role)
        if role=='A':raise RuntimeError('device disconnected')
    control.adb=adb
    assert control.restore()
    assert calls==['B','A']
    saved=json.loads(control.journal.read_text())
    assert [item['role'] for item in saved['undo']]==['A']
    control.adb=lambda *args:None
    assert control.restore()==[] and not control.journal.exists()


def test_recover_uses_original_udid_and_shell_quotes(tmp_path,monkeypatch):
    monkeypatch.setattr(device,'ROOT',tmp_path)
    path=tmp_path/'.runtime/device-restore.json';path.parent.mkdir()
    path.write_text(json.dumps({'devices':{'A':'original-A'},'undo':[{'role':'A','args':['shell','settings','put','global','name','value with spaces']}]}))
    monkeypatch.setattr(device,'find_adb',lambda config:'/adb')
    run=Mock();monkeypatch.setattr(device.subprocess,'run',run)
    assert device.recover(pair_config())==[]
    args=run.call_args.args[0]
    assert args[:3]==['/adb','-s','original-A']
    assert args[3:]==['shell',"settings put global name 'value with spaces'"]


def test_preflight_ready_is_junit_skipped_not_product_pass(tmp_path):
    reporter=Reporter(pair_config(),tmp_path)
    reporter.results=[{'id':'only-preflight','status':'READY','message':'not executed','seconds':0}]
    reporter.finish()
    assert '<skipped' in (tmp_path/'junit.xml').read_text()


def test_gallery_coordinates_are_derived_from_camera_tile_and_reject_other_layouts():
    from tammi_runner.gallery import cell_after_camera
    assert cell_after_camera({'x':24,'y':400,'width':255,'height':255},1080,1)=={'x':410,'y':528}
    with pytest.raises(Blocked):cell_after_camera({'x':24,'y':400,'width':500,'height':30},1080,1)
    with pytest.raises(Blocked):cell_after_camera({'x':24,'y':400,'width':255,'height':255},1080,3)


def test_cached_peer_row_can_have_clickable_false_without_requiring_network_search():
    from tammi_runner.pages import AppPage
    config=pair_config();driver=SimpleNamespace(page_source='<hierarchy/>')
    page=AppPage(driver,config,'A',lambda:None)
    page.login_and_verify=Mock();page.peer_role='B';page.peer_name='Test B'
    page.elements=lambda xpath:[object()] if 'starts-with(@content-desc' in xpath and '@clickable="true"' not in xpath else []
    page.click=Mock();page.composer=Mock()
    page.open_peer('B')
    assert 'starts-with(@content-desc' in page.click.call_args.args[0]
    assert 'Tìm kiếm' not in page.click.call_args.args[0]
    page.composer.assert_called_once()


@pytest.mark.parametrize('additional_bubble',[False,True])
def test_forward_requires_new_copy_at_correct_receiver(additional_bubble):
    run=object.__new__(FullRun);run.p={'flow':'forward'};run.marker='APPIUM-123456789abc'
    a=SimpleNamespace(peer_name='Target B');b=SimpleNamespace(peer_name='Source A')
    def wait(predicate,message):
        assert predicate(),message
    b.wait=wait;run.pair=lambda:(a,b);run.send=Mock();run.record=Mock()
    u=Mock();run.ui=lambda role:u
    run.marker_count=Mock(side_effect=[1,1,2 if additional_bubble else 1])
    if additional_bubble:
        run.chat();run.record.assert_called_with('forwarded_payload')
    else:
        with pytest.raises(AssertionError,match='bản chuyển tiếp'):run.chat()
        run.record.assert_not_called()
    u.fill.assert_called_with('search_input','Target B')
    assert any(call.kwargs.get('member')=='Target B' for call in u.click.call_args_list)


def test_transport_reset_keeps_results_and_refuses_pending_owned_work(tmp_path):
    from tammi_runner.cli import Context
    ctx=object.__new__(Context);ctx.owned_call_roles={'A'};ctx.pages={};ctx.devices_control=None;ctx.server=Mock()
    with pytest.raises(RuntimeError,match='tài nguyên'):ctx.reset_transport()
    ctx.server.stop.assert_not_called()


def test_resume_selects_only_cancelled_without_retrying_failures(tmp_path):
    from argparse import Namespace
    from tammi_runner.cli import selected_cases
    path=tmp_path/'summary.json';path.write_text(json.dumps({'results':[{'id':'APP-OPEN','status':'FAIL'},{'id':'AUTH-LOGIN','status':'ERROR'},{'id':'CHAT-015-FUNCTIONAL','status':'CANCELLED'}]}))
    selected=selected_cases(Namespace(case=[],resume_from=str(path)))
    assert [case.id for case in selected]==['CHAT-015-FUNCTIONAL']


def test_hidden_video_controls_reveal_once_on_largest_native_frame(monkeypatch):
    from tammi_runner.pages import AppPage
    config=pair_config();config['locators']={'call_end':'END'}
    visible=[False];actions=[]
    frames=[SimpleNamespace(id='local',rect={'x':400,'y':0,'width':100,'height':100}),SimpleNamespace(id='remote',rect={'x':0,'y':0,'width':1000,'height':2000})]
    def execute(argv,**kwargs):actions.append(argv[-5:]);visible[0]=True
    monkeypatch.setattr('tammi_runner.pages.find_adb',lambda _: 'adb')
    monkeypatch.setattr('tammi_runner.pages.subprocess.run',execute)
    page=AppPage(SimpleNamespace(current_activity='com.tammi.call.host.presentation.CallActivity',tap=execute,get_settings=lambda:{'waitForIdleTimeout':1000},update_settings=lambda _:None),config,'A',lambda:None)
    page.elements=lambda xpath:([object()] if visible[0] else []) if xpath=='END' else frames if 'TextureView' in xpath else [object()] if 'Bạn' in xpath else []
    page.reveal_call_controls();page.reveal_call_controls()
    assert actions==[['250','1100','250','1100','100']]


def test_image_adapter_decodes_real_files_and_distinguishes_different_content(tmp_path):
    import importlib.util
    from PySide6.QtGui import QImage,QColor
    spec=importlib.util.spec_from_file_location('test_media_probe',ROOT/'scripts/probes/media_integrity.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    first=QImage(32,32,QImage.Format.Format_RGB888);other=QImage(32,32,QImage.Format.Format_RGB888)
    for x in range(32):
        for y in range(32):
            color=QColor(x*8,y*8,(x+y)*4);first.setPixelColor(x,y,color);other.setPixelColor(x,y,QColor(255-x*8,255-y*8,255-(x+y)*4))
    path=tmp_path/'real.png';assert first.save(str(path))
    decoded=module.decode(path)
    assert module.similarity(first,decoded)['correlation']>.999
    assert module.similarity(first,other)['correlation']<0
    invalid=tmp_path/'invalid.png';invalid.write_bytes(b'not an image')
    with pytest.raises(AssertionError,match='giải mã'):module.decode(invalid)


def test_video_probe_is_explicitly_blocked_before_adb_or_test_actions(tmp_path):
    import subprocess,sys
    payload={'schema':1,'challenge':'new-challenge','marker':'APPIUM-123456789abc','case_id':'CHAT-006-CAMERA_VIDEO','phase':'prepare','report_directory':str(tmp_path),'devices':{}}
    response=subprocess.run([sys.executable,str(ROOT/'scripts/probes/media_integrity.py')],input=json.dumps(payload),capture_output=True,text=True,check=True)
    result=json.loads(response.stdout)
    assert result['challenge']==payload['challenge'] and result['blocked']
    assert not result['measurements']


def test_call_cleanup_fallback_only_stops_owned_staging_package(monkeypatch,tmp_path):
    from tammi_runner.cli import Context
    from tammi_runner import cli
    config=pair_config();reporter=Reporter(config,tmp_path)
    ctx=Context(config,reporter,None);ctx.server=Mock()
    failing=SimpleNamespace(owned_draft=None,end_owned_call=Mock(side_effect=AssertionError('hidden controls')),clear_owned_draft=Mock())
    other=SimpleNamespace(owned_draft=None,end_owned_call=Mock(),clear_owned_draft=Mock())
    ctx.pages={'A':failing,'B':other};ctx.owned_call_roles={'A'}
    monkeypatch.setattr(cli,'find_adb',lambda _: '/adb')
    calls=Mock();monkeypatch.setattr(cli.subprocess,'run',calls)
    assert ctx.cleanup()==[]
    assert calls.call_count==1
    assert calls.call_args.args[0]==['/adb','-s','device-A','shell','am','force-stop','com.viettel.appviettel.staging']
    other.end_owned_call.assert_not_called()
    assert ctx.transport_dirty


@pytest.mark.parametrize('service,expected', [
    ('  * ServiceRecord{abc u0 com.viettel.appviettel.staging/com.tammi.call.platform.services.CallForegroundService}', True),
    ('  * ServiceRecord{abc u0 com.viettel.appviettel.staging/com.dvm.chatcall.notification.call.ThirdPartyCallService}', True),
    ('  * ServiceRecord{abc u0 com.viettel.appviettel.staging/org.chromium.content.app.SandboxedProcessService0:0}', False),
    ('  (nothing)', False),
])
def test_call_guard_detects_hidden_service_without_treating_webview_as_call(monkeypatch,service,expected):
    from tammi_runner import pages
    monkeypatch.setattr(pages,'find_adb',lambda _: '/adb')
    monkeypatch.setattr(pages.subprocess,'run',lambda *a,**kw:SimpleNamespace(stdout=service))
    page=pages.AppPage(SimpleNamespace(),pair_config(),'A',lambda:None)
    assert page.call_service_active() is expected


def test_call_guard_blocks_hidden_call_before_any_ui_mutation():
    from tammi_runner.pages import AppPage
    page=AppPage(Mock(),pair_config(),'A',lambda:None)
    page.call_service_active=lambda:True
    page.elements=Mock(side_effect=AssertionError('Không được phụ thuộc control khi service đã báo active'))
    with pytest.raises(Blocked,match='còn cuộc gọi/service'):page.require_idle_call()
    page.driver.assert_not_called()


def test_call_cleanup_cannot_accept_hidden_controls_while_service_remains():
    from tammi_runner.pages import AppPage
    config=pair_config();config['locators']={'call_end':'END','call_reject':'REJECT'}
    page=AppPage(SimpleNamespace(current_package=config['app_package']),config,'A',lambda:None)
    page.elements=lambda _:[]
    page.restore_owned_call_view=lambda:None
    page.call_service_active=lambda:True
    def check_wait(predicate,message,**kw):
        assert not predicate()
        raise AssertionError(message)
    page.wait=check_wait
    with pytest.raises(AssertionError,match='PiP/service'):page.end_owned_call()


def test_cached_row_waits_for_stable_current_bounds_before_one_tap():
    from tammi_runner.pages import AppPage
    positions=iter([{'x':0,'y':800,'width':1000,'height':200},
                    {'x':0,'y':500,'width':1000,'height':200},
                    {'x':0,'y':500,'width':1000,'height':200}])
    class Row:
        id='row'
        def is_displayed(self):return True
        @property
        def rect(self):return next(positions)
    driver=Mock();page=AppPage(driver,pair_config(),'A',lambda:None)
    page.elements=lambda _: [Row()]
    page.click('ROW',stable_bounds=True)
    driver.execute_script.assert_called_once_with('mobile: clickGesture',{'x':500,'y':600})


def test_incoming_banner_is_not_shadowed_by_old_call_history_in_chat():
    from tammi_runner.pages import AppPage
    config=pair_config();config['locators']={'call_accept':'ACCEPT','call_reject':'REJECT'}
    driver=SimpleNamespace(current_package=config['app_package'])
    page=AppPage(driver,config,'B',lambda:None);page.peer_name='Caller A'
    opened=[False];taps=[]
    page.allow_test_permission=lambda:False
    def elements(xpath):
        if xpath=='ACCEPT':return [object()] if opened[0] else []
        if xpath=='REJECT':return []
        if '/ancestor::*' in xpath:raise AssertionError('Không được coi lịch sử chat là notification SystemUI')
        return [object()] if 'Cuộc gọi video đến' in xpath else []
    def click(xpath):taps.append(xpath);opened[0]=True
    page.elements=elements;page.click=click
    def wait(predicate,message,**kw):
        for _ in range(3):
            if predicate():return True
        raise AssertionError(message)
    page.wait=wait;page.wait_incoming()
    assert len(taps)==1 and 'Cuộc gọi video đến' in taps[0]


def test_pair_suite_excludes_device_c_and_account_c_prerequisites():
    from argparse import Namespace
    from tammi_runner.cli import selected_cases
    selected=selected_cases(Namespace(suite='pair',case=[]))
    ids={case.id for case in selected}
    assert 'CHAT-TEXT-PAIR' in ids and 'CALL-012-CALLER_BACKGROUND' in ids
    assert not any('C' in case.roles or 'account:C' in case.requirements or 'member_name:C' in case.requirements for case in selected)
    assert not any(case.id.startswith('CALL-023-') or case.id.startswith('CALL-024-') or case.id.startswith('CALL-025-') or case.id.startswith('CALL-026-') for case in selected)


def test_pair_suite_rejects_explicit_c_case_before_execution():
    from argparse import Namespace
    from tammi_runner.cli import selected_cases
    case=next(case for case in CASES if 'C' in case.roles)
    with pytest.raises(Blocked,match='không chạy case cần C'):selected_cases(Namespace(suite='pair',case=[case.id]))


def test_message_reply_action_is_not_an_active_call():
    from tammi_runner.pages import AppPage
    config=pair_config();config['locators']={'call_accept':'MESSAGE_REPLY','call_end':'END','call_reject':'REJECT'}
    page=AppPage(SimpleNamespace(),config,'A',lambda:None)
    page.call_service_active=lambda:False
    page.elements=lambda xpath:[object()] if xpath=='MESSAGE_REPLY' else []
    assert not page.call_active()


def test_missed_notification_parser_distinguishes_update_peer_and_channel():
    from tammi_runner.notifications import missed_versions
    def record(key,peer,stamp,channel='appviettel_missed_call_channel'):
        return f'NotificationRecord(x: pkg=com.viettel.appviettel.staging user=UserHandle{{0}} key={key} Notification(channel={channel}))\n android.title=String ({peer})\n mUpdateTimeMs={stamp}\n'
    before=record('call-key','Caller A',100)+record('sms-key','Caller A',110,'appviettel_sms_channel_v2')
    after=record('call-key','Caller A',200)+record('other-key','Other person',300)
    assert missed_versions(before,'com.viettel.appviettel.staging','Caller A')=={'call-key':100}
    assert missed_versions(after,'com.viettel.appviettel.staging','Caller A')=={'call-key':200}


def test_missed_notification_requires_new_version_not_just_visible_old_text():
    case=next(case for case in CASES if case.id=='CALL-017-FUNCTIONAL')
    run=object.__new__(FullRun);run.case=case;run.done=set();run.ctx=SimpleNamespace(reporter=Mock(),assertion_results={})
    page=Mock();page.peer_name='Caller A';run.page=lambda _:page
    ui=Mock();run.ui=lambda _:ui
    run.devices=Mock();run.devices.missed_notifications.side_effect=[{'key':100},{'key':101}]
    def wait(predicate,message,**kw):
        assert predicate() is False
        assert predicate() is True
    page.wait=wait
    run.new_missed_notification('B',{'key':100})
    ui.notification.assert_called_once_with('Cuộc gọi')
    assert 'fresh_missed_notification' in run.done


def test_original_image_acceptance_compares_every_pixel_despite_png_metadata(tmp_path):
    import importlib.util
    from PySide6.QtGui import QImage,QColor
    spec=importlib.util.spec_from_file_location('image_pixel_probe',ROOT/'scripts/probes/media_integrity.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    original=QImage(16,16,QImage.Format.Format_RGB888);original.fill(QColor(30,60,90))
    reencoded=original.copy();reencoded.setText('Comment','Đã encode lại metadata')
    first=tmp_path/'first.png';second=tmp_path/'second.png';assert original.save(str(first)) and reencoded.save(str(second))
    assert first.read_bytes()!=second.read_bytes()
    assert module.pixel_digest(module.decode(first))==module.pixel_digest(module.decode(second))
    reencoded.setPixelColor(0,0,QColor(31,60,90))
    assert module.pixel_digest(original)!=module.pixel_digest(reencoded)


def test_click_does_not_replace_semantic_node_with_fullscreen_ancestor():
    from tammi_runner.pages import AppPage
    node=SimpleNamespace(id='chip',is_displayed=lambda:True)
    root=SimpleNamespace(id='fullscreen',is_displayed=lambda:True)
    driver=Mock();page=AppPage(driver,pair_config(),'B',lambda:None)
    page.elements=lambda xpath:[root] if 'ancestor-or-self' in xpath else [node]
    page.click('OWNED_REACTION_CHIP')
    driver.execute_script.assert_called_once_with('mobile: clickGesture',{'elementId':'chip'})


def test_pair_suite_preserves_source_filter_instead_of_running_all_cases():
    from argparse import Namespace
    from tammi_runner.cli import selected_cases
    selected=selected_cases(Namespace(suite='pair',case=[],source=['CHAT-SRC-003']))
    assert selected and all('CHAT-SRC-003' in case.sources for case in selected)
    assert not any(case.id.startswith('CALL-') for case in selected)


def test_camera_shutter_uses_native_bounds_and_refuses_other_screens():
    from tammi_runner.suite_ui import camera_capture_locator
    source='<hierarchy><node content-desc="Đóng"/><node content-desc="Đổi camera"/><node clickable="true" bounds="[20,20][68,68]"><child content-desc="Đèn flash"/></node><node clickable="true" bounds="[100,500][176,576]"><canvas/></node><node clickable="true" bounds="[100,600][148,648]"><text text="Ảnh"/></node></hierarchy>'
    assert '[100,500][176,576]' in camera_capture_locator(source)
    with pytest.raises(Blocked,match='màn camera'):camera_capture_locator('<hierarchy/>')


def test_transport_reset_only_removes_owned_uia_forward(monkeypatch,tmp_path):
    from tammi_runner.cli import Context
    from tammi_runner import cli
    cfg=pair_config();ctx=Context(cfg,Reporter(cfg,tmp_path),None)
    ctx.drivers={'A':Mock()};ctx.server=Mock()
    monkeypatch.setattr(cli,'find_adb',lambda _: '/adb')
    calls=[]
    def command(args,**kwargs):
        calls.append(args)
        return SimpleNamespace(stdout='device-A tcp:8201 tcp:6790\ndevice-B tcp:8202 tcp:6790\ndevice-A tcp:9000 tcp:9000\n')
    monkeypatch.setattr(cli.subprocess,'run',command)
    ctx.reset_transport()
    assert calls==[['/adb','forward','--list'],['/adb','-s','device-A','forward','--remove','tcp:8201']]
    assert not ctx.drivers


def test_camera_reference_uses_only_new_capture_and_keeps_local_copy(tmp_path,monkeypatch):
    import importlib.util
    from PySide6.QtGui import QImage,QColor
    spec=importlib.util.spec_from_file_location('capture_reference_probe',ROOT/'scripts/probes/media_integrity.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    marker='APPIUM-'+'a'*12;folder=tmp_path/('media-'+marker);folder.mkdir()
    old='/sdcard/Android/data/com.viettel.appviettel.staging/files/IMG_old.jpg'
    new='/sdcard/Android/data/com.viettel.appviettel.staging/files/IMG_new.jpg'
    (folder/'state.json').write_text(json.dumps({'before_camera_files':[old],'before_A':[],'before_B':[],'owned_received':[]}))
    source=tmp_path/'source.png';image=QImage(24,24,QImage.Format.Format_RGB888);image.fill(QColor(30,60,90));assert image.save(str(source))
    monkeypatch.setattr(module,'camera_files',lambda _: [old,new])
    pulled=[]
    def adb(payload,role,*args):
        assert role=='A' and args[:2]==('pull',new)
        Path(args[2]).write_bytes(source.read_bytes());pulled.append(args[1]);return ''
    from pathlib import Path
    monkeypatch.setattr(module,'adb',adb)
    result=module.main({'marker':marker,'case_id':'CHAT-006-CAMERA_PHOTO','phase':'capture_reference','challenge':'fresh','report_directory':str(tmp_path)})
    state=json.loads((folder/'state.json').read_text())
    assert result['challenge']=='fresh' and pulled==[new]
    assert state['camera_source']==new and Path(state['camera_reference']).read_bytes()==source.read_bytes()


def test_ai_consent_sheet_is_only_closed_without_grant_or_decline():
    from tammi_runner.pages import AppPage
    page=AppPage(Mock(),pair_config(),'A',lambda:None)
    shown=[True];clicked=[]
    page.ai_consent_visible=lambda:shown[0]
    def click(xpath):clicked.append(xpath);shown[0]=False
    page.click=click
    page.wait=lambda predicate,message: predicate() or pytest.fail(message)
    page.dismiss_ai_consent()
    assert clicked==['//*[@content-desc="Đóng"]']


def test_tammi_case_blocks_without_explicit_consent_precondition(tmp_path,monkeypatch):
    monkeypatch.setattr('tammi_runner.full_runner.ROOT',tmp_path)
    case=next(case for case in CASES if case.id=='CHAT-036-PEER')
    with pytest.raises(Blocked,match='tammi_ai_consent_acknowledged'):
        preflight(pair_config(),case,[{'udid':'device-'+r,'state':'device'} for r in ('A','B')])


def test_privacy_decline_button_alone_is_not_an_active_call():
    from tammi_runner.pages import AppPage
    config=pair_config();config['locators']={'call_accept':'ACCEPT','call_end':'END','call_reject':'DECLINE'}
    page=AppPage(Mock(),config,'A',lambda:None)
    page.call_service_active=lambda:False
    page.elements=lambda xpath:[object()] if xpath=='DECLINE' else []
    assert not page.call_active()


def test_empty_composer_releases_owned_draft_without_delete_gesture():
    from tammi_runner.pages import AppPage
    page=AppPage(Mock(),pair_config(),'A',lambda:None);page.owned_draft='APPIUM-owned'
    field=Mock();field.get_attribute.return_value=''
    page.elements=lambda _: [field]
    page.draft_journal=Mock(return_value=['APPIUM-owned','APPIUM-other'])
    page.clear_owned_draft()
    assert page.owned_draft is None
    page.driver.execute_script.assert_not_called()
    page.draft_journal.assert_called_with(['APPIUM-other'])


def test_ringer_enum_and_restore_use_android_uppercase(tmp_path,monkeypatch):
    monkeypatch.setattr(device,'ROOT',tmp_path)
    control=device.Devices(SimpleNamespace(config=pair_config()))
    calls=[];values=iter(['1','2'])
    def adb(role,*args):
        calls.append(args)
        return '- mode (external) = '+{'1':'VIBRATE','2':'NORMAL'}[next(values)] if args==('shell','dumpsys','audio') else ''
    control.adb=adb
    control.ringer('B','normal')
    assert ('shell','cmd','audio','set-ringer-mode','NORMAL') in calls
    assert control.undo[-1]['args'][-1]=='VIBRATE'
    assert control.restore()==[]
    assert calls[-1]==('shell','cmd','audio','set-ringer-mode','VIBRATE')


@pytest.mark.parametrize("secure", ["true", "false"])
def test_wake_uses_adb_fallback_only_for_nonsecure_keyguard(secure):
    from tammi_runner.device import Devices

    page = Mock()
    page.driver.is_locked.return_value = True
    control = object.__new__(Devices)
    control.ctx = SimpleNamespace(page=lambda role: page)
    control.adb = Mock(return_value=f"  secure={secure}\n")
    if secure == "true":
        with pytest.raises(Blocked, match="keyguard"):
            control.wake("B")
        control.adb.assert_called_once_with("B", "shell", "dumpsys", "window", "policy")
        page.wait.assert_not_called()
    else:
        control.wake("B")
        assert control.adb.call_args_list[-1].args == ("B", "shell", "wm", "dismiss-keyguard")
        page.wait.assert_called_once()


def test_recover_normalizes_legacy_ringer_journal(tmp_path,monkeypatch):
    monkeypatch.setattr(device,'ROOT',tmp_path)
    path=tmp_path/'.runtime/device-restore.json';path.parent.mkdir()
    path.write_text(json.dumps({'devices':{'B':'old-B'},'undo':[{'role':'B','args':['shell','cmd','audio','set-ringer-mode','vibrate']}]}))
    monkeypatch.setattr(device,'find_adb',lambda config:'/adb')
    run=Mock();monkeypatch.setattr(device.subprocess,'run',run)
    assert device.recover(pair_config())==[]
    assert run.call_args.args[0]==['/adb','-s','old-B','shell','cmd audio set-ringer-mode VIBRATE']


def test_start_video_call_does_not_depend_on_ringer_variant():
    run=object.__new__(FullRun);a=Mock();b=Mock()
    for page in (a,b):page.elements.return_value=[]
    run.open=Mock(side_effect=[a,b]);run.ctx=SimpleNamespace(owned_call_roles=set())
    assert run.start_call(kind='video')==(a,b)
    a.call_control.assert_called_once_with('call_video')
    assert run.ctx.owned_call_roles=={'A','B'}
