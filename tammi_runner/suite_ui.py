"""Locator theo nhãn/resource của ứng dụng; override qua Thiết lập nếu build đổi semantics."""
import re
from xml.etree import ElementTree as ET

from .common import Blocked
from .pages import literal


def label(*labels):
    return '//*['+' or '.join(f'@text={literal(t)} or @content-desc={literal(t)}' for t in labels)+']'


DEFAULTS = {
    "attachment": '//android.widget.EditText/parent::*/parent::*/android.view.View[@clickable="true"][1]',
    "image":label("Ảnh"), "camera":label("Máy ảnh","Camera","Mở camera"),
    "file":label("Tài liệu","Tệp tin"),"location":label("Vị trí"),"poll":label("Bình chọn"),
    "send":label("Send","Gửi tin nhắn","Gửi"),"confirm":label("Đồng ý","Xác nhận"),
    "new_chat":label("Thêm liên hệ"),"new_group":label("Nhóm mới","Tạo nhóm mới"),
    "create_group":label("Tạo nhóm"),"group_name":'(//android.widget.EditText)[1][//android.widget.TextView[@text="Tạo nhóm mới"]]',
    "group_member_search":'(//android.widget.EditText)[last()]',
    "search_input":'//android.widget.EditText',"member_result":'//*[@class!="android.widget.EditText" and (@text={member} or contains(@content-desc,{member}))]',
    "profile":'//*[@text={peer_name}]/ancestor::*[@clickable="true"][1]',
    "profile_search":label("Tìm kiếm tin nhắn","Tìm tin nhắn"),"profile_media":label("Ảnh, video, liên kết","Ảnh, video, tệp","Ảnh, video","Ảnh, liên kết và tài liệu"),
    "conversation_pin":label("Ghim trò chuyện","Ghim"),"conversation_unpin":label("Bỏ ghim trò chuyện","Bỏ ghim"),
    "mute":label("Tắt thông báo"),"unmute":label("Bật thông báo"),
    "reply":label("Trả lời"),"forward":label("Chuyển tiếp"),"edit":label("Chỉnh sửa","Sửa tin nhắn","Chỉnh sửa tin nhắn"),
    "delete":label("Xoá","Xóa","Thu hồi"),"delete_everyone":label("Xóa với mọi người","Xoá với mọi người","Thu hồi với mọi người"),
    "revoke":label("Thu hồi"),
    "deleted":label("Tin nhắn đã được thu hồi","Tin nhắn đã bị xóa","Tin nhắn đã được xóa"),
    "menu_more":label("Thêm...","Thêm"),
    "pin":label("Ghim","Ghim tin nhắn"),"unpin":label("Bỏ ghim","Bỏ ghim tin nhắn"),
    "pin_indicator":'//*[contains(@text,"Tin nhắn đã ghim") or contains(@content-desc,"Tin nhắn đã ghim") or @text="Đã ghim" or @content-desc="Tin Nhắn Đã Ghim"]',
    "edit_confirm":label("Xác nhận chỉnh sửa tin nhắn"),
    "reaction":'(//*[@content-desc="Thêm biểu tượng cảm xúc"]/ancestor::*[count(.//*[@clickable="true"])=7][1]//*[@clickable="true"])[1]',
    "reaction_remove":label("Nhấn để gỡ","Tap to remove"),
    "reaction_sheet":label("Chi tiết"),
    "reaction_count_one":'//*[@text="Chi tiết"]/ancestor::*[.//*[@text="Tất cả"] and not(.//android.widget.EditText)][1]//*[@text="Tất cả"]/parent::*[.//*[@text="1"]]',
    "reaction_details":'//*[contains(@content-desc,{marker})]/parent::*/android.view.View[@clickable="true" and not(*)]',
    "reactor":'//*[@text={member} or contains(@content-desc,{member})]',
    "typing":'//*[contains(@text,"đang nhập") or contains(@content-desc,"đang nhập") or contains(@text,"đang soạn")]',
    "offline_error":'//*[contains(@text,"Không có kết nối") or contains(@text,"Lỗi gửi tin nhắn") or contains(@content-desc,"Gửi lại")]',
    "retry":label("Gửi lại","Thử lại"),
    "unread_banner":'//*[contains(@text,"tin nhắn chưa đọc") or contains(@content-desc,"tin nhắn chưa đọc")]',
    "inapp_message_banner":'//*[contains(@text,{marker}) or contains(@content-desc,{marker})][not(@class="android.widget.EditText")]',
    "voice_record":label("Voice Record"),"voice_send":label("Gửi tin nhắn thoại"),
    "voice_bubble":'//*[contains(@content-desc,"Tin nhắn thoại") or contains(@content-desc,"Tin nhắn âm thanh")]',
    "voice_play":label("Phát","Phát tin nhắn thoại"),
    "poll_question":'(//android.widget.EditText)[1]',
    "poll_option_1":'(//android.widget.EditText)[2]',"poll_option_2":'(//android.widget.EditText)[3]',
    "poll_create":'//*[@text="Tạo bình chọn"]/ancestor-or-self::*[@clickable="true" and @enabled="true"][1]',"poll_vote":label("Bình chọn"),
    "poll_result":'//*[contains(@text,"1 người bình chọn") or contains(@text,"100%")]',
    "mention_choice":'//*[@text={member} or @content-desc={member}]',
    "tammi_choice":label("Tammi"),"tammi_reply":'//*[contains(@content-desc,"Tammi") and not(contains(@content-desc,{marker}))]',
    "leave_group":label("Rời nhóm"),"group_qr":label("Mã QR nhóm","Mã QR"),
    "invite_link":label("Link tham gia nhóm","Liên kết tham gia nhóm"),"copy_link":label("Sao chép liên kết","Sao chép"),
    "join_group":label("Tham gia nhóm","Tham gia"),"group_members":label("Thành viên","Thành viên nhóm"),
    "member_count":'//*[contains(@text,"thành viên") or contains(@content-desc,"thành viên")]',
    "qr_scan":label("Scan mã QR","Quét mã QR"),"qr_gallery":label("Chọn ảnh QR","Ảnh","Thư viện"),
    "qr_save":label("Lưu mã QR","Lưu ảnh","Lưu"),
    "camera_shutter":label("Chụp ảnh","Shutter","Capture"),"camera_video":label("Video"),
    "camera_record":label("Quay video","Record"),"camera_done":label("Xong","Dùng ảnh","Sử dụng video"),
    "picker_search":label("Tìm kiếm","Search"),"picker_search_input":'//android.widget.EditText',
    "picker_item":'//*[@text={filename} or @content-desc={filename}]',"picker_done":label("Xong","Chọn","Select"),
    "quality":label("Chất lượng","HD","Tiêu chuẩn","Ảnh gốc"),"standard":label("Tiêu chuẩn"),"hd":label("HD"),"original":label("Ảnh gốc","Gốc"),
    "media_bubble":'//*[contains(@content-desc,{filename}) or @text={filename}]',
    "media_open":label("Toàn màn hình","Phát","Mở"),
    "media_save":label("Tải xuống","Lưu ảnh","Lưu vào thiết bị"),
    "media_limit_error":'//*[contains(@text,"vượt quá") or contains(@text,"quá lớn") or contains(@text,"dung lượng tối đa")]',
    "media_metadata":'//*[contains(@text,{filename}) or contains(@content-desc,{filename})]',
    "current_location":label("Gửi vị trí hiện tại","Chia sẻ vị trí hiện tại","Vị trí hiện tại"),
    "live_location":label("Chia sẻ hành trình","Chia sẻ vị trí trực tiếp"),
    "location_send":label("Chia sẻ","Gửi vị trí"),"location_bubble":label("Tin nhắn vị trí","Chia sẻ hành trình"),
    "live_stop":label("Dừng chia sẻ","Dừng"),"location_coordinates":'//*[contains(@text,{latitude}) and contains(@text,{longitude})]',
    "group_call_menu":'//*[@text={peer_name}]/ancestor::*[@clickable="true"][1]/following-sibling::*[last()]//*[@clickable="true"]',
    "group_audio":label("Gọi điện","Gọi thoại","Gọi nhóm thoại"),"group_video":label("Gọi video","Gọi nhóm video"),
    "outgoing_ringing":label("Đang đổ chuông"),"connecting":'//*[contains(@text,"Đang nối máy") or contains(@text,"Đang kết nối") or @text="Đang gọi"]',
    "rejected_reason":'//*[contains(@text,"từ chối") or contains(@text,"Từ chối")]',
    "busy_reason":'//*[contains(@text,"đang bận") or contains(@text,"Đang bận")]',
    "unreachable":'//*[contains(@text,"Không liên lạc được") or contains(@text,"không liên lạc được")]',
    "timeout_result":'//*[contains(@text,"không liên lạc được") or contains(@content-desc,"không liên lạc được") or contains(@text,"Người nhận không bắt máy") or contains(@content-desc,"Người nhận không bắt máy")]',
    "missed_call":'//*[contains(@text,"Cuộc gọi thoại nhỡ") or contains(@text,"Cuộc gọi nhỡ") or contains(@content-desc,"Cuộc gọi nhỡ")]',
    "call_bubble":label("Gọi lại"),"network_warning":'//*[contains(@text,"không ổn định") or contains(@text,"Đang kết nối lại")]',
    "mic":label("Bật/Tắt Mic"),"speaker":label("Loa ngoài/Loa trong"),"camera_toggle":label("Bật/Tắt Camera"),
    "mic_off":label("Đã tắt micro"),"pip":label("Toàn màn hình"),
    "end_accept":label("Kết thúc và Trả lời","Kết thúc và chấp nhận"),
    "meeting_new":label("Tạo cuộc họp","Tạo Meet","Họp ngay"),"meeting_start":label("Bắt đầu cuộc họp","Bắt đầu","Tham gia"),
    "meeting_join":label("Tham gia","Tham gia cuộc họp"),"meeting_share":label("Chia sẻ màn hình","Chia sẻ\nmàn hình"),
    "projection_start":label("Bắt đầu ngay","Start now","Bắt đầu"),"meeting_sharing":label("Đang trình chiếu","Bạn đang chia sẻ màn hình với mọi người"),
    "meeting_leave":label("Rời cuộc họp","Rời"),"meeting_end_all":label("Rời và kết thúc cuộc họp","Kết thúc cho tất cả","Kết thúc cuộc họp"),
    "meeting_link":label("Sao chép liên kết","Sao chép link"),"meeting_camera_off":label("Đã tắt camera"),
    "miniapp_viettel":label("Viettel++"),"miniapp_ready":label("Viettel++","Ưu đãi"),
}


def camera_capture_locator(source):
    root=ET.fromstring(source)
    labels={node.get("content-desc") for node in root.iter()}
    if not {"Đóng","Đổi camera"}.issubset(labels):raise Blocked("Chưa xác minh màn camera để tìm nút chụp không có nhãn.")
    candidates=[]
    for node in root.iter():
        if node.get("clickable")!="true":continue
        if any(child.get("text") or child.get("content-desc") for child in node.iter()):continue
        box=list(map(int,re.findall(r"\d+",node.get("bounds",""))))
        if len(box)!=4:continue
        width,height=box[2]-box[0],box[3]-box[1]
        if width>0 and abs(width-height)<=max(3,width*.05):candidates.append(node.get("bounds"))
    if len(candidates)!=1:raise Blocked("Không có duy nhất nút chụp camera theo cấu trúc native; cần locator camera_shutter.")
    return '//*[@clickable="true" and @bounds='+literal(candidates[0])+']'


class UI:
    def __init__(self, page, variables=None):
        self.page=page;self.variables=variables or {}

    def xpath(self,key,**values):
        if key in ("camera_shutter","camera_record") and not self.page.config.get("locators",{}).get(key):
            return camera_capture_locator(self.page.driver.page_source)
        locator=self.page.config.get("locators",{}).get(key) or DEFAULTS.get(key)
        if not locator:raise Blocked(f"Thiếu locator {key}; cần hiệu chỉnh semantics cho build hiện tại.")
        variables={"peer_name":self.page.peer_name or "",**self.variables,**values}
        for key,value in variables.items():locator=locator.replace("{"+key+"}",literal(str(value)))
        if re.search(r"\{\w+\}",locator):raise Blocked("Locator còn tham số chưa có: "+locator)
        return locator

    def click(self,key,**values):self.page.click(self.xpath(key,**values),stable_bounds=(key in ("reaction_details","group_call_menu","send","poll_create","meeting_start","meeting_join")),call_controls=key in ("camera_toggle","mic"))
    def find(self,key,timeout=25,**values):return self.page.find(self.xpath(key,**values),timeout)
    def exists(self,key,**values):return self.page.elements(self.xpath(key,**values))
    def absent(self,key,timeout=25,**values):self.page.wait(lambda:not self.exists(key,**values),"Control vẫn còn: "+key,timeout)
    def fill(self,key,text):
        element=self.find(key)
        if element.get_attribute("text"):
            self.page.driver.execute_script("mobile: clickGesture",{"elementId":element.id})
            self.page.wait(self.page.driver.is_keyboard_shown,"Ô nhập chưa nhận focus để thay nội dung.",timeout=10)
            self.page.driver.press_keycode(29,metastate=4096);self.page.driver.press_keycode(67)
            self.page.wait(lambda:not self.find(key).get_attribute("text") or self.find(key).get_attribute("text")==self.find(key).get_attribute("hint"),"Nội dung cũ chưa xóa bằng bàn phím.")
        self.find(key).send_keys(text)
        self.page.wait(lambda: self.find(key).get_attribute("text")==text,"Ô nhập chưa giữ đúng nội dung.")
    def message(self,marker):
        value=literal(marker)
        return self.page.find(f'//*[@class!="android.widget.EditText" and (contains(@text,{value}) or contains(@content-desc,{value}))]')
    def menu(self,marker):
        if not marker.startswith("APPIUM-"):raise Blocked("Chỉ mở menu thay đổi tin nhắn có marker do run tạo.")
        previous=[None]
        def stable():
            self.page.driver.page_source
            element=self.message(marker);bounds=element.get_attribute("bounds")
            if bounds and bounds==previous[0]:return element
            previous[0]=bounds
            return False
        element=self.page.wait(stable,"Bubble test còn chuyển vị trí trước khi mở menu.")
        self.page.driver.execute_script("mobile: longClickGesture",{"elementId":element.id,"duration":650})
        self.find("reply",timeout=8)
    def profile(self):
        self.click("profile")
        self.find("profile_search")
    def choose_mention(self,member):
        # Gợi ý trợ lý AI đứng trước thành viên; chỉ cuộn trong popup mention.
        panel=self.page.find('//*[@scrollable="true" and .//*[@text="Nhắc đến tất cả mọi người"]]')
        scope='//*[@scrollable="true" and @bounds='+literal(panel.get_attribute('bounds'))+']'
        wanted=scope+'//*[@text='+literal(member)+' or @content-desc='+literal(member)+']'
        for attempt in range(9):
            self.page.check_cancel()
            # Query snapshot mới theo bounds popup; element context Compose có thể giữ cây con cũ sau scroll.
            self.page.driver.page_source
            matches=[e for e in self.page.elements(wanted) if e.is_displayed()]
            if len(matches)==1:
                self.page.driver.execute_script('mobile: clickGesture',{'elementId':matches[0].id})
                return
            if len(matches)>1:raise Blocked('Tên mention trùng trong popup; cần định danh thành viên rõ hơn.')
            if attempt==8:break
            # Compose có thể trả canScrollMore=false trong khi danh sách vẫn vừa chuyển vị trí.
            self.page.driver.execute_script('mobile: scrollGesture',{'elementId':panel.id,'direction':'down','percent':.65})
        raise Blocked('Không thấy thành viên đã xác minh trong popup mention: '+member)
    def notification(self,marker):
        if self.page.driver.current_package not in ("com.android.systemui","com.oplus.systemui.plugins"):
            self.page.driver.open_notifications()
        value=literal(marker)
        return self.page.find(f'//*[contains(@text,{value}) or contains(@content-desc,{value})]',timeout=40)
    def open_notification(self,marker):
        self.notification(marker)
        self.page.click(f'//*[contains(@text,{literal(marker)}) or contains(@content-desc,{literal(marker)})]')
    def open_named(self,name):
        self.page.home()
        row='//*[starts-with(@content-desc,'+literal(name+",")+')]'
        if len(self.page.elements(row))==1:
            self.page.driver.page_source
            self.page.click(row,stable_bounds=True);self.page.composer();self.page.peer_name=name;self.page.conversation_name=name;return
        self.page.click(self.page.text_locator("Tìm kiếm"))
        self.fill("search_input",name);self.page.keyboard_back()
        self.page.click(f'//*[@class!="android.widget.EditText" and @text={literal(name)}]')
        self.page.wait(lambda: not self.page.elements('//*[@content-desc="Scan mã QR"]') and self.page.elements('//android.widget.EditText'),"Chưa mở hội thoại tên được cấu hình.")
        self.page.peer_name=name
        self.page.conversation_name=name
    def labels(self):
        return [n.get("text") or n.get("content-desc") for n in ET.fromstring(self.page.driver.page_source).iter() if n.get("text") or n.get("content-desc")]
