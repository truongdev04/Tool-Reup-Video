# Tiến độ dự án — Tool Video Localization & Automation

> File này được ghi đè mỗi phiên. Đọc trước khi bắt đầu việc mới.

## 1. Mục tiêu

Phase 2 (kế hoạch v3) đã xong hoàn toàn. Đang làm Phase 3: approval gates
(§11.2) + voice consent (§18.2) — đã thực thi xong và đã xác nhận vận hành
được thật (không chỉ unit test) qua CLI mới `scripts/manage_gates.py`.

## 2. Những phần đã hoàn thành

**Phase 2 — đã xong, đã commit+push** (diarize §6.5, multi-voice TTS §6.9,
font fallback §13.2/§14, compose §6.14 logo+CTA+intro/outro). Chi tiết:
[.claude/rules/diarization.md](../rules/diarization.md),
[.claude/rules/providers.md](../rules/providers.md),
[.claude/rules/fonts.md](../rules/fonts.md),
[.claude/rules/compose.md](../rules/compose.md).

**Approval gates + voice consent (§11.2, §18.2) — đã commit+push.** Chi tiết
đầy đủ: [.claude/rules/approval-gates.md](../rules/approval-gates.md).

- `services/approval_gates.py` (`ensure_gates()`/`approve()`),
  `services/voice_consent.py` (`ensure_voice_consent()`).
- `core/orchestrator.py::GATE_AFTER_STAGE` + `Orchestrator._pending_gate` —
  `run_pipeline` dừng đúng chỗ khi cổng bật mà chưa duyệt.
- `workers/tts/stage.py::_enforce_voice_consent` — chặn TTS trước khi
  synthesize nếu giọng đã đăng ký `is_cloned=True` mà thiếu consent hợp lệ.
- `db/models.py::Project.approval_gates` (JSON, mặc định rỗng = tự động).
- 21 test mới (`test_approval_gates.py`, `test_voice_consent.py`).

**CLI vận hành gate — MỚI phiên này, `scripts/manage_gates.py`.**

- Subcommand: `list` (job hoặc cả project), `set-project` (cấu hình mặc định
  cho job mới), `set-job` (bật/tắt trực tiếp một job đã tồn tại), `approve`,
  `resume`.
- `services/pipeline_runner.py::resume_job()` (mới) — gọi lại
  `run_pipeline()` cho một job đang `NEEDS_REVIEW`, đọc `job.presets` đã lưu
  từ lần chạy gốc (provider dịch/TTS) thay vì fallback mặc định. Tiện sửa
  luôn 1 lỗ hổng có sẵn: `RenderJob.presets` trước đây KHÔNG BAO GIỜ được
  ghi (cột tồn tại từ Phase 0, không có chỗ nào set) — giờ
  `run_for_video()` ghi `job.presets = presets` mỗi lần gọi.
- **Đã xác nhận bằng pipeline THẬT, không chỉ unit test**: tạo project với
  `approval_gates={"transcript": True}`, chạy `scripts/run_pipeline.py` →
  dừng đúng ngay sau `stt`; `manage_gates.py list` hiện đúng trạng thái "CHỜ
  DUYỆT"; `approve` rồi `resume` → 4 stage đầu cache-hit tức thì, các stage
  sau chạy thật tới khi xong (QC needs_review vì lỗi fixture đã biết, không
  liên quan gate).

## 3. Trạng thái hiện tại

- **212/212 test pass** (`apps/api/tests`).
- **Lỗi đã biết, KHÔNG phải mới**: QC `background_retained` FAIL trên
  es-ES — hạn chế của fixture tổng hợp (sine wave), không phải bug render.
- **Chưa commit/push**: `scripts/manage_gates.py` (mới),
  `services/pipeline_runner.py` (thêm `resume_job()` + fix `job.presets`),
  và cập nhật rule docs (`approval-gates.md`, `tech-debt.md`) của phiên này.
- **Chưa kích hoạt được trên pipeline thật**: diarize + multi-voice TTS thật
  (chưa có `HF_TOKEN`); voice consent cũng chưa từng test trên giọng
  `elevenlabs` thật (chỉ có test với provider giả) — vì đăng ký `Voice`/
  `VoiceConsent` vẫn phải làm qua Python thủ công, chưa có CLI riêng cho việc
  đó (approval gates thì đã có CLI).
- Nợ kỹ thuật khác (chi tiết: [.claude/rules/tech-debt.md](../rules/tech-debt.md)):
  `forced_align` xấp xỉ tuyến tính; `speech_rate_cps` chưa hiệu chuẩn cho
  `elevenlabs`/`openai_tts`; `render` chưa áp `FitStrategy.VIDEO_STRETCH`;
  chưa có render preset (§14); `speaker_voices` chưa có cho `elevenlabs`;
  dry-run cost estimate (§17.1) chưa có; `onscreen_text` vẫn stub; Phase 3
  hạ tầng Celery/Redis chưa bắt đầu.

## 4. Bước tiếp theo

1. **Xác nhận commit/push CLI `manage_gates.py` + `resume_job()`** (đang
   chờ, chưa `git add`).
2. Lựa chọn còn mở từ phiên trước (chưa chọn cái nào): dry-run cost estimate
   (§17.1), Phase 5 (`publish`, OAuth từng nền tảng), hoặc việc nhỏ nâng chất
   lượng (hiệu chuẩn `speech_rate_cps`, `FitStrategy.VIDEO_STRETCH`, render
   preset).
3. Nếu người dùng lấy được `HF_TOKEN`: `.venv/bin/pip install pyannote.audio`,
   export `HF_TOKEN`, chạy lại `scripts/run_pipeline.py` để xác nhận diarize
   + multi-voice TTS chạy thật.
