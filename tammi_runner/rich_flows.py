"""Các hành trình media, nhóm, vị trí và Meet dùng chung bộ assertion đầy đủ."""
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from .common import ROOT, Blocked
from .pages import literal, phone_nodes


def remember(run,callback):
    run.ctx.suite_cleanup.append(callback)


def group_create(run,name):
    a=run.page("A");u=run.ui("A");a.home();u.click("new_chat");u.click("new_group")
    u.fill("group_name",name)
    # Màn hiện tại yêu cầu hai thành viên ngoài người tạo; C chỉ cần tài khoản, chưa cần session.
    for role in ("B","C"):
        phone=run.ctx.config["devices"][role]["account"]["phone"]
        fields=a.elements('//android.widget.EditText')
        search=next((e for e in fields if e.get_attribute("text")!=name and "Tên nhóm" not in (e.get_attribute("text") or "")),None)
        if not search:raise Blocked("Màn tạo nhóm chưa expose ô tìm thành viên độc lập.")
        u.fill("group_member_search",phone)
        lab=run.ctx.config["lab"]
        name_for_a=lab.get("member_names_by_viewer",{}).get("A",{}).get(role) or lab["member_names"][role]
        u.click("member_result",member=name_for_a)
    a.keyboard_back();u.click("create_group")
    def clean():
        if not name.startswith("APPIUM-"):raise RuntimeError("Không dọn nhóm không do run tạo.")
        u.open_named(name);u.profile()
        locator=run.ctx.config.get("locators",{}).get("group_dissolve") or '//*[@text="Giải tán nhóm"]'
        a.click(locator)
        if u.exists("confirm"):u.click("confirm")
        a.home()
    remember(run,clean)
    a.find(a.text_locator(name));a.composer();a.peer_name=name;a.conversation_name=name
    return name


def mention(run,reply=False):
    a,b=run.pair("group");u=run.ui("A");member=run.ctx.config["lab"]["member_names"]["B"]
    run.type_owned("A",run.marker+" @")
    u.choose_mention(member)
    text=a.composer().get_attribute("text")
    assert member in text,"Mention không dùng đúng tên theo cấu hình danh bạ/nickname."
    a.owned_draft=text;a.draft_journal(a.draft_journal()+[text])
    u.click("send");run.release_draft_if_empty("A");b.message_received(run.marker)
    bubble=run.ui("B").message(run.marker)
    assert member in (bubble.get_attribute("content-desc") or bubble.get_attribute("text")),"B không nhận đúng tên mention."
    if reply:
        run.ui("B").menu(run.marker);run.ui("B").click("reply")
        run.page("B").send(run.marker+" reply");a.message_received(run.marker+" reply")
        quote=run.ctx.config.get("locators",{}).get("reply_mention") or f'//*[contains(@content-desc,{literal(member)}) and contains(@content-desc,{literal(run.marker)})]'
        a.find(quote);run.record("quoted_mention","reply_received")
    else:run.record("mention_identity","received_mention")


def poll(run):
    a,b=run.pair("group");u=run.ui("A");u.click("attachment");u.click("poll")
    u.fill("poll_question",run.marker);u.fill("poll_option_1",run.marker+" one");u.fill("poll_option_2",run.marker+" two")
    a.keyboard_back()
    for _ in range(6):
        if u.exists('poll_create'):break
        panel=a.find('//*[@scrollable="true"]')
        a.driver.execute_script('mobile: scrollGesture',{'elementId':panel.id,'direction':'down','percent':.65})
    u.click("poll_create");b.message_received(run.marker);run.record("poll_created")
    option=b.text_locator(run.marker+' one')
    b.click(option,stable_bounds=True)
    # Android gửi phiếu ngay khi chọn option; không có nút xác nhận Bình chọn riêng.
    b.find(option+'/parent::*//*[@content-desc="Đã chọn"]')
    card='//*[@text='+literal(run.marker)+']/ancestor::*[.//*[@text='+literal(run.marker+' one')+'] and .//*[@text='+literal(run.marker+' two')+']][1]'
    for role in ("A","B"):
        run.page(role).find(card+'//*[@text="1 người bình chọn"]')
    run.record("vote_synced")


def camera_auto_save(run):
    a=run.page("A");title=a.text_locator("Tự động lưu ảnh/video đã chụp")
    row=title+'/ancestor::*[.//*[@text="Bật" or @text="Tắt"]][1]'
    def open_settings():
        a.home();a.click('//*[@content-desc="Cài đặt"]')
        a.wait(lambda:a.elements(title) or a.elements('//*[@text="Tin nhắn"]'),"Chưa mở cài đặt tin nhắn.")
        if not a.elements(title):a.click('//*[@text="Tin nhắn"]')
        a.find(title)
    def read():
        value=a.find(row+'//*[@text="Bật" or @text="Tắt"]').get_attribute("text")
        if value not in ("Bật","Tắt"):raise Blocked("Không đọc được trạng thái tự lưu camera.")
        return value=="Bật"
    def set_value(enabled):
        open_settings()
        if read()==enabled:return
        a.click(title)
        switch=a.find('//*[@checkable="true"]')
        checked=switch.get_attribute("checked")
        if checked not in ("true","false"):raise Blocked("Switch tự lưu chưa expose checked; không đoán trạng thái.")
        if (checked=="true")!=enabled:a.click('//*[@checkable="true"]')
        a.click('//*[@text="Xác nhận"]')
        a.wait(lambda:len(a.elements(title))==1 and read()==enabled,"Chưa lưu đúng trạng thái tự lưu camera.")
    open_settings();original=read()
    from .common import save_private_json
    save_private_json(run.ctx.reporter.directory/'camera-auto-save-before.json',{"role":"A","udid":run.ctx.config["devices"]["A"]["udid"],"enabled":original})
    if not original:
        remember(run,lambda:set_value(original))
        set_value(True)
    run.ctx.reporter.emit("step","Đã xác minh tự lưu camera bật; cleanup sẽ khôi phục giá trị trước test.")
    a.open_peer()


def open_owned_video(run):
    b=run.page('B')
    own='//*[contains(@text,'+literal(run.marker)+') or contains(@content-desc,'+literal(run.marker)+')]/preceding-sibling::android.view.View[1]'
    b.click(own,stable_bounds=True)
    play='//*[@content-desc="Phát/Tạm dừng"]'
    download='//*[@content-desc="Tải xuống" or @text="Tải xuống"]'
    last_tap=[time.monotonic()]
    def ready():
        source=b.driver.page_source
        nodes=[node for node in ET.fromstring(source).iter() if node.get('displayed')!='false']
        # Gallery đồng bộ pager bất đồng bộ: phải thấy caption đúng VÀ control video.
        labels=[node.get('content-desc','')+' '+node.get('text','') for node in nodes]
        if any(run.marker in label for label in labels) and any('Phát/Tạm dừng' in label for label in labels):
            return bool(b.elements(download))
        if time.monotonic()-last_tap[0]>=3:
            if b.elements('//android.widget.EditText'):
                # Tap đầu chỉ tải video về cache; mở lại đúng bubble sau khi tải xong.
                if not b.elements(own+'//*[@content-desc="Tải video xuống"]'):b.click(own,stable_bounds=True)
            else:
                # Player tự ẩn controls sau 4 giây; tap giữa viewer để hiện lại.
                size=b.driver.get_window_size()
                b.driver.execute_script('mobile: clickGesture',{'x':size['width']//2,'y':size['height']//2})
            last_tap[0]=time.monotonic()
        return False
    b.wait(ready,'Chưa xác minh Gallery đang mở đúng caption video của run; không tải thumbnail/ảnh khác.',timeout=180)
    # Giữ controls tại thời điểm lưu thay vì chạm nút của pager trước khi đồng bộ.
    b.click(play,stable_bounds=True)
    b.click(download,stable_bounds=True);b.allow_test_permission()
    if b.elements('//*[@text="Tải lại"]'):b.click('//*[@text="Tải lại"]',stable_bounds=True)


def media(run):
    flow=run.p["flow"];kind=run.p.get("media","camera_photo")
    a,b=run.pair("group" if flow=="whatsapp_camera" else None);u=run.ui("A")
    fixture=run.ctx.config["fixtures"][kind]
    original=a.composer().get_attribute("text") or ""
    if original not in ("","Nhập tin nhắn"):
        if original not in a.draft_journal():raise Blocked("Có nháp sẵn trước gửi media; không ghi đè.")
        a.owned_draft=original;a.clear_owned_draft();a.open_peer()
    if run.p.get("save_camera"):camera_auto_save(run)
    before=None
    if flow=="whatsapp_camera":
        run.probe("whatsapp_call");run.record("whatsapp_call_active")
    if kind.startswith("camera_"):
        before=run.devices.adb("A","shell","content","query","--uri","content://media/external/images/media","--projection","_id:_display_name")
        u.click("attachment");u.click("camera");a.allow_test_permission()
        if kind=="camera_video":
            u.click("camera_video");u.click("camera_record");run.devices.wait_seconds(4,"Quay video test 4 giây");u.click("camera_record")
        else:u.click("camera_shutter")
        if u.exists("camera_done"):u.click("camera_done")
        else:a.composer()  # PreviewMediaScreen dùng composer + Send, không có bước “Xong”.
        if kind in ("camera_photo","camera_video") and flow!="whatsapp_camera":run.probe("media_integrity",phase="capture_reference")
        if flow=="whatsapp_camera":
            a.composer();run.record("camera_capture","camera_not_frozen");return
        filename=None
    else:
        path=Path(fixture["path"]).expanduser();path=path if path.is_absolute() else ROOT/path
        paths=[path]
        if kind=="multiple_images":
            second=fixture.get("second_path")
            if not second:raise Blocked("Fixture multiple_images cần second_path.")
            second_path=Path(second).expanduser();paths.append(second_path if second_path.is_absolute() else ROOT/second_path)
        from .gallery import select
        filename=select(run,paths)[0]
    if run.p.get("reject"):
        if not u.exists("media_limit_error"):
            if kind=="image_over_20mb" and u.exists("quality"):
                u.click("quality");u.click("original")
                if u.exists("confirm"):u.click("confirm")
            u.click("send")
        u.find("media_limit_error");run.record("size_limit_error")
        # Không có caption/filename bên nhận trong cả cửa sổ kiểm tra.
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            run.ctx.check();assert run.marker not in b.driver.page_source,"Media vượt giới hạn vẫn được chuyển."
        run.record("no_delivery");return
    if run.p.get("quality"):
        u.click("quality");u.click(run.p["quality"])
        if u.exists("confirm"):u.click("confirm")
    caption=run.ctx.config.get("locators",{}).get("media_caption") or '//android.widget.EditText[contains(@hint,"chú thích") or contains(@text,"chú thích")]'
    inputs=a.elements(caption) or a.elements('//android.widget.EditText')
    if inputs:
        a.draft_journal(a.draft_journal()+[run.marker]);a.owned_draft=run.marker
        inputs[0].send_keys(run.marker)
    u.click("send")
    if inputs:
        if kind=='gallery_video':
            marker=literal(run.marker)
            locator='//*[@class!="android.widget.EditText" and (contains(@text,'+marker+') or contains(@content-desc,'+marker+'))]'
            progress=[0]
            def received():
                if time.monotonic()-progress[0]>=30:
                    run.ctx.reporter.emit('step','Chờ video lớn gửi xong và xuất hiện ở B; vẫn giữ session A/B.')
                    progress[0]=time.monotonic()
                return next((element for element in b.elements(locator) if element.is_displayed()),None)
            target=b.wait(received,'Video lớn chưa tới B trong 15 phút.',timeout=900)
        else:target=run.ui("B").message(run.marker)
    elif filename:target=run.ui("B").find("media_bubble",filename=filename,timeout=60)
    else:
        # Camera cần caption để phân biệt ảnh mới với ảnh cũ; không PASS bằng việc tìm ảnh bất kỳ.
        if not inputs:raise Blocked("Cần media_caption semantics trên bản app này để đối chiếu đúng media camera mới.")
        target=run.ui("B").message(run.marker)
    if inputs:run.release_draft_if_empty("A")
    run.record("sent_media")
    if kind in ('camera_video','gallery_video'):
        open_owned_video(run)
        run.record('receiver_open')
        run.probe('media_integrity',fixture=kind);run.record('media_metadata');return
    # Caption và ảnh có thể là hai node anh em; mở ảnh trong chính item có caption marker.
    own_image='//*[contains(@content-desc,'+literal(run.marker)+') or contains(@text,'+literal(run.marker)+')]/ancestor::*[.//*[@content-desc="Tin nhắn hình ảnh"]][1]//*[@content-desc="Tin nhắn hình ảnh"]'
    sibling_image='//*[contains(@content-desc,'+literal(run.marker)+')]/preceding-sibling::android.view.View[1]'
    siblings=b.elements(sibling_image)
    pictures=[image for image in siblings if image.rect["height"]>target.rect["height"]*3 and image.rect["width"]>=target.rect["width"]*.8]
    selected_image=sibling_image
    if not pictures:
        # Không leo tới toàn bộ danh sách rồi mở nhầm ảnh của tin cũ.
        own_image=own_image.replace('/ancestor::*[.//*[@content-desc="Tin nhắn hình ảnh"]]', '/ancestor::*[.//*[@content-desc="Tin nhắn hình ảnh"] and not(.//*[contains(@content-desc,"APPIUM-") and not(contains(@content-desc,'+literal(run.marker)+'))])]')
        pictures=b.elements(own_image)
        selected_image=own_image
    if not pictures:raise Blocked("Caption đã nhận nhưng chưa xác định được đúng vùng ảnh; không click ảnh khác.")
    if kind=="multiple_images":
        # Fixture có đúng 2 ảnh; layout nguồn đặt ô đầu ở góc trên/trái, tâm album có thể là đường chia ô.
        def open_album_tile(fraction):
            previous=[None]
            def stable_album():
                rect=b.find(selected_image).rect
                if rect==previous[0]:return rect
                previous[0]=rect;return False
            rect=b.wait(stable_album,"Album test còn chuyển vị trí.")
            b.driver.execute_script("mobile: clickGesture",{"x":int(rect["x"]+rect["width"]*.25),"y":int(rect["y"]+rect["height"]*fraction)})
        open_album_tile(.25)
    else:b.click(selected_image,stable_bounds=True)
    locator=run.ctx.config.get("locators",{}).get("media_viewer") or '//*[@text="Tải xuống" or @content-desc="Tải xuống"]'
    b.find(locator);run.record("receiver_open")
    run.ui("B").click("media_save");b.allow_test_permission()
    if kind=="multiple_images":
        # Mở riêng ô thứ hai của album đúng marker, tránh pager chứa cả ảnh lịch sử hội thoại.
        b.driver.back();b.message_received(run.marker)
        open_album_tile(.75);b.find(locator)
        run.ui("B").click("media_save");b.allow_test_permission()
    # Adapter đo file đã mở: checksum/dimensions/duration, không dùng việc có icon làm bằng chứng đủ nội dung.
    values=run.probe("media_integrity",fixture=kind,filename=filename,quality=run.p.get("quality"))
    assert values["decodable"]==1
    run.record("media_metadata")
    if run.p.get("quality"):
        assert 0<values["received_bytes"]<100*1024*1024
        if run.p["quality"]=="original":
            # PNG có thể được encode lại mà vẫn giữ nguyên toàn bộ pixel và độ phân giải.
            assert values["checksum_matches"]==1 or values.get("exact_pixels_match")==1,"Ảnh gốc không giữ nguyên dữ liệu file hoặc toàn bộ pixel/độ phân giải."
        run.record("compression_size")
    if run.p.get("save_camera"):
        assert values.get("camera_public_saved")==1,"Ảnh camera chưa được lưu vào Gallery/MediaStore public ở A (file tạm riêng của app chưa đủ)."
        run.record("camera_saved")


def voice(run):
    a,b=run.pair()
    u=run.ui("A")
    receiver_control='//*[@content-desc="Tải âm thanh" or @content-desc="Play" or @content-desc="Pause"]'
    run.send()
    if b.elements(receiver_control):
        raise Blocked("Hội thoại đang hiển thị tin thoại cũ, chưa có locator nhận diện riêng tin mới.")
    record=u.xpath("voice_record")+'/ancestor-or-self::*[@clickable="true"][1]'
    a.click(record,stable_bounds=True)
    a.allow_test_permission()
    u.find("voice_send",timeout=8)
    run.devices.wait_seconds(8,"Ghi tin thoại test để đủ cửa sổ lấy mẫu playback.")
    a.click(u.xpath("voice_send")+'/ancestor-or-self::*[@clickable="true"][1]',stable_bounds=True)
    try:
        bubble=b.find(receiver_control,timeout=45)
    except AssertionError as error:
        raise Blocked("Chưa tìm thấy control của tin thoại mới trên B.") from error
    if len(b.elements(receiver_control))!=1:
        raise Blocked("Có nhiều control phát trên màn nhận, chưa quy được tin mới.")
    run.record("new_voice_message")
    if bubble.get_attribute("content-desc")=="Tải âm thanh":
        b.click('//*[@content-desc="Tải âm thanh"]',stable_bounds=True)
    play='//*[@content-desc="Play"]'
    b.find(play,timeout=30)
    if len(b.elements(receiver_control))!=1:
        raise Blocked("Có nhiều control phát sau khi tải tin thoại.")
    run.probe("voice_playback_signal",phase="prepare",stage="baseline")
    b.click(play,stable_bounds=True)
    run.probe("voice_playback_signal")
    run.record("receiver_playback_signal_started","receiver_playback_signal_stopped")


def location(run):
    if not run.p["live"]:
        from .location_lab import current_location
        return current_location(run)
    a,b=run.pair(run.p["context"]);u=run.ui("A");u.click("attachment");u.click("location");a.allow_test_permission()
    u.click("live_location" if run.p["live"] else "current_location")
    if u.exists("location_send"):u.click("location_send")
    active=[bool(run.p["live"])]
    def stop_live():
        if active[0]:
            run.open("A",run.p["context"]);u.click("live_stop");active[0]=False
    if active[0]:remember(run,stop_live)
    bubble=run.ui("B").find("location_bubble",timeout=45);run.record("location_received")
    b.driver.execute_script("mobile: clickGesture",{"elementId":bubble.id})
    loc=run.ctx.config["lab"]["location"]
    run.ui("B").find("location_coordinates",latitude=loc["latitude"],longitude=loc["longitude"])
    run.record("coordinates_match")
    if run.p["live"]:
        run.probe("location_live");run.record("live_updates")
        u.click("live_stop");active[0]=False;run.ui("B").page.find(run.ui("B").page.text_locator("Đã dừng chia sẻ hành trình"))
        run.record("live_stopped")


def group_qr_image(run,name):
    from PySide6.QtGui import QImageReader

    a=run.page("A")
    pattern=re.compile(r"_id=(\d+), _data=(/storage/emulated/0/Pictures/QR_"+re.escape(name)+r"_\d+\.png), _size=([1-9]\d*)$")

    def saved_images():
        result=run.devices.adb("A","shell","content","query","--uri","content://media/external/images/media",
                               "--projection","_id:_data:_size")
        return {int(match[1]):match[2] for line in result.splitlines() if (match:=pattern.search(line))}

    before=saved_images()
    run.ui("A").click("qr_save")

    def new_image():
        images={key:path for key,path in saved_images().items() if key not in before}
        if len(images)>1:
            raise Blocked("Có nhiều ảnh QR mới trùng nhóm test trong MediaStore.")
        return next(iter(images.values()),None)

    try:
        source=a.wait(new_image,"Chưa thấy ảnh QR của nhóm test trong MediaStore.",timeout=15)
    except AssertionError as error:
        raise Blocked(str(error)) from error
    run.devices.remember("A","shell","rm","-f",source)
    local=run.ctx.reporter.directory/(run.marker+".png")
    run.devices.adb("A","pull",source,local)
    if QImageReader(str(local)).read().isNull():
        raise Blocked("Ảnh QR mới lưu không giải mã được.")
    return local


def group_lifecycle(run):
    name=group_create(run,run.marker+" group");a=run.page("A");b=run.page("B");u=run.ui("A")
    run.record("group_created");u.profile()
    if run.p["join"]=="link":
        u.click("invite_link");u.click("copy_link");link=a.driver.get_clipboard_text()
        parsed=urlparse(link)
        assert parsed.scheme in ("https","http") and parsed.netloc,"Không lấy được link nhóm hợp lệ."
        run.record("invite_shared")
        # B là thành viên được thêm khi tạo; rời rồi join lại bằng link để không giả PASS vì đã có membership.
        run.ui("B").open_named(name);run.ui("B").profile();run.ui("B").click("leave_group")
        if run.ui("B").exists("confirm"):run.ui("B").click("confirm")
        run.devices.adb("B","shell","am","start","-a","android.intent.action.VIEW","-d",link,"-p",run.ctx.config["app_package"])
    else:
        u.click("group_qr")
        local=group_qr_image(run,name)
        run.record("invite_shared")
        remote="/sdcard/Download/"+local.name
        run.devices.remember("B","shell","rm","-f",remote)
        run.devices.adb("B","push",local,remote)
        run.devices.adb("B","shell","am","broadcast","-a","android.intent.action.MEDIA_SCANNER_SCAN_FILE","-d","file://"+remote)
        run.ui("B").open_named(name);run.ui("B").profile();run.ui("B").click("leave_group")
        if run.ui("B").exists("confirm"):run.ui("B").click("confirm")
        b.home();run.ui("B").click("qr_scan");run.ui("B").click("qr_gallery")
        run.ui("B").click("picker_item",filename=local.name)
    run.ui("B").click("join_group");b.find(b.text_locator(name));b.composer();run.record("joined_membership")
    run.ui("B").profile();run.ui("B").click("leave_group")
    if run.ui("B").exists("confirm"):run.ui("B").click("confirm")
    b.home();run.ui("A").open_named(name);u.profile();u.click("group_members")
    member=run.member_name("B");a.wait(lambda:not a.elements(a.text_locator(member)),"B chưa rời membership nhóm.")
    run.record("left_membership")


def profile(run):
    a,b=run.pair(run.p.get("context"));u=run.ui("A")
    run.send();u.profile()
    if run.p.get("context")=="peer":
        phone=run.ctx.config["devices"]["B"]["account"]["phone"]
        a.wait(lambda:phone_nodes(a.driver.page_source,phone),"Profile chưa hiển thị đúng số tài khoản B.")
    else:
        a.find('//*[starts-with(@text,'+literal(a.peer_name)+')]')
    run.record("profile_identity")
    u.click("profile_search");u.fill("search_input",run.marker);u.message(run.marker);run.record("profile_search")
    run.open("A",run.p.get("context"));u.profile()
    was_pinned=bool(u.exists("conversation_unpin"));was_muted=bool(u.exists("unmute"))
    def restore():
        run.open("A",run.p.get("context"));u.profile()
        if bool(u.exists("conversation_unpin"))!=was_pinned:u.click("conversation_pin" if was_pinned else "conversation_unpin")
        if bool(u.exists("unmute"))!=was_muted:u.click("mute" if was_muted else "unmute")
    remember(run,restore)
    u.click("conversation_unpin" if was_pinned else "conversation_pin")
    u.find("conversation_pin" if was_pinned else "conversation_unpin");run.record("pin_toggle")
    u.click("unmute" if was_muted else "mute");u.find("mute" if was_muted else "unmute");run.record("mute_toggle")
    u.click("profile_media");u.find("profile_media");run.record("media_access")


def pin_order(run):
    a,b=run.pair();u=run.ui('A');names=(a.peer_name,run.ctx.config['groups']['primary']);states={}
    if names[0]==names[1]:raise Blocked('Cần hai hội thoại khác nhau để kiểm tra thứ tự ghim.')
    def order():
        a.home()
        if a.elements(a.text_locator('Tất cả')):a.click(a.text_locator('Tất cả'),stable_bounds=True)
        width=a.driver.get_window_size()['width'];rows=[]
        for node in ET.fromstring(a.driver.page_source).iter():
            desc=node.get('content-desc','');bounds=list(map(int,re.findall(r'\d+',node.get('bounds',''))))
            if node.get('class')!='android.view.View' or ',' not in desc or len(bounds)!=4:continue
            w,h=bounds[2]-bounds[0],bounds[3]-bounds[1]
            if w>=width*.8 and width*.08<=h<=width*.35:rows.append((bounds[1],desc.split(',',1)[0]))
        return list(dict.fromkeys(name for _,name in sorted(rows)))
    def set_pin(name,wanted):
        u.open_named(name);u.profile()
        if bool(u.exists('conversation_unpin'))!=wanted:u.click('conversation_pin' if wanted else 'conversation_unpin')
        a.wait(lambda:bool(u.exists('conversation_unpin'))==wanted,'Chưa xác nhận trạng thái ghim của '+name)
    for name in names:
        u.open_named(name);u.profile();states[name]=bool(u.exists('conversation_unpin'))
    original=order();old_pinned=[name for name in original if states.get(name)]
    count=sum(states.values())
    if len(old_pinned)!=count or original[:count]!=old_pinned:
        raise Blocked('Không chứng minh được thứ tự ghim gốc để khôi phục; chưa đổi trạng thái ghim.')
    save={'states':states.copy(),'pinned_order':old_pinned}
    from .common import save_private_json
    save_private_json(run.ctx.reporter.directory/('pins-'+run.marker+'.json'),save)
    pending=[True]
    def restore():
        if not pending[0]:return
        for name in names:set_pin(name,False)
        for name in reversed(old_pinned):set_pin(name,True)
        if old_pinned:assert order()[:len(old_pinned)]==old_pinned,'Chưa khôi phục đúng thứ tự ghim gốc.'
        pending[0]=False
    remember(run,restore)
    for name in names:set_pin(name,False)
    for name in names:set_pin(name,True)
    current=order()
    assert len(current)>=2 and current[:2]==[names[1],names[0]],'Hội thoại ghim gần nhất chưa đứng đầu.'
    run.record('pinned_order');restore();run.record('restore_pins')


def end_meeting(run):
    if not getattr(run,'meeting_owned',False):return
    a=run.page('A');u=run.ui('A')
    if not a.call_active() and not run.page('B').call_active():
        run.meeting_owned=False;run.ctx.owned_call_roles.difference_update(('A','B'));return
    # Activate launcher khi CallActivity đang ở trước sẽ đưa host về MainActivity.
    if a.driver.current_package!=run.ctx.config['app_package']:
        a.driver.activate_app(run.ctx.config['app_package'])
    if not u.exists('meeting_end_all'):
        a.reveal_call_controls();a.call_control('call_end')
    u.click('meeting_end_all')
    description='//*[contains(@text,"Bạn có chắc chắn muốn kết thúc cuộc họp")]/ancestor::*[.//*[@text="Kết thúc"]][1]//*[@text="Kết thúc"]'
    a.wait(lambda:a.elements(description) or not a.call_active(),'Chưa có xác nhận kết thúc phòng Meet do run tạo.',timeout=12)
    if a.elements(description):a.click(description,stable_bounds=True)
    run.ended(a,run.page('B'))
    run.meeting_owned=False;run.ctx.owned_call_roles.difference_update(('A','B'))


def meeting_start(run):
    a,b=run.page('A'),run.page('B');u=run.ui('A')
    u.open_named(run.ctx.config['groups']['primary'])
    u.click('group_call_menu');u.click('meeting_new')
    name=run.ctx.config.get('lab',{}).get('member_names',{}).get('B')
    if not name:raise Blocked('Cần tên B đã xác minh để chỉ mời B vào Meet.')
    a.find(a.text_locator(name),timeout=30)
    clear=a.text_locator('Bỏ chọn tất cả')
    if a.elements(clear):a.click(clear);a.find(a.text_locator('Chọn tất cả'))
    if len(a.elements(a.text_locator(name)))!=1:raise Blocked('Tên B trùng/không duy nhất trong danh sách; không mời thành viên khác.')
    a.click(a.text_locator(name),stable_bounds=True)
    a.find('//*[@text="Đã chọn: (1)" or starts-with(@text,"Đã chọn: 1/")]')
    a.click('//*[@content-desc="Gửi lời mời"]/ancestor-or-self::*[@clickable="true"][1]',stable_bounds=True)
    # Copy link ở lobby do run vừa tạo, trước khi mở phòng; không lấy link phòng có sẵn.
    copy='(//*[@content-desc="Sao chép"])[1]'
    visible_link=a.find('//android.widget.TextView[starts-with(@text,"https://") or starts-with(@text,"http://")]',timeout=30).get_attribute('text')
    a.find(copy,timeout=30);a.click(copy,stable_bounds=True)
    a.driver.activate_app('io.appium.settings')
    try:link=a.driver.get_clipboard_text()
    finally:a.driver.activate_app(run.ctx.config['app_package'])
    assert urlparse(link).scheme in ('http','https') and link==visible_link,'Clipboard không khớp link ở lobby vừa tạo.'
    u.find('meeting_start',timeout=20)
    run.meeting_owned=True;run.ctx.owned_call_roles.update(('A','B'))
    run.ctx.call_cleanup.append(lambda:end_meeting(run))
    u.click('meeting_start')
    a.wait(lambda:a.call_service_active() or a.elements(a.named('call_end')),'Host chưa vào phòng Meet mới.',timeout=40)
    run.devices.adb('B','shell','am','start','-a','android.intent.action.VIEW','-d',link,'-p',run.ctx.config['app_package'])
    b.driver.page_source
    run.ui('B').click('meeting_join')
    b.wait(lambda:b.call_service_active(),'B chưa vào CallActivity/service sau khi bấm Tham gia từ lobby.',timeout=40)
    for page in (a,b):page.allow_test_permission();page.wait_connected()
    return a,b,link


def meeting(run):
    a,b,link=meeting_start(run);u=run.ui("A");run.record("meeting_created","joined")
    for role in ("A","B"):
        run.ui(role).click("group_members");run.page(role).find(run.page(role).text_locator(run.member_name("B" if role=="A" else "A")))
        run.page(role).driver.back()
    run.record("member_identity")
    for role in ("A","B"):
        run.ui(role).click("mic");run.ui(role).click("camera_toggle")
    run.probe("meeting_media");run.record("camera_mic_state")
    u.click("meeting_share");u.click("projection_start");run.ui("B").find("meeting_sharing");run.record("screen_shared")
    run.probe("meeting_web",join_link=link);run.record("web_participant")
    run.ui("B").click("meeting_leave");run.ended(b);run.record("left")
    u.click("meeting_end_all")
    if u.exists("confirm"):u.click("confirm")
    run.ended(a);run.record("ended")


def long_call(run):
    if run.p["meeting"]:
        try:a,b,_=meeting_start(run)
        except AssertionError as error:raise Blocked('Chưa thiết lập được phòng Meet A/B để bắt đầu đo 15 phút: '+str(error)) from error
    else:a,b=run.start_call(kind="video");run.answer(a,b)
    def camera_state(off=None):
        values=run.probe('camera_capture');off=run.p['camera_off'] if off is None else off
        return all((values[role+'_active_clients']==0 if off else values[role+'_active_clients']>=1) for role in ('A','B'))
    if run.p['meeting']:
        values=run.probe('camera_capture')
        for role in ('A','B'):
            if values[role+'_active_clients']==0:
                run.page(role).reveal_call_controls();run.ui(role).click('camera_toggle')
    # Camera phải active ở cả hai phía trước khi kiểm tra tắt; không PASS từ trạng thái chưa mở.
    a.wait(lambda:camera_state(False),'CameraService chưa xác nhận camera active trên cả A/B.',timeout=20)
    if run.p['camera_off']:
        for role in ('A','B'):
            run.page(role).reveal_call_controls()
            run.ui(role).click('camera_toggle')
        a.wait(camera_state,'CameraService chưa xác nhận camera tắt trên cả A/B.',timeout=20)
    run.record('camera_state_confirmed')
    for role in ("A","B"):
        run.devices.setting(role,"global","stay_on_while_plugged_in",0)
        run.devices.setting(role,"system","screen_off_timeout",30000)
    started=time.monotonic();duration=run.p["hold_seconds"]
    while time.monotonic()-started<duration:
        run.ctx.check()
        assert camera_state(),"CameraService đổi trạng thái camera trong cuộc gọi dài."
        for role in ("A","B"):
            state=run.devices.adb(role,"shell","dumpsys","power")
            assert re.search(r"mWakefulness=Awake|Wakefulness:\s*Awake",state),"Máy tự sleep trong cuộc gọi dài: "+role
            # Control video tự ẩn; không tap màn hình để giữ sáng hoặc coi nút ẩn là call ended.
            assert run.page(role).call_service_active(),"Service cuộc gọi kết thúc trước 15 phút: "+role
        run.devices.wait_seconds(min(20,duration-(time.monotonic()-started)),"Giữ cuộc gọi, không chạm màn hình để giữ sáng")
    for page in (a,b):page.wait_connected()
    run.record("connected_over_15_minutes","both_screens_awake")
    if run.p['meeting']:end_meeting(run)
    else:run.stop_call(a,b)


def run_rich(run):
    flow=run.p["flow"]
    if flow in ("mention","reply_mention"):mention(run,flow=="reply_mention")
    elif flow=="poll":poll(run)
    elif flow in ("media","whatsapp_camera"):media(run)
    elif flow=="voice":voice(run)
    elif flow=="location":location(run)
    elif flow=="group_lifecycle":group_lifecycle(run)
    elif flow=="profile":profile(run)
    elif flow=="pin_conversation":pin_order(run)
    elif flow=="meeting":meeting(run)
    elif flow=="long_call":long_call(run)
    elif flow=="tammi":
        a,b=run.pair(run.p["context"]);u=run.ui("A");run.type_owned("A",run.marker+" @")
        u.click("tammi_choice");text=a.composer().get_attribute("text")
        assert "Tammi" in text
        a.owned_draft=text;a.draft_journal(a.draft_journal()+[text])
        # send_keys trên TammiEditText thay toàn bộ text và làm mất span mention; nhập nối bằng key event.
        a.driver.execute_script("mobile: clickGesture",{"elementId":a.composer().id})
        a.driver.press_keycode(123,metastate=4096)
        run.devices.adb("A","shell","input","text"," 2+2")
        a.owned_draft=a.composer().get_attribute("text");a.draft_journal(a.draft_journal()+[a.owned_draft])
        assert "Tammi" in a.owned_draft and run.marker in a.owned_draft and "2+2" in a.owned_draft,"Mention hoặc câu hỏi bị mất khi nhập nối."
        run.record("tammi_mention")
        u.click("send")
        if a.ai_consent_visible():
            a.dismiss_ai_consent();a.clear_owned_draft()
            raise Blocked("App còn yêu cầu đồng ý xử lý qua ChatGPT/Gemini; cần người dùng tự xử lý consent, script không tự cấp.")
        run.release_draft_if_empty("A");u.find("tammi_reply",timeout=90);run.record("tammi_response")
    elif flow=="rich_text":
        a,b=run.pair();fixture=run.ctx.config["fixtures"]["rich_text"];path=Path(fixture["path"]);path=path if path.is_absolute() else ROOT/path
        a.send(run.marker+" "+path.read_text(),expected_display=run.marker);b.message_received(run.marker)
        for text in fixture["expected_text"]:b.find('//*[contains(@text,'+literal(text)+') or contains(@content-desc,'+literal(text)+')]')
        run.record("semantic_content");url=fixture["url"]
        b.click('//*[@text='+literal(urlparse(url).netloc)+']')
        assert urlparse(url).netloc in b.driver.page_source,"Link mở sai target."
        run.record("link_target")
    elif flow=="zero_data":
        run.probe("zero_data_sim",sim=run.ctx.config["lab"]["zero_data_sim"]);run.record("sim_no_quota")
        run.pair();run.send();run.record("chat_delivered")
        a,b=run.start_call();run.answer(a,b);run.record("call_connected");run.stop_call(a,b)
        a,b,_=meeting_start(run);run.probe("meeting_media");run.record("meeting_connected");run.stop_call(a,b)
        a.home();a.click(a.text_locator("Dịch vụ"));run.ui("A").click("miniapp_viettel");run.ui("A").find("miniapp_ready",timeout=60);run.record("miniapp_loaded")
    else:raise RuntimeError("Không có handler cho flow "+flow)
