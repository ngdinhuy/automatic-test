# Tammi Test Desktop

App Desktop điều khiển các script Python/Appium cố định. Không gọi AI/LLM lúc chạy test.

## Mở app trên máy hiện tại

Double-click `Tammi Test Desktop.app` hoặc `Launch.command` trong folder này.

1. Quét thiết bị, chọn máy A và máy B nếu có.
2. Mở Thiết lập để kiểm tra tài khoản staging, OTP và đường dẫn công cụ.
3. Chọn kịch bản rồi bấm **Run selected**. Mặc định chỉ chọn APP-OPEN, không tự chạy testcase khi mở app.
4. Xem log realtime hoặc mở report. **Stop** tạo yêu cầu dừng và chờ cleanup; lệnh Appium hiện tại có thể cần đến khoảng 70 giây để trả về khi thiết bị không phản hồi.

App tự tạo Appium Server local và session cần thiết cho lần chạy. Chỉ dọn tiến trình do chính runner tạo, không kill ADB hoặc Appium khác của người dùng.

## Script terminal

Chạy từ folder `automation-desktop`:

```bash
./scripts/doctor.sh
./scripts/run-all.sh  # Toàn bộ script hiện có; report đối chiếu đủ Excel
./scripts/run.sh --case APP-OPEN
./scripts/run.sh --case AUTH-LOGIN --case CHAT-OPEN-PEER --case CHAT-DRAFT
./scripts/run.sh --case CHAT-TEXT-PAIR
./scripts/run.sh --case CALL-RECALL-A --case CALL-RECALL-B
```

CLI đầy đủ: `.venv/bin/python -m tammi_runner.cli --help`. Các lệnh chạy test dùng cùng code với Desktop, không yêu cầu chat với AI.

Mã thoát: `0` mọi case PASS, `1` FAIL/ERROR hoặc lỗi cleanup, `2` có BLOCKED, `130` người dùng dừng. Chạy lại không ghi đè báo cáo cũ.

## Phạm vi hiện có

Có 112 script: 8 core, 100 biến thể chức năng theo Excel, 3 phép đo tín hiệu Android một phần và 1 case video nguồn >100 MB bổ sung. Trong đó 100 biến thể chức năng bám 73 nhóm Excel trong phạm vi. Có mã chưa đồng nghĩa đã nghiệm thu đủ: nhiều locator/điều kiện lab của luồng mới cần kiểm chứng trên máy. Xem [PLAN.md](PLAN.md), [VALIDATION.md](VALIDATION.md), [LAB.md](LAB.md).

Desktop có nút/tab [Điều kiện test lab](DESKTOP-LAB-CHECK.md), tự kiểm tra trước Run và giải thích thiết bị/nguồn đo còn thiếu. Desktop hỗ trợ A/B/C, chọn nhóm Core/Chat/Call, preflight và thiết lập JSON groups/fixtures/lab/limits. Mở lại Desktop nếu đang dùng bản cửa sổ cũ. Từng dòng Excel và biến thể nằm trong testcases/chat và testcases/call. Ba nhóm Call 33/38/39 loại trừ được giữ để đối chiếu, không được giả PASS.

```bash
./scripts/preflight.sh --all
./scripts/run.sh --suite core
./scripts/run.sh --source CHAT-SRC-015
./scripts/run.sh --suite chat
./scripts/run.sh --suite call
./scripts/recover.sh  # Khôi phục khi có device-restore journal
```

`--all` gồm các bài sleep 330 giây / giữ call 910 giây. Preflight READY chỉ là đủ điều kiện cấu hình; PASS cần hành động/assertion thật. Call có timer tiến chưa chứng minh chất lượng audio. Không test màu/font/layout. Nháp được bảo vệ bằng ownership journal, thay đổi mạng/chuông có journal khôi phục. Chỉ tin marker của chính run được sửa/thu hồi.

## Log và báo cáo

Mỗi run ở `reports/<run-id>/`: `events.jsonl`, `runner.log`, `appium.log`, `summary.json`, `junit.xml`, `report.html`, `source-coverage.json`; evidence screenshot/logcat sau khi xác minh tài khoản; hierarchy đã lọc thông tin có thể được lưu để debug màn hồ sơ, nhưng không lưu màn login/OTP.

OTP và số tài khoản được lọc trước khi ghi log; không thu screenshot/hierarchy màn login. Evidence có thể chứa dữ liệu hội thoại của tài khoản test, chỉ lưu local. Không gửi source hoặc credentials ra dịch vụ AI.

## Build / Install APK

Tab APK / Build có nút build host `../AppViettel`, arm8/full/debug theo staging hoặc prod. Build chỉ chạy khi bấm nút hoặc gọi script:

```bash
./scripts/build.sh --host /duong-dan/AppViettel --environment staging
./scripts/install.sh --apk /duong-dan/staging.apk --role A
```

Nút Install xác minh package bằng aapt rồi cài staging APK bằng `adb install -r -t`. Runner hiện không chạy test prod. Install staging đã PASS trên máy B bằng cùng APK từ máy A. Build chưa chạy thực tế; không đổi signing hoặc Gradle config.

## Setup lại / chuyển máy

Cần macOS 14+, Python 3.10+, Node tương thích Appium 3.2.2, JDK, Android SDK/platform-tools và quyền ADB.

```bash
PYTHON_BIN=/duong-dan/python3 ./scripts/setup.sh
./scripts/desktop.sh
```

Setup tạo venv, cài dependencies từ `requirements.lock`, Appium từ `package-lock.json`, driver UiAutomator2 8.6.0 vào `.runtime/appium`. Không đổi Appium global hoặc dependency Android.

App `.app` hiện là launcher local, dùng venv và source bên cạnh; cần giữ nó trong folder công cụ. Chưa phải bản standalone có thể copy riêng mỗi `.app` sang máy khác. Muốn chuyển máy, copy source/lockfile/workbook và setup lại, không copy venv hoặc node_modules giữa OS. Bản Windows đóng gói chưa được triển khai.

Repo này chứa công cụ kiểm thử độc lập. `config/examples` chứa cấu hình mẫu. Cấu hình lab thật lưu tại `config/local` với quyền file 0600. File Excel nguồn dùng riêng có thể đặt tại `sources/common-tc-call-chat.xlsx`. Catalog và testcase đã xuất có sẵn trong repo.

Adapter video/tín hiệu Android và lệnh chạy riêng: [MEASUREMENT-SETUP.md](MEASUREMENT-SETUP.md).

Các case đã gỡ điều kiện lab để chạy tiếp: `scripts/run-blocked-ready.sh` (hai bài gọi video dài, mỗi bài hơn 15 phút). Adapter CameraService chỉ xác minh trạng thái capture, không đo chất lượng video.


### Chạy tiếp, giữ nguyên PASS

Desktop: chọn các case rồi bấm **Chạy tiếp · bỏ PASS/FAIL**. CLI:

```sh
./scripts/run-two-devices.sh --skip-passed --skip-failed --case CALL-041-CAMERA_ON
```

`run-blocked-ready.sh` cũng bật `--skip-passed --skip-failed`. Case từng có FAIL/ERROR hợp lệ được bỏ qua khi có `--skip-failed`, kể cả lượt sau chuyển BLOCKED; kết quả cũ không đổi. Runner đọc report hoàn tất, bỏ case từng PASS và đủ assertion hiện tại, kể cả lượt sau có BLOCKED/ERROR, ghi sự kiện `skipped_pass` riêng, không tạo thêm kết quả PASS. Preflight READY, diagnostic và run CANCELLED không thay PASS. Case có assertion mới chưa chứng minh cần chạy lại; lệnh Run selected thông thường vẫn cho phép chủ động chạy lại.
