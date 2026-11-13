"""Vị trí lab cố định; không chia sẻ hoặc lưu vị trí thật của người dùng."""
from .common import Blocked,save_private_json
import re
from xml.etree import ElementTree as ET
from selenium.common.exceptions import WebDriverException

FIXTURE={'source':'appium_mock','latitude':21.028511,'longitude':105.804817}



def allow_provider(run,page,role):
    mode=run.devices.adb(role,'shell','appops','get','io.appium.settings','android:mock_location')
    if 'MOCK_LOCATION: allow' in mode:return
    # OPPO chặn shell appops; dùng lựa chọn công khai trong Developer options.
    run.devices.adb(role,'shell','am','start','-a','android.settings.APPLICATION_DEVELOPMENT_SETTINGS')
    # Mỗi lần cuộn là một request ngắn; UiScrollable dài vượt read timeout của server.
    for attempt in range(20):
        source=page.driver.page_source
        labels=[node.get('text','') for node in ET.fromstring(source).iter()]
        candidates=[label for label in labels if re.search(r'(vị trí (giả|mô phỏng)|mock location)',label,re.I)]
        if candidates:
            page.click(page.text_locator(candidates[0]),stable_bounds=True)
            break
        size=page.driver.get_window_size()
        more=page.driver.execute_script('mobile: scrollGesture',{'left':int(size['width']*.1),'top':int(size['height']*.25),'width':int(size['width']*.8),'height':int(size['height']*.65),'direction':'down','percent':.8})
        if not more:
            save_private_json(run.ctx.reporter.directory/'mock-provider-settings.json',{'source':page.driver.page_source,'attempts':attempt+1})
            raise Blocked('Chưa thấy lựa chọn nguồn mock location trong Developer options; đã lưu hierarchy để hiệu chỉnh.')
    else:raise Blocked('Không tìm thấy lựa chọn mock provider sau 20 lần cuộn.')
    page.click('//*[contains(@text,"Appium Settings")]',stable_bounds=True)
    page.wait(lambda:'MOCK_LOCATION: allow' in run.devices.adb(role,'shell','appops','get','io.appium.settings','android:mock_location'),'Chưa cấp được Appium Settings làm nguồn vị trí giả lập.',timeout=10)

def prepare(run,role='A',location=None):
    page=run.page(role);loc=location if location is not None else run.ctx.config.get('lab',{}).get('location',{})
    if loc.get('source')!='appium_mock':raise Blocked('Chỉ chạy location lab với fixture giả lập appium_mock.')
    lat=float(loc['latitude']);lon=float(loc['longitude'])
    if not -90<=lat<=90 or not -180<=lon<=180:raise Blocked('Tọa độ fixture ngoài miền hợp lệ.')
    old=run.devices.adb(role,'shell','cmd','location','is-location-enabled').strip()
    if old not in ('true','false'):raise Blocked('Không đọc được trạng thái bật vị trí để khôi phục.')
    if old=='false':
        run.devices.remember(role,'shell','cmd','location','set-location-enabled',old)
        run.devices.adb(role,'shell','cmd','location','set-location-enabled','true')
    def reset():
        try:page.driver.execute_script('mobile: resetGeolocation')
        finally:page.driver.terminate_app('io.appium.settings')
    run.ctx.suite_cleanup.append(reset)
    verified={}
    def matched():
        try:actual=page.driver.execute_script('mobile: getGeolocation')
        except WebDriverException as error:
            if 'retrieve geolocation' in str(error):return False
            raise
        good=abs(float(actual['latitude'])-lat)<=1e-5 and abs(float(actual['longitude'])-lon)<=1e-5
        if good:verified.update(actual)
        return good
    try:
        allow_provider(run,page,role)
        # Android mới giới hạn location service khi helper chưa từng ở foreground.
        page.driver.activate_app('io.appium.settings')
        page.driver.execute_script('mobile: setGeolocation',{'latitude':lat,'longitude':lon,'accuracy':5})
        page.wait(matched,'Thiết bị chưa dùng đúng vị trí giả lập; không gửi vị trí thật.',timeout=15)
    except AssertionError as error:raise Blocked(str(error)) from error
    finally:page.driver.activate_app(run.ctx.config['app_package'])
    save_private_json(run.ctx.reporter.directory/('mock-location-'+role+'.json'),{'fixture':loc,'measured':verified,'tolerance_degrees':1e-5})
    run.ctx.reporter.emit('step',role+': đã xác minh vị trí giả lập của lab',fixture=loc)


def fresh_card(source, marker):
    """Chỉ nhận card vị trí nằm sau marker mới; không mở card của lượt cũ."""
    root=ET.fromstring(source)
    def bounds(node):
        values=list(map(int,re.findall(r'\d+',node.get('bounds',''))))
        return values if len(values)==4 else None
    anchors=[bounds(n) for n in root.iter() if n.get('text')==marker or n.get('content-desc','').startswith(marker+'. ')]
    anchors=[b for b in anchors if b]
    if len(anchors)!=1:return None
    floor=anchors[0][3];found=[]
    for node in root.iter():
        if node.get('clickable')!='true' or node.get('long-clickable')!='true':continue
        rect=bounds(node)
        if not rect or rect[1]<floor-3 or rect[3]-rect[1]<100:continue
        if any(n.get('text')=='Vị trí hiện tại' for n in node.iter()):found.append(node)
    if not found:return None
    # Bỏ container bao ngoài nếu có đúng một card con.
    inner=[n for n in found if not any(child in found for child in list(n.iter())[1:])]
    return inner[0].get('bounds') if len(inner)==1 else None


def navigation_coordinates(activity_dump):
    """Đọc điểm đích do app truyền sang Maps; không dùng GPS hiện tại của B."""
    matches=re.findall(r'google\.navigation:q=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)',activity_dump)
    values=list(dict.fromkeys((float(a),float(b)) for a,b in matches))
    if len(values)!=1:raise Blocked('Không đọc được duy nhất điểm đích Maps từ intent mới trên B.')
    lat,lon=values[0]
    if not -90<=lat<=90 or not -180<=lon<=180:raise Blocked('Điểm đích Maps ngoài miền tọa độ hợp lệ.')
    return lat,lon


def current_location(run):
    from .pages import literal
    prepare(run)
    fixture=run.ctx.config['lab']['location']
    viewer={**fixture,'latitude':float(fixture['latitude'])+.01,'longitude':float(fixture['longitude'])+.01}
    prepare(run,'B',location=viewer)
    a,b=run.pair(run.p['context'])
    run.ctx.suite_cleanup.append(lambda:[page.home() for page in (a,b)])
    run.send(message=run.marker)
    u=run.ui('A');u.click('attachment')
    choice='//android.widget.TextView[@text="Vị trí"]'
    a.wait(lambda:len(a.elements(choice))==1,'Chưa xác minh duy nhất dòng Vị trí trong menu đính kèm.')
    a.click(choice,stable_bounds=True)
    def ready():
        a.allow_test_permission()
        return a.elements(a.text_locator('Vị trí hiện tại của bạn'))
    a.wait(ready,'Chưa mở được picker vị trí fixture.',timeout=25)
    a.click(a.text_locator('Vị trí hiện tại của bạn'),stable_bounds=True)
    # Chọn điểm và xác nhận là hai bước riêng trên bản staging hiện tại.
    a.find(a.text_locator('Chia sẻ vị trí hiện tại'))
    a.click(a.text_locator('Chia sẻ'),stable_bounds=True)
    a.find('//android.widget.EditText',timeout=45)
    def received():return fresh_card(b.driver.page_source,run.marker)
    try:rect=b.wait(received,'Chưa xác minh card vị trí mới sau marker ở B.',timeout=45)
    except AssertionError as error:raise Blocked(str(error)) from error
    source=b.driver.page_source
    save_private_json(run.ctx.reporter.directory/'location-received.json',{'marker':run.marker,'bounds':rect,'source':source})
    run.record('location_received')
    b.click('//*[@bounds='+literal(rect)+' and @clickable="true" and @long-clickable="true"]',stable_bounds=True)
    def direction_ready():
        b.allow_test_permission()
        return b.elements(b.text_locator('Xem đường đi'))
    b.wait(direction_ready,'B chưa mở được chi tiết vị trí vừa nhận.',timeout=25)
    b.click(b.text_locator('Xem đường đi'),stable_bounds=True)
    b.wait(lambda:b.driver.current_package=='com.google.android.apps.maps','B chưa chuyển sang Google Maps.',timeout=15)
    values=run.probe('location_destination')
    lat,lon=values['latitude'],values['longitude']
    expected=run.ctx.config['lab']['location']
    save_private_json(run.ctx.reporter.directory/'location-destination.json',{'marker':run.marker,'source':'Google Maps destination intent after opening fresh received card','measured':{'latitude':lat,'longitude':lon},'expected':expected})
    assert abs(lat-float(expected['latitude']))<=1e-5 and abs(lon-float(expected['longitude']))<=1e-5,'Điểm đích ở B khác tọa độ fixture A đã gửi.'
    run.record('coordinates_match')
    b.home();a.home()
