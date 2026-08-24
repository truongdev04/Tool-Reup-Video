# Stage contract, orchestrator & cách stage giao tiếp

## Stage contract và orchestrator

Mọi bước xử lý là một `Stage` (`core/stage.py`) với chữ ký thuần
`run(ctx, stage_input) -> StageResult`. Stage **không bao giờ gọi stage khác** —
điều phối là việc của `core/orchestrator.py`.

Nhờ contract này, Phase 3 gắn Celery chỉ là đổi cách gọi, không phải viết lại
worker. Giữ nguyên tính chất đó khi thêm stage mới.

`core/types.py` giữ `PIPELINE_ORDER` (18 stage) và `STAGE_DEPENDENCIES` —
dependency graph này là thứ điều khiển partial re-run.

## Cách stage sau lấy dữ liệu của stage trước

Stage không gọi stage khác (§11.1) — chúng liên lạc qua **DB + đường dẫn
storage theo quy ước cố định**, không qua `output_ref`. Ví dụ: `render` không
nhận đường dẫn SRT từ `subtitle`'s output — nó tự tính lại đường dẫn đó bằng
`Storage.path_for(ArtifactKind.SUBTITLE, ...)`, đúng quy ước mà `subtitle` đã
dùng để ghi file. `output_ref` chỉ phục vụ cache/observability (xem
[caching.md](caching.md)), không phải kênh truyền dữ liệu giữa các stage.

Hệ quả: một stage phụ thuộc COMPOSE (còn là stub, Phase 2) trong
`STAGE_DEPENDENCIES` vẫn dirty-propagate đúng khi upstream thật của nó (vd.
subtitle) đổi — vì cơ chế `(input_hash, output_digest)` xuyên qua cả stub. Xem
`core/orchestrator._effective_key_of` và [caching.md](caching.md).
