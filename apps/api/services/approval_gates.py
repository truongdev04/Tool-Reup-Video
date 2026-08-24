"""Approval gates — biến "manual review" thành quy trình có vết (§11.2).

Bốn cổng theo thứ tự `transcript -> translation -> audio -> final`. Mỗi cổng
là MỘT bản ghi `ApprovalGateRecord` gắn với một `render_job` cụ thể — kể cả
cổng `transcript`, vốn dữ liệu nguồn (STT) không phụ thuộc locale, vẫn có một
bản ghi riêng cho từng job/locale vì bảng `approval_gates` khoá theo
`render_job_id` (xem giới hạn đã biết trong
`.claude/rules/approval-gates.md`).

`core/orchestrator.py` là nơi ĐỌC các bản ghi này để quyết định có chặn
pipeline hay không (`Orchestrator._pending_gate`). Module này chỉ lo tạo/ghi —
không tự chặn gì cả, giữ đúng ranh giới "logic thuần tách khỏi orchestrator".
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.types import ApprovalGate
from db.base import utcnow
from db.models import ApprovalGateRecord


def ensure_gates(
    session: Session, *, render_job_id: str, config: dict[str, bool] | None = None
) -> list[ApprovalGateRecord]:
    """Đảm bảo job có đủ 4 bản ghi cổng — idempotent (§11.1), an toàn gọi lại
    nhiều lần (chỉ tạo bản ghi còn thiếu, không đụng vào bản ghi đã có, kể cả
    khi đã được duyệt).

    `config` là `Project.approval_gates`: gate -> bật/tắt. Thiếu key nào thì
    cổng đó tạo với `is_enabled=False` (tự động, không chặn) — đúng tinh thần
    "project chạy tự động hoàn toàn thì tắt hết" (§11.2).
    """
    config = config or {}
    existing = {
        row.gate: row
        for row in session.scalars(
            select(ApprovalGateRecord).where(ApprovalGateRecord.render_job_id == render_job_id)
        ).all()
    }
    records = []
    for gate in ApprovalGate:
        record = existing.get(gate)
        if record is None:
            record = ApprovalGateRecord(
                render_job_id=render_job_id, gate=gate,
                is_enabled=bool(config.get(str(gate), False)),
            )
            session.add(record)
        records.append(record)
    session.flush()
    return records


def approve(
    session: Session,
    *,
    render_job_id: str,
    gate: ApprovalGate,
    approved_by: str,
    note: str | None = None,
) -> ApprovalGateRecord:
    """Duyệt một cổng — ghi ai duyệt, lúc nào, để lineage truy vết được (§10.4).

    Gọi lại trên cổng đã duyệt chỉ cập nhật người/giờ duyệt mới nhất (idempotent
    theo hướng "duyệt lại" chứ không lỗi) — orchestrator chỉ quan tâm
    `approved_at is not None`.
    """
    record = session.scalars(
        select(ApprovalGateRecord).where(
            ApprovalGateRecord.render_job_id == render_job_id,
            ApprovalGateRecord.gate == gate,
        )
    ).first()
    if record is None:
        raise ValueError(
            f"job {render_job_id} chưa có cổng `{gate}` — gọi ensure_gates trước "
            f"(bình thường chạy tự động lúc tạo job qua pipeline_runner)"
        )
    record.approved_by = approved_by
    record.approved_at = utcnow()
    if note:
        record.note = note
    session.flush()
    return record
