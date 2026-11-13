"""Thay đổi trạng thái Android có ghi sổ khôi phục; không xóa dữ liệu ứng dụng."""
import json
import re
import shlex
import subprocess
import time
from pathlib import Path

from .common import ROOT, Blocked, find_adb, save_private_json


class Devices:
    def __init__(self, ctx):
        self.ctx, self.undo = ctx, []
        self.journal = ROOT / ".runtime/device-restore.json"
        if self.journal.exists():
            raise Blocked("Còn trạng thái Android chưa khôi phục từ job trước. Chạy CLI recover trước.")

    def adb(self, role, *args):
        if args and args[0]=="shell":args=("shell",shlex.join(map(str,args[1:])))
        command = [find_adb(self.ctx.config), "-s", self.ctx.config["devices"][role]["udid"], *map(str,args)]
        result = subprocess.run(command, text=True, capture_output=True, timeout=25, check=True)
        return result.stdout.strip()

    def missed_notifications(self, role, peer):
        from .notifications import missed_versions
        return missed_versions(self.adb(role,"shell","dumpsys","notification","--noredact"),self.ctx.config["app_package"],peer)

    def remember(self, role, *args):
        self.undo.append({"role":role,"args":list(map(str,args))})
        save_private_json(self.journal, {"devices":{r:d["udid"] for r,d in self.ctx.config["devices"].items() if d.get("udid")},"undo":self.undo})

    def setting(self, role, namespace, key, value):
        old = self.adb(role,"shell","settings","get",namespace,key)
        self.remember(role,"shell","settings", "delete" if old=="null" else "put",namespace,key,*(() if old=="null" else (old,)))
        self.adb(role,"shell","settings","put",namespace,key,value)

    def network(self, role, enabled):
        for service,key in (("wifi","wifi_on"),("data","mobile_data")):
            old = self.adb(role,"shell","settings","get","global",key)
            if old not in ("0","1"):
                raise Blocked(f"Không đọc được trạng thái {service} của {role}; không đổi mạng khi chưa biết cách khôi phục.")
            self.remember(role,"shell","svc",service,"enable" if old=="1" else "disable")
            self.adb(role,"shell","svc",service,"enable" if enabled else "disable")
        def state():
            text=self.adb(role,"shell","dumpsys","connectivity")
            import re
            match=re.search(r"Active default network:\s*(\S+)",text)
            if not match:
                raise Blocked("Android không expose Active default network theo parser hiện tại.")
            online=match.group(1).lower() not in ("none","null","-1")
            return online==enabled
        self.ctx.page(role).wait(state,"Trạng thái kết nối thực tế chưa đổi như yêu cầu.",timeout=20)

    def ringer_mode(self,role):
        text=self.adb(role,"shell","dumpsys","audio")
        match=re.search(r'^- mode \(external\) = (NORMAL|VIBRATE|SILENT)\s*$',text,re.M)
        if not match:raise Blocked("Không đọc được ringer mode từ AudioService; không đổi chế độ chuông.")
        return match[1]

    def ringer(self, role, mode):
        target=mode.upper()
        if target not in ('NORMAL','VIBRATE','SILENT'):raise ValueError('Ringer mode không hợp lệ.')
        old=self.ringer_mode(role)
        self.remember(role,"shell","cmd","audio","set-ringer-mode",old)
        self.adb(role,"shell","cmd","audio","set-ringer-mode",target)
        deadline=time.monotonic()+5
        while self.ringer_mode(role)!=target:
            if time.monotonic()>=deadline:raise Blocked("AudioService chưa đổi ringer mode đúng yêu cầu; chưa chạy cuộc gọi.")
            self.ctx.check();time.sleep(.2)

    def wait_seconds(self, seconds, message):
        deadline=time.monotonic()+seconds
        self.ctx.reporter.emit("step",message,seconds=seconds)
        last=-1
        while time.monotonic()<deadline:
            self.ctx.check()
            remaining=int(deadline-time.monotonic())
            if remaining//30!=last:
                last=remaining//30
                self.ctx.reporter.emit("progress",message,remaining_seconds=remaining)
                for driver in self.ctx.drivers.values():
                    driver.current_package
            time.sleep(min(.5,max(0,deadline-time.monotonic())))

    def state(self, role, state, sleep_seconds=0):
        page=self.ctx.page(role)
        if state=="inapp":return
        if state in ("background","killed","killed_locked","sleep"):
            page.driver.press_keycode(3)
        if state in ("killed","killed_locked"):
            self.dismiss_recents(role)
        if state in ("locked","killed_locked","sleep"):
            if page.driver.is_locked():
                raise Blocked("Máy đã khóa trước testcase; cần mở khóa trước khi runner quản lý trạng thái khóa.")
            self.remember(role,"shell","wm","dismiss-keyguard")
            self.remember(role,"shell","input","keyevent","KEYCODE_WAKEUP")
            page.driver.lock()
        if sleep_seconds:self.wait_seconds(sleep_seconds,f"{role}: giữ sleep đủ thời gian nguồn")

    def wake(self, role):
        page=self.ctx.page(role)
        if page.driver.is_locked():page.driver.unlock()
        if not page.driver.is_locked():return
        policy=self.adb(role,"shell","dumpsys","window","policy")
        secure=re.findall(r"^\s*secure=(true|false)\s*$",policy,re.M)
        if secure==["false"]:
            self.adb(role,"shell","input","keyevent","KEYCODE_WAKEUP")
            self.adb(role,"shell","wm","dismiss-keyguard")
            try:
                page.wait(lambda:not page.driver.is_locked(),"Keyguard chưa đóng sau khi đánh thức máy.",timeout=8)
                return
            except AssertionError:
                raise Blocked("Appium chưa xác nhận được keyguard đã đóng sau khi đánh thức máy.") from None
        raise Blocked("Chưa xác minh được keyguard không có khóa bảo mật. Cần mở khóa trên thiết bị.")

    def dismiss_recents(self, role):
        page=self.ctx.page(role)
        page.driver.press_keycode(187)
        locator=self.ctx.config.get("locators",{}).get("recent_app_card")
        if not locator:
            locator='//*[contains(@content-desc,"STG Tammi") or @text="STG Tammi"]/ancestor-or-self::*[@scrollable="false" and @clickable="true"][1]'
        card=page.find(locator)
        page.driver.execute_script("mobile: swipeGesture",{"elementId":card.id,"direction":"up","percent":.95})
        page.driver.press_keycode(3)
        package=self.ctx.config["app_package"]
        recents=self.adb(role,"shell","dumpsys","activity","recents")
        import re
        remaining=[line for line in recents.splitlines() if re.search(r"Recent #\d+:",line) and package in line]
        assert not remaining,"Task staging vẫn còn trong recents sau swipe; chưa chứng minh trạng thái killed."

    def restore(self):
        errors=[]
        while self.undo:
            item=self.undo[-1]
            try:self.adb(item["role"],*item["args"])
            except Exception as error:
                errors.append(f"Khôi phục {item['role']}: {type(error).__name__}")
                break
            self.undo.pop()
            if self.undo:
                data=json.loads(self.journal.read_text());data["undo"]=self.undo;save_private_json(self.journal,data)
        if not self.undo:self.journal.unlink(missing_ok=True)
        return errors


def recover(config):
    path=ROOT/".runtime/device-restore.json"
    if not path.exists():return []
    data=json.loads(path.read_text());errors=[]
    for item in reversed(data["undo"]):
        udid=data["devices"][item["role"]]
        args=list(item["args"])
        # Journal cũ dùng chữ thường; Samsung yêu cầu enum viết hoa.
        if args[:4]==["shell","cmd","audio","set-ringer-mode"] and args[-1] in ("silent","vibrate","normal"):
            args[-1]=args[-1].upper()
        if args and args[0]=="shell":args=["shell",shlex.join(args[1:])]
        try:subprocess.run([find_adb(config),"-s",udid,*args],capture_output=True,text=True,timeout=25,check=True)
        except Exception as error:errors.append(str(error));break
        data["undo"].pop();save_private_json(path,data)
    if not errors:path.unlink(missing_ok=True)
    return errors
