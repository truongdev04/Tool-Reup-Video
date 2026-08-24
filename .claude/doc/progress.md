# Tiến độ dự án — Tool Video Localization & Automation

> File này được ghi đè mỗi phiên. Đọc trước khi bắt đầu việc mới.

## 1. Mục tiêu

Theo đúng roadmap §20: Phase 0–2 xong hoàn toàn. Phase 3 ("Redis queue,
worker tách tiến trình, retry, cache, partial re-run, approval gates, QC tự
động") nay cũng đã xong hoàn toàn — retry/cache/partial-re-run/QC tự động có
từ Phase 0–2, approval gates + voice consent và hạ tầng Celery/Redis làm
xong phiên này.

## 2. Những phần đã hoàn thành

**Phase 0–2 — đã xong, đã commit+push.** Chi tiết:
[.claude/rules/diarization.md](../rules/diarization.md),
[.claude/rules/providers.md](../rules/providers.md),
[.claude/rules/fonts.md](../rules/fonts.md),
[.claude/rules/compose.md](../rules/compose.md).

**Approval gates + voice consent (§11.2, §18.2) — đã commit+push**, có CLI
vận hành (`scripts/manage_gates.py`). Chi tiết:
[.claude/rules/approval-gates.md](../rules/approval-gates.md).

**Hạ tầng Celery/Redis (§20 Phase 3) — MỚI phiên này, CHƯA commit/push.**
Chi tiết đầy đủ: [.claude/rules/infra.md](../rules/infra.md).

- `core/celery_app.py` (app Celery, broker/backend = Redis local qua
  `Settings.redis_url`), `core/tasks.py` (`run_for_video_task`/
  `resume_job_task` — chỉ gọi lại hàm thuần đã có trong `pipeline_runner.py`,
  serialize `PipelineReport` thành dict JSON trước khi trả).
- `scripts/worker.py` (khởi động worker), `scripts/run_pipeline.py
  --via-celery` (gửi task qua Redis thay vì gọi trực tiếp).
- `pyproject.toml` (+`celery`, `redis`), `core/config.py`
  (+`Settings.redis_url`), Redis cài qua `brew install redis` trên máy này.
- 3 test mới (`test_celery_tasks.py`, dùng `Task.apply()` — không cần
  redis-server thật để chạy test).
- **Đã xác nhận bằng pipeline THẬT qua Redis + worker process riêng, không
  chỉ unit test** — và bắt được 1 lỗi hạ tầng nghiêm trọng khi làm vậy:
  - Lần chạy đầu dùng pool mặc định `prefork` (fork tiến trình con) →
    `stt` (mlx-whisper, Metal GPU) FAIL 100% với lỗi
    `[metal::Device] ... Unable to reach MTLCompilerService` — Metal không
    sống sót qua `fork()`. Sửa: `scripts/worker.py` mặc định `--pool=solo`.
  - Lần chạy lại với `--pool=solo`: `ingest`/`analyze`/`separate` cache-hit
    đúng (job đã tồn tại từ lần trước), `stt` chạy thật thành công, toàn bộ
    pipeline hoàn tất `ok: True` trong ~24s.
  - Phát hiện thêm (đã ghi vào infra.md, KHÔNG phải bug — là đặc tính vốn có
    của việc tách tiến trình): biến môi trường (`VLA_DEV_FAST` v.v.) set cho
    tiến trình CLI KHÔNG tự động tới tiến trình worker — phải set trước khi
    khởi động `scripts/worker.py`.
- Tiện sửa 1 lỗ hổng có sẵn từ Phase 0: `RenderJob.presets` tồn tại nhưng
  chưa từng được ghi ở đâu — `resume_job()` cần đọc lại đúng provider đã
  dùng ở lần chạy gốc, nên `run_for_video()` giờ ghi `job.presets = presets`
  mỗi lần gọi.

## 3. Trạng thái hiện tại

- **215/215 test pass** (`apps/api/tests`).
- **Lỗi đã biết, KHÔNG phải mới**: QC `background_retained` FAIL trên
  es-ES — hạn chế của fixture tổng hợp (sine wave), không phải bug render.
- **Chưa commit/push**: toàn bộ code hạ tầng Celery/Redis phiên này (core/
  celery_app.py, core/tasks.py, scripts/worker.py, sửa scripts/run_pipeline.py,
  pyproject.toml, core/config.py, test_celery_tasks.py, rule docs liên quan)
  — đã `git add`? CHƯA, đang chờ xác nhận.
- Redis đang chạy nền trên máy này (khởi động thủ công lúc dev, KHÔNG qua
  `brew services start` nên sẽ không tự chạy lại sau khi máy khởi động lại —
  người dùng cần tự chạy `brew services start redis` nếu muốn nó persistent).
- **Chưa kích hoạt được trên pipeline thật**: diarize + multi-voice TTS thật
  (chưa có `HF_TOKEN`); voice consent chưa test với giọng thật (chỉ test với
  provider giả).
- Nợ kỹ thuật khác (chi tiết: [.claude/rules/tech-debt.md](../rules/tech-debt.md)):
  `forced_align` xấp xỉ tuyến tính; `speech_rate_cps` chưa hiệu chuẩn cho
  `elevenlabs`/`openai_tts`; `render` chưa áp `FitStrategy.VIDEO_STRETCH`;
  chưa có render preset (§14); `speaker_voices` chưa có cho `elevenlabs`;
  dry-run cost estimate (§17.1) chưa có; `onscreen_text` vẫn stub; worker
  Celery chưa test chạy song song nhiều job, chưa có supervisor tự restart.

## 4. Bước tiếp theo

1. **Xác nhận commit/push hạ tầng Celery/Redis** (đang chờ, chưa `git add`).
2. Phase 3 (roadmap §20) nay đã xong hoàn toàn. Lựa chọn còn mở cho Phase
   tiếp theo: **Phase 4** (dashboard Next.js+FastAPI thật — dev viewer hiện
   tại không phải cái này), **Phase 5** (publish/OAuth từng nền tảng), hoặc
   việc nhỏ nâng chất lượng còn tồn (dry-run cost §17.1, hiệu chuẩn
   `speech_rate_cps`, `FitStrategy.VIDEO_STRETCH`, render preset).
3. Nếu người dùng lấy được `HF_TOKEN`: `.venv/bin/pip install pyannote.audio`,
   export `HF_TOKEN`, chạy lại `scripts/run_pipeline.py` để xác nhận diarize
   + multi-voice TTS chạy thật.
