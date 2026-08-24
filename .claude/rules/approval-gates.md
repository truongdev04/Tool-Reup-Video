# Approval gates & voice consent (§11.2, §18.2)

Biến "manual review" và "đồng thuận giọng nói" từ câu chữ trong tài liệu
thành dữ liệu kiểm tra được — nguyên tắc chung của §18.2.

## Approval gates (§11.2)

Bốn cổng theo thứ tự `transcript -> translation -> audio -> final`, mỗi cổng
là một bản ghi `ApprovalGateRecord` (bảng `approval_gates`) khoá theo
`render_job_id` + `gate`.

- `services/approval_gates.py` — thuần đọc/ghi DB, không điều phối:
  `ensure_gates()` tạo đủ 4 bản ghi cho một job (idempotent, không đụng bản
  ghi đã có kể cả đã duyệt), `approve()` ghi `approved_by`/`approved_at`.
- `core/orchestrator.py::GATE_AFTER_STAGE` ánh xạ stage nào xong thì cổng nào
  (nếu bật, chưa duyệt) chặn lại: `STT -> transcript`, `TRANSLATE ->
  translation`, `TIMELINE_ASSEMBLY -> audio`, `QC -> final`.
  `Orchestrator._pending_gate` đọc bản ghi; `run_pipeline` dừng ngay sau stage
  đó, đặt `job.status = NEEDS_REVIEW`, **không** ghi đè bằng
  `SUCCEEDED`/`progress=1.0` như đường hoàn tất bình thường.
- **Tiếp tục sau khi duyệt**: `services/pipeline_runner.py::resume_job()` gọi
  lại `run_pipeline()` (không cần method riêng trong `Orchestrator`) — mọi
  stage đã chạy trước cổng cache-hit tức thì (§16), pipeline chỉ thực sự chạy
  tiếp từ chỗ dừng. `resume_job()` đọc `job.presets` (provider dịch/TTS đã
  lưu lúc `run_for_video()` tạo/chạy job lần đầu) để KHÔNG vô tình đổi
  provider giữa chừng.
- **Vận hành qua CLI**: `scripts/manage_gates.py` — `list` (xem trạng thái 4
  cổng của một job hoặc mọi job của một project), `set-project` (bật/tắt cổng
  mặc định cho job MỚI), `set-job` (bật/tắt trực tiếp một job đã tồn tại),
  `approve`, `resume`. Xem docstring đầu file để có ví dụ đầy đủ. Đã chạy thử
  trên pipeline thật (không phải chỉ unit test): tạo project với
  `approval_gates={"transcript": True}`, chạy pipeline dừng đúng sau `stt`,
  `list` hiện đúng "CHỜ DUYỆT", `approve` rồi `resume` chạy tiếp — 4 stage đầu
  cache-hit, các stage sau chạy thật tới khi xong.
- **Cấu hình bật/tắt theo project**: `Project.approval_gates` (JSON,
  `ApprovalGate` -> bool). `services/pipeline_runner.py` gọi `ensure_gates()`
  ngay khi tạo/lấy `RenderJob`, đọc config từ đó. Thiếu key nào = tắt (chạy
  tự động) — project mới mặc định rỗng, đúng "project chạy tự động hoàn toàn
  thì tắt hết".
- **Mặc định an toàn khi thiếu bản ghi cổng**: job không đi qua
  `ensure_gates` (test dựng `StageContext` thẳng, hoặc code gọi
  `Orchestrator` mà không qua `pipeline_runner`) thì `_pending_gate` luôn trả
  `None` — không tự chặn gì. Cùng nguyên tắc "thiếu cấu hình thì bỏ qua" của
  `diarize`/`compose` (xem [diarization.md](diarization.md),
  [compose.md](compose.md)) — không phải lỗ hổng, là lựa chọn có chủ ý để
  không phá vỡ mọi test/luồng chưa biết tới approval gates.

### Giới hạn đã biết

- **Cổng `transcript` không dùng chung giữa các locale của cùng source.**
  `approval_gates` khoá theo `render_job_id`, kể cả với STT vốn
  `cache_scope=SOURCE` (không phụ thuộc locale) — duyệt transcript cho job
  es-ES không tự động duyệt cho job ja-JP dù cùng một bản STT. Chấp nhận vì
  đổi sang khoá theo source đòi hỏi sửa schema `approval_gates` (đã có từ
  Phase 0) — để riêng, không sửa trong lượt này.
- **`rerun_from` (partial re-run, §11.3) không đi qua gate check.** Gate chỉ
  được kiểm trong `run_pipeline`, không trong `run_stage`/`rerun_from` — coi
  đây là đường vận hành nội bộ đáng tin (người đã biết mình đang sửa gì), có
  chủ đích không chặn lại.
- Chưa có API/dashboard thật (Phase 4) — `scripts/manage_gates.py` là CLI nội
  bộ, không có auth/phân quyền ai được gọi `approve`.

## Voice consent (§18.2)

`services/voice_consent.py::ensure_voice_consent()` được `TTSStage` gọi
TRƯỚC vòng lặp synthesize (`workers/tts/stage.py::_enforce_voice_consent`),
gộp mọi voice ID sẽ dùng trong job (giọng theo speaker + giọng mặc định —
xem [diarization.md](diarization.md) mục multi-voice).

Bảng `voices` (model `Voice`) là nơi ĐĂNG KÝ một `provider_voice_id` cụ thể
LÀ giọng nhân bản: không có bản ghi khớp `provider` + `provider_voice_id` thì
coi như không phải giọng nhân bản, **không chặn** — không tự suy diễn
`is_cloned` từ tên giọng. Đây là điểm khác biệt quan trọng với cách TTS chọn
giọng thật sự: `services/tts/*.json` (`TTSConfig.voices`/`speaker_voices`,
xem [providers.md](providers.md)) mới là nguồn cấu hình giọng THẬT — bảng
`Voice` hoàn toàn tách biệt, chỉ dùng để đăng ký "voice_id này cần consent".

Có bản ghi, `is_cloned=True`, nhưng thiếu `consent` hoặc `consent.is_valid_at()`
sai (hết hạn/bị thu hồi/chưa tới ngày hiệu lực) → `NonRetryableError`, chặn
TTS ngay từ đầu `run()` — không tốn công synthesize rồi mới báo lỗi giữa
chừng.

### Giới hạn đã biết

- Chỉ enforce khi `TTSStage.run()` thực sự chạy. Một job cache-hit (§16)
  không đi qua lại đường này — consent bị thu hồi SAU khi audio đã cache thì
  không tự động chặn việc tái dùng audio cũ đó.
- Không có UI/API để đăng ký `Voice`/`VoiceConsent` — hiện chỉ tạo được qua
  Python (script, migration thủ công, hoặc endpoint tương lai ở Phase 4).
