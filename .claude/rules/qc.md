# QC (§15)

Ba lớp tách biệt, theo đúng mẫu "logic thuần tách khỏi I/O" của dự án (xem
[coding-style.md](coding-style.md)):
`workers/qc/checks.py` (luật quyết định, nhận số đã đo, không I/O) →
`services/qc_media.py` (đo thật: gọi ffmpeg `blackdetect`/`volumedetect`) →
`workers/qc/stage.py` (gom dữ liệu từ DB + hai lớp trên, ghi verdict).

Verdict tổng hợp: có FAIL → FAIL; không FAIL nhưng có WARN → WARN; còn lại →
PASS (`overall_verdict`). Một số vi phạm CỐ Ý chỉ là WARN chứ không FAIL — vd.
`cue_cps` vượt nhẹ, vì `workers/subtitle/splitter.py` đã cố ý chấp nhận vượt
CPS cho unit quá ngắn thay vì vỡ vụn cue (xem [subtitle.md](subtitle.md)); QC
không được mâu thuẫn với quyết định đó.

Khi thêm check mới: viết hàm thuần trong `checks.py` trước, test bằng số liệu
giả lập (không cần media thật), rồi mới nối vào `stage.py`. Việc ĐO (ffmpeg
thật) và việc QUYẾT ĐỊNH (ngưỡng nào là FAIL) phải tách bạch — trộn hai việc
vào một hàm thì không test được luật quyết định mà không tốn thời gian chạy
ffmpeg.

`check_font_coverage` là ngoại lệ về "đo": phép đo không gọi ffmpeg mà đọc
bảng `cmap` của font qua `fontTools` (`missing_glyphs`) — vẫn tách bạch đo/
quyết định đúng mẫu trên, chỉ khác công cụ đo. Font dùng để đo phải là ĐÚNG
font sẽ dùng để burn hardsub thật (`services/fonts.py`, dùng chung với
`render`) — xem [fonts.md](fonts.md).
