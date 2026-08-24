# Nợ kỹ thuật đã biết

- `speech_rate_cps` trong `config/presets/locale/*.json` là ước lượng chung,
  chưa đo cho từng provider TTS (đã hiệu chuẩn riêng cho `macos_say` trong
  `config/tts/macos_say.json` — provider khác vẫn đang dùng ước lượng chung
  cho tới khi đo).
- `forced_align` là xấp xỉ tuyến tính, không phải alignment cấp phoneme — xem
  [subtitle.md](subtitle.md). Đủ cho subtitle timing, không đủ chính xác cho
  lip-sync hay karaoke-highlight.
- `render` chưa áp `FitStrategy.VIDEO_STRETCH` (co giãn hình) — quyết định này
  được lưu trong `SegmentTiming` nhưng chưa có stage nào đọc và thực thi nó.
  Compose (Phase 2, branding) là nơi hợp lý để làm việc này.
- `render` chưa có render preset (§14) để chọn bitrate/aspect ratio theo cấu
  hình — đang hard-code 6000k, giữ nguyên resolution/aspect nguồn.
- Multi-voice TTS theo speaker (`workers/tts/voice_assignment.py`) đã nối dây
  — nhưng `speaker_voices` (giọng phụ) trong config chỉ điền cho `macos_say`
  (en-US, fr-FR) và `openai_tts` (mọi locale). `elevenlabs` chưa có vì cần
  voice ID thật từ tài khoản, không tự bịa được. Xem [providers.md](providers.md).
- Font fallback (`font_stack` → filter `subtitles`) đã nối dây — xem
  [fonts.md](fonts.md). Chỉ bundle 3 family (Noto Sans/JP/Arabic) đủ cho 5
  locale hiện có; thêm locale hệ chữ mới (Hindi, Thái...) phải tải thêm font
  theo đúng quy trình trong `apps/api/assets/fonts/README.md`.
- Approval gates + voice consent (§11.2, §18.2) đã thực thi, có CLI
  (`scripts/manage_gates.py`) VÀ dashboard thật (§19, duyệt/xem cổng trong
  Video Workspace) — xem [approval-gates.md](approval-gates.md),
  [dashboard.md](dashboard.md). Còn thiếu: chưa có auth/phân quyền ở cả CLI
  lẫn dashboard; chưa có CLI/UI để đăng ký `Voice`/`VoiceConsent` (chỉ tạo
  được qua Python thủ công); cổng `transcript` khoá theo `render_job_id` nên
  duyệt cho locale này không tự duyệt cho locale khác của cùng source dù
  transcript dùng chung (`cache_scope=SOURCE`); `rerun_from` (partial re-run)
  không đi qua gate check.
- Dashboard Phase 4 (§19) mới làm "vòng vận hành lõi": Projects, Video
  Workspace (sửa inline translation, drift timeline, QC, approval gate),
  Batch Queue — xem [dashboard.md](dashboard.md). Còn thiếu: **Publishing
  Calendar** (chờ Phase 5 có `publish` thật mới có gì để hiện) và **Settings**
  (provider API key, concurrency, retention...); không auth; Batch Queue
  không tự refresh khi Celery đổi trạng thái job nền (phải tự tải lại trang).
- Ước tính chi phí dry-run trước khi batch chạy (§17.1) chưa có — soft/hard
  limit (nếu có) chỉ chặn được *khi đang chạy*, không cảnh báo trước.
- `onscreen_text` vẫn là `NotImplementedStage` — theo §15, `onscreen_text`
  còn bản ghi `pending` phải làm QC FAIL, nhưng QC hiện không có check này vì
  chưa có dữ liệu OCR thật để kiểm.
- Hạ tầng Phase 3 (Redis/Celery, worker tách tiến trình) đã có — xem
  [infra.md](infra.md). Dev viewer (`apps/api/api/routes/pipeline.py`) vẫn
  chạy đồng bộ có chủ ý (không phải dashboard Phase 4 thật); chỉ
  `scripts/run_pipeline.py --via-celery` đi qua worker. Worker BẮT BUỘC
  `--pool=solo` (đã set mặc định trong `scripts/worker.py`) vì `mlx-whisper`
  (Metal GPU) không sống sót qua `fork()` của pool `prefork` mặc định — đã
  bắt lỗi này khi chạy thử thật, không phải đoán. Chưa test nhiều job chạy
  song song thật sự (solo = xếp hàng tuần tự trong 1 worker); chưa có
  supervisor tự khởi động lại worker khi crash.
