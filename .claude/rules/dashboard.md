# Dashboard Phase 4 (§19, §20)

Hai phần tách biệt, cố ý không gộp:

- **Dev viewer** (`apps/api/api/routes/pipeline.py` + `apps/api/api/static/`)
  — trang tĩnh HTML/JS, CHỈ để chạy thử pipeline cục bộ. Có từ Phase 0.
- **Dashboard thật** (`apps/api/api/routes/dashboard.py` + `apps/web/`) —
  Next.js app riêng, gọi backend qua CORS (`apps/api/api/main.py`). Đây mới
  là phần §19 nói tới.

Lượt đầu (§19 "vòng vận hành lõi"): Projects, Video Workspace, Batch Queue,
QC Review (lồng trong Video Workspace). Publishing Calendar
([publishing.md](publishing.md)) và Settings (mục dưới) đã làm ở các lượt
sau.

## Backend — `apps/api/api/routes/dashboard.py`

Đọc thẳng model qua `session_scope()`, không có service layer riêng (project/
job/unit list chỉ là SELECT + reshape JSON, không có logic nghiệp vụ đáng
tách). Hai chỗ CÓ logic thật, nằm ở service module theo đúng mẫu tách I/O
khỏi logic của dự án:

- `services/translation_edit.py` — sửa inline một `translation_unit`.
- `services/pipeline_runner.py::rerun_stages_for_job` — chạy một tập stage
  chỉ định cho job đã tồn tại (dùng chung với `resume_job`, xem
  [approval-gates.md](approval-gates.md)).

### Sửa inline translation — KHÔNG chạy lại TranslateStage

Đây là quyết định kiến trúc quan trọng nhất của dashboard. Người dùng tự
cung cấp bản dịch đúng qua UI — gọi lại LLM (`rerun_from(TRANSLATE)`) sẽ tốn
tiền vô ích VÀ có thể model dịch ra khác, ghi đè mất bản sửa thủ công.

`edit_unit_translation()` thay vào đó:
1. Tạo `Translation` version mới, deactivate bản cũ (đúng lineage §10.4,
   cùng mẫu `TranslateStage._next_version`/`_deactivate_previous`).
2. Tự ghi một `StageRun` MỚI cho `TRANSLATE` — **cùng `input_hash`** với lần
   chạy thật gần nhất (để bản thân TRANSLATE vẫn cache-hit, không gọi lại
   provider), nhưng `output_ref` chứa digest nội dung SAU khi sửa (để
   downstream thấy đúng thay đổi qua chuỗi `(input_hash, output_digest)`,
   §16).
3. Router gọi `rerun_stages_for_job(job_id, dependents_of(TRANSLATE))` — loại
   TRANSLATE khỏi tập stage chạy lại (khác `Orchestrator.rerun_from` vốn ép
   force-run chính stage được truyền vào).

**Điều kiện bắt buộc**: TRANSLATE phải đã chạy qua `Orchestrator.run_stage()`
thật ít nhất một lần trước đó (ghi `StageRun` thật) — sửa inline một job chưa
từng chạy translate sẽ không có gì để bump, không lỗi nhưng cũng không đổi
downstream cache. Đây không phải flow thực tế (dashboard chỉ hiện job đã có
translation_unit), nhưng cần biết khi viết test.

### Bug đã bắt được khi soát cơ chế này: `TranslateStage.output_ref` thiếu nội dung

Trước khi làm dashboard, `output_ref` thật của `TranslateStage` (không phải
StageRun thủ công ở trên) chỉ chứa SỐ LƯỢNG (`units_translated`,
`over_budget`...), không chứa CHỮ đã dịch. Dịch lại ra nội dung khác nhưng
cùng số lượng (vd. sửa glossary rồi `rerun_from(translate)`) thì
`output_digest` không đổi → downstream cache hit nhầm bản dịch CŨ — đúng
kiểu lỗi nghiêm trọng nhất mà [caching.md](caching.md) cảnh báo. Đã sửa:
thêm `texts_digest` (digest nội dung dịch thật) vào `output_ref`, xem
`workers/translation/stage.py` + `test_translate_stage.py`.

## Frontend — `apps/web/`

Next.js App Router, mọi trang là Client Component (`"use client"`) fetch
thẳng từ trình duyệt qua `src/lib/api.ts` — không SSR, không server actions.
Không có codegen kiểu OpenAPI → TypeScript: sửa route ở
`dashboard.py` thì phải tự sửa type khớp trong `api.ts`. Chi tiết chạy/cấu
trúc: `apps/web/README.md`.

## Ước tính chi phí — `GET /projects/{id}/estimate` (§17.1)

`services/cost_estimate.py::estimate_batch()` — KHÔNG gọi mạng, KHÔNG tốn
tiền, chỉ đọc DB + config. Nguyên tắc ưu tiên nguồn số (khớp "tự đo usage
thực tế" của §17): `ApiUsage` thật (`is_estimate=False`) của ĐÚNG provider >
giá niêm yết trong `ProviderConfig`/`TTSConfig` > cảnh báo "không ước tính
được" (KHÔNG bao giờ lặng lẽ trả `0.0` khi giá thật sự chưa biết — `0.0`
nghĩa là free thật, vd. `mock`/`ollama`/`macos_say` đã khai rõ trong JSON;
`None` là "chưa ai điền giá", hai trường hợp này PHẢI phân biệt được qua
`warnings`, xem `test_provider_chua_khai_gia_thi_bao_warning_...`). Ký tự
nguồn ưu tiên `Transcript.full_text` thật; chưa transcribe thì suy đoán thô
từ `duration_ms × speech_rate_cps` của `source_locale` — luôn cảnh báo rõ.
`already_done` đánh dấu (video, locale) đã có TRANSLATE+TTS `StageRun`
SUCCEEDED — chạy lại nhiều khả năng cache-hit (§16), gần như không tốn thêm,
nhưng vẫn hiện số đầy đủ (không tự ý coi bằng 0). CLI tương đương:
`scripts/estimate_cost.py`. Frontend:
`apps/web/src/components/CostEstimatePanel.tsx`, nhúng vào trang Project
detail, dropdown provider lấy từ chính `/api/dashboard/settings` (mục dưới)
để không lặp danh sách provider ở hai nơi.

Giới hạn đã biết: đây là ước tính CHO MỘT PROJECT khi người vận hành chủ
động mở trang/gọi CLI, KHÔNG phải bước "xác nhận bắt buộc trước khi submit
batch" như §17.1 mô tả — dự án hiện chưa có API "chạy batch N video" nào để
gắn bước xác nhận đó vào (`scripts/run_pipeline.py` chạy trực tiếp qua CLI
theo video/locale chỉ định, không phải submit qua dashboard).

## Settings — `apps/api/api/routes/settings.py` (READ-ONLY)

Quyết định phạm vi có chủ ý (hỏi người dùng trước khi làm): trang Settings
CHỈ hiện trạng thái, KHÔNG cho sửa gì qua UI. Ba mảnh trong tech-debt.md có
mức sẵn sàng khác nhau:

- **API key provider** (translation/TTS): [providers.md](providers.md) đã
  quy định "chỉ đọc từ biến môi trường tại thời điểm gọi, không lưu DB" —
  route chỉ trả `is_configured`/`api_key_env` (TÊN biến, không phải GIÁ TRỊ),
  không có ô nhập key nào. `test_khong_lo_api_key_that_ra_response` khoá lại
  ràng buộc này bằng cách set biến môi trường giả rồi assert giá trị đó
  không xuất hiện trong JSON response.
- **Concurrency**: chưa có field nào để hiện — không có cơ chế giới hạn "số
  job chạy song song" trong code (`scripts/worker.py` luôn `--pool=solo`,
  xem [infra.md](infra.md)). Cố tình không bịa field giả.
- **Retention**: hiện đúng `services/storage.py::RETENTION_DAYS` (không hard-
  code lại số trong route) nhưng chỉ để xem — không có tiến trình purge nào
  đọc dict đó (xem [tech-debt.md](tech-debt.md)), nên sửa qua UI cũng vô
  nghĩa cho tới khi có purge job thật.

Cũng hiện: kết quả `Settings.verify_ffmpeg()`, danh sách publishing platform
(`services/publishing/registry`), model + trạng thái `HF_TOKEN` của diarize
([diarization.md](diarization.md)), ngưỡng duration-fit/QC
([duration-fitting.md](duration-fitting.md)), và
`token_encryption_key_configured` ([publishing.md](publishing.md)) — luôn là
cờ boolean, không bao giờ là giá trị secret thật.

## Giới hạn đã biết

- Không có auth trên cả router lẫn frontend — dev tool nội bộ, chưa expose
  ra ngoài máy dev. Bắt buộc chốt trước khi triển khai thật.
- Batch Queue không tự refresh khi job chạy nền qua Celery đổi trạng thái —
  phải tự tải lại trang (không có polling/websocket).
- `job.error_message` giờ được xoá khi job thành công sau lần fail trước
  (sửa trong `core/orchestrator.py` khi làm dashboard này — phát hiện lúc
  soát dữ liệu thật qua API, trước đó lỗi cũ hiển thị mãi dù job đã ok).
