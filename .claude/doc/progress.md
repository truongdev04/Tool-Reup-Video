# Tiến độ dự án — Tool Video Localization & Automation

> File này được ghi đè mỗi phiên. Đọc trước khi bắt đầu việc mới.

## 1. Mục tiêu

Hoàn thiện 4 phần còn thiếu của pipeline localization: stage `diarize`,
multi-voice TTS, font fallback cho hardsub, và `compose` Phase 2 đầy đủ
(logo+CTA+intro/outro) — theo kế hoạch v3 (§6.5, §6.9, §13.2, §6.14).

## 2. Những phần đã hoàn thành

**Diarize (§6.5)** — `pyannote.audio`, tự bỏ qua (không `NonRetryableError`)
khi thiếu thư viện/`HF_TOKEN` để không chặn pipeline của người chưa có token.
- `workers/diarization/assign.py` (module thuần, gán speaker theo overlap),
  `stage.py`; `services/diarization_pyannote.py` (backend I/O, lazy-import);
  `core/config.py` (`Settings.diarization_*`); `.claude/rules/diarization.md`.

**Multi-voice TTS (§6.9)** — nối `Speaker.voice_mapping` vào `tts`, biến
diarize thành có tác dụng thật lên audio.
- `workers/tts/voice_assignment.py` (module thuần — speaker đầu tiên = giọng
  mặc định, sau đó lấy từ pool phụ, giọng thủ công luôn thắng);
  `services/tts/base.py` (`speaker_voices`, `alt_voices_for`); `workers/tts/
  stage.py` (`_voice_assignment`, dùng chung cho `cache_params`+`run`);
  `config/tts/macos_say.json` (en-US/fr-FR), `openai_tts.json` (mọi locale).

**Font fallback cho hardsub (§13.2, §14)** — bundle 3 font Noto thật
(Latin/JP/Arabic, OFL license, `apps/api/assets/fonts/`), nối vào filter
`subtitles` (`fontsdir`/`force_style`) + QC đo glyph coverage thật.
- `services/fonts.py` (`resolve()` — nguồn DUY NHẤT cho cả `render` và `qc`);
  `services/qc_media.py::missing_glyphs()` (đọc `cmap` qua `fontTools`);
  `workers/qc/checks.py::check_font_coverage()` (FAIL, không WARN);
  `pyproject.toml` (+`fonttools`); `.claude/rules/fonts.md`.

**Compose Phase 2 đầy đủ (§6.14)** — logo → CTA → nối intro/outro.
- `services/compose_video.py` (+`overlay_cta`, `prepare_clip_for_concat`,
  `concat_clips`); `services/branding.py` (mới —
  `resolve_intro_outro_durations`, dùng chung `render`+`qc`);
  `workers/compose/stage.py` viết lại; `services/storage.py`
  (+`shared_dir()`); `services/ffmpeg.py` (+`escape_filter_value` dùng
  chung); `.claude/rules/compose.md`.
- **3 lỗi nghiêm trọng bắt được khi test bằng pipeline thật** (trích frame +
  đo `volumedetect`, không chỉ đọc code):
  1. `concat` từ chối nối do SAR lệch (`1:1` vs `18221:18225`) dù đã khớp
     resolution/fps → sửa `setsar=1`, ép cả clip chính qua cùng filter chain.
  2. **Audio/phụ đề lệch đồng bộ**: intro/outro làm video dài hơn audio (§9)
     và SRT (§8.3) vốn chỉ tính theo timeline nội dung chính → giọng đọc phát
     đè lên intro, outro bị `-shortest` cắt mất. Sửa: `render` dịch audio
     (`adelay`+`apad`) và viết lại SRT dịch offset trước khi burn; `qc` cộng
     offset vào `expected_duration_ms` và điểm lấy mẫu `background_retained`.
  3. **Cache "gà và trứng"**: `compose` không override `cache_params` (brand
     đổi mà cache không invalidate); sửa xong thì `cache_params` đọc
     `project.brand_profile_id` TRƯỚC khi `run()` kịp tạo brand placeholder,
     khiến job locale 2 tính ra cache key khác job 1 → compose chạy 2 lần
     thay vì 1. Sửa: `cache_params()` tự gọi `_resolve_brand` (idempotent).
- Tiện sửa 1 lỗi có sẵn: brand placeholder dùng chung mọi project nhưng lưu
  theo `project_id` → `Storage.shared_dir()` (ngoài `projects/`), thêm
  `storage/shared/` vào `.gitignore` (suýt commit nhầm asset runtime).

**Git/GitHub**: thêm remote `origin` → `https://github.com/truongdev04/
Tool-Reup-Video.git` (public), `git push -u origin main` thiết lập tracking.
4 commit đã push (rules refactor, diarize, multi-voice TTS, font fallback).

## 3. Trạng thái hiện tại

- **192/192 test pass** (`apps/api/tests`), pipeline chạy thật end-to-end
  trên fixture 7s × 2 locale (es-ES, ja-JP): ~28s (DoD §21: 2 phút).
- Đã xác nhận bằng mắt: intro/outro/CTA hiện đúng vị trí, đúng font Noto Sans
  có dấu tiếng Việt, audio im lặng đúng trong intro/outro (-91dB) và có tiếng
  trong nội dung chính, `compose` chỉ chạy 1 lần cho 2 locale (cache đúng).
- **Lỗi đã biết, KHÔNG phải mới**: QC `background_retained` FAIL trên
  es-ES — hạn chế của fixture tổng hợp (sine wave), không phải bug render.
- **Chưa commit/push**: toàn bộ code compose Phase 2 (đã `git add`, chưa
  commit) — diarize/multi-voice/font fallback đã commit+push từ trước.
- **Chưa kích hoạt được trên pipeline thật** (chỉ test bằng mock/provider
  giả): diarize + multi-voice TTS — máy này chưa cài `pyannote.audio`/chưa
  có `HF_TOKEN` (hướng dẫn 3 bước ở README mục "Diarize (§6.5)").
- Nợ kỹ thuật khác (chi tiết: `.claude/rules/tech-debt.md`): `forced_align`
  xấp xỉ tuyến tính; `speech_rate_cps` chưa hiệu chuẩn cho `elevenlabs`/
  `openai_tts`; `render` chưa áp `FitStrategy.VIDEO_STRETCH`; chưa có render
  preset (§14, bitrate hard-code); `speaker_voices` chưa có cho `elevenlabs`;
  font fallback mới phủ 5 locale hiện có; approval_gates/voice_consents có
  bảng DB nhưng chưa stage nào dùng; CTA/intro-outro không dịch theo locale
  (quyết định có chủ ý, giữ `compose.cache_scope=SOURCE`).

## 4. Bước tiếp theo

1. **Xác nhận commit/push code compose Phase 2** (đang chờ, đã `git add`).
2. Chọn ưu tiên kế tiếp — Phase 2 của kế hoạch nay đã xong hoàn toàn:
   Phase 3 (approval_gates + voice_consents thực thi, dry-run cost §17.1)
   hay Phase 5 (`publish`, OAuth từng nền tảng)?
3. Nếu người dùng lấy được `HF_TOKEN`: `.venv/bin/pip install pyannote.audio`,
   export `HF_TOKEN`, chạy lại `scripts/run_pipeline.py` để xác nhận diarize
   + multi-voice TTS chạy thật (hiện mới test bằng mock).
4. Việc nhỏ hơn nếu cần nâng chất lượng: hiệu chuẩn `speech_rate_cps` cho
   `elevenlabs`/`openai_tts`, thực thi `FitStrategy.VIDEO_STRETCH`, render
   preset (§14).
