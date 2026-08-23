# Data model

Nguồn sự thật cho schema là kế hoạch §10. Khi implement, tạo migration đủ 17 bảng:

**Giữ từ v2 (§10.1):** projects, source_videos, transcripts, speakers, translations,
voices, subtitle_presets, brand_profiles, render_jobs, output_files, publishing_jobs,
api_usage, error_logs.

**Segment 4 tầng, thay cho bảng `segments` cũ (§10.2):** stt_segments, translation_units,
tts_chunks, subtitle_cues, segment_links (mapping N:M).

**Mới ở v3 (§10.3):** segment_timing, approval_gates, voice_consents, onscreen_text,
stage_runs.

Chưa chọn công cụ migration (Alembic hay khác) — đó là một trong các việc đầu tiên
của Phase 0 (docs §20), chưa cần chốt trong lúc dựng khung thư mục này.
