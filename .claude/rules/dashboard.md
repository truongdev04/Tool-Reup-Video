# Dashboard Phase 4 (§19, §20)

Hai phần tách biệt, cố ý không gộp:

- **Dev viewer** (`apps/api/api/routes/pipeline.py` + `apps/api/api/static/`)
  — trang tĩnh HTML/JS, CHỈ để chạy thử pipeline cục bộ. Có từ Phase 0.
- **Dashboard thật** (`apps/api/api/routes/dashboard.py` + `apps/web/`) —
  Next.js app riêng, gọi backend qua CORS (`apps/api/api/main.py`). Đây mới
  là phần §19 nói tới.

Lượt đầu (§19 "vòng vận hành lõi"): Projects, Video Workspace, Batch Queue,
QC Review (lồng trong Video Workspace). Publishing Calendar và Settings để
lượt sau — xem [tech-debt.md](tech-debt.md).

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

## Giới hạn đã biết

- Không có auth trên cả router lẫn frontend — dev tool nội bộ, chưa expose
  ra ngoài máy dev. Bắt buộc chốt trước khi triển khai thật.
- Batch Queue không tự refresh khi job chạy nền qua Celery đổi trạng thái —
  phải tự tải lại trang (không có polling/websocket).
- `job.error_message` giờ được xoá khi job thành công sau lần fail trước
  (sửa trong `core/orchestrator.py` khi làm dashboard này — phát hiện lúc
  soát dữ liệu thật qua API, trước đó lỗi cũ hiển thị mãi dù job đã ok).
