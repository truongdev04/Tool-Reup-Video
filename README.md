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

# Chạy pipeline trên clip mẫu 10s, 2 locale
.venv/bin/python scripts/run_pipeline.py

# Chạy lại 1 stage và mọi stage phụ thuộc nó (partial re-run, docs §11.3)
.venv/bin/python scripts/run_pipeline.py --rerun-from translate

# Test
.venv/bin/python -m pytest apps/api/tests -q
```

## Trạng thái

Pipeline chạy thật tới `translate`. Clip mẫu 7s, 2 locale: **~9s** lần đầu,
**~0,04s** khi dùng cache (ngân sách DoD §21 là 2 phút).

| Stage | Trạng thái | Công nghệ |
|---|---|---|
| `ingest` | ✅ | checksum, rights_note bắt buộc |
| `analyze` | ✅ | ffprobe |
| `separate` | ✅ | Demucs htdemucs trên MPS |
| `stt` | ✅ | mlx-whisper (Metal), word timestamps |
| `segment_plan` | ✅ | logic thuần |
| `translate` | ✅ | 8 provider, xem bên dưới |
| `duration_fit` | 🟡 | logic xong, chờ TTS để nối vào pipeline |
| `diarize`, `tts`, `forced_align`, `timeline_assembly`, `subtitle`, `render`, `qc`, `publish` | ⬜ | stub giữ đúng contract |

Nền tảng Phase 0: 23 bảng data model (§10), stage contract (§11.1),
orchestrator có cache/retry/partial re-run (§11.3, §16), storage layout (§12),
harness (§21). **66 test.**

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

### Ba điểm lệch khỏi kế hoạch (có chủ ý)

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

### Số liệu cần hiệu chuẩn

`speech_rate_cps` trong `config/presets/locale/*.json` hiện là **ước lượng**,
chưa đo từ TTS thật. Sai số ở đây đẩy thẳng vào drift. Phải đo lại sau khi chốt
provider TTS, rồi bật cờ `speech_rate_calibrated`.

### Việc tiếp theo

`tts` → `forced_align` → `timeline_assembly` → `subtitle` → `render`.
Quyết định còn mở: [docs/decisions.md](docs/decisions.md).
