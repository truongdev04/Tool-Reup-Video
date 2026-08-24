# Môi trường & lệnh thường dùng

## Ràng buộc môi trường

Hai thứ này sai là hỏng ngầm, khó truy:

- **Python 3.12** (không phải 3.13/3.14). PyTorch, Demucs, mlx-whisper chưa có
  wheel cho bản mới hơn. `apps/api/pyproject.toml` đã pin `>=3.12,<3.13`.
- **`ffmpeg-full`**, không phải `ffmpeg`. Bản `ffmpeg` thường của Homebrew thiếu
  libass/freetype nên **không có filter `subtitles`, `ass`, `drawtext`** —
  không burn được hardsub, không vẽ được text branding. `ffmpeg-full` là keg-only
  nên `core/config.py` trỏ thẳng `/opt/homebrew/opt/ffmpeg-full/bin/`, không dựa
  vào PATH. `Settings.verify_ffmpeg()` kiểm tra 6 filter bắt buộc và harness chặn
  ngay từ đầu nếu thiếu.

## Lệnh thường dùng

```bash
# Test
.venv/bin/python -m pytest apps/api/tests -q
.venv/bin/python -m pytest apps/api/tests/test_duration_fit.py -q     # một file
.venv/bin/python -m pytest apps/api/tests -q -k "drift"               # một nhóm
.venv/bin/python -m pytest apps/api/tests/test_cache_chain.py::test_cache_hit_khi_khong_doi_gi -q

# Chạy pipeline trên clip mẫu
.venv/bin/python scripts/run_pipeline.py                          # 2 locale mặc định
.venv/bin/python scripts/run_pipeline.py --locales es-ES -v
.venv/bin/python scripts/run_pipeline.py --rerun-from translate   # partial re-run §11.3

# Vòng lặp dev nhanh: Whisper base thay vì large-v3-turbo
VLA_DEV_FAST=1 .venv/bin/python scripts/run_pipeline.py

# Chọn provider dịch
VLA_TRANSLATION_PROVIDER=mock .venv/bin/python scripts/run_pipeline.py

# Reset trạng thái
rm -f vla.db && rm -rf storage/projects/*

# Hạ tầng Celery/Redis (§20 Phase 3) — xem .claude/rules/infra.md
brew services start redis                          # một lần
.venv/bin/python scripts/worker.py                  # tiến trình worker riêng
.venv/bin/python scripts/run_pipeline.py --via-celery   # gửi qua Redis thay vì gọi trực tiếp
```

Không có bước build, không có linter cấu hình sẵn.
