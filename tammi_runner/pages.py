"""Các thao tác Appium xác định sẵn, không sử dụng AI khi thực thi."""
from __future__ import annotations

import re
import time
import hashlib
import json
import subprocess
from xml.etree import ElementTree as ET

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

from .common import Blocked, ROOT, save_private_json, find_adb


def literal(value):
    if "'" not in value:
        return "'" + value + "'"
    if '"' not in value:
        return '"' + value + '"'
    return "concat(" + ', "\'", '.join("'" + s + "'" for s in value.split("'")) + ")"


def phone_nodes(source, phone):
    expected = {phone, "84" + phone[1:]}
    result = []
    for node in ET.fromstring(source).iter():
        if node.get("class", "").endswith("EditText"):
            continue
        for key in ("text", "content-desc"):
            value = node.get(key, "")
            digits = re.sub(r"\D", "", value)
            if digits in expected:
                result.append((key, value))
    return result


def avatar_locator(source):
    nodes = list(ET.fromstring(source).iter())
    parents = {child: node for node in nodes for child in node}
    search = next((n for n in nodes if n.get("text") == "Tìm kiếm tính năng"), None)
    if search is None:
        raise Blocked("Không tìm thấy thanh tìm kiếm để định vị avatar hồ sơ.")
    while search.get("clickable") != "true" and search in parents:
        search = parents[search]
    def rect(node):
        values = re.findall(r"\d+", node.get("bounds", ""))
        return tuple(map(int, values)) if len(values) == 4 else None
    box = rect(search)
    if not box:
        raise Blocked("Không đọc được vị trí thanh tìm kiếm.")
    candidates = []
    for node in nodes:
        area = rect(node)
        if node.get("clickable") != "true" or not area:
            continue
        overlap = min(area[3], box[3]) - max(area[1], box[1])
        if area[2] <= box[0] and overlap > (box[3] - box[1]) / 2:
            candidates.append((area[2], node.get("bounds")))
    if not candidates:
        raise Blocked("Avatar chưa có accessibility ID và không xác định được control cạnh thanh tìm kiếm. Cấu hình profile_open trong Thiết lập.")
    bounds = max(candidates)[1]
    return f'//*[@clickable="true" and @bounds={literal(bounds)}]'


def unique_contact_result(source, phone):
    root = ET.fromstring(source)
    nodes = list(root.iter())
    inputs = [re.sub(r"\D", "", n.get("text", "")) for n in nodes if n.get("class", "").endswith("EditText")]
    if phone not in inputs or not any(n.get("text") == "Liên hệ (1)" for n in nodes):
        return None
    candidates = []
    for node in nodes:
        descendants = list(node.iter())
        descriptions = {n.get("content-desc") for n in descendants}
        if node.get("clickable") != "true" or not {"Gọi", "Gọi video"}.issubset(descriptions):
            continue
        labels = [n.get("text") for n in descendants if n.get("class") == "android.widget.TextView" and n.get("text")]
        if labels:
            candidates.append((node, max(labels, key=len)))
    if len(candidates) != 1:
        return None
    node, name = candidates[0]
    return f'//*[@clickable="true" and @bounds={literal(node.get("bounds"))}]', name


class AppPage:
    def __init__(self, driver, config, role, check_cancel, emit=None):
        self.driver, self.config, self.role = driver, config, role
        self.check_cancel = check_cancel
        self.account_verified = False
        self.peer_name = None
        self.peer_role = None
        self.conversation_name = None
        self.owned_draft = None
        self.emit = emit or (lambda *_args, **_kwargs: None)

    def wake_for_interaction(self):
        # Chỉ dùng lúc chuẩn bị thao tác; không gọi trong vòng quan sát sleep/awake.
        if not self.config.get('lab',{}).get('unsecured_devices'):return
        if self.driver.is_locked():
            self.driver.unlock()
            self.wait(lambda:not self.driver.is_locked(),'Máy test chưa mở được khóa; không nhập PIN hoặc bỏ qua bảo mật.',timeout=8)

    def wait(self, condition, message, timeout=25):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.check_cancel()
            try:
                result = condition()
                if result:
                    return result
            except (NoSuchElementException, StaleElementReferenceException):
                pass
            time.sleep(0.25)
        raise AssertionError(message)

    def elements(self, xpath):
        return self.driver.find_elements(AppiumBy.XPATH, xpath)

    def find(self, xpath, timeout=25):
        return self.wait(lambda: next((e for e in self.elements(xpath) if e.is_displayed()), None),
                         "Không tìm thấy control theo locator: " + xpath, timeout)

    def click(self, xpath, stable_bounds=False, call_controls=False, dismiss_setup=False):
        previous = None
        def perform():
            nonlocal previous
            # Tap chính node mang semantics; bọc ancestor trên Compose có thể trả về vùng toàn màn hình.
            controls = self.elements(xpath)
            target = next((element for element in controls if element.is_displayed()), None)
            if not target:
                if dismiss_setup:self.dismiss_optional_setup()
                if call_controls:self.reveal_call_controls()
                return False
            # Chỉ lấy lại locator khi UIA báo stale trước khi thực hiện gesture; lỗi khác được trả ra.
            if stable_bounds or call_controls:
                rect = target.rect
                if rect != previous:
                    previous = rect
                    return False
                if call_controls:
                    subprocess.run([find_adb(self.config),"-s",self.config["devices"][self.role]["udid"],
                                    "shell","input","tap",str(int(rect["x"]+rect["width"]/2)),
                                    str(int(rect["y"]+rect["height"]/2))],capture_output=True,text=True,check=True,timeout=15)
                    return True
                # Row draft đổi vị trí sau khi về danh sách; dùng bounds ổn định vừa đọc từ UIA.
                self.driver.execute_script("mobile: clickGesture", {"x": int(rect["x"] + rect["width"] / 2),
                                                                   "y": int(rect["y"] + rect["height"] / 2)})
            else:
                self.driver.execute_script("mobile: clickGesture", {"elementId": target.id})
            return True
        self.wait(perform, "Không bấm được control theo locator: " + xpath)

    def text_locator(self, text):
        value = literal(text)
        return f"//*[@text={value} or @content-desc={value}]"

    def named(self, key, default=None):
        locator = self.config.get("locators", {}).get(key) or default
        if not locator:
            raise Blocked(f"Chưa cấu hình locator {key}; không dùng tọa độ phỏng đoán.")
        if "{peer_name}" in locator:
            if not self.peer_name:
                raise Blocked("Chưa xác minh tên liên hệ từ kết quả tìm số điện thoại để định vị header gọi.")
            locator = locator.replace("{peer_name}", literal(self.peer_name))
        return locator

    def keyboard_back(self):
        if self.driver.is_keyboard_shown():
            self.driver.press_keycode(4)
            self.wait(lambda: not self.driver.is_keyboard_shown(), "Bàn phím chưa đóng sau một lần Back.", timeout=8)

    def allow_test_permission(self):
        source = self.driver.page_source
        if "permissioncontroller" not in source or "Tammi" not in source:
            return False
        allow = self.elements('//*[@resource-id="com.android.permissioncontroller:id/permission_allow_button"'
                              ' or @resource-id="com.android.permissioncontroller:id/permission_allow_foreground_only_button"'
                              ' or @resource-id="com.android.permissioncontroller:id/permission_allow_all_button"]')
        if not allow:
            return False
        self.driver.execute_script("mobile: clickGesture", {"elementId": allow[0].id})
        return True

    def dismiss_optional_setup(self):
        known = ('Tự động đồng bộ danh bạ', 'Liên kết Viettel Money',
                 'Cho phép nhận cuộc gọi viễn thông qua app Viettel Tammi')
        if any(self.elements(self.text_locator(title)) for title in known) and self.elements('//*[@text="Để sau"]'):
            self.click('//*[@text="Để sau"]')
            return True
        return False

    def prepare_auth_route(self):
        for _ in range(8):
            self.check_cancel()
            if self.elements('//*[@text="Tài khoản đã vượt quá số lượng thiết bị cho phép"]'):
                raise Blocked(f"Tài khoản {self.role} vượt giới hạn thiết bị. Chờ người dùng đăng xuất thiết bị cũ; script không tự hủy phiên khác.")
            if self.allow_test_permission() or self.dismiss_optional_setup():
                continue
            if (self.driver.current_activity.endswith(".MeetingPrepareActivity")
                    and self.elements(self.text_locator("Tham gia"))):
                # Lobby còn lại sau lượt chưa join; không có service call (đã kiểm tra đầu case).
                self.home()
                continue
            if (self.elements('//*[@text="Google Map"]')
                    and self.elements('//*[@text="Vị trí được chia sẻ" or @text="Chia sẻ vị trí" or @text="Vị trí hiện tại"]')):
                # Map còn mở từ diagnostic/lượt dừng; về home trước khi xác minh tài khoản.
                self.home()
                continue
            if self.elements('//*[@content-desc="Ảnh có thể phóng to"]'):
                # Job trước có thể dừng ở Gallery; đóng màn media trước khi mở hồ sơ xác minh.
                self.driver.back()
                continue
            if (self.elements('//*[@text="Tự động lưu ảnh/video đã chụp"]')
                    and self.elements('//*[@content-desc="Quay lại"]')):
                # Lượt camera trước đã khôi phục cài đặt và dừng tại màn Tin nhắn.
                self.click('//*[@content-desc="Quay lại"]')
                continue
            if (self.elements('//*[@content-desc="Tìm tin nhắn" or @text="Tìm tin nhắn"]')
                    and self.elements('//*[@content-desc="Ảnh, liên kết và tài liệu" or @text="Ảnh, liên kết và tài liệu"]')):
                # Hồ sơ hội thoại còn mở từ lượt trước; về màn chính trước khi xác minh tài khoản.
                self.home()
                continue
            if self.elements('//*[@text="Nhập mã OTP"]'):
                self.driver.back()
                continue
            if (self.elements('//android.widget.EditText') or self.elements('//*[@content-desc="Tin nhắn"]')
                    or self.elements('//*[@text="Hồ sơ cá nhân" or @text="Đăng xuất"]')):
                return
            next_step = '//*[@text="Đăng nhập ngay!" or @text="Bỏ qua" or @text="Bắt đầu" or @text="Tiếp tục"]'
            if self.elements(next_step):
                self.click(next_step)
                continue
            self.wait(lambda: self.elements('//android.widget.EditText')
                      or self.elements('//*[@content-desc="Tin nhắn"]') or self.elements(next_step),
                      "Chưa tới màn đăng nhập hoặc màn chính.", timeout=15)

    def home(self):
        self.wake_for_interaction()
        package = self.config["app_package"]
        if self.driver.current_package != package:
            self.driver.activate_app(package)
        if self.elements('//*[@content-desc="Cài đặt"]'):
            return
        self.keyboard_back()
        for _ in range(8):
            self.check_cancel()
            if self.driver.current_package != package:
                self.driver.activate_app(package)
                self.find('//*[@content-desc="Tin nhắn"]')
            if self.elements('//*[@content-desc="Cài đặt"]'):
                return
            bottom = self.elements('//*[@content-desc="Tin nhắn"]')
            if bottom:
                self.driver.execute_script("mobile: clickGesture", {"elementId": bottom[-1].id})
            else:
                self.driver.back()
        self.emit("step", f"{self.role}: khởi động lại app để về màn đầu, giữ nguyên dữ liệu")
        self.driver.terminate_app(package)
        self.driver.activate_app(package)
        self.find('//*[@content-desc="Cài đặt"]')

    def logout_for_test_account(self):
        self.emit("step", f"{self.role}: đăng xuất staging để dùng đúng tài khoản test đã cấu hình")
        logout = '//*[@text="Đăng xuất" or @content-desc="Đăng xuất"]/ancestor-or-self::*[@clickable="true"][1]'
        for _ in range(10):
            self.check_cancel()
            controls = self.elements(logout)
            if controls:
                self.driver.execute_script("mobile: clickGesture", {"elementId": controls[-1].id})
                break
            scrollers = self.elements('//*[@scrollable="true"]')
            if not scrollers:
                raise Blocked("Không tìm được vùng cuộn để mở nút Đăng xuất staging.")
            self.driver.execute_script("mobile: scrollGesture", {"elementId": scrollers[0].id,
                                                                 "direction": "down", "percent": 0.75})
        else:
            raise Blocked("Không tìm thấy nút Đăng xuất trên hồ sơ.")
        self.wait(lambda: self.elements('//*[contains(@text,"chắc chắn muốn đăng xuất")]')
                  or self.elements('//*[@text="Thiết lập mật khẩu"]'), "Không mở được xác nhận đăng xuất.")
        if self.elements('//*[@text="Thiết lập mật khẩu"]'):
            defer = self.find('//*[@text="Để sau"]/ancestor-or-self::*[@clickable="true"][1]')
            self.driver.execute_script("mobile: clickGesture", {"elementId": defer.id})
        else:
            confirm = self.find('//*[@text="Đồng ý" or @content-desc="Đồng ý"]/ancestor-or-self::*[@clickable="true"][1]')
            self.driver.execute_script("mobile: clickGesture", {"elementId": confirm.id})
        self.find('//*[starts-with(@text,"Đăng nhập")]', timeout=40)
        self.login_and_verify(allow_switch=False)

    def login_and_verify(self, allow_switch=False):
        self.wake_for_interaction()
        phone = self.config["devices"][self.role].get("account", {}).get("phone")
        otp = self.config["devices"][self.role].get("account", {}).get("otp")
        if not phone:
            raise Blocked(f"Chưa cấu hình tài khoản cho thiết bị {self.role}.")
        if self.driver.current_package != self.config["app_package"]:
            self.driver.activate_app(self.config["app_package"])
        if self.account_verified and not self.elements('//*[starts-with(@text,"Đăng nhập") and not(@text="Đăng nhập ngay!")]'):
            self.home()
            return
        self.prepare_auth_route()
        login_button = '//*[@text="Đăng nhập với OTP" or @text="Đăng nhập"]'
        if self.elements(login_button) and self.elements('//android.widget.EditText'):
            if not otp:raise Blocked(f'Chưa có phiên đăng nhập trên {self.role}; cần OTP của tài khoản này trước khi gửi yêu cầu đăng nhập.')
            field = self.find('//android.widget.EditText')
            field.clear()
            field.send_keys(phone)
            entered = re.sub(r"\D", "", field.get_attribute("text") or "")
            if not entered.endswith(phone[1:]):
                raise Blocked("Ô số điện thoại chưa nhận đúng tài khoản test; không yêu cầu OTP cho số khác.")
            self.keyboard_back()
            self.click(login_button)
            self.find('//*[@text="Nhập mã OTP"]', timeout=40)
            fields = self.elements('//*[@content-desc="OTP Text Field"]') or self.elements('//android.widget.EditText')
            if len(fields) == 1:
                fields[0].send_keys(otp)
            elif len(fields) == len(otp):
                for element, digit in zip(fields, otp):
                    element.send_keys(digit)
            else:
                self.wait(self.driver.is_keyboard_shown, "Ô OTP ẩn chưa nhận focus bàn phím.", timeout=10)
                # BasicTextField OTP của app có alpha(0), chỉ nhận phím khi màn OTP đã được xác nhận.
                for digit in otp:
                    self.driver.press_keycode(7 + int(digit))
            def logged_in():
                self.allow_test_permission()
                self.dismiss_optional_setup()
                if self.elements('//*[@text="Tài khoản đã vượt quá số lượng thiết bị cho phép"]'):
                    raise Blocked(f"Tài khoản {self.role} đã vượt số thiết bị cho phép; cần người dùng đăng xuất thiết bị cũ hoặc đổi tài khoản. Script không tự chọn thiết bị để đăng xuất.")
                return self.elements('//*[@content-desc="Dịch vụ"]')
            self.wait(logged_in, "Chưa vào được màn chính sau khi nhập OTP.", timeout=45)
        if self.account_verified:
            self.home()
            return
        self.home()
        self.emit("step", f"{self.role}: mở hồ sơ để xác minh tài khoản")
        self.click('//*[@content-desc="Dịch vụ"]/ancestor::*[@clickable="true"][1]',
                   stable_bounds=True,dismiss_setup=True)
        self.find('//*[@text="Tìm kiếm tính năng"]')
        avatar = self.config.get("locators", {}).get("profile_open")
        if not avatar:
            previous=[None]
            def stable_avatar():
                current=avatar_locator(self.driver.page_source)
                if current==previous[0]:return current
                previous[0]=current;return False
            avatar=self.wait(stable_avatar,"Avatar hồ sơ chưa ổn định sau chuyển màn.")
        self.click(avatar, stable_bounds=True)
        self.wait(lambda: phone_nodes(self.driver.page_source, phone)
                  or self.elements('//*[@text="Hồ sơ cá nhân" or @text="Chỉnh sửa thông tin"]'), "Không đọc được hồ sơ tài khoản.")
        source = self.driver.page_source
        if not phone_nodes(source, phone):
            if self.elements('//*[@text="Hồ sơ cá nhân"]'):
                self.click('//*[@text="Hồ sơ cá nhân"]')
            def identity_ready():
                source = self.driver.page_source
                return next((role for role, data in self.config["devices"].items()
                             if data.get("account", {}).get("phone")
                             and phone_nodes(source, data["account"]["phone"])), None)
            try:
                detected_role = self.wait(identity_ready, "Hồ sơ chưa tải được số tài khoản test.", timeout=15)
            except AssertionError as error:
                if allow_switch:
                    return self.logout_for_test_account()
                raise Blocked("Chưa đọc được số tài khoản test trên hồ sơ. Kiểm tra tài khoản đang đăng nhập hoặc locator profile_open.") from error
            if detected_role != self.role:
                if allow_switch:
                    return self.logout_for_test_account()
                raise Blocked(f"Thiết bị {self.role} đang đăng nhập tài khoản cấu hình {detected_role}. Đổi số tài khoản A/B trong Thiết lập hoặc đăng nhập lại đúng vai.")
            source = self.driver.page_source
        if not phone_nodes(source, phone):
            raise Blocked(f"Thiết bị {self.role} chưa xác minh đúng tài khoản staging. Hãy đăng nhập đúng tài khoản trong Thiết lập.")
        self.account_verified = True
        self.home()

    def open_peer(self, peer_role=None):
        self.login_and_verify()
        peer_role = peer_role or ("B" if self.role == "A" else "A")
        # Row được hiệu chỉnh bằng marker gửi từ đúng tài khoản, ràng buộc cả hai số.
        known=self.config.get('lab',{}).get('verified_peer_rows',{}).get(self.role,{}).get(peer_role,{})
        own_phone=self.config['devices'][self.role].get('account',{}).get('phone')
        peer_phone=self.config['devices'][peer_role].get('account',{}).get('phone')
        if (known.get('name') and known.get('viewer_phone')==own_phone and known.get('peer_phone')==peer_phone):
            candidate='//*[starts-with(@content-desc,'+literal(known['name']+',')+')]'
            if len(self.elements(candidate))==1:
                self.peer_role=peer_role;self.peer_name=known['name'];self.conversation_name=None
        if self.peer_role==peer_role and self.peer_name and not self.conversation_name:
            row='//*[starts-with(@content-desc,'+literal(self.peer_name+",")+')]'
            if len(self.elements(row))==1:
                # Làm mới snapshot sau chuyển màn trước khi dùng bounds của row Compose.
                self.driver.page_source
                self.click(row, stable_bounds=True)
                self.composer()
                self.conversation_name=None
                return
        self.peer_role = peer_role
        self.peer_name = None
        self.conversation_name = None
        peer = self.config["devices"][peer_role]["account"]["phone"]
        self.emit("step", f"{self.role}: tìm hội thoại của tài khoản {peer_role}")
        self.driver.page_source
        search = self.named("conversation_search", '//*[@text="Tìm kiếm"]/ancestor::*[@clickable="true"][1]')
        self.click(search, stable_bounds=True)
        search_input = self.named("search_input", '//android.widget.EditText')
        try:
            field = self.find(search_input, timeout=5)
        except AssertionError:
            # Một lần chạm qua ADB khi UI vẫn ở danh sách và gesture Appium chưa mở search.
            entry = next((element for element in self.elements(search) if element.is_displayed()), None)
            if entry is not None and self.elements('//*[@content-desc="Cài đặt"]'):
                rect = entry.rect
                x, y = (str(int(rect[axis] + rect[size] / 2)) for axis, size in (("x","width"),("y","height")))
                subprocess.run([find_adb(self.config), "-s", self.config["devices"][self.role]["udid"],
                                "shell", "input", "tap", x, y], capture_output=True, check=True, timeout=15)
            field = self.find(search_input)
        field.clear()
        field.send_keys(peer)
        entered = re.sub(r"\D", "", field.get_attribute("text") or "")
        if entered != peer:
            raise Blocked("Ô tìm kiếm chưa nhận đúng toàn bộ số tài khoản đối diện.")
        # Chọn row kết quả khi bàn phím còn mở; Back có thể đóng search trên ColorOS lúc IME chuyển trạng thái.
        result = self.config.get("devices", {}).get(peer_role, {}).get("search_result_xpath")
        name = None
        if not result:
            def resolve():
                source = self.driver.page_source
                matches = phone_nodes(source, peer)
                if matches:
                    key, value = matches[0]
                    return (f'//*[@class!="android.widget.EditText" and @{key}={literal(value)}]'
                            '/ancestor-or-self::*[@clickable="true"][1]', None)
                return unique_contact_result(source, peer)
            result, name = self.wait(resolve, "Không có kết quả duy nhất cho đầy đủ số tài khoản đối diện.")
        self.click(result)
        self.wait(lambda: not self.elements('//*[@content-desc="Scan mã QR"]')
                  and self.elements('//android.widget.EditText'), "Chưa rời màn tìm kiếm để vào hội thoại.")
        if name:
            self.find(self.text_locator(name))
        self.peer_name = name
        self.composer()

    def composer(self):
        return self.find(self.named("composer", '//android.widget.EditText'))

    def send(self, message, expected_display=None):
        self.wake_for_interaction()
        original = self.composer().get_attribute("text") or ""
        if original not in ("", "Nhập tin nhắn"):
            if original in self.draft_journal():
                self.owned_draft = original
                self.clear_owned_draft()
                self.open_peer()
            else:
                raise Blocked("Hội thoại có nháp sẵn; không ghi đè hoặc gửi kèm nháp của người dùng.")
        journal = self.draft_journal()
        journal.append(message)
        self.draft_journal(journal)
        self.owned_draft = message
        self.composer().send_keys(message)
        self.wait(lambda:self.composer().get_attribute('text')==message,'Ô soạn chưa giữ đúng nội dung trước gửi.')
        self.click(self.named("send", '//*[@content-desc="Send" or @content-desc="Gửi tin nhắn"]'),stable_bounds=True)
        self.wait(lambda: self.composer().get_attribute("text") in ("", "Nhập tin nhắn"), "Ô soạn chưa trống sau khi gửi.")
        self.owned_draft = None
        self.draft_journal([value for value in self.draft_journal() if value != message])
        self.keyboard_back()
        self.message_received(expected_display or message)

    def message_received(self, message):
        value = literal(message)
        full=f'//*[@class!="android.widget.EditText" and (contains(@text,{value}) or contains(@content-desc,{value}))]'
        if len(message)>256 and message.startswith("APPIUM-"):
            # Text dài được vẽ thu gọn. Đối chiếu dữ liệu đầy đủ qua chính chức năng Sao chép của app.
            # Không dùng phần preview hoặc marker làm bằng chứng đã nhận đủ payload.
            prefix=message.split(" ",1)[0]
            self.wait(lambda:self.elements(full) or self.elements('//*[contains(@content-desc,'+literal(prefix)+') and contains(@content-desc,"Xem thêm")]'),"Chưa nhận bubble text dài đúng marker.",timeout=35)
            if self.elements(full):return
            from .suite_ui import UI
            UI(self).menu(prefix)
            self.click(self.text_locator("Sao chép"))
            self.driver.activate_app("io.appium.settings")
            try:actual=self.driver.get_clipboard_text()
            finally:self.driver.activate_app(self.config["app_package"])
            assert actual==message,"Sao chép từ bubble bên "+self.role+" chưa trả đúng đủ nội dung text dài."
            self.emit("assertion",self.role+": clipboard của bubble đúng toàn bộ payload dài; không đánh giá layout/font.")
            return
        self.find(full, timeout=35)

    def draft(self, marker):
        self.open_peer()
        original = self.composer().get_attribute("text") or ""
        if original not in ("", "Nhập tin nhắn"):
            if original in self.draft_journal():
                self.owned_draft = original
                self.clear_owned_draft()
                self.open_peer()
            else:
                raise Blocked("Hội thoại có bản nháp sẵn; không ghi đè dữ liệu của người dùng.")
        journal = self.draft_journal()
        journal.append(marker)
        self.draft_journal(journal)
        self.owned_draft = marker
        self.composer().send_keys(marker)
        self.home()
        value = literal(marker)
        self.find(f'//*[contains(@content-desc,{value}) or contains(@text,{value})]')
        self.open_peer()
        self.wait(lambda: marker == self.composer().get_attribute("text"), "Tin nháp không được khôi phục đúng.")
        self.clear_owned_draft()

    def clear_owned_draft(self):
        if self.owned_draft:
            self.emit("step", f"{self.role}: dọn nháp có ownership và kiểm tra lại sau khi mở hội thoại")
            fields = self.elements(self.named("composer", '//android.widget.EditText'))
            if not fields:
                self.open_current()
                fields = [self.composer()]
            if fields[0].get_attribute("text") in ("", "Nhập tin nhắn"):
                marker=self.owned_draft;self.owned_draft=None
                self.draft_journal([value for value in self.draft_journal() if value!=marker])
                self.emit("step",f"{self.role}: ô soạn đã trống; kết thúc ownership, không xóa dữ liệu.")
                return
            if fields[0].get_attribute("text") != self.owned_draft:
                raise RuntimeError("Không xác minh được bản nháp của run; không tự xóa.")
            marker = self.owned_draft
            self.driver.execute_script("mobile: clickGesture", {"elementId": fields[0].id})
            self.wait(self.driver.is_keyboard_shown, "Ô nháp chưa nhận focus bàn phím để dọn an toàn.", timeout=10)
            self.driver.press_keycode(29, metastate=4096)
            self.driver.press_keycode(67)
            self.wait(lambda: self.composer().get_attribute("text") in ("", "Nhập tin nhắn"), "Không xóa được nháp do run tạo.")
            # Nháp đã xóa; lỗi xác minh sau đó không được làm lần cleanup sau xóa lại ô khác.
            self.owned_draft = None
            self.home()
            self.wait(lambda: marker not in self.driver.page_source, "Nháp đã xóa vẫn còn trong danh sách.")
            self.open_current()
            self.wait(lambda: self.composer().get_attribute("text") in ("", "Nhập tin nhắn"), "Nháp cũ xuất hiện lại sau khi mở hội thoại.")
            self.owned_draft = None
            self.draft_journal([value for value in self.draft_journal() if value != marker])
            self.home()

    def open_current(self):
        if self.conversation_name:
            from .suite_ui import UI
            UI(self).open_named(self.conversation_name)
        else:
            self.open_peer(self.peer_role)

    def draft_journal(self, values=None):
        device = self.config["devices"][self.role]
        key = hashlib.sha256((device["udid"] + ":" + device["account"]["phone"]).encode()).hexdigest()
        path = ROOT / ".runtime/owned-drafts.json"
        journal = json.loads(path.read_text()) if path.exists() else {}
        if values is not None:
            journal[key] = values
            save_private_json(path, journal)
        return journal.get(key, [])

    def ai_consent_visible(self):
        source=self.driver.page_source
        return "Trải nghiệm tiện ích AI" in source and "ChatGPT" in source and "Cho phép" in source

    def dismiss_ai_consent(self):
        if self.ai_consent_visible():
            # Chỉ đóng sheet, không chọn Cho phép/Từ chối và không đổi lựa chọn chia sẻ dữ liệu.
            self.click('//*[@content-desc="Đóng"]')
            self.wait(lambda:not self.ai_consent_visible(),"Chưa đóng sheet xin phép AI.")
            self.emit("step","Đã đóng sheet AI để chạy case khác; chưa cấp quyền chia sẻ dữ liệu.")

    def call_service_active(self):
        # Đọc service độc lập với control đang ẩn, PiP hoặc app đang ở nền.
        result = subprocess.run([find_adb(self.config), "-s", self.config["devices"][self.role]["udid"],
                                 "shell", "dumpsys", "activity", "services", self.config["app_package"]],
                                capture_output=True, text=True, timeout=15, check=True)
        return bool(re.search(r"\* ServiceRecord\{[^\n]*/(?:com\.tammi\.call\.platform\.services\.CallForegroundService|com\.dvm\.chatcall\.notification\.call\.ThirdPartyCallService)\b", result.stdout))

    def call_active(self):
        if self.call_service_active():
            return True
        locators=self.config.get("locators",{})
        if locators.get("call_end") and self.elements(locators["call_end"]):return True
        if all(locators.get(key) and self.elements(locators[key]) for key in ("call_accept","call_reject")):return True
        # Cả thanh đang gọi và nền video đều có thể tồn tại khi nút kết thúc bị ẩn.
        bar = '//android.widget.TextView[string-length(@text)=5 and substring(@text,3,1)=":" and translate(@text,"0123456789:","")=""]/parent::*[.//*[@text=" • "]]'
        return bool(self.elements(bar) or (self.elements('//*[@text="Bạn"]') and self.elements('//android.view.TextureView')))

    def require_idle_call(self):
        if self.call_active():
            raise Blocked(f"{self.role}: còn cuộc gọi/service trước testcase; không nhận quyền sở hữu hoặc can thiệp cuộc gọi có sẵn.")
        self.emit("step", f"{self.role}: không có cuộc gọi/service trước testcase")

    def call_control(self, key):
        titles = {"call_audio": "gọi thoại", "call_video": "gọi video", "call_accept": "nhận cuộc gọi",
                  "call_reject": "từ chối cuộc gọi", "call_end": "kết thúc cuộc gọi"}
        self.emit("step", f"{self.role}: {titles.get(key, key)}")
        if key in ('call_audio','call_video'):self.wake_for_interaction()
        if key in ("call_accept", "call_reject"):
            self.wait_incoming()
        self.allow_test_permission()
        self.click(self.named(key), stable_bounds=key in ("call_accept", "call_reject", "call_end"))
        if key in ("call_audio", "call_video"):
            self.wait(lambda: self.allow_test_permission() or self.elements(self.named("call_end"))
                      or self.elements(self.named("call_reject")), "Chưa mở màn gọi sau khi bấm gọi.", timeout=15)
            for _ in range(3):
                if not self.allow_test_permission():
                    break

    def wait_incoming(self):
        def ready():
            self.allow_test_permission()
            if self.elements(self.named("call_accept")) or self.elements(self.named("call_reject")):
                return True
            current_package = self.driver.current_package
            if current_package not in (self.config["app_package"],"com.android.systemui","com.oplus.systemui.plugins"):
                self.driver.open_notifications()
                return False
            name = literal(self.peer_name or "")
            notification='//*[@text='+name+']/ancestor::*[.//*[contains(@text,"Cuộc gọi thoại") or contains(@text,"Cuộc gọi video")] and not(.//*[contains(@text,"nhỡ")])][1]'
            # Chỉ đọc notification trong SystemUI, tránh khớp lịch sử call trong hội thoại.
            if current_package != self.config["app_package"] and self.peer_name and self.elements(notification):
                self.click(notification)
                return False
            banner = (f'//*[contains(@text,{name}) or contains(@content-desc,{name})]'
                      '[contains(@text,"Cuộc gọi thoại đến") or contains(@content-desc,"Cuộc gọi thoại đến") or contains(@text,"Cuộc gọi video đến") or contains(@content-desc,"Cuộc gọi video đến")]')
            if self.peer_name and self.elements(banner):
                self.emit("step", f"{self.role}: mở banner cuộc gọi đến của tài khoản đối diện")
                self.click(banner)
            return False
        self.wait(ready, "Không nhận được màn hoặc banner cuộc gọi đến của tài khoản đối diện.", timeout=40)

    def open_owned_call_notification(self):
        if not self.peer_name:
            raise Blocked("Chưa có tên peer đã xác minh để mở đúng notification cuộc gọi.")
        self.driver.open_notifications()
        peer=literal(self.peer_name)
        card='//*[@text='+peer+']/ancestor::*[.//*[contains(@resource-id,"chronometer")] and .//*[@content-desc="Gác máy" or @content-desc="Kết thúc" or @text="Gác máy" or @text="Kết thúc"]][1]'
        # Tap tên trong card đang chạy, không tap action kết thúc hoặc notification gọi nhỡ.
        self.click(card+'//*[@text='+peer+']')
        self.wait(lambda:self.driver.current_package==self.config["app_package"],"Notification chưa mở lại app gọi.")
        self.restore_owned_call_view()

    def restore_owned_call_view(self):
        if self.elements(self.named("call_end")):return
        timer='//android.widget.TextView[string-length(@text)=5 and substring(@text,3,1)=":" and translate(@text,"0123456789:","")=""]'
        bar=timer+'/parent::*[.//*[@text=" • "]]'
        if self.peer_name:bar+='[.//*[@text='+literal(self.peer_name)+']]'
        if self.elements(bar):
            self.click(bar)
            self.wait(lambda:self.elements(self.named("call_end")) or self.elements('//*[@text="Bạn"]'),"Thanh call chưa mở lại màn cuộc gọi.")
        self.reveal_call_controls()

    def reveal_call_controls(self):
        if self.elements(self.named("call_end")):return
        # Service còn chạy không chứng minh Compose trước mắt là màn call.
        if not self.driver.current_activity.endswith(".CallActivity"):return
        # Khi B vừa vào Meet, grid đổi kích thước và semantics có thể mất một nhịp.
        # Chờ control ổn định trước; tap ngay lúc này có thể làm ẩn control đang hiện.
        try:
            self.wait(lambda:self.elements(self.named("call_end")),"Control call chưa sẵn sàng.",timeout=2)
            return
        except AssertionError:pass
        if not self.elements('//*[@text="Bạn"]') and not self.call_service_active():return
        frames=self.elements('//android.view.TextureView')
        roots=self.elements('//androidx.compose.ui.platform.ComposeView')
        if not roots and not frames:return
        frame=max(roots or frames,key=lambda element:element.rect["width"]*element.rect["height"])
        # Khi tắt cả hai camera không còn TextureView; dùng nền Compose của call có service/nhãn Bạn.
        # OngoingCallScreen ẩn control sau 5 giây; tap nền video lớn để hiện lại, theo onTap trong source.
        rect=frame.rect
        # Samsung chặn trả kết quả injection UiAutomation tới 10 giây, quá cửa sổ control.
        # Dùng ADB tap nền đã lấy bounds qua Appium; vẫn xác minh control bằng Appium.
        idle=self.driver.get_settings().get("waitForIdleTimeout",1000)
        self.driver.update_settings({"waitForIdleTimeout":0})
        try:
            x=str(int(rect["x"]+rect["width"]*0.25));y=str(int(rect["y"]+rect["height"]*0.55))
            # Giữ DOWN 100 ms để combinedClickable của ô Meet nhận đủ một nhịp chạm.
            subprocess.run([find_adb(self.config),"-s",self.config["devices"][self.role]["udid"],
                            "shell","input","swipe",x,y,x,y,"100"],capture_output=True,text=True,check=True,timeout=15)
            self.wait(lambda:self.elements(self.named("call_end")),"Nền video chưa hiện lại control cuộc gọi.",timeout=5)
        finally:self.driver.update_settings({"waitForIdleTimeout":idle})

    def wait_connected(self):
        locator = self.named("call_connected")
        def ready():
            self.allow_test_permission()
            self.restore_owned_call_view()
            return next((e for e in self.elements(locator) if e.is_displayed()), None)
        initial = self.wait(ready, "Chưa có timer xác nhận kết nối cuộc gọi.", timeout=40).get_attribute("text")
        def progressed():
            # Timer có thể ẩn cùng control ngay sau lần đọc đầu; chỉ hiện lại ở bước xác minh.
            self.restore_owned_call_view()
            return any(e.get_attribute("text") != initial for e in self.elements(locator))
        self.wait(progressed,"Timer cuộc gọi chưa tiến sau khi kết nối.", timeout=8)
        self.emit("step", f"{self.role}: đã xác minh timer cuộc gọi đang tiến")

    def end_owned_call(self):
        self.wake_for_interaction()
        locator = self.config.get("locators", {}).get("call_end")
        if locator:
            if self.driver.current_package in ("com.android.systemui","com.oplus.systemui.plugins"):
                self.driver.press_keycode(4)
            if self.driver.current_package!=self.config["app_package"]:
                self.driver.activate_app(self.config["app_package"])
            self.restore_owned_call_view()
            elements = self.elements(locator)
            if elements:
                self.click(locator)
                self.wait(lambda: not self.elements(locator), "Không dọn được cuộc gọi do run tạo.")
            elif self.elements(self.named("call_reject")):
                self.click(self.named("call_reject"))
        self.wait(lambda: not self.call_active(), "Cuộc gọi/PiP/service do run tạo chưa kết thúc.", timeout=20)
