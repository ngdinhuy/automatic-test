# Adapter và lệnh chạy đo

## Các adapter đã có

| Adapter | Nguồn đo | Kiểm tra thực hiện | Giới hạn |
|---|---|---|---|
| media_integrity (ảnh) | File thật ở A/B qua MediaStore/ADB | Giải mã, SHA256/pixel, nội dung ảnh nhận | Không test màu/font/layout |
| media_integrity → video_integrity | Video nguồn và video mới tải ở B | Giải mã hết video/audio, số frame, thời lượng, track audio, SHA256, so 5 frame theo thời gian | Không thay phép đo âm thanh loa hoặc chất lượng cuộc gọi |
| camera_capture | CameraService Active Camera Clients theo package và PID hiện tại | Xác minh cả hai camera active; sau thao tác tắt phải không còn active client; chỉ lấy danh sách live, loại CONNECT trong lịch sử | Không đo FPS, khuôn mặt hoặc hình bên nhận |
| android_signals | AudioPlaybackConfiguration và VibratorManager theo UID staging | Client phát đang active, rung được Android chấp nhận, chỉ lấy sự kiện mới sau snapshot | Không đổi trạng thái OS thành RMS, SNR hay độ rung vật lý; case có coverage partial |
| voice_playback_signal | AudioService trên máy B theo UID staging | Sau khi B nhận tin thoại mới, chụp baseline rồi xác minh một player media mới bắt đầu và dừng trong hai mẫu liên tiếp | Coverage partial. Chưa đo độ rõ hoặc độ đầy đủ của nội dung âm thanh |
| audio_duplex | AudioService trên A/B | Ghép UID, chủ audio mode và client thoại cùng Binder để đọc trạng thái thu/phát. Với case mất mạng, kiểm tra nhả audio mode sau kết thúc | Coverage partial. Chưa đo âm nghe được, SNR hoặc độ trễ |
| audio_routes | AudioService trên máy gọi | Xác minh route loa trong, loa ngoài, Bluetooth thoại, tai nghe dây/USB và mức volume của route dây | Cần cả Bluetooth thoại và tai nghe dây/USB hiện trong Android. Runner báo thời điểm rút/cắm lại tai nghe dây |
| notification_alert | Android NotificationManager và event log trên B | Ghép marker, notification key và thời điểm cập nhật của tin staging mới với cờ dispatch chuông và rung | Coverage partial. Cần log cùng key và thời điểm, chưa đo chuông/rung vật lý |

## Chạy lại

Từ folder automation-desktop, sau setup và cắm A/B:

```bash
.venv/bin/python scripts/import-video-fixture.py --role A --remote /sdcard/Movies/fixture-test.mp4
./scripts/run-media-lab.sh
```

Import chỉ copy file được chỉ định, không xóa/chỉnh file gốc. Fixture phải là video thật >100 MiB, decoder phải đọc hết. Video OPPO hiện dùng khoảng 128 MB, chưa đủ cho case Excel video sau nén >1000 MB. Không tự padding file hoặc thay ngưỡng Excel. File video riêng tư không nằm trong gói source; chuyển máy cần import lại/copy fixture và cấu hình đường dẫn.

## Kết quả và evidence

Report từng run lưu probe JSON, số đo, snapshot UID, state trước test, checksum và frame so sánh. File tải ở B chỉ được dọn sau khi đối chiếu khớp nguồn; không xóa file không xác minh được. Session A/B có keepalive khi chờ file lớn, thời gian chờ tối đa 15 phút và có log tiến trình.

Các phép đo nghe rõ hai chiều/độ trễ, rung vật lý, Bluetooth/tai nghe, quota SIM và web Meet vẫn cần nguồn đo/tài khoản/thiết bị phù hợp. Những case đầy đủ trong Excel tiếp tục BLOCKED khi chưa đo đủ, dù case Android signals riêng lẻ PASS.

Decoder dùng imageio-ffmpeg 0.6.0 và FFmpeg null output để giải mã toàn bộ, sau đó so frame mẫu. Tham khảo: https://github.com/imageio/imageio-ffmpeg và https://www.ffmpeg.org/ffmpeg.html.

## Các case BLOCKED đã có hướng chạy tiếp

`./scripts/run-blocked-ready.sh` chạy thông báo khi B đang mở Test refactor, rồi các bài video/Meet A/B camera bật/tắt, mỗi bài giữ thật 910 giây; bộ lọc bỏ mọi case đã PASS hoặc từng FAIL/ERROR. CameraService được kiểm tra định kỳ; hạ timeout màn hình xuống 30 giây và tắt luôn sáng khi cắm sạc bằng setting có journal, khôi phục khi kết thúc. Không tap màn hình trong cửa sổ đo; service call phải còn hoạt động, hai máy phải Awake và timer phải tiến ở cuối bài. Không thay phép đo chất lượng video bằng số camera client.

CHAT-019 dùng hội thoại riêng và Test refactor. Script lưu trạng thái/thứ tự ghim gốc, chỉ đổi khi chứng minh được khả năng khôi phục và khôi phục sau bài; không cần tạo nhóm mới hoặc dùng C. Thông báo khác hội thoại dùng Test refactor trên B và tin mới từ A; watcher B chạy ngay lúc A gửi để không bỏ lỡ banner ngắn.

Chẩn đoán nhanh riêng control camera off: `.venv/bin/python scripts/check-camera-off-controls.py`. Chẩn đoán không cộng PASS sản phẩm và không thay bài 910 giây. Trên Samsung, helper dùng bounds xác định qua Appium và ADB tap cho nền/camera để không bỏ lỡ control tự ẩn trong lúc UiAutomation chờ trả lệnh.

Chẩn đoán setup/kết thúc phòng mới: `.venv/bin/python scripts/check-meeting-controls.py`. Script chỉ mời B đã xác minh, không chạy lại bài 15 phút và không tạo kết quả PASS sản phẩm.
