# Tiến độ dự án — Tool Video Localization & Automation

> File này được ghi đè mỗi phiên. Đọc trước khi bắt đầu việc mới.

## 1. Mục tiêu

Phase 2 (kế hoạch v3) đã xong hoàn toàn — xem mục 2. Đang làm Phase 3:
approval gates (§11.2) + voice consent thực thi (§18.2), phần được người
dùng chọn ưu tiên kế tiếp sau khi Phase 2 hoàn tất.

## 2. Những phần đã hoàn thành

**Phase 2 — đã xong, đã commit+push** (diarize §6.5, multi-voice TTS §6.9,
font fallback §13.2/§14, compose §6.14 logo+CTA+intro/outro). Chi tiết từng
phần: [.claude/rules/diarization.md](../rules/diarization.md),
[.claude/rules/providers.md](../rules/providers.md),
[.claude/rules/fonts.md](../rules/fonts.md),
[.claude/rules/compose.md](../rules/compose.md).

**Approval gates + voice consent (§11.2, §18.2) — MỚI phiên này.** Chi tiết
đầy đủ (kể cả giới hạn đã biết): [.claude/rules/approval-gates.md](../rules/approval-gates.md).

- `services/approval_gates.py` (mới) — `ensure_gates()`/`approve()`, thuần
  đọc/ghi DB, idempotent.
- `core/orchestrator.py` — `GATE_AFTER_STAGE` (STT→transcript,
  TRANSLATE→translation, TIMELINE_ASSEMBLY→audio, QC→final),
  `Orchestrator._pending_gate`, `run_pipeline` dừng đúng chỗ khi cổng bật mà
  chưa duyệt (`job.status=NEEDS_REVIEW`, không ghi đè SUCCEEDED/progress=1.0).
  Tiếp tục sau khi duyệt = gọi lại `run_pipeline()`, không cần method riêng
  (mọi stage đã chạy cache-hit tức thì).
- `db/models.py` — `Project.approval_gates` (JSON, gate→bool, mặc định rỗng
  = tự động hoàn toàn).
- `services/pipeline_runner.py` — gọi `ensure_gates()` khi tạo/lấy job, đọc
  config từ `project.approval_gates`.
- `services/voice_consent.py` (mới) — `ensure_voice_consent()`: tra bảng
  `voices` theo `provider`+`provider_voice_id`, nếu `is_cloned=True` mà
  thiếu `VoiceConsent` hợp lệ (`is_valid_at()`) thì `NonRetryableError`. Chưa
  đăng ký = không chặn (không tự suy diễn is_cloned từ tên giọng).
- `workers/tts/stage.py` — `TTSStage._enforce_voice_consent()` gọi trước
  vòng lặp synthesize, gộp mọi voice (theo speaker + mặc định) kiểm 1 lần.
- Test mới: `test_approval_gates.py` (12 test — service + orchestrator dùng
  stage giả kiểu `test_cache_chain.py`), `test_voice_consent.py` (9 test).
- **Mặc định an toàn**: job không đi qua `ensure_gates`/voice không đăng ký
  trong bảng `voices` → không bị chặn gì — không phá bất kỳ test/luồng nào
  đã có từ trước (212/212 test cũ vẫn pass nguyên).

## 3. Trạng thái hiện tại

- **212/212 test pass** (`apps/api/tests`), pipeline thật vẫn chạy end-to-end
  đúng ~29s trên fixture 2 locale sau khi đổi orchestrator (đã chạy lại xác
  nhận bằng `scripts/run_pipeline.py`, gates mặc định tắt nên không có gì
  đổi hành vi khi không cấu hình).
- **Lỗi đã biết, KHÔNG phải mới**: QC `background_retained` FAIL trên
  es-ES — hạn chế của fixture tổng hợp (sine wave), không phải bug render.
- **Chưa commit/push**: toàn bộ code approval gates + voice consent phiên
  này (đã sửa/tạo file, CHƯA `git add`/commit).
- **Chưa kích hoạt được trên pipeline thật**: diarize + multi-voice TTS thật
  (chỉ test bằng mock — máy này chưa có `HF_TOKEN`); approval gates/voice
  consent cũng vậy — có test đầy đủ nhưng chưa từng bật gate thật trên một
  lần chạy `scripts/run_pipeline.py` (chưa có API/CLI để set
  `Project.approval_gates`/gọi `approve()` ngoài Python trực tiếp).
- Nợ kỹ thuật khác (chi tiết: [.claude/rules/tech-debt.md](../rules/tech-debt.md)):
  `forced_align` xấp xỉ tuyến tính; `speech_rate_cps` chưa hiệu chuẩn cho
  `elevenlabs`/`openai_tts`; `render` chưa áp `FitStrategy.VIDEO_STRETCH`;
  chưa có render preset (§14); `speaker_voices` chưa có cho `elevenlabs`;
  dry-run cost estimate (§17.1) chưa có; `onscreen_text` vẫn stub; Phase 3
  hạ tầng Celery/Redis chưa bắt đầu (đang chạy tuần tự trong 1 tiến trình).

## 4. Bước tiếp theo

1. **Xác nhận commit/push code approval gates + voice consent** (đang chờ,
   chưa `git add`).
2. Cân nhắc thêm CLI/script nhỏ để set `Project.approval_gates` và gọi
   `approve()` mà không cần mở Python thủ công — hiện chỉ dùng được qua
   test/script tự viết, chưa có đường vận hành thật.
3. Chọn ưu tiên kế tiếp sau khi approval gates/voice consent ổn định — các
   lựa chọn còn lại từ phiên trước vẫn mở: dry-run cost estimate (§17.1),
   Phase 5 (`publish`, OAuth từng nền tảng), hoặc việc nhỏ nâng chất lượng
   (hiệu chuẩn `speech_rate_cps`, `FitStrategy.VIDEO_STRETCH`, render preset).
4. Nếu người dùng lấy được `HF_TOKEN`: `.venv/bin/pip install pyannote.audio`,
   export `HF_TOKEN`, chạy lại `scripts/run_pipeline.py` để xác nhận diarize
   + multi-voice TTS chạy thật (hiện mới test bằng mock).
