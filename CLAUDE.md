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
nguồn.** Sau TTS phải chạy forced alignment trên chính audio mới. Cột
`subtitle_cues.from_forced_alignment` là cờ để QC kiểm chứng bằng dữ liệu thay
vì bằng mắt.

### Tái dựng audio (§9)

Track cuối là `TTS + background gốc`, **không phải thay thế**. Demucs tách ra
`background.wav` và phải giữ lại — thay nguyên track audio bằng TTS là mất sạch
nhạc nền, tiếng động và không khí video gốc.

### Provider LLM

Thêm provider mới **không phải sửa code** — thả một file JSON vào
`apps/api/config/providers/`. Chỉ có 3 giao thức thật sự khác nhau
(`services/providers/adapters.py`): `openai_compatible` (phủ OpenAI, OpenRouter,
9Router, Groq, DeepSeek, Ollama, LM Studio, vLLM...), `anthropic`, `gemini`,
cộng `mock` cho test.

API key chỉ đọc từ biến môi trường tại thời điểm gọi. Không lưu DB, không log.

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

`speech_rate_cps` trong `config/presets/locale/*.json` là **ước lượng**, chưa đo
từ TTS thật. Đây là con số quyết định `char_budget`, và sai số ở đó đẩy thẳng
vào drift. Phải hiệu chuẩn sau khi chốt provider TTS rồi mới bật cờ
`speech_rate_calibrated` — hiện có test chặn việc tự nhận đã hiệu chuẩn.

## Commit

Commit message tiếng Việt, giải thích **vì sao** chứ không chỉ *cái gì*. Khi sửa
một lỗi thiết kế, ghi lại lỗi đó là gì và tại sao cách cũ sai — các commit hiện
có trong repo là mẫu tham khảo.

Kết bằng:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```
