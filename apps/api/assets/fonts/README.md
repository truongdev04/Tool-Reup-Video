# Font bundle cho hardsub (§13.2, §14)

Nhúng sẵn 3 font Noto để render subtitle KHÔNG phụ thuộc font hệ thống —
libass/fontconfig vẫn tự tìm được fallback qua font cài sẵn của máy (đã kiểm
chứng: JA/AR render đúng trên macOS nhờ Hiragino/Geeza Pro có sẵn), nhưng đó
là hành vi không ổn định giữa các máy: một server Linux không có các font hệ
thống tương đương sẽ ra ô vuông đúng như §13.2 cảnh báo. Bundle font để hành
vi giống nhau trên mọi máy chạy pipeline. Cách nối vào filter `subtitles` xem
`services/fonts.py` và `.claude/rules/subtitle.md`.

`manifest.json` map family name (đúng tên khai trong `font_stack` của
`config/presets/locale/*.json`) sang file đã bundle.

## Nguồn & giấy phép

Cả 3 file lấy từ [google/fonts](https://github.com/google/fonts) (nhánh
`main`, thư mục `ofl/`), giấy phép **SIL Open Font License 1.1** (`OFL.txt`)
— tự do nhúng/phân phối lại.

File gốc là **variable font** (nhiều trục weight/width trong 1 file, vài MB).
Đã dùng `fontTools.varLib.instancer` để "đóng băng" về đúng một static
instance Regular (`wght=400`, `wdth=100` nếu có trục đó), giảm kích thước và
tránh mọi ứng xử khó đoán của variable font trên các bản libass cũ:

```bash
python -m fontTools.varLib.instancer "NotoSans[wdth,wght].ttf" wght=400 wdth=100 \
    --update-name-table -o NotoSans-Regular.ttf
```

`--update-name-table` là bắt buộc — thiếu cờ này, tên family trong font vẫn
giữ theo default instance GỐC của trục variable (với `NotoSansJP[wght].ttf`,
default là `wght=100` = "Thin", không phải "Regular") thay vì theo toạ độ vừa
pin — libass sẽ không khớp được `force_style=FontName=...` với family thật.

Chỉ bundle 3 family đủ cho 5 locale hiện có (`en-US`, `es-ES`, `vi-VN` dùng
chung "Noto Sans"; `ja-JP` dùng "Noto Sans JP"; `ar-SA` dùng "Noto Sans
Arabic"). Thêm locale hệ chữ mới (Hindi, Thái...) thì tải thêm family tương
ứng theo đúng quy trình trên, cập nhật `manifest.json` và `font_stack` của
locale preset đó.
