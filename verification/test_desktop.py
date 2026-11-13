"""Kiểm chứng Desktop và worker giả, không chạy testcase trên điện thoại."""
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from desktop_app.window import MainWindow


@pytest.fixture(scope="module")
def qt():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qt):
    widget = MainWindow(auto_scan=False)
    yield widget
    widget.close()


def test_desktop_does_not_run_tests_on_start_and_prod_disables_run(window):
    assert window.worker is None and window.scanner is None
    assert window.checks[0].isChecked()
    assert not any(c.isChecked() for c in window.checks[1:])
    assert window.run_button.isEnabled()
    window.environment.setCurrentIndex(1)
    assert not window.run_button.isEnabled()


def test_stop_writes_control_file_without_killing_unrelated_process(window, tmp_path):
    window.stop_file = tmp_path / "stop"
    window.stop()
    assert window.stop_file.is_file()
    assert "cleanup" in window.status.text()


def test_desktop_streams_scripted_worker_events(window, qt, tmp_path):
    report = tmp_path / "report.html"
    report.write_text("<html>fake desktop transport verification</html>")
    events = [{"kind": "case_start", "case_id": "APP-OPEN", "message": "start"},
              {"kind": "case_result", "case_id": "APP-OPEN", "status": "BLOCKED", "message": "missing test fixture"},
              {"kind": "finished", "report": str(report), "message": "done"}]
    worker = QProcess(window)
    window.worker = worker
    window.total_cases = 1
    window.progress.setRange(0, 1)
    worker.readyReadStandardOutput.connect(window.read_worker)
    worker.finished.connect(window.job_finished)
    code = "import json; events=" + repr(events) + "; [print(json.dumps(e),flush=True) for e in events]"
    worker.start(sys.executable, ["-u", "-c", code])
    deadline = time.monotonic() + 8
    while worker.state() != QProcess.ProcessState.NotRunning and time.monotonic() < deadline:
        qt.processEvents()
        time.sleep(0.01)
    qt.processEvents()
    assert worker.state() == QProcess.ProcessState.NotRunning
    assert window.table.item(0, 3).text() == "BLOCKED"
    assert "missing test fixture" in window.log.toPlainText()
    assert window.report_button.isEnabled()
    assert window.progress.value() == 1


def test_pair_selection_never_checks_c_cases_and_can_run_pair_chat(window):
    from tammi_runner.cases import DISPLAY_CASES
    window.select_scope('pair')
    selected={case.id for case,check in zip(DISPLAY_CASES,window.checks) if check.isChecked()}
    assert 'CHAT-TEXT-PAIR' in selected and 'CALL-012-CALLER_BACKGROUND' in selected
    assert not selected.intersection(case.id for case in DISPLAY_CASES if 'C' in case.roles or 'account:C' in case.requirements)
    assert window.worker is None


def test_desktop_groups_variants_by_excel_row(window):
    ids=[window.table.item(row,1).text().splitlines()[0] for row in range(window.table.rowCount())]
    assert ids[:4]==['APP-OPEN','AUTH-LOGIN','AUTH-LOGIN-B','CHAT-OPEN-PEER']
    assert ids.index('CHAT-026-FUNCTIONAL') < ids.index('CHAT-027-SLEEP')
    normal=ids.index('CALL-006-NORMAL')
    assert ids[normal+1:normal+3]==['CALL-006-ANDROID_SIGNALS','CALL-007-SILENT']
    assert ids[-1]=='VIDEO-FILE-OVER-100MB'


def test_resume_button_skips_pass_and_displays_retained_result(window,monkeypatch):
    from unittest.mock import Mock
    start=Mock();monkeypatch.setattr(window,'start_job',start)
    window.resume_button.click()
    start.assert_called_once_with('run',['--skip-passed','--skip-failed'])
    window.handle_event({'kind':'skipped_pass','case_id':'APP-OPEN','message':'Giữ nguyên PASS'})
    assert window.table.item(0,3).text()=='PASS (giữ nguyên)'
    window.environment.setCurrentIndex(1)
    assert not window.resume_button.isEnabled()


def test_skipped_failure_keeps_history_without_marking_pass(window):
    window.handle_event({'kind':'skipped_history','case_id':'APP-OPEN','message':'Giữ kết quả cũ'})
    assert window.table.item(0,3).text()=='Giữ kết quả cũ'


def test_lab_ui_explains_missing_hardware_without_product_pass(window):
    window.show_lab_readiness({'cases':[{'id':'CALL-003-OFFLINE','name':'Nhạc chờ','status':'BLOCKED','detail':'Thiếu nguồn thu A','needs':'Mic/USB audio riêng máy A'}], 'probes':[{'name':'ringback','status':'UNVERIFIED','detail':'Chưa kiểm tra nguồn thu','needs':'Mic A'}],'ready':0,'blocked':1,'skipped':0})
    assert window.tabs.currentWidget()==window.lab_tab
    assert window.lab_table.rowCount()==2
    assert window.lab_table.item(0,2).text()=='Thiếu điều kiện'
    assert 'Mic/USB audio' in window.lab_table.item(0,4).text()
    assert not window.lab_ready
    assert window.table.item(0,3).text()=='Chưa chạy'


def test_blocked_lab_check_does_not_start_pending_run(window,monkeypatch):
    from unittest.mock import Mock
    start=Mock();monkeypatch.setattr(window,'start_job',start)
    window.worker=QProcess(window)
    window.active_command='lab-check';window.pending_run=['--skip-passed','--skip-failed']
    window.job_finished(2)
    start.assert_not_called()
    assert window.pending_run is None


def test_ready_lab_check_starts_original_run_with_history_filters(window,monkeypatch):
    from unittest.mock import Mock
    start=Mock();monkeypatch.setattr(window,'start_job',start)
    window.worker=QProcess(window)
    window.active_command='lab-check';window.pending_run=['--skip-passed','--skip-failed'];window.lab_ready=True
    window.job_finished(0)
    start.assert_called_once_with('run',['--skip-passed','--skip-failed'])


def test_stop_during_lab_check_never_starts_test_run(window,monkeypatch,tmp_path):
    from unittest.mock import Mock
    start=Mock();monkeypatch.setattr(window,'start_job',start)
    window.worker=QProcess(window);window.active_command='lab-check'
    window.pending_run=[];window.lab_ready=True;window.stop_file=tmp_path/'stop';window.stop_file.touch()
    window.job_finished(0)
    start.assert_not_called()
