# Tiến độ dự án — Tool Video Localization & Automation

> File này được ghi đè mỗi phiên. Đọc trước khi bắt đầu việc mới.

## 1. Mục tiêu

Theo roadmap §20: Phase 0–3 xong hoàn toàn. Phase 4 (Dashboard) — "vòng vận
hành lõi" (Projects, Video Workspace, Batch Queue, QC Review) đã xong và xác
nhận chạy thật qua trình duyệt phiên này. Còn lại của Phase 4: Publishing
Calendar (chờ Phase 5), Settings.

## 2. Những phần đã hoàn thành

**Phase 0–3 — đã xong, đã commit+push.** Chi tiết:
[.claude/rules/compose.md](../rules/compose.md),
[.claude/rules/approval-gates.md](../rules/approval-gates.md),
[.claude/rules/infra.md](../rules/infra.md).

**Dashboard Phase 4 — vòng vận hành lõi (§19) — MỚI phiên này, CHƯA
commit/push.** Chi tiết đầy đủ: [.claude/rules/dashboard.md](../rules/dashboard.md).

- Backend: `apps/api/api/routes/dashboard.py` (mới) — Projects (list/detail),
  Batch Queue (list job mọi project, lọc theo trạng thái), Video Workspace
  (chi tiết 1 job: unit/translation/drift/QC/gates), sửa inline translation
  (PATCH + rerun-downstream), approve gate, resume job. CORS bật trong
  `api/main.py` cho `localhost:3000`.
- Service mới: `services/translation_edit.py` — sửa bản dịch KHÔNG gọi lại
  LLM, tự bump cache `TRANSLATE` (cùng `input_hash`, `output_ref` đổi theo
  nội dung) để downstream (`duration_fit`→`tts`→...→`qc`) chạy lại đúng mà
  TRANSLATE vẫn cache-hit. `services/pipeline_runner.py::rerun_stages_for_job`
  (mới, refactor từ `resume_job`) — chạy một tập stage chỉ định cho job có sẵn.
- **Bug bắt được khi soát cơ chế cache cho tính năng này**:
  `TranslateStage.output_ref` trước đây chỉ chứa SỐ LƯỢNG, không chứa NỘI
  DUNG bản dịch — dịch lại ra chữ khác nhưng cùng số lượng thì
  `output_digest` không đổi, downstream cache hit nhầm bản dịch CŨ. Đã sửa
  (`texts_digest`), có regression test (`test_translate_stage.py`).
- Bug nhỏ khác bắt được khi soát dữ liệu thật qua API:
  `RenderJob.error_message` không được xoá khi job thành công sau lần fail
  trước — dashboard hiện lỗi cũ mãi dù đã chạy lại OK. Đã sửa trong
  `core/orchestrator.py`, có test.
- Frontend: `apps/web/` — Next.js 16 (App Router, TypeScript, Tailwind v4),
  toàn Client Component gọi thẳng backend qua `src/lib/api.ts`. 4 trang:
  Projects (`/`), Project detail (`/projects/[id]`), Batch Queue (`/queue`),
  Video Workspace (`/jobs/[id]` — transcript/dịch có sửa inline qua
  `UnitEditor` + preview "sẽ chạy lại gì" trước khi lưu, `DriftTimeline` SVG
  theo đúng yêu cầu §19, `GatesPanel` duyệt/chạy tiếp cổng, QC findings, video
  player).
- **Đã xác nhận bằng trình duyệt thật (chrome-devtools), không chỉ
  build/lint pass**: mở cả 4 trang với dữ liệu thật từ job Celery smoke test
  trước đó; bấm "Sửa" một câu dịch → lưu → thấy đúng preview stage sẽ chạy
  lại → sau khi lưu, downstream chạy lại thật (log uvicorn xác nhận PATCH +
  POST rerun-downstream 200 OK), UI tự refetch và hiện đúng: bản dịch mới,
  drift timeline chuyển đỏ (bản dịch dài hơn làm audio trôi >300ms), QC
  chuyển FAIL đúng chỗ, video re-render (frame khác). Không có console error.
- `apps/web/CLAUDE.md`/`AGENTS.md` (tự sinh bởi `next dev`, KHÔNG xoá — file
  cảnh báo Next.js 16 có breaking changes so với training data, đã đọc
  `node_modules/next/dist/docs/` trước khi code theo đúng hướng dẫn đó).

## 3. Trạng thái hiện tại

- **221/221 test Python pass** (`apps/api/tests`). Frontend: `npx tsc
  --noEmit` sạch, `npm run lint` sạch, `npm run build` thành công.
- **Lỗi đã biết, KHÔNG phải mới**: QC `background_retained` FAIL trên
  es-ES — hạn chế của fixture tổng hợp (sine wave), không phải bug render.
- **Chưa commit/push**: toàn bộ code dashboard phiên này (backend
  `dashboard.py`, `translation_edit.py`, sửa `pipeline_runner.py`/
  `orchestrator.py`/`main.py`, test mới, và cả thư mục `apps/web/`) — chưa
  `git add`.
- **Chưa làm**: Publishing Calendar (chờ Phase 5 có gì để hiện), Settings
  (provider API key/concurrency/retention), auth cho cả CLI lẫn dashboard,
  tự động refresh Batch Queue khi Celery đổi trạng thái nền.
- Nợ kỹ thuật khác (chi tiết: [.claude/rules/tech-debt.md](../rules/tech-debt.md)):
  `forced_align` xấp xỉ tuyến tính; `speech_rate_cps` chưa hiệu chuẩn cho
  `elevenlabs`/`openai_tts`; `render` chưa áp `FitStrategy.VIDEO_STRETCH`;
  chưa có render preset (§14); `speaker_voices` chưa có cho `elevenlabs`;
  dry-run cost estimate (§17.1) chưa có; `onscreen_text` vẫn stub; diarize +
  multi-voice TTS thật chưa kích hoạt được (chưa có `HF_TOKEN`).

## 4. Bước tiếp theo

1. **Xác nhận commit/push toàn bộ dashboard Phase 4** (đang chờ, chưa
   `git add` — lượng thay đổi lớn, gồm cả `apps/web/` mới).
2. Phase 0–4 (phần lõi) đã xong theo roadmap §20. Lựa chọn kế tiếp: hoàn
   thiện nốt Phase 4 (Settings — không phụ thuộc gì khác, làm được ngay;
   Publishing Calendar phải chờ Phase 5), hoặc bắt đầu **Phase 5** (`publish`,
   OAuth từng nền tảng — xem ràng buộc quota §18.3 trước khi thiết kế), hoặc
   việc nhỏ nâng chất lượng còn tồn (dry-run cost §17.1, hiệu chuẩn
   `speech_rate_cps`, `FitStrategy.VIDEO_STRETCH`, render preset).
3. Nếu người dùng lấy được `HF_TOKEN`: `.venv/bin/pip install pyannote.audio`,
   export `HF_TOKEN`, chạy lại `scripts/run_pipeline.py` để xác nhận diarize
   + multi-voice TTS chạy thật.
