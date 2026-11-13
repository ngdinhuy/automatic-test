"""Chỉ dùng fixture giả lập đã xác minh, luôn bỏ mock và trở về app test."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from tammi_runner.location_lab import FIXTURE,prepare
from tammi_runner.common import Blocked


def setup_run():
    driver=Mock();page=SimpleNamespace(driver=driver)
    devices=SimpleNamespace(adb=Mock(side_effect=lambda role,*args:'MOCK_LOCATION: allow' if 'appops' in args else 'true'),remember=Mock())
    ctx=SimpleNamespace(config={'app_package':'com.example.staging','lab':{'location':dict(FIXTURE)}},suite_cleanup=[],reporter=Mock())
    return SimpleNamespace(ctx=ctx,page=lambda _:page,devices=devices),page,driver


def test_mock_must_match_after_async_update_and_cleanup_resets_provider(tmp_path):
    run,page,driver=setup_run();run.ctx.reporter.directory=tmp_path;attempt=[0]
    def execute(command,*args):
        if command=='mobile: getGeolocation':
            attempt[0]+=1
            return {'latitude':0,'longitude':0} if attempt[0]==1 else FIXTURE
    driver.execute_script.side_effect=execute
    def wait(condition,*args,**kwargs):
        assert not condition();assert condition()
    page.wait=wait
    prepare(run)
    assert driver.activate_app.call_args.args==('com.example.staging',)
    run.ctx.suite_cleanup.pop()()
    driver.execute_script.assert_called_with('mobile: resetGeolocation')


def test_unconfirmed_mock_stops_before_sharing_and_restores_app():
    run,page,driver=setup_run()
    def wait(*args,**kwargs):raise AssertionError('mock chưa khớp')
    page.wait=wait
    with pytest.raises(Blocked,match='mock chưa khớp'):prepare(run)
    driver.activate_app.assert_called_with('com.example.staging')
    assert len(run.ctx.suite_cleanup)==1


def test_provider_selects_native_label_without_long_scroll_request():
    from tammi_runner.location_lab import allow_provider
    run,page,driver=setup_run()
    run.devices.adb.side_effect=['MOCK_LOCATION: deny','Starting Settings','MOCK_LOCATION: allow']
    driver.page_source='<hierarchy><node text="Ứng dụng vị trí mô phỏng"/></hierarchy>'
    page.text_locator=lambda text:'//*[@text="'+text+'"]'
    page.click=Mock();page.wait=lambda condition,*args,**kwargs:condition() or pytest.fail('provider chưa được cấp')
    allow_provider(run,page,'A')
    assert 'Ứng dụng vị trí mô phỏng' in page.click.call_args_list[0].args[0]
    assert 'Appium Settings' in page.click.call_args_list[1].args[0]
    driver.find_element.assert_not_called()


def test_received_card_must_follow_unique_marker_and_reject_ambiguous_cards():
    from tammi_runner.location_lab import fresh_card
    def card(rect):return '<node class="android.view.View" clickable="true" long-clickable="true" bounds="'+rect+'"><node class="android.widget.TextView" text="Vị trí hiện tại"/></node>'
    marker='<node class="android.view.View" content-desc="marker-new. 08:19" bounds="[20,500][300,550]"/>'
    old=card('[10,100][400,400]');new=card('[10,600][400,1000]')
    assert fresh_card('<hierarchy>'+old+marker+new+'</hierarchy>','marker-new')=='[10,600][400,1000]'
    assert fresh_card('<hierarchy>'+old+new+'</hierarchy>','marker-new') is None
    assert fresh_card('<hierarchy>'+marker+new+card('[10,1100][400,1450]')+'</hierarchy>','marker-new') is None


def test_destination_reads_navigation_intent_and_rejects_multiple_points():
    from tammi_runner.location_lab import navigation_coordinates
    assert navigation_coordinates('Intent { dat=google.navigation:q=21.02852,105.80482&mode=d }')==(21.02852,105.80482)
    with pytest.raises(Blocked):navigation_coordinates('gps lastLocation latitude=21.02852 longitude=105.80482')
    with pytest.raises(Blocked):navigation_coordinates('google.navigation:q=21.1,105.1 google.navigation:q=21.2,105.2')


def test_uncached_location_read_is_polled_until_fixture_not_counted_as_product_error(tmp_path):
    from selenium.common.exceptions import WebDriverException
    run,page,driver=setup_run();run.ctx.reporter.directory=tmp_path;reads=[0]
    def execute(command,*args):
        if command=='mobile: getGeolocation':
            reads[0]+=1
            if reads[0]==1:raise WebDriverException("Cannot execute the 'retrieve geolocation' action")
            return FIXTURE
    driver.execute_script.side_effect=execute
    def wait(condition,*args,**kwargs):assert not condition();assert condition()
    page.wait=wait
    prepare(run)
    assert reads[0]==2
