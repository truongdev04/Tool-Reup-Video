# Tiến độ dự án — Tool Video Localization & Automation

> File này được ghi đè mỗi phiên. Đọc trước khi bắt đầu việc mới.

## 1. Mục tiêu

Hoàn thiện roadmap §20 từ Phase 2 (compose) tới Phase 5 (publishing) —
approval gates, hạ tầng Celery/Redis, dashboard Phase 4, và publishing.

## 2. Những phần đã hoàn thành

**Compose Phase 2** (commit `3aa819c`, đã push) — logo→CTA→intro/outro,
sửa lỗi SAR concat, đồng bộ audio/subtitle với intro/outro, cache
"gà-trứng" của brand. `services/compose_video.py`, `services/branding.py`,
`workers/compose/stage.py`.

**Approval gates + voice consent §11.2/§18.2** (commit `4cd3801`, `07b0739`,
đã push) — `services/approval_gates.py`, `services/voice_consent.py`,
`core/orchestrator.py::GATE_AFTER_STAGE`/`_pending_gate`, `Project.approval_gates`,
`workers/tts/stage.py::_enforce_voice_consent`. CLI `scripts/manage_gates.py`
(list/set-project/set-job/approve/resume) + `pipeline_runner.py::resume_job`/
`rerun_stages_for_job`. Sửa lỗ hổng `RenderJob.presets` chưa từng được ghi.

**Hạ tầng Celery/Redis §20 Phase 3** (commit `7d0f3b3`, đã push) —
`core/celery_app.py`, `core/tasks.py` (`run_for_video_task`/`resume_job_task`),
`scripts/worker.py`, `scripts/run_pipeline.py --via-celery`. Bug thật bắt
được: pool `prefork` mặc định làm vỡ Metal GPU của `mlx-whisper` khi fork()
— sửa mặc định `--pool=solo`. Biến môi trường không tự truyền tới worker
(khác tiến trình).

**Dashboard Phase 4 §19** (commit `7a7a1fa`, đã push) — backend
`api/routes/dashboard.py` (Projects/Batch Queue/Video Workspace/gates),
`services/translation_edit.py` (sửa inline translation KHÔNG gọi lại LLM,
tự bump cache `TRANSLATE` giữ nguyên `input_hash`/đổi `output_digest`).
Frontend `apps/web/` (Next.js 16 App Router + Tailwind v4): trang Projects,
Project detail, Batch Queue, Video Workspace (`DriftTimeline` SVG,
`UnitEditor`, `GatesPanel`). Bug thật bắt được: `TranslateStage.output_ref`
thiếu nội dung dịch (chỉ có số lượng) → cache downstream không invalidate
khi dịch lại ra chữ khác; sửa bằng `texts_digest`. Bug nhỏ: `job.error_message`
không tự xoá khi job thành công sau lần fail trước.

**Publishing / Phase 5 §6.17/§18.1/§18.3** (commit `8c62bf7`, **CHƯA push**
theo yêu cầu người dùng) — `services/publishing/` (base/adapters/registry/
quota, config-driven, chỉ provider `mock`), `db.PlatformAccount` (token mã
hoá qua `services/crypto.py` Fernet — bảng thứ 24), `workers/publishing/stage.py::PublishStage`
(chặn: QC PASS → account hợp lệ/tự refresh → còn quota → publish, ghi
`PublishingJob`, không có `_clear_previous` vì mỗi lần là sự kiện thật),
`api/routes/publishing.py` (OAuth 3-legged thật qua `mock`, state CSRF).
Frontend: `/publish` (Publishing Calendar), `PublishPanel` trong Video
Workspace. Bug thật bắt được: SQLite mất tzinfo khi đọc lại
`DateTime(timezone=True)` qua session mới → `db/base.py::UTCDateTime` sửa
cho MỌI cột datetime trong schema.

**Rule docs mới**: `.claude/rules/{approval-gates,infra,dashboard,publishing}.md`.

## 3. Trạng thái hiện tại

- **238/238 test Python pass** (`.venv/bin/python -m pytest apps/api/tests -q`).
- Frontend `apps/web/`: `tsc --noEmit` sạch, `eslint` sạch, `next build`
  thành công (6 route).
- Đã xác nhận **bằng trình duyệt thật** (chrome-devtools MCP) cho cả Phase 4
  (sửa inline translation → downstream chạy lại thật → QC/drift cập nhật
  đúng) và Phase 5 (kết nối OAuth account → publish bị chặn đúng khi QC
  fail → thu hồi account).
- Lỗi đã biết KHÔNG phải mới: QC `background_retained` FAIL trên es-ES —
  hạn chế fixture sine wave tổng hợp, không phải bug render.
- **Git**: `main` đang ahead `origin/main` 1 commit (`8c62bf7`, Publishing
  Phase 5) — **chưa push theo yêu cầu người dùng**. 4 commit trước đó
  (compose, approval gates, Celery, dashboard) đã push.
- diarize + multi-voice TTS thật vẫn chưa kích hoạt được trên máy này
  (thiếu `HF_TOKEN`) — chỉ test qua mock.

**Settings Phase 4 — READ-ONLY** (chưa commit, xem `git status`) —
`apps/api/api/routes/settings.py` (mới, `GET /api/dashboard/settings`),
đăng ký trong `apps/api/api/main.py`. Phạm vi chốt sau khi hỏi người dùng:
CHỈ hiện trạng thái, không sửa gì qua UI, vì 3 mảnh tech-debt cũ có mức sẵn
sàng khác nhau — API key provider chỉ đọc env var, không lưu DB
(`providers.md`) nên không thể có ô sửa; concurrency chưa có cơ chế giới hạn
nào trong code để sửa; retention (`RETENTION_DAYS`) chưa có tiến trình purge
nào đọc nên sửa qua UI vô nghĩa. Trả về: trạng thái configured của mọi
provider dịch/TTS/publishing (không bao giờ lộ giá trị key/token thật —
`test_khong_lo_api_key_that_ra_response` khoá lại), `verify_ffmpeg()`,
`RETENTION_DAYS`, ngưỡng duration-fit/QC, model + trạng thái `HF_TOKEN` của
diarize, hạ tầng (database_url/storage_root/redis_url/token_encryption_key
đã cấu hình chưa). Frontend: `apps/web/src/app/settings/page.tsx` + type
`SettingsStatus`/`ProviderStatus`/`SettingsPlatformStatus` trong `api.ts` +
link Nav. Test: `apps/api/tests/test_settings_route.py` (6 test, gọi thẳng
hàm route không qua HTTP client — cùng mẫu test hàm thuần). Đã xác nhận
bằng trình duyệt thật (chrome-devtools MCP) trên dữ liệu backend thật.
Cập nhật `.claude/rules/dashboard.md` (mục Settings mới) và `tech-debt.md`.

**Ước tính chi phí dry-run §17.1** (commit tiếp theo cùng lượt, đã push) —
`apps/api/services/cost_estimate.py::estimate_batch()` (không gọi mạng,
không tốn tiền — chỉ đọc DB/config). Ưu tiên `ApiUsage` thật
(`is_estimate=False`) hơn giá niêm yết config; phân biệt rõ "giá = 0.0 thật
sự free" (mock/ollama/macos_say) với "giá = None chưa ai điền" (openai/
claude/gemini/openrouter/9router hiện tại — luôn cảnh báo, không lặng lẽ
trả $0). Ký tự nguồn ưu tiên `Transcript.full_text` thật, suy đoán thô từ
`duration_ms` khi chưa transcribe. `already_done` đánh dấu (video, locale)
đã chạy TRANSLATE+TTS thành công (khả năng cache-hit §16). CLI
`scripts/estimate_cost.py` (đã chạy thử thật trên `vla.db` dev, project
"Celery Smoke Test"). Endpoint `GET /api/dashboard/projects/{id}/estimate`
trong `dashboard.py`. Frontend `CostEstimatePanel.tsx` nhúng vào trang
Project detail, dropdown provider lấy từ `/api/dashboard/settings` (không
lặp danh sách). Test: `test_cost_estimate.py` (8 test). Đã xác nhận bằng
trình duyệt thật trên dữ liệu dev thật. Cập nhật `dashboard.md`,
`tech-debt.md`.

## 4. Bước tiếp theo

Roadmap §20 core (Phase 0–5) đã xong về kiến trúc + vòng vận hành lõi của
dashboard (Projects, Video Workspace, Batch Queue, Publishing Calendar,
Settings, ước tính chi phí). Việc còn mở, chưa chọn cái nào tiếp theo:

1. Nối publish với 1 nền tảng thật (YouTube dễ nhất — cần người dùng tự tạo
   OAuth app trên Google Cloud Console, không tự làm được).
2. Cơ chế purge thật cho retention (`RETENTION_DAYS` mới chỉ để xem ở
   Settings, chưa có tiến trình đọc) — RỦI RO: phải tránh xoá file mà
   `StageRun` cache vẫn còn trỏ tới (xem cảnh báo trong caching.md), nên cần
   thiết kế cẩn thận (xoá kèm invalidate StageRun liên quan), KHÔNG làm vội.
3. Cơ chế giới hạn concurrency thật (worker luôn `--pool=solo`).
4. §17.1 chưa có API "submit batch N video" để gắn bước xác nhận trước khi
   chạy — hiện chỉ là trang/CLI ước tính chủ động, không phải gate bắt buộc.
5. Phase 6 (mở rộng): on-screen text inpainting (`onscreen_text` vẫn
   `NotImplementedStage`), monitoring, regression tests. Lip-sync đã CHỐT
   không làm cho MVP (§23).
6. Việc nhỏ nâng chất lượng: hiệu chuẩn `speech_rate_cps` cho provider TTS
   khác `macos_say`, `FitStrategy.VIDEO_STRETCH`, render/publishing preset
   §14.
7. Nếu có `HF_TOKEN`: `.venv/bin/pip install pyannote.audio`, export
   `HF_TOKEN`, chạy lại `scripts/run_pipeline.py` để xác nhận diarize +
   multi-voice TTS chạy thật.
