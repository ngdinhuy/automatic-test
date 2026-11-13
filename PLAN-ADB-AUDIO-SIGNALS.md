# Plan kiểm tra tín hiệu chuông ADB — cập nhật 13/11/2026

Lượt thiết bị `20261113-111625-981832` xác nhận CALL-003-OFFLINE PASS partial với baseline trống, một player đúng UID không muted và hai mẫu liên tiếp sau kết thúc không còn player. CALL-004-RINGING thấy player đúng UID trong chuông. Sau thao tác nhận, OPPO gặp lỗi ZEGO Express `1002078`, nên case FAIL và thiếu mẫu sau khi kết nối. Player trên ROM OPPO không expose deviceId trong cả hai case. Lượt `20261113-112838-019955` xác nhận CALL-006-NORMAL PASS partial theo tín hiệu player mới trên Samsung.

Đã triển khai cho CALL-003-OFFLINE và CALL-004-RINGING, thay yêu cầu mic C bằng probe tín hiệu ADB.

1. Trước gọi: lấy UID chính xác, lưu dumpsys audio/audio_flinger/audio_policy; baseline phải không có player app đang started.
2. Trong chuông: yêu cầu player mới hoặc chuyển paused/stopped sang started đúng UID, usage RINGTONE/VOICE_COMMUNICATION/SIGNALLING. Không lấy player active từ baseline.
3. Kiểm tra mutedState; thiếu trường này thì BLOCKED. Stream muted hoặc mọi mức volume expose đều 0 thì FAIL. Lưu bảng volume và deviceId nếu có. Không suy route thực từ danh sách tai nghe kết nối; volume theo đúng route chưa liên kết được thì chỉ giữ evidence. Route/volume không expose được ghi unavailable, không bịa giá trị.
4. CALL-003 kết thúc gọi rồi kiểm tra player chuông dừng; CALL-004 nhận gọi rồi kiểm tra player chuông dừng, sau đó kết thúc cuộc gọi. Yêu cầu 2 snapshot liên tiếp player đã theo dõi không còn started. Không yêu cầu player thoại mới phải dừng khi vừa nhận cuộc gọi.
5. Lưu before/during/after, timestamp, UID, role, challenge, trạng thái và kết quả vào reports/<run>/ringback-<marker>/. Baseline gắn serial và hết hạn sau 180 giây.

PASS được ghi theo phạm vi tín hiệu, coverage partial; không đo RMS/SNR, không chứng minh nội dung âm hay loa vật lý. Thay assertion ringback_audio bằng ringback_signal_started + ringback_signal_stopped. Thiếu phase sau thì không thể ghi đủ assertion PASS.

## Đã làm

- Adapter scripts/probes/ringback_audio.py dùng ADB A/B; không dùng mic C/calibration.
- Parser tammi_runner/ringback_signals.py và kiểm thử player khác UID, player cũ, usage sai, muted/thiếu trạng thái, volume 0, player không dừng, đổi UID, evidence 3 pha.
- full_runner.py tích hợp vòng đời gọi; probes.py kiểm tra schema tín hiệu và phase after.
- Desktop lab dùng healthcheck/NEEDS mới; không yêu cầu nguồn thu mic cho ringback.

## Còn lại

- Chạy healthcheck và 2 case eligible trên thiết bị khi tiếp tục lượt chạy; chưa có kết quả thiết bị cho logic mới.
- Xác minh parser và field route/volume trên từng ROM. Nếu không đủ thông tin thì báo rõ giới hạn, không nâng thành kiểm chứng output vật lý.
- Nếu app dùng lại cùng player chuông làm thoại, after sẽ chưa đạt: cần bằng chứng chuyển nguồn/usage để hỗ trợ đúng, không bỏ assertion dừng.
- Các probe voice_playback/audio_duplex/incoming_alert khác chưa chuyển sang logic này; không bật hàng loạt hoặc coi hết BLOCKED.
- Giữ mọi lịch sử; chạy chọn lọc --skip-passed --skip-failed, không tự chạy lại PASS/FAIL cũ. Location vẫn chỉ prod.

Lệnh chọn lọc khi lab đủ điều kiện:

```bash
bash scripts/run.sh --suite all --case CALL-003-OFFLINE --case CALL-004-RINGING --skip-passed --skip-failed
```

## Kiểm tra triển khai

- Full verification: 157 passed (trước khi thêm integration test cuối).
- Chạy lại riêng test_ringback_signals.py sau khi thêm integration: 4 passed, gồm lưu đủ 3 pha, không dừng player thì FAIL và đổi UID thì BLOCKED.
- compileall thành công. Chưa chạy testcase sản phẩm trên thiết bị, không cộng thêm PASS nghiệp vụ.
- Đã cấu hình private staging ringback command + healthcheck_command bằng `scripts/configure-ringback-signals.py`. Máy khác có thể chạy lại script này; không chứa credentials trong script.
