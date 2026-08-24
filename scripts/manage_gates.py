#!/usr/bin/env python
"""CLI vận hành approval gates (§11.2) — chưa có dashboard (Phase 4), đây là
đường DUY NHẤT ngoài Python thủ công để bật/tắt cổng, duyệt, và chạy tiếp
một job đang dừng chờ duyệt. Xem `.claude/rules/approval-gates.md`.

    # Xem trạng thái 4 cổng của một job
    python scripts/manage_gates.py list --job <job_id>

    # Xem mọi job của một project + cổng nào (nếu có) đang chặn
    python scripts/manage_gates.py list --project "Demo Phase 0"

    # Bật cổng translation+final cho MỌI job MỚI tạo sau này của project
    # (không đụng job đã có — xem ensure_gates() trong services/approval_gates.py)
    python scripts/manage_gates.py set-project --project "Demo Phase 0" translation=on final=on

    # Bật/tắt trực tiếp một cổng của MỘT job cụ thể (kể cả job đã tạo từ trước)
    python scripts/manage_gates.py set-job --job <job_id> transcript=on

    # Duyệt một cổng
    python scripts/manage_gates.py approve --job <job_id> transcript --by "qa@example.com"

    # Chạy tiếp job sau khi duyệt (mọi stage trước cổng cache-hit tức thì)
    python scripts/manage_gates.py resume --job <job_id>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_API = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(_API))

from sqlalchemy import select  # noqa: E402

from core.orchestrator import PipelineReport  # noqa: E402
from core.types import ApprovalGate, JobStatus  # noqa: E402
from db.base import create_all, session_scope  # noqa: E402
from db.models import ApprovalGateRecord, Project, RenderJob  # noqa: E402
from services.approval_gates import approve as approve_gate  # noqa: E402
from services.approval_gates import ensure_gates  # noqa: E402
from services.pipeline_runner import resume_job  # noqa: E402

GREEN, YELLOW, RED, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"


def _parse_kv_gates(pairs: list[str]) -> dict[str, bool]:
    """`transcript=on translation=off` -> {"transcript": True, "translation": False}."""
    out: dict[str, bool] = {}
    valid = {str(g) for g in ApprovalGate}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"sai định dạng `{pair}` — cần dạng `gate=on` hoặc `gate=off`")
        gate, _, value = pair.partition("=")
        if gate not in valid:
            raise SystemExit(f"cổng `{gate}` không hợp lệ — chọn trong {sorted(valid)}")
        if value.lower() not in ("on", "off"):
            raise SystemExit(f"giá trị `{value}` không hợp lệ — dùng `on` hoặc `off`")
        out[gate] = value.lower() == "on"
    return out


def _print_gates(job: RenderJob, records: list[ApprovalGateRecord]) -> None:
    colour = {
        JobStatus.SUCCEEDED: GREEN, JobStatus.NEEDS_REVIEW: YELLOW, JobStatus.FAILED: RED,
    }.get(job.status, "")
    print(
        f"\n  Job {job.id[:8]}  ·  locale {job.locale}  ·  "
        f"{colour}{job.status}{RESET}  ·  stage {job.current_stage or '-'}"
    )
    by_gate = {r.gate: r for r in records}
    for gate in ApprovalGate:
        r = by_gate.get(gate)
        if r is None:
            print(f"    {gate:<12}{DIM}chưa tạo bản ghi (job chưa qua ensure_gates){RESET}")
            continue
        state = f"{GREEN}BẬT{RESET}" if r.is_enabled else f"{DIM}tắt{RESET}"
        if not r.is_enabled:
            approval = ""
        elif r.approved_at:
            approval = f"{GREEN}đã duyệt{RESET} bởi {r.approved_by} lúc {r.approved_at:%Y-%m-%d %H:%M}"
        else:
            approval = f"{YELLOW}CHỜ DUYỆT{RESET}"
        print(f"    {gate:<12}{state:<20}{approval}")


def cmd_list(args: argparse.Namespace) -> int:
    with session_scope() as session:
        if args.job:
            job = session.get(RenderJob, args.job)
            if job is None:
                print(f"{RED}không có job {args.job}{RESET}")
                return 1
            records = session.scalars(
                select(ApprovalGateRecord).where(ApprovalGateRecord.render_job_id == job.id)
            ).all()
            _print_gates(job, list(records))
            return 0

        project = session.query(Project).filter_by(name=args.project).one_or_none()
        if project is None:
            print(f"{RED}không có project `{args.project}`{RESET}")
            return 1
        jobs = session.scalars(
            select(RenderJob).where(RenderJob.project_id == project.id)
        ).all()
        if not jobs:
            print(f"{DIM}project `{args.project}` chưa có job nào{RESET}")
            return 0
        for job in jobs:
            records = session.scalars(
                select(ApprovalGateRecord).where(ApprovalGateRecord.render_job_id == job.id)
            ).all()
            _print_gates(job, list(records))
        return 0


def cmd_set_project(args: argparse.Namespace) -> int:
    updates = _parse_kv_gates(args.gates)
    create_all()
    with session_scope() as session:
        project = session.query(Project).filter_by(name=args.project).one_or_none()
        if project is None:
            print(f"{RED}không có project `{args.project}`{RESET}")
            return 1
        project.approval_gates = {**project.approval_gates, **updates}
        print(f"{GREEN}đã cập nhật{RESET} project `{args.project}`.approval_gates = {project.approval_gates}")
        print(f"{DIM}chỉ áp dụng cho job MỚI tạo sau lệnh này — dùng `set-job` cho job đã có{RESET}")
        return 0


def cmd_set_job(args: argparse.Namespace) -> int:
    updates = _parse_kv_gates(args.gates)
    create_all()
    with session_scope() as session:
        job = session.get(RenderJob, args.job)
        if job is None:
            print(f"{RED}không có job {args.job}{RESET}")
            return 1
        records = {r.gate: r for r in ensure_gates(session, render_job_id=job.id)}
        for gate, enabled in updates.items():
            records[ApprovalGate(gate)].is_enabled = enabled
        _print_gates(job, list(records.values()))
        return 0


def cmd_approve(args: argparse.Namespace) -> int:
    create_all()
    with session_scope() as session:
        try:
            record = approve_gate(
                session, render_job_id=args.job, gate=ApprovalGate(args.gate),
                approved_by=args.by, note=args.note,
            )
        except ValueError as exc:
            print(f"{RED}{exc}{RESET}")
            return 1
        print(
            f"{GREEN}đã duyệt{RESET} cổng `{record.gate}` cho job {args.job[:8]} "
            f"bởi {record.approved_by} lúc {record.approved_at:%Y-%m-%d %H:%M}"
        )
        print(f"{DIM}chạy tiếp: python scripts/manage_gates.py resume --job {args.job}{RESET}")
        return 0


def _print_report(report: PipelineReport) -> None:
    print(f"\n  Job {report.job_id[:8]}  ·  locale {report.locale}")
    print(f"  {DIM}{'stage':<20}{'trạng thái':<14}{'thời gian':>10}   ghi chú{RESET}")
    for o in report.outcomes:
        colour = {
            JobStatus.SUCCEEDED: GREEN, JobStatus.NEEDS_REVIEW: YELLOW, JobStatus.FAILED: RED,
        }.get(o.status, "")
        timing = "cache" if o.cached else f"{o.duration_ms} ms"
        note = o.note or ""
        print(f"  {o.stage:<20}{colour}{o.status:<14}{RESET}{timing:>10}   {DIM}{note}{RESET}")
    print(f"  {DIM}{'─' * 62}{RESET}")
    print(f"  tổng {report.total_ms} ms · {report.cached_count} stage dùng cache")


def cmd_resume(args: argparse.Namespace) -> int:
    try:
        report = resume_job(args.job)
    except ValueError as exc:
        print(f"{RED}{exc}{RESET}")
        return 1
    _print_report(report)
    return 0 if report.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="xem trạng thái cổng của một job hoặc mọi job của một project")
    group = p_list.add_mutually_exclusive_group(required=True)
    group.add_argument("--job", help="job id")
    group.add_argument("--project", help="tên project")
    p_list.set_defaults(func=cmd_list)

    p_set_proj = sub.add_parser("set-project", help="bật/tắt cổng mặc định cho job MỚI của một project")
    p_set_proj.add_argument("--project", required=True)
    p_set_proj.add_argument("gates", nargs="+", help="vd. transcript=on translation=off")
    p_set_proj.set_defaults(func=cmd_set_project)

    p_set_job = sub.add_parser("set-job", help="bật/tắt trực tiếp cổng của một job cụ thể đã tồn tại")
    p_set_job.add_argument("--job", required=True)
    p_set_job.add_argument("gates", nargs="+", help="vd. transcript=on")
    p_set_job.set_defaults(func=cmd_set_job)

    p_approve = sub.add_parser("approve", help="duyệt một cổng của một job")
    p_approve.add_argument("--job", required=True)
    p_approve.add_argument("gate", choices=[str(g) for g in ApprovalGate])
    p_approve.add_argument("--by", required=True, help="ai duyệt — ghi vào approved_by (§10.4 lineage)")
    p_approve.add_argument("--note")
    p_approve.set_defaults(func=cmd_approve)

    p_resume = sub.add_parser("resume", help="chạy tiếp một job đang dừng chờ duyệt")
    p_resume.add_argument("--job", required=True)
    p_resume.set_defaults(func=cmd_resume)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
