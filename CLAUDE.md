# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Tool nội bộ: từ 1 video gốc → dịch/lồng tiếng/phụ đề → xuất nhiều phiên bản ngôn
ngữ và thương hiệu. Kiến trúc đầy đủ nằm ở
[docs/Ke_Hoach_Tool_Video_Localization_Automation_v3.md](docs/Ke_Hoach_Tool_Video_Localization_Automation_v3.md);
quyết định còn mở ở [docs/decisions.md](docs/decisions.md).

Chi tiết theo từng miền được tách vào `.claude/rules/` (xem bảng bên dưới) thay
vì nhồi hết vào file này — **đọc đúng rule của khu vực đang sửa trước khi sửa**,
không cần đọc hết mọi file mỗi phiên.

## Luôn áp dụng, không phụ thuộc khu vực

- **Tiếng Việt** cho toàn bộ doc/comment/docstring/lỗi/commit. Chi tiết + quy
  ước commit: [.claude/rules/conventions.md](.claude/rules/conventions.md).
- **Python 3.12** (không phải 3.13/3.14) và **`ffmpeg-full`** (không phải
  `ffmpeg` thường của brew — thiếu libass/freetype, không burn được hardsub).
  Sai một trong hai thứ này là hỏng ngầm, khó truy. Chi tiết + lệnh thường
  dùng: [.claude/rules/environment.md](.claude/rules/environment.md).

## Bản đồ rule theo khu vực code

| Khu vực / file | Đọc rule |
|---|---|
| `core/stage.py`, `core/orchestrator.py` — contract, cách stage giao tiếp | [stage-contract.md](.claude/rules/stage-contract.md) |
| Cache key, `CacheScope`, `STAGE_DEPENDENCIES` — **đọc trước khi đổi dữ liệu một stage đọc/ghi** | [caching.md](.claude/rules/caching.md) |
| `workers/segment_planner/` | [segments.md](.claude/rules/segments.md) |
| `workers/duration_fit/` | [duration-fitting.md](.claude/rules/duration-fitting.md) |
| `workers/subtitle/`, `workers/forced_align/` | [subtitle.md](.claude/rules/subtitle.md) |
| `workers/audio/`, `services/audio_timeline.py`, `services/audio_mix.py` | [audio.md](.claude/rules/audio.md) |
| `workers/diarization/`, `services/diarization_pyannote.py` | [diarization.md](.claude/rules/diarization.md) |
| `workers/compose/` | [compose.md](.claude/rules/compose.md) |
| `services/providers/`, `services/tts/`, `config/providers/`, `config/tts/` | [providers.md](.claude/rules/providers.md) |
| `services/storage.py` | [storage.md](.claude/rules/storage.md) |
| `workers/qc/`, `services/qc_media.py` | [qc.md](.claude/rules/qc.md) |
| `services/fonts.py`, `apps/api/assets/fonts/` — dùng chung giữa `render` và `qc` | [fonts.md](.claude/rules/fonts.md) |
| `services/approval_gates.py`, `services/voice_consent.py`, `ApprovalGateRecord`/`VoiceConsent` | [approval-gates.md](.claude/rules/approval-gates.md) |
| Viết code mới ở bất kỳ đâu (idempotency, hard-code, module thuần, test) | [coding-style.md](.claude/rules/coding-style.md) |
| Trước khi bắt đầu việc mới — biết trước cái gì đang dang dở | [tech-debt.md](.claude/rules/tech-debt.md) |

Xem thêm [.claude/README.md](.claude/README.md) cho ý nghĩa các thư mục con
khác trong `.claude/` (`agents/`, `skills/`, `hooks/`, `doc/`).
