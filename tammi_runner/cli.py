"""CLI được dùng chung bởi Desktop và các shell script."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from copy import copy
from dataclasses import asdict
from pathlib import Path

from .cases import CASES, select_cases, uses_only_pair
from .common import (ROOT, DEFAULT_CONFIG, Blocked, Cancelled, Reporter, find_adb,
                     list_devices, load_config, validate_devices, save_private_json)
from .runtime import ManagedAppium, RunLock, check_cancel


class Context:
    def __init__(self, config, reporter, stop_file):
        self.config, self.reporter, self.stop_file = config, reporter, stop_file
        self.cancelled = False
        self.cleaning = False
        self.drivers, self.pages = {}, {}
        self.owned_call_roles = set()
        self.devices_control = None
        self.suite_cleanup = []
        self.call_cleanup = []
        self.assertion_results = {}
        self.transport_dirty = False
        self._last_keepalive = time.monotonic()
        self.server = ManagedAppium(config, reporter, self.check)

    def check(self):
        if not self.cleaning:
            if self.cancelled:
                raise Cancelled("Đã nhận yêu cầu dừng.")
            check_cancel(self.stop_file)
            now=time.monotonic()
            if self.drivers and now-self._last_keepalive>=30:
                # Khi chờ media ở B vẫn giữ session A sống; không kích hoạt hay chuyển màn app.
                self._last_keepalive=now
                for driver in self.drivers.values():driver.current_package

    def page(self, role):
        if role not in self.pages:
            from appium import webdriver
            from appium.options.android import UiAutomator2Options
            from appium.webdriver.client_config import AppiumClientConfig
            from .pages import AppPage
            if self.server.url is None:
                self.server.start()
            device = self.config["devices"][role]
            package = self.config["app_package"]
            installed = subprocess.run([find_adb(self.config), "-s", device["udid"], "shell", "pm", "path", package],
                                       capture_output=True, text=True, timeout=15, check=True)
            if not installed.stdout.strip().startswith("package:"):
                raise Blocked(f"Thiết bị {role} chưa có app staging. Cài APK trong tab Build trước.")
            self.reporter.emit("step", "Tạo session Android " + role)
            options = UiAutomator2Options().load_capabilities({
                "platformName": "Android", "appium:automationName": "UiAutomator2",
                "appium:udid": device["udid"], "appium:systemPort": device.get("system_port", 8201 if role == "A" else 8202),
                "appium:appPackage": package, "appium:appActivity": self.config.get("app_activity", "com.vt.platform.MainActivity"),
                "appium:noReset": True, "appium:forceAppLaunch": False,
                "appium:autoGrantPermissions": False, "appium:newCommandTimeout": 600,
                "appium:uiautomator2ServerReadTimeout": 20000,
            })
            driver = webdriver.Remote(self.server.url, options=options,
                                       client_config=AppiumClientConfig(remote_server_addr=self.server.url, timeout=70))
            self.drivers[role] = driver
            driver.update_settings({"waitForIdleTimeout": 1000})
            helper_notice = driver.find_elements("xpath", '//*[@resource-id="com.coloros.phonemanager:id/alertTitle" and contains(@text,"io.appium.uiautomator2.server")]')
            if helper_notice:
                driver.find_element("xpath", '//*[@resource-id="android:id/button2" and @text="Bỏ qua"]').click()
            subprocess.run([find_adb(self.config),"-s",device["udid"],"shell","cmd","statusbar","collapse"],
                           capture_output=True,text=True,timeout=10,check=True)
            driver.activate_app(package)
            self.pages[role] = AppPage(driver, self.config, role, self.check, self.reporter.emit)
            self.pages[role].dismiss_ai_consent()
        return self.pages[role]

    def evidence(self, case_id):
        directory = self.reporter.directory / "evidence" / case_id
        for role, driver in self.drivers.items():
            if not self.pages.get(role):
                continue
            directory.mkdir(parents=True, exist_ok=True)
            try:
                source = driver.page_source
                verified = self.pages[role].account_verified
                if not verified and any(marker in source for marker in ("Nhập mã OTP", "Đăng nhập", 'password="true"')):
                    from xml.etree import ElementTree as ET
                    import re
                    controls = []
                    for node in ET.fromstring(source).iter():
                        text = node.get("text", "")
                        if node.get("password") == "true" or node.get("class", "").endswith("EditText"):
                            continue
                        if text and not re.search(r"\d", text):
                            controls.append({"class": node.get("class"), "text": text,
                                             "clickable": node.get("clickable"), "bounds": node.get("bounds")})
                    save_private_json(directory / f"{role}-auth-controls.json", controls)
                    self.reporter.emit("warning", "Bỏ qua evidence màn đăng nhập để tránh lưu thông tin xác thực")
                    continue
                source = self.reporter.redact(source)
                (directory / f"{role}-hierarchy.xml").write_text(source, encoding="utf-8")
                if not verified:
                    continue
                driver.save_screenshot(str(directory / f"{role}.png"))
                logs = driver.get_log("logcat")
                (directory / f"{role}-logcat.json").write_text(self.reporter.redact(json.dumps(logs, ensure_ascii=False)), encoding="utf-8")
            except Exception as error:
                self.reporter.emit("warning", f"Không thu đủ evidence cho {role}: {type(error).__name__}")

    def cleanup(self):
        self.cleaning = True
        errors = []
        call_errors=[]
        owned_roles=set(self.owned_call_roles)
        if self.devices_control:
            errors.extend(self.devices_control.restore())
        while self.call_cleanup:
            callback=self.call_cleanup.pop()
            try:callback()
            except Exception as error:errors.append(self.reporter.redact(f"Cleanup phòng test: {error}"))
        for role, page in self.pages.items():
            try:
                if role in self.owned_call_roles:
                    page.end_owned_call()
                page.clear_owned_draft()
            except Exception as error:
                if role in owned_roles and not page.owned_draft:call_errors.append((role,error))
                else:errors.append(self.reporter.redact(f"Cleanup {role}: {error}"))
        if call_errors:
            self.reporter.emit("warning","UI không dọn được call test; dừng đúng package staging trên các vai do run sở hữu, giữ nguyên kết quả lỗi.")
            for role in owned_roles:
                try:
                    subprocess.run([find_adb(self.config),"-s",self.config["devices"][role]["udid"],"shell","am","force-stop",self.config["app_package"]],capture_output=True,text=True,timeout=15,check=True)
                except Exception as error:errors.append(self.reporter.redact(f"Không dọn được call test {role}: {error}"))
            self.transport_dirty=True
        self.owned_call_roles.clear()
        while self.suite_cleanup:
            callback=self.suite_cleanup.pop()
            try:callback()
            except Exception as error:errors.append(self.reporter.redact(f"Cleanup suite: {error}"))
        return errors

    def reset_transport(self):
        if self.owned_call_roles or any(page.owned_draft for page in self.pages.values()) or (self.devices_control and self.devices_control.undo):
            raise RuntimeError("Còn tài nguyên chưa dọn; không tự khởi tạo session mới.")
        self.reporter.emit("warning","Khởi tạo lại Appium sau lỗi transport; giữ ERROR, không chạy lại testcase.")
        self.server.stop()
        # Server lỗi có thể để lại forward UIA; chỉ xóa port của session mà Context này đã tạo.
        if self.drivers:
            adb=find_adb(self.config)
            listed=subprocess.run([adb,"forward","--list"],capture_output=True,text=True,timeout=15,check=True).stdout
            forwards={tuple(line.split()) for line in listed.splitlines() if len(line.split())==3}
            for role in self.drivers:
                device=self.config["devices"][role]
                port="tcp:"+str(device.get("system_port",8201 if role=="A" else 8202))
                if (device["udid"],port,"tcp:6790") in forwards:
                    subprocess.run([adb,"-s",device["udid"],"forward","--remove",port],capture_output=True,text=True,timeout=15,check=True)
        self.drivers.clear();self.pages.clear()
        self.devices_control=None
        self.server=ManagedAppium(self.config,self.reporter,self.check)
        self.cleaning=False
        self.transport_dirty=False

    def close(self):
        errors = self.cleanup()
        for role, driver in self.drivers.items():
            try:
                driver.quit()
            except Exception as error:
                errors.append(self.reporter.redact(f"Đóng session {role}: {type(error).__name__}"))
        try:
            self.server.stop()
        except Exception as error:
            errors.append(self.reporter.redact(f"Dừng server: {type(error).__name__}"))
        self.reporter.cleanup_errors.extend(errors)


def execute_case(ctx, case):
    ctx.check()
    if case.action == "suite":
        from .full_runner import execute
        return execute(ctx,case)
    validate_devices(ctx.config, list_devices(ctx.config), case.roles)
    if case.action.startswith("recall"):
        keys = ("call_audio", "call_accept", "call_reject", "call_end", "call_connected")
        missing = [k for k in keys if not ctx.config.get("locators", {}).get(k)]
        if missing:
            raise Blocked("Cần locator call trong Thiết lập: " + ", ".join(missing))
    page = ctx.page("B" if case.action == "login_b" else "A")
    if case.action == "launch":
        page.wait(lambda: page.driver.current_package == ctx.config["app_package"], "Không mở đúng package staging.")
        return "Mở đúng app staging; đây là kiểm tra setup."
    if case.action in ("login", "login_b"):
        page.login_and_verify(allow_switch=True)
        return "Đã đăng nhập và xác minh đúng tài khoản staging: " + page.role
    if case.action == "open_peer":
        page.open_peer()
        ctx.evidence(case.id)
        return "Đã tìm đúng số tài khoản B và mở ô soạn tin; không gửi tin."
    marker = "APPIUM-" + uuid.uuid4().hex[:12]
    if case.action == "draft":
        page.draft(marker)
        return "Nháp xuất hiện trong danh sách và được khôi phục; đã dọn nháp của run. Coverage một phần CHAT-SRC-015."
    if case.action == "text_pair":
        other = ctx.page("B")
        page.open_peer()
        other.open_peer()
        for sender, receiver, suffix in ((page, other, "A-B"), (other, page, "B-A")):
            ctx.check()
            text = marker + " " + suffix
            ctx.reporter.emit("step", "Gửi và assert nội dung ở thiết bị đối diện " + suffix)
            sender.send(text)
            receiver.message_received(text)
        return "Hai bên đã nhận đúng text có run ID. Tin test được giữ làm evidence; chưa test max ký tự/font."
    if case.action in ("recall_a", "recall_b"):
        other = ctx.page("B")
        page.require_idle_call()
        other.require_idle_call()
        page.open_peer()
        other.open_peer()
        caller, receiver = (page, other) if case.action == "recall_a" else (other, page)
        end = ctx.config["locators"]["call_end"]
        if caller.elements(end) or receiver.elements(end):
            raise Blocked("Đang có cuộc gọi sẵn; không can thiệp cuộc gọi của người dùng.")
        ctx.owned_call_roles.update(("A", "B"))
        caller.call_control("call_audio")
        receiver.wait_incoming()
        receiver.call_control("call_reject")
        receiver.call_control("call_audio")
        caller.call_control("call_accept")
        for current in (caller, receiver):
            current.wait_connected()
        ctx.evidence(case.id + "-connected")
        caller.call_control("call_end")
        for current in (caller, receiver):
            current.wait(lambda p=current: not p.call_active(), "Cuộc gọi mới/service chưa kết thúc trên cả hai thiết bị.")
        ctx.owned_call_roles.clear()
        return "Đã từ chối và thiết lập cuộc gọi ngược chiều, kết thúc hai phía; chưa đo audio."
    raise Blocked("Chưa có action cho case này.")


def run(args, config):
    selected = selected_cases(args)
    skipped=[]
    skip_failed=getattr(args,'skip_failed',False)
    if getattr(args,'skip_passed',False) or skip_failed:
        from .resume import pending_cases
        selected,skipped=pending_cases(selected,ROOT/'reports',skip_passed=getattr(args,'skip_passed',False),skip_failed=skip_failed)
    reporter = Reporter(config, args.output)
    for case in skipped:
        reporter.emit('skipped_history' if skip_failed else 'skipped_pass',
                      'Giữ kết quả cũ theo bộ lọc PASS/FAIL/ERROR, không chạy lại.' if skip_failed else 'Giữ nguyên PASS, không chạy lại.',case_id=case.id)
    ctx = Context(config, reporter, args.stop_file)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: setattr(ctx, "cancelled", True))
    reporter.emit("started", "Bắt đầu chạy script Appium", report_directory=str(reporter.directory))
    cancelled = False
    lock = RunLock()
    acquired = False
    try:
        lock.__enter__()
        acquired = True
        if (ROOT/".runtime/device-restore.json").exists():
            raise Blocked("Còn trạng thái Android cần khôi phục. Chạy scripts/recover.sh trước.")
        contaminated = False
        for case in selected:
            start = time.monotonic()
            reporter.emit("case_start", case.name, case_id=case.id)
            status = "PASS"
            transport_failed=False
            try:
                ctx.check()
                if contaminated:
                    raise Blocked("Cleanup trước đó lỗi; cần kiểm tra thiết bị trước khi chạy tiếp.")
                ctx.cleaning = False
                message = execute_case(ctx, case)
            except Cancelled as error:
                status, message, cancelled = "CANCELLED", str(error), True
            except Blocked as error:
                status, message = "BLOCKED", str(error)
                ctx.evidence(case.id)
            except AssertionError as error:
                status, message = "FAIL", str(error)
                ctx.evidence(case.id)
            except Exception as error:
                status, message = "ERROR", f"{type(error).__name__}: {error}"
                transport_failed=any(token in message for token in ("Could not proxy command","socket hang up","ECONNREFUSED","InvalidSessionIdException","NoSuchDriverException"))
                if not transport_failed:ctx.evidence(case.id)
                else:reporter.emit("warning","Transport lỗi, bỏ evidence qua session hỏng; log Appium giữ trong report.",case_id=case.id)
            finally:
                errors = ctx.cleanup()
                reporter.cleanup_errors.extend(errors)
                contaminated = contaminated or bool(errors)
                if errors and status=="PASS":
                    status,message="ERROR","Assertion đạt nhưng cleanup lỗi: "+"; ".join(errors)
                elif ctx.transport_dirty and status=="PASS":
                    status,message="ERROR","Assertion đạt nhưng phải force-stop để dọn call test; cần chạy lại trước khi nghiệm thu."
            result = {"id": case.id, "name": case.name, "status": status,
                      "seconds": round(time.monotonic() - start, 2),
                      "message": reporter.redact(message), "sources": list(case.sources), "coverage": case.note}
            result['coverage_level']=case.coverage_level
            result["expected_assertions"]=list(case.obligations)
            result["proved_assertions"]=ctx.assertion_results.get(case.id,[])
            result["cleanup_recovery"]=ctx.transport_dirty
            reporter.results.append(result)
            reporter.emit("case_result", result["message"], case_id=case.id, status=status,
                          seconds=result["seconds"])
            if (transport_failed or ctx.transport_dirty) and not contaminated and not cancelled:
                try:ctx.reset_transport()
                except Exception as error:
                    reporter.cleanup_errors.append(reporter.redact(str(error)));contaminated=True
            if cancelled:
                break
    except (Blocked, Cancelled) as error:
        for case in selected:
            if case.id not in {r["id"] for r in reporter.results}:
                result = {"id": case.id, "status": "CANCELLED" if isinstance(error, Cancelled) else "BLOCKED",
                          "message": str(error), "seconds": 0}
                reporter.results.append(result)
                reporter.emit("case_result", result["message"], case_id=case.id, status=result["status"], seconds=0)
    finally:
        ctx.close()
        if acquired:
            lock.__exit__(None, None, None)
        if cancelled:
            for case in selected:
                if case.id not in {r["id"] for r in reporter.results}:
                    result = {"id": case.id, "status": "CANCELLED", "message": "Chưa chạy vì lượt test đã dừng.", "seconds": 0}
                    reporter.results.append(result)
                    reporter.emit("case_result", result["message"], case_id=case.id, status="CANCELLED", seconds=0)
        reporter.finish()
        from .coverage import write_coverage
        write_coverage(reporter)
    statuses = {r["status"] for r in reporter.results}
    if "CANCELLED" in statuses:
        return 130
    if statuses & {"FAIL", "ERROR"} or reporter.cleanup_errors:
        return 1
    return 2 if "BLOCKED" in statuses else 0


def selected_cases(args):
    if getattr(args,"suite",None)=="pair":
        scoped=copy(args);scoped.suite="all"
        selected=selected_cases(scoped)
        disallowed=[case.id for case in selected if not uses_only_pair(case)]
        if (args.case or getattr(args,"source",None)) and disallowed:raise Blocked("Suite A/B không chạy case cần C: "+", ".join(disallowed))
        return [case for case in selected if uses_only_pair(case)]
    if args.case:return select_cases(args.case)
    resume=getattr(args,"resume_from",None)
    if resume:
        path=Path(resume).expanduser();path=path/"summary.json" if path.is_dir() else path
        value=json.loads(path.read_text())
        unfinished={row["id"] for row in value["results"] if row["status"]=="CANCELLED"}
        return [case for case in CASES if case.id in unfinished]
    source=getattr(args,"source",None)
    if source:
        selected=[case for case in CASES if set(source)&set(case.sources)]
        known={item for case in selected for item in case.sources}
        unknown=set(source)-known
        if unknown:raise Blocked("Nguồn bị loại/không có script: "+", ".join(sorted(unknown)))
        return selected
    suite=getattr(args,"suite",None)
    if suite=="core":return [case for case in CASES if case.action!="suite"]
    if suite=="chat":return [case for case in CASES if case.action=="suite" and case.id.startswith("CHAT-")]
    if suite=="call":return [case for case in CASES if case.action=="suite" and case.id.startswith("CALL-")]
    if suite=="lab":return [case for case in CASES if any(req.startswith("probe:") for req in case.requirements) or case.params.get("hold_seconds") or "C" in case.roles]
    if suite=="all" or getattr(args,"all",False):return list(CASES)
    return select_cases(["APP-OPEN"])


def preflight_report(args,config):
    from .full_runner import preflight
    reporter=Reporter(config,args.output)
    available=list_devices(config)
    for case in selected_cases(args):
        try:
            if case.action=="suite":preflight(config,case,available)
            else:validate_devices(config,available,case.roles)
            status,message="READY","Đủ điều kiện cấu hình/thiết bị; CHƯA CHẠY assertion sản phẩm."
        except Blocked as error:status,message="BLOCKED",str(error)
        reporter.results.append({"id":case.id,"name":case.name,"status":status,"message":message,"seconds":0,"sources":list(case.sources)})
        reporter.emit("case_result",message,case_id=case.id,status=status)
    reporter.finish()
    from .coverage import write_coverage
    write_coverage(reporter)
    return 2 if any(row["status"]=="BLOCKED" for row in reporter.results) else 0


def build(args, config):
    reporter = Reporter(config, args.output)
    host = Path(args.host).expanduser().resolve()
    wrapper = host / ("gradlew.bat" if os.name == "nt" else "gradlew")
    env = args.environment
    task = f":app:assemble{env.title()}Arm8FullDebug"
    process = None
    reader = None
    lock = RunLock()
    acquired = False
    try:
        if not wrapper.is_file():
            raise Blocked("Không tìm thấy Gradle wrapper tại host đã chọn.")
        lock.__enter__()
        acquired = True
        reporter.emit("started", "Build " + task, report_directory=str(reporter.directory))
        process = subprocess.Popen([str(wrapper), task, "--console=plain"], cwd=host,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   start_new_session=os.name != "nt")
        def read():
            for line in process.stdout:
                reporter.emit("build", line.rstrip())
        import threading
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        while process.poll() is None:
            check_cancel(args.stop_file)
            time.sleep(0.2)
        reader.join(timeout=3)
        if process.returncode:
            raise RuntimeError(f"Gradle trả mã {process.returncode}; xem runner.log.")
        variant = f"{env}Arm8FullDebug"
        metadata = []
        for candidate in (host / "app/build/outputs/apk").rglob("output-metadata.json"):
            value = json.loads(candidate.read_text())
            if value.get("variantName") == variant:
                metadata.append((candidate, value))
        if len(metadata) != 1:
            raise RuntimeError("Không xác định duy nhất được APK từ output-metadata.json của variant.")
        path, value = metadata[0]
        apk = path.parent / value["elements"][0]["outputFile"]
        if not apk.is_file():
            raise RuntimeError("Metadata có APK nhưng file không tồn tại.")
        reporter.emit("artifact", "Build thành công", apk=str(apk), environment=env)
        reporter.results.append({"id": "BUILD", "status": "PASS", "message": str(apk), "seconds": 0})
    except Cancelled:
        reporter.results.append({"id": "BUILD", "status": "CANCELLED", "message": "Đã yêu cầu dừng build", "seconds": 0})
    except Blocked as error:
        reporter.results.append({"id": "BUILD", "status": "BLOCKED", "message": str(error), "seconds": 0})
    except Exception as error:
        reporter.results.append({"id": "BUILD", "status": "ERROR", "message": reporter.redact(error), "seconds": 0})
    finally:
        if process and process.poll() is None:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait(timeout=5)
        if reader:
            reader.join(timeout=3)
        if acquired:
            lock.__exit__(None, None, None)
        reporter.finish()
    if any(r["status"] == "CANCELLED" for r in reporter.results):
        return 130
    if any(r["status"] == "BLOCKED" for r in reporter.results):
        return 2
    return 0 if all(r["status"] == "PASS" for r in reporter.results) else 1


def install(args, config):
    reporter = Reporter(config, args.output)
    try:
        with RunLock():
            roles = tuple(args.role or ["A"])
            validate_devices(config, list_devices(config), roles)
            apk = Path(args.apk or "").expanduser().resolve()
            if not apk.is_file() or apk.suffix.lower() != ".apk":
                raise Blocked("Chưa chọn file APK hợp lệ.")
            tools = config.get("tools", {})
            sdk = Path(tools.get("android_home") or os.environ.get("ANDROID_HOME")
                       or Path.home() / "Library/Android/sdk")
            candidates = list((sdk / "build-tools").glob("*/aapt")) + list((sdk / "build-tools").glob("*/aapt.exe"))
            if not candidates:
                raise Blocked("Cần aapt trong Android SDK Build-Tools để xác minh APK trước khi cài.")
            import re
            candidates.sort(key=lambda p: [int(x) for x in re.findall(r"\d+", p.parent.name)], reverse=True)
            data = subprocess.run([str(candidates[0]), "dump", "badging", str(apk)],
                                  capture_output=True, text=True, timeout=30, check=True).stdout
            match = re.search(r"package: name='([^']+)'", data)
            if not match or match.group(1) != config["app_package"]:
                raise Blocked("APK không thuộc package staging; không cài nhầm app prod.")
            reporter.emit("started", "Cài APK staging", report_directory=str(reporter.directory))
            for role in roles:
                check_cancel(args.stop_file)
                reporter.emit("step", "Đang cài APK vào máy " + role)
                result = subprocess.run([find_adb(config), "-s", config["devices"][role]["udid"],
                                         "install", "-r", "-t", str(apk)], capture_output=True,
                                        text=True, timeout=180, check=True)
                if "Success" not in result.stdout:
                    raise RuntimeError("ADB chưa xác nhận cài thành công.")
                reporter.results.append({"id": "INSTALL-" + role, "status": "PASS", "seconds": 0,
                                         "message": "Đã cài đúng package staging"})
                check_cancel(args.stop_file)
    except (Blocked, Cancelled) as error:
        reporter.results.append({"id": "INSTALL", "status": "BLOCKED" if isinstance(error, Blocked) else "CANCELLED",
                                 "seconds": 0, "message": str(error)})
    except Exception as error:
        reporter.results.append({"id": "INSTALL", "status": "ERROR", "seconds": 0, "message": reporter.redact(error)})
    finally:
        reporter.finish()
    statuses = {r["status"] for r in reporter.results}
    if "CANCELLED" in statuses:
        return 130
    if "ERROR" in statuses:
        return 1
    return 2 if "BLOCKED" in statuses else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tammi Desktop / Appium runner")
    parser.add_argument("command", choices=("devices", "doctor", "cases", "run", "build", "install", "preflight", "lab-check", "recover"))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--case", action="append")
    parser.add_argument("--all", action="store_true", help="Chạy mọi script đã triển khai và đối chiếu đủ dòng Excel trong report")
    parser.add_argument("--skip-failed",action="store_true",help="Bỏ case từng FAIL hoặc ERROR trong lịch sử hợp lệ, giữ nguyên báo cáo cũ.")
    parser.add_argument("--skip-passed",action="store_true",help="Chạy tiếp: bỏ case từng PASS đủ assertion theo lịch sử hợp lệ.")
    parser.add_argument("--resume-from",help="Chạy case CANCELLED từ report trước, giữ nguyên kết quả FAIL/ERROR cũ.")
    parser.add_argument("--suite",choices=("core","chat","call","lab","all","pair"))
    parser.add_argument("--source",action="append",help="Chọn toàn bộ biến thể của ID nguồn, ví dụ CHAT-SRC-015")
    parser.add_argument("--output")
    parser.add_argument("--stop-file")
    parser.add_argument("--host", default=str(ROOT.parent.parent / "AppViettel"))
    parser.add_argument("--environment", choices=("staging", "prod"), default="staging")
    parser.add_argument("--apk")
    parser.add_argument("--role", choices=("A", "B", "C"), action="append")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.command=="lab-check":
        from .readiness import report
        return report(args,config,selected_cases(args))
    if args.command=="preflight":return preflight_report(args,config)
    if args.command=="recover":
        from .device import recover
        with RunLock():errors=recover(config)
        print(json.dumps({"errors":errors,"restored":not errors},ensure_ascii=False))
        return 1 if errors else 0
    if args.command == "cases":
        print(json.dumps([asdict(c) for c in CASES], ensure_ascii=False))
        return 0
    if args.command == "devices":
        print(json.dumps({"devices": list_devices(config)}, ensure_ascii=False), flush=True)
        return 0
    if args.command == "doctor":
        reporter = Reporter(config, args.output)
        def connected():
            devices = list_devices(config)
            if not any(d["state"] == "device" for d in devices):
                raise Blocked("Chưa có máy được ADB cấp quyền và sẵn sàng.")
            return devices
        def driver_version():
            version = json.loads((ROOT / ".runtime/appium/node_modules/appium-uiautomator2-driver/package.json").read_text())["version"]
            if version != "8.6.0":
                raise Blocked("Cần UiAutomator2 8.6.0.")
            return version
        def tool_exists(name, default):
            path = Path(config.get("tools", {}).get(name) or default)
            if not path.exists():
                raise Blocked(f"Không tìm thấy {name}; cập nhật đường dẫn trong Thiết lập.")
            return str(path)
        import shutil
        checks = (("ADB", lambda: find_adb(config)), ("Thiết bị", connected),
                  ("UiAutomator2", driver_version),
                  ("Appium", lambda: tool_exists("appium", ROOT / "node_modules/.bin/appium")),
                  ("Android SDK", lambda: tool_exists("android_home", os.environ.get("ANDROID_HOME") or Path.home() / "Library/Android/sdk")),
                  ("JDK", lambda: tool_exists("java_home", os.environ.get("JAVA_HOME") or "/Applications/Android Studio.app/Contents/jbr/Contents/Home")))
        for name, fn in checks:
            try:
                value = fn()
                reporter.results.append({"id": name, "status": "PASS", "message": reporter.redact(value), "seconds": 0})
                reporter.emit("setup", f"{name}: OK")
            except Exception as error:
                reporter.results.append({"id": name, "status": "ERROR", "message": reporter.redact(error), "seconds": 0})
        reporter.finish()
        return 0 if all(r["status"] == "PASS" for r in reporter.results) else 1
    return {"run": run, "build": build, "install": install}[args.command](args, config)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({"kind": "fatal", "message": type(error).__name__ + ": " + str(error)}, ensure_ascii=False), flush=True)
        sys.exit(1)
