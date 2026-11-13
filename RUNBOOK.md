# Chạy Appium lần sau

Desktop và CLI dùng cùng Python/Appium. Không cần AI trong lúc chạy test.

1. Cắm Android A/B, mở khóa và cấp USB debugging. Case Call 23–26 cần thêm máy/tài khoản C.
2. Mở `Tammi Test Desktop.app` hoặc `Launch.command`, quét rồi chọn đúng vai A/B/C.
3. Trong Thiết lập, kiểm tra tài khoản, OTP, locator và JSON `groups/fixtures/lab/limits`.
4. Chọn Core/Chat/Call hoặc từng case. Bấm **Kiểm tra điều kiện test lab**, xem tab điều kiện rồi chạy. Run tự kiểm tra lại trước khi bắt đầu. Dùng **Chạy tiếp · bỏ PASS/FAIL** để giữ kết quả cũ. Chi tiết: [DESKTOP-LAB-CHECK.md](DESKTOP-LAB-CHECK.md).
5. Xem log realtime và report. Stop chờ lệnh hiện tại trả về rồi dọn tài nguyên do run tạo.

Chạy từ folder `automation-desktop`:

```bash
./scripts/doctor.sh
.venv/bin/python scripts/setup-lab.py --group "Test refactor" --verify-group
./scripts/preflight.sh --all
./scripts/run.sh --suite core
./scripts/run-two-devices.sh
./scripts/run.sh --source CHAT-SRC-015
./scripts/run.sh --suite chat
./scripts/run.sh --suite call
./scripts/run-all.sh
```

Chọn **Chọn A/B** trên Desktop hoặc chạy `scripts/run-two-devices.sh` để loại mọi case cần thiết bị/tài khoản C. Khi máy C chưa sẵn sàng, chỉ dùng nhóm A/B; case thiếu điều kiện lab khác vẫn ghi BLOCKED.

Có 112 script: 8 core, 100 biến thể chức năng cho 73 nhóm nguồn, 3 case tín hiệu Android partial và 1 case video nguồn >100 MB bổ sung. Có mã chưa đồng nghĩa đã nghiệm thu trên thiết bị. Xem `VALIDATION.md` và `source-coverage.json` của từng run. Ba nhóm loại trừ vẫn giữ trong danh mục: Call 33 iOS-only, 38/39 viễn thông. Call 36/37 dùng Android–Android.

`--all` bao gồm các bài giữ cuộc gọi 910 giây và sleep 330 giây. Case thiếu điều kiện ghi BLOCKED trước hành động sản phẩm; không tự bỏ điều kiện để PASS. Chỉ chọn case cần thiết khi đang hiệu chỉnh. `testcases/chat/` và `testcases/call/` chứa từng dòng gốc + biến thể, có thể xuất lại bằng `.venv/bin/python scripts/export-cases.py`.

Một Appium Server local quản lý các session với UDID/systemPort khác nhau; runner tự mở/dừng server. Không cần tự mở hai server.

Chạy riêng nhóm khóa/sleep A/B đã cấu hình:

```bash
./scripts/run-two-devices.sh --case CALL-027-LOCKED_AUDIO --case CALL-027-LOCKED_VIDEO --case CALL-034-SLEEP
```

Case sleep giữ máy B 330 giây thật. Ngày 11/11/2026, A/B báo `secure=false`, nên dùng `lab.unsecured_devices=true`; runner hiện chưa có cơ chế nhập PIN bảo mật. Không cấu hình cờ này cho máy chưa đối chiếu điều kiện khóa.


Mỗi run lưu `reports/<id>/report.html`, `summary.json`, JUnit, JSONL, Appium log và evidence. READY là kiểm tra cấu hình, chưa phải PASS. SCRIPT_VARIANTS_PASS ở coverage chỉ có khi mọi biến thể chức năng của nhóm nguồn PASS đủ assertion trong cùng run. Không đánh giá màu/font/layout.

Nếu job bị ngắt khi đang đổi mạng/khóa máy, runner ghi lệnh khôi phục vào `.runtime/device-restore.json`. Cắm lại đúng máy rồi chạy:

```bash
./scripts/recover.sh
```

Không xóa journal để vượt preflight. Mạng/chuông được lưu trước khi đổi và khôi phục theo thứ tự ngược. Chỉ nháp có ownership journal được tự dọn. Không ghi đè nháp người dùng. Tin có marker APPIUM được giữ để đối chiếu; case sửa/xóa chỉ dùng tin do chính run tạo.

Tạo fixture ảnh PNG hợp lệ và rich text:

```bash
.venv/bin/python scripts/prepare-fixtures.py --large-image
```

Copy các mục cần dùng trong `fixtures/generated/manifest.json` vào `fixtures` ở Thiết lập. Video >1000 MiB phải là video giải mã được do bạn chuẩn bị; công cụ không tạo file giả. Các phép đo âm thanh/video/rung/nhận file cần adapter lab thực, xem `LAB.md`. Thiếu adapter ghi BLOCKED.

Repo này chứa source của công cụ kiểm thử. `.app` là launcher dùng source/venv bên cạnh; chưa phải gói standalone để copy riêng. Khi chuyển máy, copy source, lockfile, scripts, catalog/testcases; chạy setup lại, cấu hình tài khoản và tool paths trên máy mới. Không chia sẻ config/local, reports hoặc APK nội bộ nếu không cần thiết.

Chạy riêng các phép đo/video đã thêm: `./scripts/run-media-lab.sh`. Nguồn đo, cách import video OPPO và giới hạn: [MEASUREMENT-SETUP.md](MEASUREMENT-SETUP.md).


## Tiếp tục phần chưa hoàn tất

Chọn case trên Desktop rồi bấm **Chạy tiếp · bỏ PASS/FAIL**, hoặc dùng:

```sh
./scripts/run-two-devices.sh --skip-passed --skip-failed --case CALL-041-CAMERA_OFF
```

Bộ lọc giữ nguyên PASS đã đủ assertion, bỏ case từng FAIL/ERROR trong lịch sử hợp lệ và ghi sự kiện bỏ qua riêng. Kết quả không được tính lại thành PASS. BLOCKED chưa bắt đầu/hoàn tất hành trình vẫn có thể chạy khi điều kiện được bổ sung. `Run selected` là lệnh chạy chủ động, không áp dụng bộ lọc này.
