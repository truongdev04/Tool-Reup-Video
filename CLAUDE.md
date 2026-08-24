# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Ngôn ngữ

Toàn bộ tài liệu, comment, docstring, thông báo lỗi và commit message trong dự án
này viết bằng **tiếng Việt**. Giữ nguyên quy ước đó khi thêm code mới.

## Kế hoạch kiến trúc là nguồn chân lý

[docs/Ke_Hoach_Tool_Video_Localization_Automation_v3.md](docs/Ke_Hoach_Tool_Video_Localization_Automation_v3.md)
là tài liệu thiết kế đầy đủ. Code tham chiếu tới nó bằng ký hiệu mục (`§7.2`,
`§11.3`, `§16`...) trong docstring và comment.

**Đọc mục liên quan trước khi sửa một module**, và giữ tham chiếu `§` khi viết
code mới — đó là cách người đọc sau biết quyết định này đến từ đâu. Khi phải làm
khác kế hoạch, ghi rõ lý do ngay tại chỗ lệch (xem các ví dụ trong
`services/storage.py` và `core/orchestrator.py`).

Quyết định còn mở nằm ở [docs/decisions.md](docs/decisions.md).

## Lệnh thường dùng

```bash
# Test
.venv/bin/python -m pytest apps/api/tests -q
.venv/bin/python -m pytest apps/api/tests/test_duration_fit.py -q     # một file
.venv/bin/python -m pytest apps/api/tests -q -k "drift"               # một nhóm
.venv/bin/python -m pytest apps/api/tests/test_cache_chain.py::test_cache_hit_khi_khong_doi_gi -q

# Chạy pipeline trên clip mẫu
.venv/bin/python scripts/run_pipeline.py                          # 2 locale mặc định
.venv/bin/python scripts/run_pipeline.py --locales es-ES -v
.venv/bin/python scripts/run_pipeline.py --rerun-from translate   # partial re-run §11.3

# Vòng lặp dev nhanh: Whisper base thay vì large-v3-turbo
VLA_DEV_FAST=1 .venv/bin/python scripts/run_pipeline.py

# Chọn provider dịch
VLA_TRANSLATION_PROVIDER=mock .venv/bin/python scripts/run_pipeline.py

# Reset trạng thái
rm -f vla.db && rm -rf storage/projects/*
```

Không có bước build, không có linter cấu hình sẵn.

## Ràng buộc môi trường

Hai thứ này sai là hỏng ngầm, khó truy:

- **Python 3.12** (không phải 3.13/3.14). PyTorch, Demucs, mlx-whisper chưa có
  wheel cho bản mới hơn. `apps/api/pyproject.toml` đã pin `>=3.12,<3.13`.
- **`ffmpeg-full`**, không phải `ffmpeg`. Bản `ffmpeg` thường của Homebrew thiếu
  libass/freetype nên **không có filter `subtitles`, `ass`, `drawtext`** —
  không burn được hardsub, không vẽ được text branding. `ffmpeg-full` là keg-only
  nên `core/config.py` trỏ thẳng `/opt/homebrew/opt/ffmpeg-full/bin/`, không dựa
  vào PATH. `Settings.verify_ffmpeg()` kiểm tra 6 filter bắt buộc và harness chặn
  ngay từ đầu nếu thiếu.

## Kiến trúc

### Stage contract và orchestrator

Mọi bước xử lý là một `Stage` (`core/stage.py`) với chữ ký thuần
`run(ctx, stage_input) -> StageResult`. Stage **không bao giờ gọi stage khác** —
điều phối là việc của `core/orchestrator.py`.

Nhờ contract này, Phase 3 gắn Celery chỉ là đổi cách gọi, không phải viết lại
worker. Giữ nguyên tính chất đó khi thêm stage mới.

`core/types.py` giữ `PIPELINE_ORDER` (18 stage) và `STAGE_DEPENDENCIES` —
dependency graph này là thứ điều khiển partial re-run.

### Cache — phần dễ làm sai nhất

Ba cơ chế chồng lên nhau trong `Orchestrator`:

1. **Cache key nối chuỗi.** Key của một stage gồm `(input_hash, output_digest)`
   của các stage upstream. Dùng **cả hai** là cố ý: `output_digest` bắt trường
   hợp nội dung đổi (sửa câu dịch); `input_hash` bắt trường hợp một stage trả
   output hằng số — loại stage đó sẽ nuốt thay đổi từ upstream và âm thầm phá
   vỡ invalidation của toàn bộ downstream.

2. **`CacheScope`.** Stage `SOURCE` (`ingest`, `analyze`, `separate`, `stt`)
   không phụ thuộc locale nên mọi bản ngôn ngữ dùng chung kết quả. Stage `JOB`
   giới hạn trong phạm vi job vì `output_ref` trỏ tới bản ghi của chính job đó.

   **Khai `CacheScope.SOURCE` thì `cache_params` phải BỎ locale.** Lớp cơ sở đã
   xử lý, nhưng nếu override `cache_params` thì đừng thêm locale vào — kèm vào
   là cache_scope mất tác dụng dù khai báo đúng, và sai lầm lan xuống cả chuỗi.
   `test_stage_source_scope_cho_hash_giong_nhau_moi_locale` chặn regression này.

3. **Bump `config_version`** trong `core/config.py` để vô hiệu hoá toàn bộ cache.

Nguyên tắc khi phân vân: cache sai thì xuất ra video có audio cũ mà không ai
biết; cache trượt thì chỉ tốn thêm thời gian. **Luôn nghiêng về chạy lại.**

### Bốn tầng segment (§5)

Đây là điểm kiến trúc quan trọng nhất và dễ hiểu nhầm nhất. Không có bảng
`segments` gộp — bốn tầng cắt đoạn khác nhau, nối bằng `segment_links` (N:M):

| Tầng | Bảng | Cắt theo |
|---|---|---|
| 1 | `stt_segments` | khoảng lặng — vụn, hay cắt giữa câu |
| 2 | `translation_units` | câu/ý trọn vẹn — thiếu ngữ cảnh là dịch sai |
| 3 | `tts_chunks` | ngữ điệu tự nhiên — mỗi chunk là **một file audio riêng** |
| 4 | `subtitle_cues` | giới hạn đọc — CPS, số dòng, min/max duration |

`workers/segment_planner/planner.py` là module thuần (không API, không DB) phụ
trách gộp/tách giữa các tầng.

Điều kiện bắt buộc để partial re-run hoạt động: **mỗi `tts_chunk` phải là một
file riêng có địa chỉ**, và composition là bước ghép file, không phải một lệnh
FFmpeg khổng lồ chạy một lần.

### Duration Fitting (§7)

Bài toán khó nhất của dubbing. `workers/duration_fit/fitter.py` là module thuần
áp thang 4 chiến lược theo đúng thứ tự: dịch có ràng buộc → ăn khoảng lặng →
chỉnh tempo (0,92–1,08) → co giãn hình. Không chiến lược nào đủ thì đánh dấu
manual review, **không ép bừa**.

`decide()` nhận `cumulative_drift_ms` và nhắm khung `target - cumulative_drift`.
Xét từng đơn vị độc lập là sai: mỗi đơn vị lệch 240ms đều nằm trong dung sai
10%, nhưng 8 đơn vị dồn lại vượt xa ngưỡng 300ms của DoD §21.

### Nguyên tắc bất biến về subtitle (§8.3)

**Subtitle luôn sinh từ timestamp của audio sẽ phát, không bao giờ từ audio
nguồn.** Cột `subtitle_cues.from_forced_alignment` là cờ để QC kiểm chứng bằng
dữ liệu thay vì bằng mắt.

`forced_align` (`workers/forced_align/aligner.py`) KHÔNG dùng WhisperX/MFA như
§8 đề xuất — dùng chính mlx-whisper chạy lại trên audio TTS để lấy ranh giới
đoạn (nơi có khoảng lặng thật), rồi rải ký tự bản dịch vào đó theo tỉ lệ. Đây
là xấp xỉ tuyến tính có neo bằng audio thật, không phải alignment cấp phoneme.
Lý do: WhisperX/MFA cần model CTC riêng từng ngôn ngữ, phủ yếu các locale mục
tiêu (ja/vi/ar). Cách này không phụ thuộc ngôn ngữ.

**cps_max là ràng buộc MỀM khi TTS đọc nhanh hơn ngưỡng đọc** — TTS thường đọc
nhanh hơn tốc độ đọc thoải mái của phụ đề. `workers/subtitle/splitter.py` chỉ
tách cue vì lý do CPS sau khi cue đã đạt `min_cue_ms`; nếu không, giọng đọc
nhanh hơn `cps_max` một chút (rất hay gặp) sẽ khiến MỌI cặp từ liên tiếp "vượt
ngưỡng", vỡ vụn thành cue 1 từ nhấp nháy suốt video.

### Tái dựng audio (§9)

Track cuối là `TTS + background gốc`, **không phải thay thế**. Demucs tách ra
`background.wav` và phải giữ lại — thay nguyên track audio bằng TTS là mất sạch
nhạc nền, tiếng động và không khí video gốc.

`timeline_assembly` đặt mỗi `tts_chunk` tại **vị trí tuyệt đối** `unit.start_ms`
trong track dài bằng cả video (`services/audio_timeline.py`), không nối đuôi
nhau — nhờ vậy khoảng lặng và các mốc hình ảnh vẫn đúng chỗ. `render` trộn
track đó với `background.wav` rồi chuẩn hoá bằng **loudnorm hai lượt**
(`services/audio_mix.py`) — một lượt cho kết quả không ổn định giữa các file.

### Cách stage sau lấy dữ liệu của stage trước

Stage không gọi stage khác (§11.1) — chúng liên lạc qua **DB + đường dẫn
storage theo quy ước cố định**, không qua `output_ref`. Ví dụ: `render` không
nhận đường dẫn SRT từ `subtitle`'s output — nó tự tính lại đường dẫn đó bằng
`Storage.path_for(ArtifactKind.SUBTITLE, ...)`, đúng quy ước mà `subtitle` đã
dùng để ghi file. `output_ref` chỉ phục vụ cache/observability (§16), không
phải kênh truyền dữ liệu giữa các stage.

Hệ quả: một stage phụ thuộc COMPOSE (còn là stub, Phase 2) trong
`STAGE_DEPENDENCIES` vẫn dirty-propagate đúng khi upstream thật của nó (vd.
subtitle) đổi — vì cơ chế `(input_hash, output_digest)` xuyên qua cả stub. Xem
`core/orchestrator._effective_key_of`.

### Provider LLM và TTS

Thêm provider mới **không phải sửa code** — thả một file JSON. Dịch:
`apps/api/config/providers/`, 3 giao thức (`services/providers/adapters.py`):
`openai_compatible` (phủ OpenAI, OpenRouter, 9Router, Groq, DeepSeek, Ollama,
LM Studio, vLLM...), `anthropic`, `gemini`, cộng `mock` cho test. TTS:
`apps/api/config/tts/`, tương tự (`services/tts/adapters.py`):
`macos_say` (local), `elevenlabs`, `openai_tts`.

API key chỉ đọc từ biến môi trường tại thời điểm gọi. Không lưu DB, không log.

Tốc độ đọc (`speech_rate_cps`) nằm trong config của TỪNG provider TTS, không
phải locale preset — đo bằng `scripts/calibrate_speech_rate.py`. Đổi provider
TTS thì phải đo lại.

### Storage

`services/storage.py` — artifact **không** phụ thuộc locale nằm ở cấp project
(`source`, `analysis`, `separated`, `transcript`) để cache dùng chung giữa các
locale; artifact phụ thuộc locale nằm dưới `jobs/{job_id}/`. Đây là chỗ lệch có
chủ ý so với layout phẳng của §12, vốn sẽ khiến bản ES và JA ghi đè nhau.

`RETENTION_DAYS` phải phủ hết mọi `ArtifactKind` (có test chặn).

## Quy ước khi viết code

- **Không hard-code** provider, voice, language, logo, subtitle style, ngưỡng.
  Tất cả nằm trong `config/presets/` hoặc `Settings`.
- **`NonRetryableError`** (`core/stage.py`) cho lỗi chạy lại bao nhiêu lần cũng
  vậy: thiếu file, sai cấu hình, thiếu stage phụ thuộc. Orchestrator dừng ngay
  thay vì đốt thêm hai lượt retry.
- **Stage phải idempotent**: chạy lại cùng input không tạo bản ghi trùng. Các
  stage ghi DB đều có `_clear_previous()` chạy trước khi ghi.
- **Filter graph** dựng bằng `FilterGraph` builder (`services/ffmpeg.py`), không
  nối chuỗi string — đây là nguồn bug khó debug nhất của loại tool này.
- **Module logic thuần tách khỏi stage.** `planner.py`, `fitter.py` không chạm
  DB/API nên test được đầy đủ mà không tốn tiền. Giữ mẫu đó cho module mới.
- **Test đặt tên bằng tiếng Việt mô tả hành vi**, và assert message giải thích
  *vì sao* điều đó quan trọng, không chỉ *cái gì* sai.

## Nợ kỹ thuật đã biết

- `speech_rate_cps` trong `config/presets/locale/*.json` là ước lượng chung,
  chưa đo cho từng provider TTS (đã hiệu chuẩn riêng cho `macos_say` trong
  `config/tts/macos_say.json` — provider khác vẫn đang dùng ước lượng chung
  cho tới khi đo).
- `forced_align` là xấp xỉ tuyến tính, không phải alignment cấp phoneme — xem
  mục "Nguyên tắc bất biến về subtitle" ở trên. Đủ cho subtitle timing, không
  đủ chính xác cho lip-sync hay karaoke-highlight.
- `render` chưa áp `FitStrategy.VIDEO_STRETCH` (co giãn hình) — quyết định này
  được lưu trong `SegmentTiming` nhưng chưa có stage nào đọc và thực thi nó.
  Compose (Phase 2, branding) là nơi hợp lý để làm việc này.
- `render` chưa có render preset (§14) để chọn bitrate/aspect ratio theo cấu
  hình — đang hard-code 6000k, giữ nguyên resolution/aspect nguồn.

## Commit

Commit message tiếng Việt, giải thích **vì sao** chứ không chỉ *cái gì*. Khi sửa
một lỗi thiết kế, ghi lại lỗi đó là gì và tại sao cách cũ sai — các commit hiện
có trong repo là mẫu tham khảo.

Kết bằng:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```
