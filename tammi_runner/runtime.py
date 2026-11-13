"""Quản lý tiến trình Appium và tài nguyên của một lần chạy."""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from .common import ROOT, Blocked, Cancelled


class RunLock:
    def __enter__(self):
        self.path = ROOT / ".runtime/run.lock"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w") as stream:
                    stream.write(str(os.getpid()))
                return self
            except FileExistsError:
                try:
                    pid = int(self.path.read_text())
                    os.kill(pid, 0)
                except ProcessLookupError:
                    self.path.unlink(missing_ok=True)
                    continue
                except (ValueError, PermissionError):
                    pass
                raise Blocked("Có một job đang chạy hoặc lock chưa được dọn. Kiểm tra .runtime/run.lock.")
        raise Blocked("Không lấy được run lock.")

    def __exit__(self, *_):
        self.path.unlink(missing_ok=True)


class ManagedAppium:
    def __init__(self, config, reporter, check_cancel):
        self.config, self.reporter, self.check_cancel = config, reporter, check_cancel
        self.process = None
        self.reader = None
        self.url = None

    def start(self):
        tools = self.config.get("tools", {})
        local_binary = ROOT / "node_modules/.bin/appium"
        appium = tools.get("appium") or (str(local_binary) if local_binary.is_file() else shutil.which("appium"))
        if not appium:
            raise Blocked("Chưa có Appium. Chạy scripts/setup.sh trước.")
        env = os.environ.copy()
        env["APPIUM_HOME"] = str(ROOT / ".runtime/appium")
        sdk = tools.get("android_home") or env.get("ANDROID_HOME")
        if not sdk:
            sdk = str(Path.home() / "Library/Android/sdk")
        env["ANDROID_HOME"] = sdk
        java = tools.get("java_home") or env.get("JAVA_HOME")
        studio_jdk = Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home")
        if not java and studio_jdk.exists():
            java = str(studio_jdk)
        if java:
            env["JAVA_HOME"] = java
        driver_manifest = ROOT / ".runtime/appium/node_modules/appium-uiautomator2-driver/package.json"
        if not driver_manifest.exists():
            raise Blocked("Chưa cài UiAutomator2 trong runtime local. Chạy scripts/setup.sh.")
        driver = json.loads(driver_manifest.read_text())
        if driver["version"] != "8.6.0":
            raise Blocked("Runner yêu cầu UiAutomator2 8.6.0 đã khóa phiên bản.")
        version = subprocess.run([appium, "--version"], env=env, text=True, capture_output=True,
                                 timeout=20, check=True).stdout.strip()
        if version != "3.2.2":
            raise Blocked("Runner yêu cầu Appium 3.2.2; cập nhật đường dẫn Appium trong Thiết lập.")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        self.process = subprocess.Popen([appium, "--address", "127.0.0.1", "--port", str(port),
                                         "--log-level", "info", "--log-no-colors"], env=env, cwd=ROOT,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                        start_new_session=os.name != "nt")
        def read():
            for line in self.process.stdout:
                self.reporter.emit("appium", line.rstrip())
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            self.check_cancel()
            if self.process.poll() is not None:
                raise Blocked("Appium Server không khởi động được; xem appium.log.")
            try:
                with urllib.request.urlopen(self.url + "/status", timeout=1) as response:
                    if json.load(response)["value"].get("ready"):
                        self.reporter.emit("setup", "Appium Server đã sẵn sàng")
                        return self.url
            except (OSError, ValueError, KeyError):
                time.sleep(0.2)
        raise Blocked("Appium Server không sẵn sàng trong 45 giây.")

    def stop(self):
        if self.process and self.process.poll() is None:
            if os.name != "nt":
                os.killpg(self.process.pid, signal.SIGTERM)
            else:
                self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    os.killpg(self.process.pid, signal.SIGKILL)
                else:
                    self.process.kill()
                self.process.wait(timeout=5)
        if self.reader:
            self.reader.join(timeout=2)


def check_cancel(stop_file):
    if stop_file and Path(stop_file).exists():
        raise Cancelled("Đã dừng theo yêu cầu.")
