"""Cấu hình, sự kiện và báo cáo của bộ test."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/local/staging.json"


class Blocked(Exception):
    pass


class Cancelled(Exception):
    pass


def load_config(path=DEFAULT_CONFIG):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    config.setdefault("devices",{}).setdefault("C",{"udid":None,"system_port":8203,"account":{"phone":"","otp":""}})
    if config.get("environment") != "staging":
        raise Blocked("Runner hiện chỉ hỗ trợ tài khoản staging.")
    if config.get("app_package") != "com.viettel.appviettel.staging":
        raise Blocked("Package không phải app staging được phép test.")
    if config.get("platform", "Android") != "Android":
        raise Blocked("Chỉ hỗ trợ Android–Android.")
    return config


def find_adb(config):
    candidates = [config.get("tools", {}).get("adb"), shutil.which("adb")]
    sdk = config.get("tools", {}).get("android_home") or os.environ.get("ANDROID_HOME")
    if sdk:
        candidates.append(str(Path(sdk) / "platform-tools/adb"))
    candidates.append(str(Path.home() / "Library/Android/sdk/platform-tools/adb"))
    for path in candidates:
        if path and Path(path).is_file():
            return str(Path(path).resolve())
    raise Blocked("Không tìm thấy adb. Cấu hình Android SDK trong Thiết lập.")


def list_devices(config):
    result = subprocess.run([find_adb(config), "devices", "-l"], capture_output=True,
                            text=True, timeout=15, check=True)
    rows = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or line.startswith("*"):
            continue
        meta = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
        rows.append({"udid": parts[0], "state": parts[1], "model": meta.get("model", "Android")})
    return rows


def validate_devices(config, available, roles):
    states = {d["udid"]: d["state"] for d in available}
    ids = [config.get("devices", {}).get(r, {}).get("udid") for r in roles]
    if not all(ids):
        raise Blocked("Chưa chọn đủ thiết bị " + ", ".join(roles))
    if len(set(ids)) != len(ids):
        raise Blocked("Các vai A/B/C phải dùng thiết bị khác nhau.")
    for role, udid in zip(roles, ids):
        if states.get(udid) != "device":
            raise Blocked(f"Thiết bị {role} chưa kết nối hoặc chưa cấp quyền ADB.")
    ports = [config["devices"][r].get("system_port", 8201 + i) for i, r in enumerate(roles)]
    if len(set(ports)) != len(ports):
        raise Blocked("systemPort của các thiết bị phải khác nhau.")
    accounts = [config["devices"][r].get("account", {}).get("phone") for r in roles]
    if len(roles) > 1 and (not all(accounts) or len(set(accounts)) != len(accounts)):
        raise Blocked("Case nhiều máy cần các tài khoản staging khác nhau.")


def save_private_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    path.chmod(0o600)


class Reporter:
    def __init__(self, config, directory=None):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.directory = Path(directory or ROOT / "reports" / stamp).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.secrets = set()
        for device in config.get("devices", {}).values():
            for key in ("phone", "otp", "password"):
                value = device.get("account", {}).get(key)
                if value:
                    self.secrets.add(str(value))
                    if key == "phone" and value.startswith("0"):
                        self.secrets.add("84" + value[1:])
        self.lock = threading.Lock()
        self.results = []
        self.cleanup_errors = []

    def redact(self, value):
        text = str(value)
        for secret in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(secret, "[REDACTED]")
            if secret.isdigit() and len(secret) >= 10:
                pattern = r"(?<!\d)" + r"[\s.\-]*".join(secret) + r"(?!\d)"
                text = re.sub(pattern, "[REDACTED]", text)
        text = re.sub(r'"value"\s*:\s*\[[^\]]*\]', '"value":["REDACTED"]', text)
        text = re.sub(r'"keycode"\s*:\s*\d+', '"keycode":"REDACTED"', text)
        text = re.sub(r"(?i)(bearer\s+)[\w.\-]+", r"\1[REDACTED]", text)
        text = re.sub(r"\b(?:0\d{9}|84\d{9})\b", "[PHONE]", text)
        return text

    def sanitize(self, value):
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, list):
            return [self.sanitize(item) for item in value]
        if isinstance(value, dict):
            return {key: self.sanitize(item) for key, item in value.items()}
        return value

    def emit(self, kind, message="", **fields):
        item = {"time": datetime.now().astimezone().isoformat(), "kind": kind,
                "message": message, **fields}
        item = self.sanitize(item)
        line = json.dumps(item, ensure_ascii=False)
        with self.lock:
            with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
            if kind == "appium":
                with (self.directory / "appium.log").open("a", encoding="utf-8") as stream:
                    stream.write(item["message"] + "\n")
            else:
                with (self.directory / "runner.log").open("a", encoding="utf-8") as stream:
                    stream.write(line + "\n")
            print(line, flush=True)

    def finish(self):
        self.results = self.sanitize(self.results)
        self.cleanup_errors = self.sanitize(self.cleanup_errors)
        data = {"results": self.results, "cleanup_errors": self.cleanup_errors,
                "report_directory": str(self.directory)}
        save_private_json(self.directory / "summary.json", data)
        suite = ET.Element("testsuite", name="Tammi Appium", tests=str(len(self.results)),
                           failures=str(sum(r["status"] == "FAIL" for r in self.results)),
                           errors=str(sum(r["status"] == "ERROR" for r in self.results)),
                           skipped=str(sum(r["status"] in ("BLOCKED", "CANCELLED", "READY") for r in self.results)))
        for result in self.results:
            case = ET.SubElement(suite, "testcase", name=result["id"], classname="tammi.functional",
                                 time=str(result.get("seconds", 0)))
            status = result["status"]
            tag = "failure" if status == "FAIL" else "error" if status == "ERROR" else "skipped"
            if status != "PASS":
                ET.SubElement(case, tag, message=result["message"]).text = result["message"]
        ET.ElementTree(suite).write(self.directory / "junit.xml", encoding="utf-8", xml_declaration=True)
        rows = "".join("<tr><td>" + "</td><td>".join(html.escape(str(r.get(k, "")))
                       for k in ("id", "status", "seconds", "message")) + "</td></tr>" for r in self.results)
        content = ("<!doctype html><meta charset=utf-8><title>Tammi test report</title>"
                   "<style>body{font:15px system-ui;margin:36px;color:#172234}table{border-collapse:collapse;width:100%}"
                   "td,th{border:1px solid #d9e0e8;text-align:left;padding:12px}th{background:#f2f5f9}</style>"
                   "<h1>Tammi · Kết quả Appium</h1><p>Kết quả được tạo bởi script xác định sẵn.</p>"
                   "<table><tr><th>Case</th><th>Kết quả</th><th>Giây</th><th>Chi tiết</th></tr>" + rows + "</table>"
                   "<h2>Cleanup</h2><pre>" + html.escape("\n".join(self.cleanup_errors) or "Không có lỗi") + "</pre>"
                   "<p>Evidence debug (nếu có) nằm trong thư mục evidence. Log: runner.log và appium.log.</p>")
        (self.directory / "report.html").write_text(content, encoding="utf-8")
        append_probe_summary(self.directory)
        self.emit("finished", "Đã ghi báo cáo", report=str(self.directory / "report.html"))


def python_executable():
    return sys.executable


def sha256_file(path):
    """Đọc theo block để dùng được Python 3.10 và file lớn."""
    digest=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest()


def append_probe_summary(directory):
    """Hiện số đo của từng case từ event đã lọc dữ liệu nhạy cảm; không đổi kết quả testcase."""
    directory=Path(directory);report=directory/'report.html';events=directory/'events.jsonl'
    if not report.exists() or not events.exists():return
    content=report.read_text()
    if 'id="probe-measurements"' in content:return
    rows=[];case=''
    for line in events.read_text().splitlines():
        try:event=json.loads(line)
        except ValueError:continue
        if event.get('kind')=='case_start':case=event.get('case_id','')
        values=event.get('measurements')
        if event.get('kind')!='assertion' or not isinstance(values,dict) or not values:continue
        fields=(case,event.get('message',''),json.dumps(values,ensure_ascii=False))
        rows.append('<tr>'+''.join('<td>'+html.escape(str(value))+'</td>' for value in fields)+'</tr>')
    if not rows:return
    section=('<h2 id="probe-measurements">Số đo adapter</h2>'
             '<p>Android signals chỉ đo dispatch hệ thống; chưa đo RMS/SNR hoặc rung vật lý. '
             'Số đo ở case FAIL không làm case thành PASS.</p>'
             '<table><tr><th>Case</th><th>Adapter / phase</th><th>Số đo</th></tr>'+''.join(rows)+'</table>'
             '<p><a href="events.jsonl">Runner events</a> · <a href="appium.log">Appium log</a></p>')
    report.write_text(content+section)
