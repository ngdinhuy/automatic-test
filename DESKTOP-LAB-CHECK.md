# Kiểm tra điều kiện test lab trên Desktop

1. Chọn A/B và các testcase ở tab **Chạy test**.
2. Bấm **Kiểm tra điều kiện test lab**. Tab **Điều kiện test lab** mở với kết quả từng case, adapter và thiết bị âm thanh Android đang nối.
3. Xem cột **Kết quả kiểm tra** và **Cần chuẩn bị**. Có thể ẩn các case giữ kết quả cũ.
4. Sau khi chuẩn bị thêm thiết bị/nguồn đo, bấm **Kiểm tra lại điều kiện đã chọn**. Dùng **Chạy tiếp · bỏ PASS/FAIL** để giữ mọi kết quả PASS/FAIL/ERROR hợp lệ trước đó.

Cả Run selected và Chạy tiếp đều tự kiểm tra lại điều kiện trước khi chạy. Nếu còn case thiếu điều kiện trong lựa chọn, lượt Run chưa bắt đầu; bỏ chọn case thiếu hoặc bổ sung điều kiện rồi kiểm tra lại. Kiểm tra lab không gửi tin, không thực hiện cuộc gọi và không cộng PASS sản phẩm. Có adapter và có kết nối chưa chứng minh đã truyền được âm thanh/hình ảnh; số đo sản phẩm được lấy trong run.

| Trạng thái | Ý nghĩa |
|---|---|
| Đủ điều kiện | Đủ điều kiện cấu hình/thiết bị để bắt đầu testcase. Chưa phải PASS. |
| Thiếu điều kiện / Chưa cấu hình | Thiếu máy, fixture, cấu hình hoặc adapter. |
| Chưa xác minh nguồn đo | Có command nhưng chưa xác minh được nguồn đo/thiết bị ngoài. |
| Có adapter · đo khi chạy | Adapter tích hợp tồn tại; số đo thật được lấy khi chạy testcase. |
| Đã đọc kết nối | AudioService vừa liệt kê thiết bị đang nối A/B; không lấy từ bảng volume hay log lịch sử. |
| Giữ lịch sử | Case được bỏ qua theo bộ lọc lịch sử; không chạy lại. |

Giả lập được GPS và đầu vào file âm thanh/video. Giả lập không thay nguồn thu để nghiệm thu loa/mic, rung, tai nghe, FPS bên nhận hay SIM hết quota. Các case đó cần thiết bị/nguồn đo thật.

## Adapter và healthcheck

`config/local/staging.json` giữ cấu hình riêng, đã Git ignore. Với probe ngoài, khai báo `lab.probes.<tên>.command` cho phép đo và `healthcheck_command` để kiểm tra nguồn đo trước Run. Cả hai là mảng argv, executable tuyệt đối, không chạy shell. Healthcheck nhận JSON stdin có `schema:1`, `challenge` mới, `phase:"check"`, tên probe, devices, tools và app_package. Chỉ trả `ready:true` khi các kiểm tra thiết bị/nguồn đo thực tế thành công; phải trả cùng schema/challenge và một danh sách `checks` không rỗng. Thiếu nguồn đo trả `ready:false` và `blocked` mô tả lý do. Không trả sẵn số đo hoặc ready cố định để vượt điều kiện.

Probe mới `scripts/probes/location_destination.py` có healthcheck Google Maps trên B và đo điểm đích được staging truyền sang Maps sau khi mở card vị trí mới. Runner dùng marker để phân biệt card mới, chỉ sử dụng GPS fixture và đối chiếu tọa độ A/B. Đã kiểm chứng healthcheck; hai case vị trí chưa PASS, xem kết quả thiết bị trong TESTLAB-STATUS.md.

```bash
cd automation-desktop
.venv/bin/python -m tammi_runner.cli lab-check --suite pair --skip-passed --skip-failed
```

Mỗi lần kiểm tra có `lab-readiness.json` và `lab-readiness.html` riêng. Dữ liệu này không nằm trong kết quả testcase sản phẩm. Khi đổi thiết bị hoặc cấu hình, kiểm tra lại; không dùng ảnh chụp/báo cáo điều kiện cũ làm bằng chứng máy còn sẵn sàng.

Kết nối tai nghe được đọc lại mỗi lần kiểm tra: hiển thị tên, A2DP/SCO, đầu vào micro và đầu ra theo máy A/B. Các case audio_routes kiểm tra đúng máy gọi, báo riêng thiếu dây/USB hoặc profile Bluetooth thoại. Chỉ có A2DP không được coi là đã đủ tai nghe thoại. Kết quả này chưa thay adapter đo âm thanh thực tế.
