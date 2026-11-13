"""Giao diện Qt; mọi tác vụ dài chạy trong worker process."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea, QSplitter, QTabWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from tammi_runner.cases import DISPLAY_CASES, uses_only_pair
from tammi_runner.common import ROOT, DEFAULT_CONFIG, load_config, save_private_json

COLORS = {"PASS": "#0f7a52", "FAIL": "#c1233a", "ERROR": "#c1233a", "BLOCKED": "#a26708", "CANCELLED": "#667085", "READY": "#526174"}


def button(text, callback, primary=False):
    item = QPushButton(text)
    if primary:
        item.setProperty("primary", True)
    item.clicked.connect(callback)
    return item


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thiết lập staging")
        self.resize(730, 760)
        self.config = json.loads(json.dumps(config))
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setVerticalSpacing(12)
        self.fields = {}
        form.addRow(QLabel("Tài khoản chỉ lưu trong config/local, được Git ignore."))
        for role in ("A", "B", "C"):
            for key, title in (("phone", "Số điện thoại"), ("otp", "OTP")):
                field = QLineEdit(config["devices"][role].get("account", {}).get(key, ""))
                if key == "otp":
                    field.setEchoMode(QLineEdit.EchoMode.Password)
                form.addRow(f"{title} · {role}", field)
                self.fields[(role, key)] = field
            result = QLineEdit(config["devices"][role].get("search_result_xpath", ""))
            result.setPlaceholderText("Tùy chọn: XPath kết quả tìm đúng tài khoản nếu locator mặc định không phù hợp")
            form.addRow(f"Kết quả tìm · {role}", result)
            self.fields[(role, "search_result_xpath")] = result
        for key, title in (("adb", "ADB executable"), ("appium", "Appium executable"),
                           ("android_home", "Android SDK"), ("java_home", "Java home")):
            field = QLineEdit(config.get("tools", {}).get(key, ""))
            form.addRow(title, field)
            self.fields[("tools", key)] = field
        self.locators = QPlainTextEdit(json.dumps(config.get("locators", {}), ensure_ascii=False, indent=2))
        self.locators.setMinimumHeight(240)
        form.addRow(QLabel("Locator nâng cao (JSON/XPath). Locator call để trống sẽ báo BLOCKED."))
        form.addRow(self.locators)
        self.advanced = QPlainTextEdit(json.dumps({key:config.get(key,{}) for key in ("groups","fixtures","lab","limits")},ensure_ascii=False,indent=2))
        self.advanced.setMinimumHeight(220)
        form.addRow(QLabel("Điều kiện nâng cao: groups, fixtures, lab/probes, limits (JSON)"))
        form.addRow(self.advanced)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.save)
        controls.rejected.connect(self.reject)
        outer.addWidget(controls)

    def save(self):
        try:
            locators = json.loads(self.locators.toPlainText())
            if not isinstance(locators, dict) or any(v is not None and not isinstance(v, str) for v in locators.values()):
                raise ValueError("Locator phải là object với giá trị XPath dạng chuỗi hoặc null.")
            advanced=json.loads(self.advanced.toPlainText())
            if not isinstance(advanced,dict) or set(advanced)-{"groups","fixtures","lab","limits"} or any(not isinstance(value,dict) for value in advanced.values()):
                raise ValueError("Điều kiện nâng cao phải là object groups/fixtures/lab/limits.")
            self.config.update(advanced)
            for role in ("A", "B", "C"):
                for key in ("phone", "otp"):
                    self.config["devices"][role].setdefault("account", {})[key] = self.fields[(role, key)].text().strip()
                self.config["devices"][role]["search_result_xpath"] = self.fields[(role, "search_result_xpath")].text().strip()
            self.config["tools"] = {key: field.text().strip() for (group, key), field in self.fields.items()
                                    if group == "tools" and field.text().strip()}
            self.config["locators"] = locators
            save_private_json(DEFAULT_CONFIG, self.config)
            self.accept()
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Chưa lưu được", str(error))


class MainWindow(QMainWindow):
    def __init__(self, auto_scan=True):
        super().__init__()
        self.setWindowTitle("Tammi Test Desktop")
        self.resize(1320, 900)
        self.setMinimumSize(1040, 720)
        self.config = load_config()
        self.worker = None
        self.active_command = None
        self.pending_run = None
        self.checked_run = False
        self.lab_ready = False
        self.scanner = None
        self.buffer = ""
        self.last_report = None
        self.stop_file = None
        self.closing = False
        self.finished_cases = 0
        self.total_cases = 0
        self.devices = []
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(280)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(22, 28, 22, 24)
        brand = QLabel("tammi")
        brand.setObjectName("brand")
        side.addWidget(brand)
        subtitle = QLabel("TEST DESKTOP")
        subtitle.setObjectName("muted")
        side.addWidget(subtitle)
        side.addSpacing(32)
        side.addWidget(QLabel("MÔI TRƯỜNG"))
        self.environment = QComboBox()
        self.environment.addItems(["Staging", "Prod · chỉ build APK"])
        self.environment.currentIndexChanged.connect(self.refresh_state)
        side.addWidget(self.environment)
        side.addSpacing(20)
        side.addWidget(QLabel("THIẾT BỊ ANDROID"))
        self.device_a = QComboBox()
        self.device_b = QComboBox()
        self.device_c = QComboBox()
        for combo in (self.device_a, self.device_b, self.device_c):
            combo.addItem("Chưa chọn", "")
            combo.currentIndexChanged.connect(self.refresh_state)
        side.addWidget(QLabel("Máy A"))
        side.addWidget(self.device_a)
        side.addWidget(QLabel("Máy B · tùy case"))
        side.addWidget(self.device_b)
        side.addWidget(QLabel("Máy C · case gọi ba bên"))
        side.addWidget(self.device_c)
        self.scan_button = button("Quét thiết bị", self.scan_devices)
        side.addWidget(self.scan_button)
        self.device_status = QLabel("Chưa quét ADB")
        self.device_status.setWordWrap(True)
        self.device_status.setObjectName("muted")
        side.addWidget(self.device_status)
        side.addSpacing(18)
        self.settings_button = button("Thiết lập tài khoản / locator", self.settings)
        side.addWidget(self.settings_button)
        self.doctor_button = button("Kiểm tra setup", lambda: self.start_job("doctor"))
        side.addWidget(self.doctor_button)
        side.addStretch()
        help_text = QLabel("Kịch bản Python + Appium\nKhông có AI trong quá trình chạy test.\n\nMỗi run có log và báo cáo riêng.")
        help_text.setWordWrap(True)
        help_text.setObjectName("muted")
        side.addWidget(help_text)
        layout.addWidget(sidebar)
        main = QVBoxLayout()
        main.setContentsMargins(30, 26, 30, 22)
        main.setSpacing(14)
        layout.addLayout(main, 1)
        title = QLabel("Chạy test theo kịch bản")
        title.setObjectName("title")
        main.addWidget(title)
        self.status = QLabel("Sẵn sàng · chọn thiết bị và kịch bản để bắt đầu")
        self.status.setObjectName("muted")
        main.addWidget(self.status)
        tabs = QTabWidget()
        self.tabs = tabs
        tests_tab = QWidget()
        tests_layout = QVBoxLayout(tests_tab)
        tests_layout.setContentsMargins(0, 14, 0, 0)
        note = QLabel(f"{len(DISPLAY_CASES)} kịch bản. Có mã script chưa đồng nghĩa đã nghiệm thu trên máy.\nPreflight kiểm tra điều kiện; case thiếu máy / fixture / probe báo BLOCKED.")
        note.setWordWrap(True)
        tests_layout.addWidget(note)
        filters=QHBoxLayout()
        for title,scope in (("Chọn A/B","pair"),("Chọn core","core"),("Chọn Chat","CHAT"),("Chọn Call","CALL"),("Chọn tất cả","all"),("Bỏ chọn","none")):
            filters.addWidget(button(title,lambda checked=False,s=scope:self.select_scope(s)))
        tests_layout.addLayout(filters)
        self.table = QTableWidget(len(DISPLAY_CASES), 5)
        self.table.setHorizontalHeaderLabels(["Chọn", "Kịch bản", "Máy", "Kết quả", "Phạm vi"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.checks = []
        for row, case in enumerate(DISPLAY_CASES):
            check = QCheckBox()
            check.setChecked(case.id == "APP-OPEN")
            check.toggled.connect(self.refresh_state)
            self.checks.append(check)
            self.table.setCellWidget(row, 0, check)
            for column, text in ((1, case.id + "\n" + case.name), (2, "+".join(case.roles)),
                                 (3, "Chưa chạy"), (4, case.note)):
                self.table.setItem(row, column, QTableWidgetItem(text))
            self.table.setRowHeight(row, 75)
        tests_layout.addWidget(self.table)
        actions = QHBoxLayout()
        self.run_button = button("▶  Run selected", lambda: self.start_job("run"), True)
        self.resume_button = button("Chạy tiếp · bỏ PASS/FAIL", lambda: self.start_job("run",["--skip-passed","--skip-failed"]))
        self.preflight_button = button("Kiểm tra điều kiện test lab", lambda:self.start_job("lab-check"))
        actions.addWidget(self.preflight_button)
        self.stop_button = button("■  Stop", self.stop)
        self.stop_button.setEnabled(False)
        self.report_button = button("Mở report", self.open_report)
        self.report_button.setEnabled(False)
        actions.addWidget(self.run_button)
        actions.addWidget(self.resume_button)
        actions.addWidget(self.stop_button)
        actions.addStretch()
        actions.addWidget(self.report_button)
        tests_layout.addLayout(actions)
        tabs.addTab(tests_tab, "Chạy test")
        self.lab_tab = self.make_lab_tab()
        tabs.addTab(self.lab_tab, "Điều kiện test lab")
        tabs.addTab(self.catalog_tab(), "Danh mục Excel")
        tabs.addTab(self.build_tab(), "APK / Build")
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(tabs)
        logs = QWidget()
        log_layout = QVBoxLayout(logs)
        log_layout.setContentsMargins(0, 8, 0, 0)
        log_layout.addWidget(QLabel("LOG REALTIME · RUNNER & APPIUM"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(4000)
        self.log.setObjectName("console")
        log_layout.addWidget(self.log)
        splitter.addWidget(logs)
        splitter.setSizes([520, 230])
        main.addWidget(splitter, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        main.addWidget(self.progress)
        self.refresh_state()
        if auto_scan:
            QTimer.singleShot(200, self.scan_devices)

    def select_scope(self,scope):
        for case,check in zip(DISPLAY_CASES,self.checks):
            check.setChecked((scope=="pair" and uses_only_pair(case)) or scope=="all" or (scope=="core" and case.action!="suite") or (scope in ("CHAT","CALL") and case.action=="suite" and case.id.startswith(scope)))

    def catalog_tab(self):
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.addWidget(QLabel("Nguồn được giữ nguyên. Có script không đồng nghĩa đã bao phủ toàn bộ nhóm testcase."))
        catalog = json.loads((ROOT / "catalog/source-cases.json").read_text())
        table = QTableWidget(len(catalog["cases"]), 3)
        table.setHorizontalHeaderLabels(["ID nguồn", "Testcase", "Trạng thái"])
        table.verticalHeader().hide()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        linked = {source for case in DISPLAY_CASES for source in case.sources}
        for row, case in enumerate(catalog["cases"]):
            status = "Có script · chưa nghiệm thu đủ" if case["source_id"] in linked else "Chưa triển khai"
            if case.get("exclusion_reason"):
                status = "Ngoài phạm vi"
            elif case.get("spec_issues"):
                status = "Cần làm rõ đặc tả"
            for column, text in enumerate((case["source_id"], case.get("description") or case.get("expected") or "", status)):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                table.setItem(row, column, item)
        outer.addWidget(table)
        return widget

    def build_tab(self):
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(18, 24, 18, 24)
        self.host_path = QLineEdit(self.config.get("host_path", str(ROOT.parent.parent / "AppViettel")))
        form.addRow("Host Android", self.host_path)
        self.build_button = button("Build APK · arm8 / full / debug", self.build)
        form.addRow(self.build_button)
        help_text = QLabel("Build dùng Gradle wrapper của app host. Test runner hiện chỉ hỗ trợ staging.\nBuild chỉ chạy khi bạn bấm nút này; chưa được kiểm chứng bằng build thực tế.")
        help_text.setWordWrap(True)
        form.addRow(help_text)
        self.apk = QLineEdit(self.config.get("apk_path") or "")
        self.apk.setPlaceholderText("Chọn APK staging để cài vào máy A/B")
        form.addRow("APK", self.apk)
        self.choose_apk = button("Chọn APK…", self.browse_apk)
        form.addRow(self.choose_apk)
        self.install_button = button("Cài APK staging vào máy đã chọn", self.install)
        form.addRow(self.install_button)
        return widget

    def make_lab_tab(self):
        tab=QWidget();layout=QVBoxLayout(tab)
        self.lab_summary=QLabel("Chưa kiểm tra. Chọn testcase ở tab Chạy test, rồi kiểm tra điều kiện.")
        self.lab_summary.setWordWrap(True);layout.addWidget(self.lab_summary)
        self.lab_check_button=button("Kiểm tra lại điều kiện đã chọn",lambda:self.start_job("lab-check"))
        layout.addWidget(self.lab_check_button)
        self.hide_lab_history=QCheckBox("Ẩn các case giữ kết quả cũ")
        self.hide_lab_history.setChecked(True)
        self.hide_lab_history.toggled.connect(self.filter_lab_history)
        layout.addWidget(self.hide_lab_history)
        note=QLabel("Thiếu thiết bị, fixture hoặc nguồn đo: BLOCKED. Có command probe chưa có nghĩa đã đo thành công.\nRun tự kiểm tra lại điều kiện trước khi thực hiện testcase.")
        note.setWordWrap(True);layout.addWidget(note)
        self.lab_table=QTableWidget(0,5)
        self.lab_table.setHorizontalHeaderLabels(["Case / probe","Nội dung","Điều kiện","Kết quả kiểm tra","Cần chuẩn bị"])
        self.lab_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.lab_table.setWordWrap(True);self.lab_table.verticalHeader().hide()
        for column in range(5):self.lab_table.horizontalHeader().setSectionResizeMode(column,QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.lab_table)
        return tab

    def filter_lab_history(self):
        for row in range(self.lab_table.rowCount()):
            item=self.lab_table.item(row,2)
            self.lab_table.setRowHidden(row,self.hide_lab_history.isChecked() and item is not None and item.text()=="Giữ lịch sử")

    def show_lab_readiness(self,event):
        self.lab_ready=bool(event.get("cases")) and event.get("blocked")==0
        rows=[(r['id'],r['name'],r['status'],r['detail'],r.get('needs','')) for r in event.get('cases',[])]
        rows += [(r['name'],'Probe / nguồn đo',r['status'],r['detail'],r.get('needs','')) for r in event.get('probes',[])+event.get('hardware',[])]
        self.lab_table.setRowCount(len(rows))
        labels={'READY':'Đủ điều kiện','BLOCKED':'Thiếu điều kiện','MISSING':'Chưa cấu hình','UNVERIFIED':'Chưa xác minh nguồn đo','CONFIGURED':'Có adapter · đo khi chạy','SKIPPED':'Giữ lịch sử','OBSERVED':'Đã đọc kết nối'}
        for row,values in enumerate(rows):
            for column,value in enumerate(values):
                item=QTableWidgetItem(labels.get(value,value) if column==2 else str(value))
                item.setToolTip(str(value));self.lab_table.setItem(row,column,item)
            self.lab_table.item(row,2).setForeground(QColor('#0f7a52' if values[2]=='READY' else '#a26708' if values[2] in ('BLOCKED','MISSING','UNVERIFIED') else '#526174'))
        conditions={row['id']:row for row in event.get('cases',[])}
        for index,case in enumerate(DISPLAY_CASES):
            if case.id in conditions:
                entry=conditions[case.id]
                text={'READY':'Chưa chạy · đủ điều kiện','BLOCKED':'BLOCKED (điều kiện)','SKIPPED':'Giữ kết quả cũ'}[entry['status']]
                self.set_result(index,text,entry['detail'])
        self.lab_table.resizeRowsToContents()
        self.filter_lab_history()
        self.lab_summary.setText(f"Đủ điều kiện: {event.get('ready',0)} · Thiếu điều kiện: {event.get('blocked',0)} · Giữ lịch sử: {event.get('skipped',0)}. Đây chưa phải kết quả test.")
        self.tabs.setCurrentWidget(self.lab_tab)
        if event.get('report'):
            self.last_report=Path(event['report']);self.report_button.setEnabled(self.last_report.is_file())

    def refresh_state(self, *_):
        if not hasattr(self, "run_button"):
            return
        busy = self.worker is not None and self.worker.state() != QProcess.ProcessState.NotRunning
        scanning = self.scanner is not None and self.scanner.state() != QProcess.ProcessState.NotRunning
        self.run_button.setEnabled(not busy and not scanning and self.environment.currentIndex() == 0 and any(c.isChecked() for c in self.checks))
        self.resume_button.setEnabled(self.run_button.isEnabled())
        self.preflight_button.setEnabled(not busy and not scanning and self.environment.currentIndex()==0 and any(c.isChecked() for c in self.checks))
        if hasattr(self,"lab_check_button"):
            self.lab_check_button.setEnabled(self.preflight_button.isEnabled())
        self.stop_button.setEnabled(busy)
        for item in (self.environment, self.device_a, self.device_b, self.device_c, self.settings_button,
                     self.doctor_button, self.build_button, self.install_button,
                     self.choose_apk, self.host_path, self.apk):
            item.setEnabled(not busy and not scanning)
        self.scan_button.setEnabled(not busy and not scanning)
        for check in self.checks:
            check.setEnabled(not busy)

    def scan_devices(self):
        if self.scanner and self.scanner.state() != QProcess.ProcessState.NotRunning:
            return
        self.scanner = QProcess(self)
        self.scanner.setWorkingDirectory(str(ROOT))
        self.scanner.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.scanner.finished.connect(self.devices_ready)
        self.scanner.errorOccurred.connect(lambda _: self.scan_error())
        self.scanner.start(sys.executable, ["-m", "tammi_runner.cli", "devices"])
        self.device_status.setText("Đang quét ADB…")
        self.refresh_state()

    def scan_error(self):
        self.device_status.setText("Không chạy được ADB worker. Kiểm tra setup.")
        self.refresh_state()

    def devices_ready(self, *_):
        output = bytes(self.scanner.readAllStandardOutput()).decode("utf-8", errors="replace")
        try:
            result = json.loads(output.strip().splitlines()[-1])
            if "devices" not in result:
                raise ValueError(result.get("message", "Không đọc được danh sách ADB"))
            self.devices = result["devices"]
            self.config = load_config()
            for role, combo in (("A", self.device_a), ("B", self.device_b), ("C", self.device_c)):
                selected = combo.currentData() or self.config["devices"][role].get("udid")
                if selected not in {d["udid"] for d in self.devices}:
                    selected = self.config["devices"][role].get("udid")
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("Chưa chọn", "")
                for d in self.devices:
                    combo.addItem(f"{d['model']} · {d['udid']} · {d['state']}", d["udid"])
                index = combo.findData(selected)
                combo.setCurrentIndex(max(0, index))
                combo.blockSignals(False)
            ready = sum(d["state"] == "device" for d in self.devices)
            self.device_status.setText(f"{ready} máy sẵn sàng.\nMáy offline/unauthorized cần kiểm tra USB debugging.")
        except (ValueError, IndexError) as error:
            self.device_status.setText("Quét ADB thất bại. Xem log.")
            self.log.appendPlainText(str(error))
        self.refresh_state()

    def persist(self):
        self.config = load_config()
        self.config["devices"]["A"]["udid"] = self.device_a.currentData() or None
        self.config["devices"]["B"]["udid"] = self.device_b.currentData() or None
        self.config["devices"]["C"]["udid"] = self.device_c.currentData() or None
        self.config["host_path"] = self.host_path.text().strip()
        self.config["apk_path"] = self.apk.text().strip() or None
        save_private_json(DEFAULT_CONFIG, self.config)

    def settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.config = dialog.config
            self.lab_ready=False
            self.lab_summary.setText("Cấu hình đã đổi. Bấm kiểm tra lại điều kiện trước khi chạy.")

    def browse_apk(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn APK staging", str(ROOT), "Android APK (*.apk)")
        if path:
            self.apk.setText(path)

    def build(self):
        environment = "staging" if self.environment.currentIndex() == 0 else "prod"
        self.start_job("build", ["--host", self.host_path.text(), "--environment", environment])

    def install(self):
        if not self.apk.text().strip():
            QMessageBox.information(self, "Chưa chọn APK", "Chọn APK staging trước khi cài.")
            return
        roles = [role for role, combo in (("A", self.device_a), ("B", self.device_b), ("C", self.device_c)) if combo.currentData()]
        if not roles:
            QMessageBox.information(self, "Chưa chọn máy", "Chọn ít nhất máy A để cài APK.")
            return
        args = ["--apk", self.apk.text().strip()]
        for role in roles:
            args.extend(["--role", role])
        self.start_job("install", args)

    def start_job(self, command, extra=None):
        if self.worker and self.worker.state() != QProcess.ProcessState.NotRunning:
            return
        if command=="run" and not self.checked_run:
            self.pending_run=list(extra or [])
            command="lab-check"
        elif command!="run":
            self.pending_run=None
        self.active_command=command
        if command=="lab-check":
            self.lab_ready=False
            self.lab_summary.setText("Đang kiểm tra thiết bị, fixture, adapter và nguồn đo…")
        self.persist()
        selected = [case.id for case, check in zip(DISPLAY_CASES, self.checks) if check.isChecked()]
        if command in ("run","preflight","lab-check") and not selected:
            return
        self.stop_file = ROOT / ".runtime" / ("stop-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        self.stop_file.parent.mkdir(parents=True, exist_ok=True)
        args = ["-u", "-m", "tammi_runner.cli", command, "--stop-file", str(self.stop_file)]
        if command in ("run","preflight","lab-check"):
            for case_id in selected:
                args.extend(["--case", case_id])
            for row, case in enumerate(DISPLAY_CASES):
                if case.id in selected:
                    self.set_result(row, "Chờ chạy")
        args.extend(extra or [])
        self.worker = QProcess(self)
        self.worker.setWorkingDirectory(str(ROOT))
        self.worker.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.worker.readyReadStandardOutput.connect(self.read_worker)
        self.worker.finished.connect(self.job_finished)
        self.worker.errorOccurred.connect(self.job_error)
        self.buffer = ""
        self.finished_cases = 0
        self.last_report = None
        self.report_button.setEnabled(False)
        self.total_cases = len(selected) if command in ("run","preflight","lab-check") else 1
        self.progress.setRange(0, self.total_cases)
        self.progress.setValue(0)
        self.status.setText("Đang chạy " + command + "…")
        self.log.appendPlainText("\n—— " + command.upper() + " ——")
        self.worker.start(sys.executable, args)
        self.refresh_state()

    def read_worker(self):
        self.buffer += bytes(self.worker.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            try:
                event = json.loads(line)
                self.handle_event(event)
            except ValueError:
                self.log.appendPlainText(line)

    def handle_event(self, event):
        kind = event.get("kind", "log")
        self.log.appendPlainText(f"[{event.get('time', '')[11:19]}] {kind.upper()}  {event.get('message', '')}")
        if "report_directory" in event:
            self.last_report = Path(event["report_directory"]) / "report.html"
        if kind == "case_start":
            self.status.setText("Đang chạy · " + event.get("case_id", ""))
        if kind in ("case_result","skipped_pass","skipped_history"):
            self.finished_cases += 1
            self.progress.setValue(self.finished_cases)
            for row, case in enumerate(DISPLAY_CASES):
                if case.id == event.get("case_id"):
                    self.set_result(row, "PASS (giữ nguyên)" if kind=="skipped_pass" else "Giữ kết quả cũ" if kind=="skipped_history" else event.get("status", ""), event.get("message", ""))
        if kind == "lab_readiness":
            self.show_lab_readiness(event)
        if kind == "artifact":
            self.apk.setText(event["apk"])
        if kind == "finished":
            self.last_report = Path(event["report"])
            self.report_button.setEnabled(self.last_report.is_file())

    def set_result(self, row, text, detail=""):
        item = self.table.item(row, 3)
        item.setText(text)
        item.setForeground(QColor(COLORS.get(text, "#526174")))
        item.setToolTip(detail)

    def job_error(self, error):
        self.log.appendPlainText("Worker error: " + str(error))
        if error == QProcess.ProcessError.FailedToStart:
            self.status.setText("Không khởi chạy được worker")
            self.refresh_state()

    def job_finished(self, code, *_):
        self.read_worker()
        if self.buffer.strip():
            self.log.appendPlainText(self.buffer)
        if self.active_command=="lab-check" and self.stop_file and self.stop_file.exists():code=130
        if self.active_command=="lab-check" and self.pending_run is not None:
            pending,self.pending_run=self.pending_run,None
            stopped=self.stop_file and self.stop_file.exists()
            if code==0 and self.lab_ready and not self.closing and not stopped:
                if self.stop_file:self.stop_file.unlink(missing_ok=True)
                self.checked_run=True
                try:self.start_job("run",pending)
                finally:self.checked_run=False
                return
        if code == 0:
            self.status.setText("Hoàn tất · xem report để biết phạm vi đã kiểm tra")
        elif code == 2:
            self.status.setText("Có case BLOCKED · xem lý do trong log / report")
        elif code == 130:
            self.status.setText("Đã dừng và dọn tài nguyên")
        else:
            self.status.setText("Job chưa thành công · xem log / report")
        if self.last_report and self.last_report.is_file():
            self.report_button.setEnabled(True)
        if self.stop_file:
            self.stop_file.unlink(missing_ok=True)
        self.refresh_state()
        if self.closing:
            self.close()

    def stop(self):
        if self.stop_file:
            self.stop_file.touch()
            self.stop_button.setEnabled(False)
            self.status.setText("Đang dừng · chờ lệnh hiện tại kết thúc và cleanup…")

    def open_report(self):
        if self.last_report and self.last_report.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_report)))

    def closeEvent(self, event):
        if self.worker and self.worker.state() != QProcess.ProcessState.NotRunning:
            self.closing = True
            self.stop()
            event.ignore()
        elif self.scanner and self.scanner.state() != QProcess.ProcessState.NotRunning:
            self.scanner.kill()
            self.scanner.waitForFinished(1000)
            event.accept()
        else:
            event.accept()


STYLE = """
QWidget { font-family: 'Arial'; font-size: 13px; color: #172234; }
QMainWindow, QDialog { background: #f5f7fa; }
QFrame#sidebar { background: white; border-right: 1px solid #e1e6ef; }
QLabel#brand { color: #ec234a; font-size: 38px; font-weight: 700; }
QLabel#title { font-size: 26px; font-weight: 700; }
QLabel#muted { color: #687587; }
QPushButton { background: white; border: 1px solid #d6dfe9; border-radius: 7px; padding: 10px 12px; }
QPushButton:hover { background: #fceef2; border-color: #ed7c93; }
QPushButton[primary=true] { background: #e92349; color: white; border: 1px solid #e92349; font-weight: 700; }
QPushButton:disabled { background: #edf0f4; color: #9aa4b2; border-color: #e1e5eb; }
QComboBox, QLineEdit { background: white; border: 1px solid #d7dfe9; border-radius: 6px; padding: 9px; }
QTableWidget { background: white; border: 1px solid #e1e6ef; gridline-color: #edf0f5; }
QHeaderView::section { background: #edf1f6; padding: 10px; border: none; font-weight: 600; }
QPlainTextEdit { background: white; border: 1px solid #d6dfe9; border-radius: 6px; padding: 8px; }
QPlainTextEdit#console { background: #152032; color: #d7e3f3; font-family: 'Menlo'; font-size: 12px; }
QTabWidget::pane { border: 0; }
QTabBar::tab { padding: 11px 18px; background: #edf1f6; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { background: white; border-bottom-color: #e92349; }
QProgressBar { background: #e4eaf2; border: 0; border-radius: 4px; height: 8px; text-align: center; }
QProgressBar::chunk { background: #e92349; border-radius: 4px; }
"""


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Arial", 13))
    app.setApplicationName("Tammi Test Desktop")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
