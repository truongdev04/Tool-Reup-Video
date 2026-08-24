"""Sửa bản dịch một `translation_unit` thủ công — dùng bởi dashboard (§19,
Video Workspace) khi người vận hành sửa trực tiếp một câu dịch sai thuật ngữ.

KHÔNG chạy lại `TranslateStage` để áp bản sửa: người dùng đã tự cung cấp bản
dịch đúng, gọi lại provider dịch chỉ tốn tiền vô ích (và có thể ghi đè mất
bản sửa nếu model dịch ra khác). Thay vào đó `edit_unit_translation` tạo một
`Translation` version mới (đúng lineage §10.4, cùng mẫu
`TranslateStage._next_version`/`_deactivate_previous`), rồi tự ghi một
`StageRun` MỚI cho `TRANSLATE` (JOB scope) với `output_ref` phản ánh nội
dung SAU khi sửa — để chuỗi cache `(input_hash, output_digest)` (§16) khiến
downstream (`duration_fit`/`tts`/...) thấy đúng thay đổi, mà không cần
`TranslateStage.run()` thật sự chạy lại. Cùng `input_hash` với lần chạy gần
nhất để bản thân TRANSLATE vẫn cache-hit khi pipeline chạy lại từ đầu.

Dùng cùng `services/pipeline_runner.py::rerun_stages_for_job` với
`stages=dependents_of(StageName.TRANSLATE)` để áp thay đổi xuống downstream —
xem `apps/api/api/routes/dashboard.py`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.hashing import output_digest
from core.types import StageName
from db.base import utcnow
from db.models import RenderJob, StageRun, Translation, TranslationUnit


def edit_unit_translation(
    session: Session, *, unit_id: str, locale: str, text: str, edited_by: str,
) -> Translation:
    """Ghi bản dịch mới cho MỘT unit + bump cache TRANSLATE của cả job.

    Raises:
        ValueError: không có unit này.
    """
    unit = session.get(TranslationUnit, unit_id)
    if unit is None:
        raise ValueError(f"không có translation_unit {unit_id}")

    previous = session.scalars(
        select(Translation).where(
            Translation.translation_unit_id == unit_id,
            Translation.locale == locale,
            Translation.is_active.is_(True),
        )
    ).all()
    for p in previous:
        p.is_active = False

    latest = session.scalars(
        select(Translation)
        .where(Translation.translation_unit_id == unit_id, Translation.locale == locale)
        .order_by(Translation.version.desc())
        .limit(1)
    ).first()
    version = (latest.version + 1) if latest else 1

    translation = Translation(
        translation_unit_id=unit_id, locale=locale, text=text,
        version=version, is_active=True, approved_by=edited_by,
    )
    session.add(translation)
    session.flush()

    _bump_translate_cache(session, render_job_id=unit.render_job_id, locale=locale)
    return translation


def _active_texts(session: Session, *, render_job_id: str, locale: str) -> dict[int, str]:
    units = session.scalars(
        select(TranslationUnit)
        .where(TranslationUnit.render_job_id == render_job_id)
        .order_by(TranslationUnit.idx)
    ).all()
    out: dict[int, str] = {}
    for u in units:
        t = session.scalars(
            select(Translation).where(
                Translation.translation_unit_id == u.id,
                Translation.locale == locale,
                Translation.is_active.is_(True),
            )
        ).first()
        if t is not None:
            out[u.idx] = t.text
    return out


def _bump_translate_cache(session: Session, *, render_job_id: str, locale: str) -> None:
    job = session.get(RenderJob, render_job_id)
    if job is None:
        return

    last_run = session.scalars(
        select(StageRun)
        .where(StageRun.render_job_id == render_job_id, StageRun.stage == StageName.TRANSLATE)
        .order_by(StageRun.created_at.desc())
        .limit(1)
    ).first()
    if last_run is None:
        # Chưa từng chạy TRANSLATE cho job này — không có gì để bump, sửa
        # inline chỉ nên xảy ra SAU khi translate đã chạy ít nhất một lần.
        return

    active = _active_texts(session, render_job_id=render_job_id, locale=locale)
    session.add(StageRun(
        render_job_id=render_job_id,
        stage=StageName.TRANSLATE,
        status=last_run.status,
        # CÙNG input_hash: giữ TRANSLATE cache-hit khi pipeline chạy lại từ
        # đầu — chỉ downstream cần thấy nội dung đổi, không phải TRANSLATE.
        input_hash=last_run.input_hash,
        output_ref={
            "provider": "manual_edit",
            "units_total": len(active),
            "units_translated": len(active),
            "target_locale": locale,
            "texts_digest": output_digest(
                {str(idx): text for idx, text in sorted(active.items())}
            ),
        },
        started_at=utcnow(),
        finished_at=utcnow(),
        duration_ms=0,
    ))
    session.flush()
