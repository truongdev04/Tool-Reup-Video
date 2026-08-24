# Quy ước khi viết code

- **Không hard-code** provider, voice, language, logo, subtitle style, ngưỡng.
  Tất cả nằm trong `config/presets/` hoặc `Settings`.
- **`NonRetryableError`** (`core/stage.py`) cho lỗi chạy lại bao nhiêu lần cũng
  vậy: thiếu file, sai cấu hình, thiếu stage phụ thuộc. Orchestrator dừng ngay
  thay vì đốt thêm hai lượt retry.
- **Stage phải idempotent**: chạy lại cùng input không tạo bản ghi trùng. Các
  stage ghi DB đều có `_clear_previous()` chạy trước khi ghi.
- **Filter graph** dựng bằng `FilterGraph` builder (`services/ffmpeg.py`), không
  nối chuỗi string — đây là nguồn bug khó debug nhất của loại tool này.
- **Module logic thuần tách khỏi stage.** `planner.py`, `fitter.py` không chạm
  DB/API nên test được đầy đủ mà không tốn tiền. Giữ mẫu đó cho module mới.
- **Test đặt tên bằng tiếng Việt mô tả hành vi**, và assert message giải thích
  *vì sao* điều đó quan trọng, không chỉ *cái gì* sai.
