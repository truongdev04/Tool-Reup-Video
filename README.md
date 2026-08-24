# Tool Reup — Video Localization & Automation

Công cụ nội bộ: từ 1 video gốc → dịch/lồng tiếng/phụ đề → xuất nhiều phiên bản
ngôn ngữ và thương hiệu, chạy theo pipeline job-based, có QC và kiểm soát chi phí.

Kiến trúc và mọi quyết định thiết kế nằm trong
[docs/Ke_Hoach_Tool_Video_Localization_Automation_v3.md](docs/Ke_Hoach_Tool_Video_Localization_Automation_v3.md) —
đọc file đó trước khi đổi cấu trúc hoặc thêm module mới.

## Cấu trúc thư mục

```
apps/
  api/            # Backend FastAPI — xem "Backend layout" bên dưới
  web/             # Frontend Next.js (bắt đầu ở Phase 4, xem docs §19)
storage/
  projects/        # Media output theo runtime, KHÔNG commit vào git (xem docs §12, §17.2)
docs/              # Kế hoạch kiến trúc + quyết định đang mở
scripts/           # Dev scripts (vd. harness chạy pipeline tuần tự — Phase 0)
docker/            # docker-compose cho Postgres/Redis (Phase 3)
```

### Backend layout (`apps/api`)

| Thư mục | Ánh xạ tới kế hoạch |
|---|---|
| `api/` | Lớp API (FastAPI routes) |
| `workers/` | 1 package / stage trong pipeline 17 bước — xem docs §4, §6 |
| `core/` | Stage contract dùng chung (`run(job_id, stage_input) -> stage_output`) — docs §11.1 |
| `models/` | Kiểu dữ liệu / domain models |
| `services/` | Logic dùng chung giữa nhiều worker (provider abstraction, storage client...) |
| `db/` | Schema + migrations — 17 bảng ở docs §10 |
| `config/presets/` | Preset theo locale/voice/subtitle/brand/render/publishing/fitting — docs §14. **Không hard-code trong source** |
| `tests/fixtures/` | Clip mẫu ~10s để vòng lặp phát triển nhanh — docs §21 |

**Lưu ý đặt tên:** kế hoạch gốc (§12) đặt tên worker đầu tiên là `import`, nhưng đó là
từ khoá dành riêng của Python nên không dùng làm tên package được. Đã đổi thành `ingest`
(khớp tên module "Source/Import Manager" ở docs §6.1). Toàn bộ tên khác giữ nguyên theo kế hoạch.

## Bắt đầu

```bash
# Yêu cầu: Python 3.12 và ffmpeg-full (KHÔNG dùng bản ffmpeg thường của brew —
# nó thiếu libass/freetype nên không burn được hardsub, xem docs §13.2)
brew install python@3.12 ffmpeg-full

python3.12 -m venv .venv
.venv/bin/pip install -e "apps/api[dev]"

# Xem pipeline chạy trên trình duyệt (dev viewer — KHÔNG phải dashboard Phase 4)
VLA_DEV_FAST=1 .venv/bin/uvicorn api.main:app --app-dir apps/api --port 8787 --reload
# mở http://localhost:8787

# Hoặc chạy thẳng qua CLI trên clip mẫu 10s, 2 locale
.venv/bin/python scripts/run_pipeline.py

# Chạy lại 1 stage và mọi stage phụ thuộc nó (partial re-run, docs §11.3)
.venv/bin/python scripts/run_pipeline.py --rerun-from translate

# Test
.venv/bin/python -m pytest apps/api/tests -q
```

`VLA_DEV_FAST=1` dùng Whisper `base` thay vì `large-v3-turbo` — tải nhanh hơn
nhiều, hợp cho việc xem thử. Bỏ biến này khi cần chất lượng transcript thật.

### Dev viewer

Trang tại `http://localhost:8787` cho phép: chọn locale đích, chọn provider
dịch/TTS, chạy pipeline trên clip mẫu hoặc video tự tải lên, xem kết quả từng
stage, xem bảng bản dịch kèm budget/drift, và nghe thử từng đoạn audio đã sinh.

Đây là lớp mỏng dựng tạm để xem kết quả mà không phải đọc log terminal — 
**không phải** dashboard Phase 4 thật (§19, sẽ là React/Next.js riêng với batch
queue, QC review, publishing calendar...). Code nằm ở `apps/api/api/`.

## Trạng thái

Pipeline chạy thật **từ ingest tới qc** — xuất video cuối cùng có giọng lồng
tiếng, phụ đề burn cứng, nhạc nền gốc còn nguyên, và có bộ kiểm tra tự động
trước khi cho publish (§15). Clip mẫu 7s, 2 locale: **~22s** lần đầu,
**~0,05s** khi dùng cache (ngân sách DoD §21 là 2 phút).

| Stage | Trạng thái | Công nghệ |
|---|---|---|
| `ingest` | ✅ | checksum, rights_note bắt buộc |
| `analyze` | ✅ | ffprobe |
| `separate` | ✅ | Demucs htdemucs trên MPS |
| `stt` | ✅ | mlx-whisper (Metal), word timestamps |
| `segment_plan` | ✅ | logic thuần |
| `translate` | ✅ | 8 provider, xem bên dưới |
| `duration_fit` | ✅ | dự báo từ độ dài bản dịch (§7) |
| `tts` | ✅ | đo thời lượng thật, áp atempo (§7) |
| `forced_align` | ✅ | STT lại trên audio TTS, xem "Forced alignment" bên dưới |
| `timeline_assembly` | ✅ | đặt từng chunk vào đúng vị trí tuyệt đối (§9) |
| `subtitle` | ✅ | cắt cue theo CPS/số dòng, xuất SRT (§6.11) |
| `render` | ✅ | trộn voice+background, loudnorm 2 lượt, burn hardsub, encode VideoToolbox |
| `qc` | ✅ | 10 check tự động, xem "QC" bên dưới |
| `diarize`, `onscreen_text`, `lipsync`, `compose`, `publish` | ⬜ | stub giữ đúng contract, xem lộ trình §20 |

Nền tảng Phase 0: 23 bảng data model (§10), stage contract (§11.1),
orchestrator có cache/retry/partial re-run (§11.3, §16), storage layout (§12),
harness (§21). **136 test.**

## QC — 10 check tự động (§15)

`workers/qc/checks.py` (logic thuần) + `workers/qc/stage.py` (đo đạc thật) +
`services/qc_media.py` (gọi ffmpeg: `blackdetect`, `volumedetect`).

| Check | Nguồn dữ liệu | Verdict khi lỗi |
|---|---|---|
| `drift` | `cumulative_drift_ms` cuối video | FAIL nếu vượt 300ms |
| `forced_alignment` | mọi cue phải có `from_forced_alignment=True` | FAIL |
| `cue_overlap` | timestamp cue chồng lấn | FAIL |
| `cue_cps` | CPS vượt ngưỡng locale | WARN nhẹ, FAIL nếu vượt >1,5x |
| `tempo_bounds` | tempo ngoài [0,92, 1,08] | FAIL (đáng lẽ fitter đã chặn) |
| `translation_complete` | thiếu bản dịch cho unit nào | FAIL |
| `output_playable` | mở được, đúng thời lượng, checksum khớp | FAIL |
| `loudness` | đo lại bằng `measure_loudnorm`, so với −14 LUFS | WARN/FAIL |
| `clipping` | true peak | WARN/FAIL |
| `background_retained` | âm lượng tại khoảng lặng lời thoại | FAIL nếu gần như im lặng |
| `black_frames` | `ffmpeg blackdetect` | FAIL nếu có đoạn đen ≥1s |

Verdict tổng hợp ghi vào `OutputFile.qc_verdict`: có FAIL → FAIL cả job; không
FAIL nhưng có WARN → WARN; còn lại → PASS. `publish` (chưa implement) sẽ chỉ
chạy khi verdict = PASS.

**Đã xác nhận trên pipeline thật**: 9/10 check PASS trên fixture (drift 0ms,
loudness −14,28 LUFS, checksum khớp...). `background_retained` FAIL trên
fixture vì nhạc nền ở đó là sine wave tổng hợp mà Demucs tách kém (đã xác minh
bằng cách đo trực tiếp: nguồn −22dB → sau Demucs −61dB) — hạn chế của fixture
tổng hợp, không phải bug ở `render`/`audio_mix`. Xem comment trong
`tests/fixtures/make_fixture.py`.

## Forced alignment — lệch khỏi kế hoạch, có chủ ý

§8 đề xuất WhisperX/MFA. Tool này dùng **chính mlx-whisper chạy lại trên audio
TTS** để lấy ranh giới đoạn (nơi có khoảng lặng thật), rồi rải ký tự của bản
dịch — đáng tin hơn text STT nhận dạng — vào các mốc đó theo tỉ lệ ký tự. Đây
KHÔNG phải forced alignment đúng nghĩa (không dùng model CTC align với text đã
biết), mà là xấp xỉ tuyến tính có neo bằng cấu trúc thời gian thật.

Lý do: WhisperX/MFA cần model CTC theo từng ngôn ngữ, và các bộ có sẵn phủ tốt
Anh/Âu nhưng rất yếu hoặc không có cho tiếng Nhật, Việt, Ả Rập — đúng các locale
mục tiêu của tool (§23 #4). Cách tiếp cận này hoạt động bất kể ngôn ngữ. Ghi
nhận như nợ kỹ thuật: nâng cấp lên WhisperX cho locale có model CTC tốt là việc
hợp lý ở Phase 2+ nếu cần độ chính xác cấp phoneme (vd. lip-sync, karaoke).

Chi tiết: `workers/forced_align/aligner.py`.

## Provider LLM

Khai báo bằng file JSON trong `apps/api/config/providers/`, **thêm provider mới
không phải sửa code**:

| Provider | Adapter | Cần API key |
|---|---|---|
| `claude` | anthropic | `ANTHROPIC_API_KEY` |
| `openai` | openai_compatible | `OPENAI_API_KEY` |
| `gemini` | gemini | `GEMINI_API_KEY` |
| `openrouter` | openai_compatible | `OPENROUTER_API_KEY` |
| `9router` | openai_compatible | `NINEROUTER_API_KEY` |
| `ollama` | openai_compatible | không — chạy local |
| `lmstudio` | openai_compatible | không — chạy local |
| `mock` | mock | không — dùng cho test |

Phần lớn provider (OpenRouter, 9Router, Groq, DeepSeek, Together, Ollama,
LM Studio, vLLM...) đều dùng API tương thích OpenAI, nên chỉ cần thả một file
JSON là xong:

```json
{
  "id": "ten-cua-ban",
  "name": "Nhà cung cấp của bạn",
  "adapter": "openai_compatible",
  "base_url": "https://api.example.com/v1",
  "model": "ten-model",
  "api_key_env": "TEN_BIEN_MOI_TRUONG"
}
```

Chọn provider khi chạy:

```bash
VLA_TRANSLATION_PROVIDER=claude .venv/bin/python scripts/run_pipeline.py
```

API key chỉ đọc từ biến môi trường tại thời điểm gọi, **không bao giờ lưu vào
database hay ghi ra log** (§18.1).

### Các điểm lệch khỏi kế hoạch (có chủ ý)

1. **Storage layout** (§12) — artifact phụ thuộc locale chuyển xuống
   `jobs/{job_id}/`; layout phẳng của kế hoạch khiến bản ES và JA ghi đè nhau.
   Artifact dùng chung (source, analysis, separated, transcript) giữ ở cấp
   project để cache được giữa các locale.

2. **Cache key nối chuỗi giữa các stage** (§16) — kế hoạch chỉ nêu
   `source checksum + provider + config version`. Như vậy stage sau không biết
   stage trước đã đổi kết quả, nên partial re-run sẽ im lặng tái dùng audio cũ.
   Cache key nay gồm cả `(input_hash, output_digest)` của upstream.

3. **Phạm vi cache** (§16) — thêm `CacheScope`. Stage không phụ thuộc locale
   (`ingest`, `analyze`, `separate`, `stt`) dùng chung kết quả giữa mọi bản ngôn
   ngữ. Với video 60 phút × 10 locale, đây là chênh lệch giữa chạy STT 1 lần và
   10 lần.

4. **Forced alignment** (§8) — dùng mlx-whisper thay vì WhisperX/MFA. Xem mục
   riêng ở trên.

5. **cps_max là ràng buộc MỀM khi TTS đọc nhanh hơn ngưỡng đọc** (§6.11) —
   TTS thường đọc nhanh hơn tốc độ đọc thoải mái của phụ đề (đã đo: `macos_say`
   đọc es-ES ~20 cps, trong khi `cps_max` của locale là 17). Tách cue NGHIÊM
   NGẶT theo CPS trong tình huống đó sẽ vỡ vụn thành cue 1 từ nhấp nháy suốt
   video — đọc còn khó hơn nhiều so với một cue hơi nhanh nhưng trọn vẹn. Nên
   splitter chỉ tách vì lý do CPS **sau khi** cue đã đạt `min_cue_ms` (đủ dài để
   đứng một mình); một unit ngắn hơn `min_cue_ms` thì chấp nhận vượt CPS thay vì
   tách. Xem `workers/subtitle/splitter.py`.

### Số liệu cần hiệu chuẩn

`speech_rate_cps` trong `config/presets/locale/*.json` hiện là **ước lượng**,
chưa đo từ TTS thật. Sai số ở đây đẩy thẳng vào drift.

Đã hiệu chuẩn cho `macos_say` (`config/tts/macos_say.json`, đo bằng
`scripts/calibrate_speech_rate.py`). Đổi provider TTS thì phải đo lại — tốc độ
đọc phụ thuộc provider, không chỉ phụ thuộc ngôn ngữ.

### Việc tiếp theo

Trục Phase 1 + qc đã xong (ingest → qc). Còn lại là các module Phase 2+:
`diarize` (speaker profile — cần quyết định provider, pyannote yêu cầu chấp
nhận điều khoản HuggingFace), `compose` (branding/CTA/intro-outro — cần asset
thương hiệu thật để demo), `publish` (OAuth từng nền tảng, Phase 5),
`onscreen_text`/`lipsync` (Phase 6 — xem quyết định #1 ở dưới). Quyết định còn
mở: [docs/decisions.md](docs/decisions.md).
