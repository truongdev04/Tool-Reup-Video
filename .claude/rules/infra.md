# Hạ tầng Celery/Redis — worker tách tiến trình (§20 Phase 3)

Stage contract (§11.1, [stage-contract.md](stage-contract.md)) tách stage
khỏi cách gọi từ Phase 0 đúng để việc này chỉ là đổi cách gọi
`services/pipeline_runner.py`, không viết lại `Orchestrator`/stage nào.

- `core/celery_app.py` — app Celery, broker/backend = `Settings.redis_url`
  (mặc định `redis://localhost:6379/0`, Redis LOCAL trên máy chạy worker,
  KHÔNG phải server từ xa — `brew install redis`).
- `core/tasks.py` — `run_for_video_task`/`resume_job_task`, mỗi task chỉ gọi
  thẳng hàm cùng tên trong `pipeline_runner.py` rồi serialize
  `PipelineReport` (dataclass lồng `StrEnum`) thành dict JSON thuần trước khi
  trả — Celery JSON serializer không tự xử lý dataclass.
- `scripts/worker.py` — khởi động worker, `scripts/run_pipeline.py
  --via-celery` — gửi task qua broker thay vì gọi trực tiếp trong tiến trình.

## Bắt buộc: `--pool=solo`, không phải mặc định `prefork`

**Đã bắt được lỗi này khi chạy thử THẬT qua `--via-celery`, không phải suy
đoán.** `stt` dùng `mlx-whisper` (Metal GPU qua MLX, xem environment.md).
Pool mặc định của Celery là `prefork` (fork tiến trình con cho mỗi task) —
Metal **không sống sót qua `fork()`**: task fail 100% với
`[metal::Device] ... Unable to reach MTLCompilerService`. `scripts/worker.py`
đã set `--pool=solo` làm mặc định (chạy tuần tự ngay trong tiến trình worker
chính, không fork) — đừng đổi lại `prefork` trừ khi đã bỏ hẳn `mlx-whisper`
khỏi `stt`. Muốn nhiều task song song thật sự (không liên quan GPU) thì cân
nhắc `--pool=threads` trước, `prefork` chỉ an toàn nếu chắc chắn stage GPU
không chạy trong tiến trình đó.

## Biến môi trường KHÔNG tự động tới worker

`VLA_DEV_FAST=1 python scripts/run_pipeline.py --via-celery` chỉ set biến
môi trường cho tiến trình CLI gửi task — KHÔNG cho tiến trình worker (đã tự
bắt gặp: lần chạy thử đầu vô tình dùng Whisper `large-v3-turbo` đầy đủ thay
vì `base` vì worker khởi động trước, không mang theo `VLA_DEV_FAST`). Set
biến môi trường (`VLA_DEV_FAST`, `VLA_TTS_PROVIDER`, `VLA_TRANSLATION_PROVIDER`...)
TRƯỚC KHI khởi động `scripts/worker.py`, không phải trước lệnh gửi task.

## `resume_job` đọc lại `job.presets`, không dùng mặc định

`services/pipeline_runner.py::resume_job()` (dùng bởi `resume_job_task` và
`scripts/manage_gates.py resume`, xem [approval-gates.md](approval-gates.md))
đọc `RenderJob.presets` đã lưu lúc `run_for_video()` tạo/chạy job lần đầu —
không phải mặc định của tiến trình gọi resume. Tiện sửa một lỗ hổng có sẵn
từ Phase 0: cột `RenderJob.presets` tồn tại nhưng trước đây KHÔNG chỗ nào
từng ghi vào nó (`run_for_video()` chỉ truyền `presets` cho `ctx.presets`,
không lưu xuống DB) — giờ ghi `job.presets = presets` mỗi lần gọi.

## Giới hạn đã biết

- **Dev viewer (`apps/api/api/routes/pipeline.py`) vẫn chạy đồng bộ**, không
  qua Celery — có chủ ý, vì đây "CHỈ để chạy thử cục bộ... không phải
  dashboard Phase 4 thật" (xem docstring đầu file đó). `--via-celery` chỉ có
  ở `scripts/run_pipeline.py`.
- Task Celery `.get(timeout=...)` chờ ĐỒNG BỘ trong tiến trình CLI — nếu
  worker chưa chạy hoặc chết giữa chừng, CLI treo tới hết timeout (300s) rồi
  raise `celery.exceptions.TimeoutError`. Không có cơ chế poll-rồi-thoát
  ngay như dashboard thật sẽ cần (Phase 4).
- Chưa test `--pool=solo` với NHIỀU job chạy đồng thời — solo nghĩa là mọi
  task xếp hàng tuần tự trong một worker, đúng ý "tách tiến trình khỏi tiến
  trình gọi" nhưng KHÔNG tăng thông lượng so với chạy trực tiếp. Muốn chạy
  song song thật sự phải tách stage GPU (`stt`) ra pool riêng
  (`--pool=solo` cho queue có `stt`, `prefork`/`threads` cho queue khác) —
  chưa làm, để khi thật sự cần.
- Chưa có supervisor/systemd/launchd khởi động lại worker khi crash — vận
  hành thủ công (`scripts/worker.py` chạy tay hoặc `run_in_background`).
