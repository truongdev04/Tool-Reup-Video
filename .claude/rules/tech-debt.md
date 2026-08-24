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
- `ApprovalGateRecord`/`approval_gates` và `VoiceConsent`/`voice_consents`
  (§11.2, §18.2) có bảng trong DB (Phase 0) nhưng KHÔNG có stage/API nào đọc
  hay ghi — 4 cổng duyệt (transcript/translation/audio/final) không được thực
  thi, và `tts` không chặn khi voice profile thiếu consent hợp lệ như plan
  yêu cầu ("TTS chặn nếu voice profile không có consent hợp lệ", §18.2).
- Ước tính chi phí dry-run trước khi batch chạy (§17.1) chưa có — soft/hard
  limit (nếu có) chỉ chặn được *khi đang chạy*, không cảnh báo trước.
- `onscreen_text` vẫn là `NotImplementedStage` — theo §15, `onscreen_text`
  còn bản ghi `pending` phải làm QC FAIL, nhưng QC hiện không có check này vì
  chưa có dữ liệu OCR thật để kiểm.
- Hạ tầng Phase 3 (Redis/Celery, worker tách tiến trình) chưa bắt đầu — toàn
  bộ pipeline vẫn chạy tuần tự trong một tiến trình qua
  `scripts/run_pipeline.py`/dev viewer.
