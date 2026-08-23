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

## Trạng thái: Phase 0 xong

Phase 0 (docs §20) dựng phần nền để Phase 1–3 không phải viết lại:

| Hạng mục | Trạng thái |
|---|---|
| 23 bảng data model (docs §10) | ✅ `apps/api/db/models.py` |
| Stage contract (docs §11.1) | ✅ `apps/api/core/stage.py` |
| Orchestrator: cache, retry, partial re-run (§11.3, §16) | ✅ `apps/api/core/orchestrator.py` |
| Storage layout + retention (§12, §17.2) | ✅ `apps/api/services/storage.py` |
| Fixture clip 10s (§21) | ✅ `apps/api/tests/fixtures/make_fixture.py` |
| Harness chạy tuần tự 18 stage (§4) | ✅ `scripts/run_pipeline.py` |
| Stage đã implement | `ingest`, `analyze` — 16 stage còn lại là stub giữ đúng contract |

Clip 10s chạy hết pipeline **~0,3 s** (ngân sách DoD §21 là 2 phút), lần 2 dùng
cache hoàn toàn.

### Hai điểm lệch khỏi kế hoạch (có chủ ý)

1. **Storage layout** (§12) — kế hoạch vẽ layout phẳng theo project, nhưng một
   source sinh nhiều job (mỗi locale một job) nên bản ES và JA sẽ ghi đè nhau.
   Artifact phụ thuộc locale được chuyển xuống `jobs/{job_id}/`; artifact dùng
   chung (source, analysis, separated, transcript) giữ ở cấp project để cache
   được giữa các locale. Chi tiết trong `services/storage.py`.

2. **Cache key nối chuỗi giữa các stage** (§16) — kế hoạch chỉ nêu cache key gồm
   `source checksum + provider + config version`. Như vậy chưa đủ: stage sau
   không biết stage trước đã đổi kết quả, nên partial re-run sẽ im lặng tái dùng
   audio cũ. Cache key nay gồm cả `(input_hash, output_digest)` của các stage
   upstream. Xem `Orchestrator._effective_key_of` và
   `tests/test_cache_chain.py`.

### Việc tiếp theo

Phase 1 (docs §20): trục localization — `separate` → `stt` → `segment_plan` →
`translate` → `duration_fit` → `tts` → `forced_align` → `timeline_assembly` →
`subtitle` → `render`.

Trước khi bắt đầu, chốt các quyết định còn mở ở [docs/decisions.md](docs/decisions.md).
