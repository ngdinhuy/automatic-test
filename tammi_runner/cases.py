"""Định nghĩa các kịch bản chức năng có thể chạy bằng script."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    id: str
    name: str
    roles: tuple[str, ...]
    action: str
    sources: tuple[str, ...] = ()
    note: str = "Chưa kiểm chứng trên thiết bị bằng script."
    params: dict = field(default_factory=dict)
    requirements: tuple[str, ...] = ()
    obligations: tuple[str, ...] = ()
    coverage_level: str = "partial"


CASES = [
    Case("APP-OPEN", "Mở đúng app staging", ("A",), "launch", note="Kiểm tra setup, không tính coverage testcase nghiệp vụ."),
    Case("AUTH-LOGIN", "Đăng nhập OTP, xác minh máy A", ("A",), "login",
         note="Chuyển sang tài khoản staging đã cấu hình nếu cần, không xóa dữ liệu app."),
    Case("AUTH-LOGIN-B", "Đăng nhập OTP, xác minh máy B", ("B",), "login_b",
         note="Chuẩn bị tài khoản B độc lập với máy A."),
    Case("CHAT-OPEN-PEER", "Tìm và mở hội thoại tài khoản B", ("A",), "open_peer", note="Không gửi tin; cần B là tài khoản Tammi hợp lệ."),
    Case("CHAT-DRAFT", "Lưu và khôi phục tin nháp", ("A",), "draft", ("CHAT-SRC-015",),
         "Bao phủ phần lưu/khôi phục draft; chưa kiểm tra gửi tin làm hết draft."),
    Case("CHAT-TEXT-PAIR", "Gửi text hai chiều A ↔ B", ("A", "B"), "text_pair", ("CHAT-SRC-003",),
         "Text thường, assert bên nhận; chưa bao phủ max ký tự và font scale."),
    Case("CALL-RECALL-A", "A gọi B, B từ chối rồi gọi lại A", ("A", "B"), "recall_a", ("CALL-SRC-036",),
         "Cần locator call trong Thiết lập; kiểm tra lifecycle, chưa đo chất lượng âm thanh."),
    Case("CALL-RECALL-B", "B gọi A, A từ chối rồi gọi lại B", ("A", "B"), "recall_b", ("CALL-SRC-037",),
         "Cần locator call trong Thiết lập; chuyển từ iOS–Android sang Android–Android."),
]

from .suite_specs import full_suite
CASES.extend(Case(**spec) for spec in full_suite())
CASES.append(Case('VIDEO-FILE-OVER-100MB','Gửi video nguồn >100 MB, tải và giải mã đầy đủ ở B',('A','B'),'suite',
                  note='Case bổ sung theo yêu cầu người dùng; chọn video từ Gallery, không thay case quay camera hoặc video sau nén >1000 MB.',
                  params={'flow':'media','media':'gallery_video'},requirements=('fixture:gallery_video','probe:media_integrity'),
                  obligations=('sent_media','receiver_open','media_metadata'),coverage_level='functional'))
for row,mode in ((5,'vibrate'),(6,'normal'),(7,'silent')):
    CASES.append(Case(f'CALL-{row:03}-ANDROID_SIGNALS',f'Đo tín hiệu Android khi B {mode}',('A','B'),'suite',(f'CALL-SRC-{row:03}',),
                      'Đo dispatch rung/phát âm thanh theo UID trong 5 giây; chưa nghiệm thu âm thanh/rung vật lý hoặc chất lượng nghe.',
                      params={'flow':'call','variant':'ringer_system','ringer':mode},requirements=('probe:android_signals',),
                      obligations=('incoming','system_alert_policy'),coverage_level='partial'))


def _display_order(case):
    if not case.sources:
        return (0 if case.action != "suite" else 3, 0, 0)
    group, _, row = case.sources[0].split("-")
    # Đặt script chính trước biến thể bổ sung của cùng dòng Excel.
    supplemental = not case.id.split("-")[1].isdigit() or case.id.endswith("-ANDROID_SIGNALS")
    return ({"CHAT": 1, "CALL": 2}[group], int(row), supplemental)


DISPLAY_CASES = tuple(sorted(CASES, key=_display_order))


def select_cases(ids):
    indexed = {c.id: c for c in CASES}
    unknown = set(ids) - set(indexed)
    if unknown:
        raise ValueError("Case chưa có script: " + ", ".join(sorted(unknown)))
    return [indexed[c] for c in dict.fromkeys(ids)]


def uses_only_pair(case):
    # Loại cả case cần tài khoản C dù chưa đòi cắm thiết bị C (ví dụ tạo nhóm).
    return set(case.roles) <= {"A", "B"} and not any(req in ("account:C", "member_name:C") for req in case.requirements)
