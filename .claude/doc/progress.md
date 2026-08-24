# Tiến độ dự án — Tool Video Localization & Automation

> File này được ghi đè mỗi phiên. Đọc trước khi bắt đầu việc mới để biết ngay
> trạng thái mà không phải đọc lại toàn bộ lịch sử commit.

## 1. Mục tiêu

Xây tool nội bộ: 1 video gốc → dịch/lồng tiếng/phụ đề/thương hiệu → xuất nhiều
phiên bản ngôn ngữ, theo kế hoạch kiến trúc v3
(`docs/Ke_Hoach_Tool_Video_Localization_Automation_v3.md`).

## 2. Những phần đã hoàn thành

### Kế hoạch
- Phản biện kế hoạch v2 (docx), viết lại thành v3 (.md, 23 mục): thêm §7
  Duration Fitting, §8 Forced Alignment, mô hình segment 4 tầng (§5), kéo data
  model lên Phase 0.

### Phase 0 — nền tảng
- `apps/api/db/models.py`: 23 bảng SQLAlchemy.
- `apps/api/core/stage.py`, `core/orchestrator.py`: stage contract, cache
  (nối chuỗi `input_hash`+`output_digest` giữa các stage), retry, partial
  re-run, `CacheScope` (SOURCE/JOB).
- `apps/api/services/storage.py`: layout theo project/job, `RETENTION_DAYS`.
- `scripts/run_pipeline.py`, `apps/api/services/pipeline_runner.py`: harness
  CLI dùng chung với dev viewer.
- Môi trường chốt: Python 3.12, `ffmpeg-full` (không phải `ffmpeg` thường —
  thiếu libass/freetype).

### Phase 1 + đầu Phase 2 — 15/18 stage thật (3 stub còn lại: `onscreen_text`,
`lipsync`, `publish`)

| Stage | File chính | Công nghệ |
|---|---|---|
| `ingest`, `analyze` | `workers/ingest/`, `workers/analyzer/` | checksum, ffprobe |
| `separate` | `workers/audio/`, `services/audio_timeline.py` | Demucs htdemucs (MPS) |
| `stt` | `workers/stt/` | mlx-whisper (Metal), word timestamps |
| `diarize` | `workers/diarization/`, `services/diarization_pyannote.py` | pyannote.audio; **tự bỏ qua** (không chặn pipeline) nếu thiếu thư viện/`HF_TOKEN` — xem mục 4 |
| `segment_plan` | `workers/segment_planner/planner.py` | gộp STT segment → translation_units |
| `translate` | `workers/translation/`, `services/providers/` | 8 provider (claude/openai/gemini/openrouter/9router/ollama/lmstudio/mock), thêm provider mới = thả JSON |
| `duration_fit`, `tts` | `workers/duration_fit/fitter.py`, `workers/tts/` | 5 chiến lược: constrained_translation → borrow_silence → tempo_adjust → pad_silence → video_stretch; provider TTS (macos_say/elevenlabs/openai_tts) |
| `forced_align` | `workers/forced_align/aligner.py` | KHÔNG dùng WhisperX/MFA — mlx-whisper chạy lại trên audio TTS lấy ranh giới đoạn, rải ký tự theo tỉ lệ |
| `timeline_assembly` | `services/audio_timeline.py` | đặt tts_chunk vào `unit.start_ms` tuyệt đối (wave+numpy) |
| `subtitle` | `workers/subtitle/splitter.py` | cắt cue theo CPS/chars_per_line/max_lines, xuất SRT |
| `compose` | `services/compose_video.py`, `workers/compose/stage.py` | overlay logo/watermark, `cache_scope=SOURCE`, tự sinh brand placeholder nếu chưa có |
| `render` | `workers/render/stage.py`, `services/audio_mix.py` | trộn voice+background, loudnorm 2 lượt, burn hardsub, encode h264_videotoolbox |
| `qc` | `workers/qc/checks.py`, `services/qc_media.py` | 10 check tự động, verdict PASS/WARN/FAIL |

### Dev viewer
- `apps/api/api/` (FastAPI + vanilla JS/CSS): chạy pipeline, xem log từng
  stage, nghe audio từng chunk, xem video FINAL + verdict QC trên trình duyệt.
- Chạy: `VLA_DEV_FAST=1 .venv/bin/uvicorn api.main:app --app-dir apps/api --port 8787 --reload`

### Công cụ hỗ trợ
- `scripts/calibrate_speech_rate.py`: đo tốc độ đọc thật theo từng provider TTS
  (đã đo cho `macos_say`, lệch tới +42% so với ước lượng ban đầu).

### 9 lỗi thiết kế/cache phát hiện và đã sửa (kèm test chặn hồi quy) — xem chi
tiết ở các phiên trước, tóm tắt trong `.claude/rules/caching.md` và
`.claude/rules/qc.md`. Không lặp lại ở đây để tránh trùng.

## 3. Việc làm trong phiên này

**Diarize (§6.5) — implement thật, thay `NotImplementedStage`.**

- `apps/api/workers/diarization/assign.py`: module thuần — gán speaker cho
  từng `stt_segment` theo overlap lớn nhất với các lượt nói diarization.
  Segment không chồng lấn lượt nói nào thì giữ nguyên `speaker_id=None` (không
  bịa giá trị mặc định).
- `apps/api/services/diarization_pyannote.py`: backend I/O — lazy-import
  `pyannote.audio`, đọc `HF_TOKEN` (tên biến chuẩn của HuggingFace, không đi
  qua cơ chế `api_key_env` như provider dịch/TTS vì chỉ có một backend).
- `apps/api/workers/diarization/stage.py`: `DiarizeStage`, `cache_scope=SOURCE`
  (giống `stt`), `cache_params` override để đưa `diarization_model` vào key.
- **Quyết định thiết kế quan trọng nhất**: thiếu `pyannote.audio` hoặc
  `HF_TOKEN` → stage **bỏ qua, KHÔNG `NonRetryableError`** (lệch có chủ ý so
  với coding-style.md, ghi rõ lý do trong docstring + rule file mới). Lý do:
  trước khi stage này tồn tại, mọi `speaker_id` đã mãi mãi `None` và cả
  pipeline vẫn chạy tốt — bắt buộc token mới chạy được sẽ là regression cho
  bất kỳ ai chưa có token. `_clear_previous` chạy trên CẢ hai nhánh (bỏ qua
  lẫn thành công) để không lệch giữa `note` và dữ liệu DB.
- Đăng ký thật vào `workers/registry.py` (bỏ khỏi `_PLANNED_PHASE`).
- Thêm `Settings.diarization_model/_min_speakers/_max_speakers`
  (`core/config.py`, đọc qua `VLA_DIARIZATION_*`).
- Rule file mới: `.claude/rules/diarization.md` — đặc biệt ghi lại nợ kỹ
  thuật: `Speaker.voice_mapping` đã có trong DB nhưng `TTSStage` chưa đọc nó —
  nghĩa là **chạy diarize xong, audio xuất ra chưa đổi giọng theo người nói**.
  Giá trị hiện tại của diarize chỉ là dữ liệu `speaker_id` đúng trong DB; nối
  dây multi-voice TTS là việc tiếp theo, cố ý để riêng (theo yêu cầu người
  dùng — không gộp 2 việc lớn cùng lúc).
- Test mới: `apps/api/tests/test_diarization.py` (8 test) — 4 test module
  thuần (`assign.py`), 4 test stage (bỏ qua khi thiếu pyannote — chạy THẬT
  không cần mock vì môi trường dev đúng là chưa cài; gán speaker thật + đo
  `total_speech_ms` bằng mock 2 hàm biên I/O; idempotency chạy lại 2 lần không
  tạo `Speaker` trùng; cache_scope).
- Đã xác nhận bằng `scripts/run_pipeline.py` thật: `diarize` chạy sau `stt`,
  bỏ qua đúng như thiết kế (`bỏ qua diarization — chưa cài pyannote.audio...`),
  cache hit đúng cho locale thứ hai (SOURCE scope hoạt động), pipeline vẫn đạt
  DoD §21 (~22s < 120s).
- Cập nhật README.md (bảng trạng thái stage, mục "Diarize (§6.5)" hướng dẫn 3
  bước lấy `HF_TOKEN`, mục "Việc tiếp theo"), `CLAUDE.md` (thêm dòng bản đồ
  rule cho `workers/diarization/`).

**Multi-voice TTS theo speaker — nối `Speaker.voice_mapping` vào `tts`.**

- `apps/api/workers/tts/voice_assignment.py`: module thuần —
  `resolve_voice_assignment(speakers, default_voice, alt_voices)`. Speaker đầu
  tiên (theo `label` sắp xếp) luôn nhận `default_voice` (không đổi hành vi
  video đơn thoại/cache cũ); speaker sau lấy lần lượt từ `alt_voices`, hết
  pool thì quay lại `default_voice` thay vì lỗi; `manual_voice` (đã set trong
  `Speaker.voice_mapping`) luôn thắng.
- `TTSConfig` (`services/tts/base.py`) thêm field `speaker_voices` +
  `alt_voices_for(locale)`. **Lưu ý**: `registry.load_config` chặn field JSON
  lạ — phải thêm field vào dataclass TRƯỚC khi thêm vào file JSON (đã gặp lỗi
  này khi thử thêm `_comment_...` vào `macos_say.json`, bắt lại và sửa ngay).
- `TTSStage._voice_assignment()`: đọc `TranslationUnit.speaker_id` +
  `Speaker` của job, gọi module thuần ở trên, rồi **ghi lại** giá trị tự động
  vào `Speaker.voice_mapping[locale]` — CHỈ điền chỗ trống, không ghi đè giá
  trị thủ công (idempotent). Dùng chung một hàm cho cả `cache_params()`
  (persist=False) và `run()` (persist=True) để tránh lệch logic.
  `cache_params()` phải tự thêm `voice_assignment` — đây là dữ liệu riêng của
  `tts`, không stage nào "mang hộ" (đúng caching.md mục 4).
- Config: `config/tts/macos_say.json` thêm `speaker_voices` cho **en-US**
  (Fred, Kathy, Ralph) và **fr-FR** (Jacques) — đã xác minh từng giọng gọi
  được thật bằng `say -v <tên> -o ...`. Các locale còn lại (es-ES, ja-JP,
  vi-VN...) CHƯA có giọng phụ an toàn — giọng `say` khác chỉ tồn tại dưới tên
  gắn ngôn ngữ hiển thị hệ thống (vd. "Eddy (Tiếng Tây Ban Nha...)"), phụ
  thuộc ngôn ngữ macOS đang set nên không đưa vào config chung được. Đã ghi
  rõ giới hạn này vào `providers.md`, không âm thầm bỏ qua.
  `config/tts/openai_tts.json` thêm `speaker_voices` cho mọi locale (echo,
  onyx, fable — giọng cố định của OpenAI TTS, dùng chung mọi ngôn ngữ theo
  tài liệu chính thức). `elevenlabs.json` CHƯA có — cần voice ID thật từ tài
  khoản, không tự bịa.
- Test mới: `apps/api/tests/test_tts_voice_assignment.py` (9 test) — 4 test
  module thuần, 5 test stage dùng `_FakeProvider` giả (không gọi `say`/API
  thật): 2 speaker ra 2 giọng khác nhau; không có speaker thì `voice=None`
  (giữ nguyên hành vi cũ khi diarize bị bỏ qua); tự ghi `voice_mapping`; giọng
  thủ công không bị ghi đè; `cache_params` phản ánh đúng `voice_assignment`.
- Đã chạy `scripts/run_pipeline.py` thật sau khi sửa: `tts` cache-miss đúng 1
  lần (do thêm `voice_assignment` vào cache_params — bump hợp lệ), toàn bộ
  pipeline vẫn chạy hết, hành vi audio không đổi (vì diarize vẫn đang bỏ qua
  trong môi trường này → mọi speaker_id vẫn `None` → không có gì để multi-voice
  kích hoạt cho tới khi có `HF_TOKEN`).
- Cập nhật `.claude/rules/diarization.md` (bỏ mục nợ kỹ thuật cũ, thêm mục
  "Multi-voice TTS theo speaker"), `.claude/rules/providers.md` (mục mới),
  `.claude/rules/tech-debt.md` (thay dòng cũ bằng giới hạn elevenlabs).

**Font fallback cho hardsub (§13.2, §14) — nối `font_stack` vào filter
`subtitles` thật + QC font coverage.**

- Đã KIỂM CHỨNG THỰC TẾ trước khi code (không đoán): render thử SRT có tiếng
  Nhật/Ả Rập qua filter `subtitles` KHÔNG sửa gì — libass/fontconfig trên máy
  dev (macOS) vẫn tự fallback đúng nhờ Hiragino Sans/Geeza Pro có sẵn trong
  hệ thống. Nghĩa là bug §13.2 cảnh báo không tái hiện được trên máy này, NHƯNG
  đó là hành vi phụ thuộc font hệ thống — không đảm bảo trên server không có
  các font đó. Quyết định: vẫn bundle font thật (theo đúng khuyến nghị của kế
  hoạch "Nhúng bộ Noto") để hành vi ổn định, không tuỳ theo máy chạy.
- Tải 3 font Noto thật từ `google/fonts` (giấy phép OFL, tự do nhúng): Noto
  Sans (Latin, phủ cả tiếng Việt có dấu), Noto Sans JP, Noto Sans Arabic. File
  gốc là variable font — dùng `fontTools.varLib.instancer --update-name-table`
  "đóng băng" về static Regular (giảm dung lượng, tránh ứng xử khó đoán của
  variable font trên libass cũ). **Bắt lỗi trong lúc làm**: thiếu
  `--update-name-table` khiến tên family trong `NotoSansJP-Regular.ttf` bị sai
  thành "Noto Sans JP **Thin**" (giữ theo default axis GỐC 100=Thin thay vì
  toạ độ 400=Regular vừa pin) — phát hiện bằng cách tự đọc `name` table qua
  `fontTools` trước khi dùng, không phải đoán. Đã sửa, xác nhận lại tên đúng.
  Lưu ở `apps/api/assets/fonts/` (~6,6MB, kèm `manifest.json` + `README.md`
  ghi rõ nguồn/license/quy trình tạo + `OFL.txt`).
- `services/fonts.py` (module mới): `resolve(font_stack, fonts_dir)` — nguồn
  DUY NHẤT quyết định family/font file cho một locale, `render` VÀ `qc` đều
  gọi chung (tránh lệch giữa font đã RENDER và font QC đã KIỂM). `font_stack`
  rỗng hoặc không family nào có file thật → trả rỗng, không ép `force_style`
  (bỏ qua, không chặn render — cùng nguyên tắc `diarize`/`compose`).
- `workers/render/stage.py`: filter `subtitles` giờ kèm
  `fontsdir='...':force_style='FontName=...'` khi có font bundle.
- `services/qc_media.py::missing_glyphs()` (đo thật qua bảng `cmap` của font
  bằng `fontTools`) + `workers/qc/checks.py::check_font_coverage()` (luật
  thuần — **FAIL, không WARN**: thiếu glyph là ô vuông nhìn thấy ngay, khác
  hẳn tình huống `cue_cps` được mềm hoá có chủ ý) + nối vào `workers/qc/stage.py`.
- `pyproject.toml`: thêm `fonttools>=4.50` (dependency thật, nhẹ — khác nhóm
  với `pyannote.audio`/torch không khai trong pyproject).
- Test mới: `apps/api/tests/test_fonts.py` (14 test — `resolve()` module
  thuần với thư mục giả; `missing_glyphs()` đo THẬT trên chính 3 font đã
  bundle trong repo cho cả 4 locale, kèm 1 test âm: ký tự Cherokee không nằm
  trong font nào phải bị phát hiện thiếu; `check_font_coverage` FAIL/PASS),
  `apps/api/tests/test_render_subtitle_filter.py` (3 test — cú pháp filter,
  dùng `fonts_dir` thật của repo để xác nhận manifest khớp `font_stack` từng
  locale, không lệch tên).
- Đã chạy pipeline thật từ đầu (không cache) sau khi sửa: `render` chạy thật
  (1984ms, không lỗi cú pháp filter), trích 1 frame từ video final es-ES ra
  xem trực tiếp — chữ hiện đúng, rõ, đúng font Noto Sans (không phải font hệ
  thống mặc định của ffmpeg). QC không phát sinh FAIL font_coverage mới trên
  cả 2 locale (text mock ASCII được Noto Sans phủ đầy đủ).
- Cập nhật `.claude/rules/fonts.md` (rule file mới), `.claude/rules/qc.md`,
  `.claude/rules/tech-debt.md` (bỏ mục font_stack cũ), `CLAUDE.md` (thêm dòng
  bản đồ rule), `README.md` (dòng `render` trong bảng trạng thái).

### Việc khác trong phiên này
- Xác nhận nội dung `.claude/rules/*.md`, `.claude/README.md`, `.mcp.json` từ
  phiên trước — khớp với `CLAUDE.md` đã refactor, không có gì bất thường.
  Theo yêu cầu người dùng: **đã `git add` (tracked), CHƯA commit** — người
  dùng nói rõ "chỉ tracked thôi không commit".
- Sửa `.claude/README.md` — dòng "mọi thư mục con đang trống" không còn đúng
  sau khi `doc/`, `rules/` có nội dung.

## 4. Trạng thái hiện tại

- **176/176 test pass** (`apps/api/tests`) — 142 cũ + 8 diarize + 9 multi-voice
  TTS + 14 font fallback + 3 render subtitle filter.
- Pipeline chạy thật end-to-end trên fixture 7s, 2 locale (es-ES, ja-JP):
  **~22s lần đầu** (DoD §21: 2 phút). QC báo `needs_review` ở es-ES do nền quá
  yếu sau mix (~-55dBFS) — đây là hạn chế đã biết của fixture (sine wave tổng
  hợp, Demucs tách kém), không phải lỗi mới, xem mục #9 lịch sử lỗi đã sửa.
- Git: **TOÀN BỘ file của phiên này (diarize + multi-voice TTS + font
  fallback) đã `git add` (tracked), CHƯA commit** — theo đúng quy ước người
  dùng chốt đầu phiên ("chỉ tracked thôi không commit"). Gồm cả file nhị phân
  mới: 3 font `.ttf` + `OFL.txt` trong `apps/api/assets/fonts/` (~6,6MB).
- Nợ kỹ thuật đã biết (xem thêm `.claude/rules/tech-debt.md`,
  `.claude/rules/diarization.md`, `.claude/rules/providers.md`,
  `.claude/rules/fonts.md`):
  - `forced_align` là xấp xỉ tuyến tính (không phải alignment cấp phoneme).
  - `speech_rate_cps` mới hiệu chuẩn cho `macos_say`; `elevenlabs`/`openai_tts`
    còn dùng ước lượng chung.
  - `render` chưa áp dụng `FitStrategy.VIDEO_STRETCH` thật.
  - Chưa có render preset (§14) — bitrate hard-code 6000k.
  - `speaker_voices` (giọng phụ multi-voice) mới điền cho `macos_say`
    (en-US, fr-FR) và `openai_tts` (mọi locale) — `elevenlabs` chưa có, cần
    voice ID thật từ tài khoản.
  - Font fallback chỉ bundle 3 family (Noto Sans/JP/Arabic) đủ cho 5 locale
    hiện có — thêm locale hệ chữ mới (Hindi, Thái...) phải tải thêm font.
  - `pyannote.audio` chưa được cài trong `.venv` của máy này (người dùng chưa
    có `HF_TOKEN` — đã chọn "cần hướng dẫn trước" thay vì tự set env ngay).
    README mục "Diarize (§6.5)" có 3 bước cụ thể để lấy token khi người dùng
    sẵn sàng. **Cho tới khi có token, multi-voice TTS vừa xây cũng không tự
    kích hoạt được trên pipeline thật** (không có speaker nào để phân biệt) —
    chỉ chạy được qua test với provider giả.

## 4b. Rà soát theo Roadmap §20 — còn thiếu gì trong từng Phase

Đối chiếu code thật với bảng Phase §20 của kế hoạch (không chỉ đọc tên stage):

- **Phase 1 (trục localization):** ✅ xong hết (ingest → render).
- **Phase 2 (chất lượng):** audio reconstruction + loudnorm ✅, diarization ✅,
  voice profiles ✅, font fallback ✅ (cả ba trong phiên này) — còn thiếu:
  branding đầy đủ (CTA động/intro-outro — cần asset thật).
- **Phase 3 (hạ tầng):** cache + partial re-run + retry + QC tự động ✅ (đã
  làm sớm từ Phase 0 theo đúng chủ đích của v3, xem §0 mục 4) — còn thiếu:
  **approval_gates** và **voice_consents** có bảng DB nhưng KHÔNG stage/API
  nào đọc/ghi (4 cổng duyệt không được thực thi; TTS không chặn giọng thiếu
  consent như §18.2 yêu cầu), Redis/Celery/worker tách tiến trình (chưa cần
  vì chưa chạy batch thật).
- **Phase 4 (dashboard):** chưa bắt đầu — dev viewer FastAPI/vanilla JS chỉ
  là công cụ xem tạm thời (README ghi rõ "KHÔNG phải dashboard Phase 4").
- **Phase 5 (publishing):** stub.
- **Phase 6:** lip-sync, onscreen_text inpainting — stub.

Toàn bộ danh sách nợ kỹ thuật chi tiết (kèm lý do + file liên quan) đã ghi vào
[.claude/rules/tech-debt.md](../rules/tech-debt.md) — đọc file đó trước khi
bắt đầu việc mới, đây là quy ước sẵn có của project (xem bảng ánh xạ rule
trong CLAUDE.md), không lặp lại nội dung ở đây.

## 5. Bước tiếp theo

1. **Người dùng lấy `HF_TOKEN`** theo hướng dẫn ở README mục "Diarize (§6.5)"
   nếu muốn diarize + multi-voice TTS chạy thật trên pipeline (không bắt buộc
   — pipeline vẫn chạy tốt khi bỏ qua, chỉ là mọi speaker chung một giọng như
   trước). Sau khi có token: `.venv/bin/pip install pyannote.audio`, export
   `HF_TOKEN`, chạy lại `scripts/run_pipeline.py` để xác nhận cả hai nhánh
   thành công trên model/audio thật (hiện mới test bằng mock).
2. **Xác nhận có commit các file của phiên này không** (diarize + multi-voice
   TTS + font fallback, đã `git add`, chưa commit) — chưa hỏi.
3. Còn thiếu ở Phase 2/3 theo rà soát mục 4b — pick 1 khi cần làm tiếp:
   branding đầy đủ (CTA/intro-outro, cần asset thương hiệu thật), approval
   gates + voice consents thực thi, dry-run cost estimate (§17.1). Chi tiết ở
   [.claude/rules/tech-debt.md](../rules/tech-debt.md).
4. Ưu tiên `publish` (OAuth từng nền tảng, Phase 5) hay hoàn thiện `compose`
   Phase 2 đầy đủ trước? Chưa tự quyết được, cần người dùng chọn.
5. Nếu tiếp tục nâng chất lượng thay vì thêm stage mới: hiệu chuẩn
   `speech_rate_cps` cho `elevenlabs`/`openai_tts`, thực thi
   `FitStrategy.VIDEO_STRETCH` trong `compose`/`render`, thêm render preset
   (§14) để chọn bitrate/aspect ratio thay vì hard-code.
