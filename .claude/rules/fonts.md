# Font fallback cho hardsub (§13.2, §14)

`services/fonts.py::resolve(font_stack, fonts_dir)` là nơi DUY NHẤT quyết
định family/font file dùng cho một locale — `workers/render/stage.py` (burn
thật) và `workers/qc/stage.py` (đo glyph coverage) đều gọi CHUNG hàm này.
Đừng để hai chỗ tự suy luận riêng — lệch nhau nghĩa là QC PASS trên bộ font
khác với bộ font thật sự lên hình.

## Vì sao phải bundle font thay vì để libass tự lo

libass/fontconfig (`ffmpeg-full`, xem environment.md) tự tìm được fallback
qua font HỆ THỐNG khi thiếu glyph — đã kiểm chứng thủ công: JA/AR render đúng
trên macOS dev nhờ Hiragino Sans/Geeza Pro có sẵn, dù không truyền
`fontsdir`/`force_style` nào. Nhưng đây là hành vi **không ổn định giữa các
máy**: một server không có các font hệ thống tương đương sẽ ra ô vuông đúng
như §13.2 cảnh báo, và visual style (họ font) sẽ khác nhau tuỳ máy chạy render
dù cùng một locale. Bundle 3 font Noto (`apps/api/assets/fonts/`, xem README
ở đó về nguồn/license/cách tạo) để hành vi giống nhau trên mọi máy.

## Không chặn pipeline khi thiếu font bundle

`resolve()` trả `primary_family=""` (rỗng) nếu `font_stack` rỗng hoặc không
family nào trong stack có file thật trong `fonts_dir` — `render` khi đó bỏ
qua `fontsdir`/`force_style`, để libass tự chọn như hành vi TRƯỚC khi có tính
năng này. Cùng nguyên tắc "bỏ qua, không chặn" mà `diarize`/`compose` đã áp
dụng (xem diarization.md, compose.md) — thiếu asset không phải lý do chặn cả
job.

## QC font_coverage là FAIL, không WARN

Khác với `cue_cps` (WARN có chủ ý — xem subtitle.md), thiếu glyph luôn là
FAIL: không có mức "chấp nhận được" của ô vuông hiện trên hình. Đo THẬT bằng
bảng `cmap` của font qua `fontTools` (`services/qc_media.py::missing_glyphs`),
không đoán bằng mắt — nhận `font_paths` rỗng thì coi MỌI ký tự (trừ khoảng
trắng/dấu câu ASCII cơ bản) là thiếu, nghiêng về phía phát hiện lỗi (§16).

## Thêm locale hệ chữ mới

Thêm locale dùng hệ chữ chưa có font (Hindi, Thái...): tải family Noto tương
ứng theo đúng quy trình trong `apps/api/assets/fonts/README.md` (bắt buộc
`fontTools.varLib.instancer --update-name-table` nếu font gốc là variable
font — thiếu cờ này family name sai, xem README), cập nhật
`manifest.json` VÀ `font_stack` của locale preset đó. Thiếu một trong hai thì
`resolve()` không tìm thấy family, coi như chưa cấu hình (không lỗi, nhưng
cũng không có tác dụng gì).
