"""Stage `ingest` — Source/Import Manager (docs §6.1).

Đổi tên từ "import" trong kế hoạch vì `import` là từ khoá Python (xem README).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select

from core.hashing import file_checksum
from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import CacheScope, ArtifactKind, StageName
from db.models import SourceVideo


class IngestStage(Stage):
    name = StageName.INGEST
    cache_scope = CacheScope.SOURCE

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        source = ctx.session.scalars(
            select(SourceVideo).where(SourceVideo.checksum == ctx.source_checksum)
        ).first()
        if source is None:
            raise NonRetryableError(
                f"chưa đăng ký source có checksum {ctx.source_checksum[:12]}"
            )

        stored = ctx.storage.root / source.storage_path
        if not stored.exists():
            raise NonRetryableError(f"file nguồn biến mất khỏi storage: {stored}")

        # Idempotent: chạy lại chỉ xác minh, không copy lại (§11.1).
        actual = file_checksum(stored)
        if actual != source.checksum:
            raise NonRetryableError(
                f"checksum lệch — file nguồn đã bị sửa. "
                f"DB={source.checksum[:12]} file={actual[:12]}"
            )

        return StageResult(
            output_ref={
                "source_video_id": source.id,
                "storage_path": source.storage_path,
                "checksum": source.checksum,
            }
        )


def register_source(
    session,
    storage,
    *,
    project_id: str,
    file_path: Path,
    rights_note: str,
    source_locale: str | None = None,
) -> SourceVideo:
    """Đăng ký video nguồn vào project. Chạy TRƯỚC khi tạo job.

    `rights_note` là bắt buộc, không cho để trống — quyền sử dụng nguồn (§18.2).
    """
    if not rights_note or not rights_note.strip():
        raise ValueError("rights_note là bắt buộc — quyền sử dụng nguồn (§18.2)")

    file_path = Path(file_path).resolve()
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    checksum = file_checksum(file_path)

    existing = session.scalars(
        select(SourceVideo).where(
            SourceVideo.project_id == project_id, SourceVideo.checksum == checksum
        )
    ).first()
    if existing:
        return existing  # idempotent: cùng file, cùng project -> không tạo bản ghi trùng

    dest = storage.path_for(
        ArtifactKind.SOURCE, project_id=project_id, filename=file_path.name
    )
    if not dest.exists():
        shutil.copy2(file_path, dest)

    source = SourceVideo(
        project_id=project_id,
        filename=file_path.name,
        storage_path=storage.relative(dest),
        checksum=checksum,
        rights_note=rights_note.strip(),
        source_locale=source_locale,
    )
    session.add(source)
    session.flush()
    return source
