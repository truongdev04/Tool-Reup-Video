"""Approval gates — biến "manual review" thành quy trình có vết (§11.2).

Hai lớp: `services/approval_gates.py` (tạo/duyệt cổng, chỉ đọc/ghi DB, không
điều phối gì) và `Orchestrator._pending_gate` + `run_pipeline` (thực sự chặn
pipeline). Dùng stage giả như `test_cache_chain.py` để test chặn/tiếp tục mà
không cần STT/translate thật.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.orchestrator import Orchestrator
from core.stage import Stage, StageContext, StageResult, register
from core.types import ApprovalGate, JobStatus, StageName
from db.models import ApprovalGateRecord, Project, RenderJob, SourceVideo
from services.approval_gates import approve, ensure_gates


class _Counting(Stage):
    """Đếm số lần THỰC SỰ chạy (không tính cache hit) — như `_Counting` của
    test_cache_chain.py, dùng lại mẫu đó để test hành vi orchestrator."""

    def __init__(self, name: StageName) -> None:
        self.name = name
        self.calls = 0

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        self.calls += 1
        return StageResult(output_ref={"run": self.calls})


@pytest.fixture
def setup(session, storage):
    project = Project(name="T")
    session.add(project)
    session.flush()
    source = SourceVideo(
        project_id=project.id, filename="a.mp4", storage_path="a.mp4",
        checksum="c0ffee", rights_note="test",
    )
    session.add(source)
    session.flush()
    job = RenderJob(project_id=project.id, source_video_id=source.id, locale="es-ES")
    session.add(job)
    session.flush()
    ctx = StageContext(
        session=session, job_id=job.id, project_id=project.id,
        source_checksum=source.checksum, locale="es-ES", storage=storage,
    )
    return job, ctx


# ---------------------------------------------------------------------------
# services/approval_gates.py
# ---------------------------------------------------------------------------


def test_project_moi_mac_dinh_khong_bat_cong_nao(session):
    """Project chạy tự động hoàn toàn thì tắt hết — mặc định phải là rỗng,
    không phải phải liệt kê đủ 4 cổng = False (§11.2)."""
    project = Project(name="T")
    session.add(project)
    session.flush()
    assert project.approval_gates == {}


def test_ensure_gates_tao_du_4_cong_tat_mac_dinh(session):
    records = ensure_gates(session, render_job_id="job-x")
    assert {r.gate for r in records} == set(ApprovalGate)
    assert all(not r.is_enabled for r in records), "thiếu config coi như tắt hết (tự động)"


def test_ensure_gates_bat_dung_cong_theo_config(session):
    records = ensure_gates(session, render_job_id="job-x", config={"translation": True})
    by_gate = {r.gate: r for r in records}
    assert by_gate[ApprovalGate.TRANSLATION].is_enabled
    assert not by_gate[ApprovalGate.TRANSCRIPT].is_enabled, "chỉ bật đúng cổng có trong config"


def test_ensure_gates_goi_lai_khong_tao_trung(session):
    """Idempotent (§11.1) — pipeline_runner gọi lại mỗi lần chạy job."""
    ensure_gates(session, render_job_id="job-x")
    ensure_gates(session, render_job_id="job-x")
    assert session.query(ApprovalGateRecord).filter_by(render_job_id="job-x").count() == 4


def test_ensure_gates_khong_dung_ban_ghi_da_duyet(session):
    ensure_gates(session, render_job_id="job-x", config={"final": True})
    approve(session, render_job_id="job-x", gate=ApprovalGate.FINAL, approved_by="qa@x")

    ensure_gates(session, render_job_id="job-x", config={"final": True})

    record = session.query(ApprovalGateRecord).filter_by(
        render_job_id="job-x", gate=ApprovalGate.FINAL,
    ).one()
    assert record.approved_by == "qa@x", "gọi lại ensure_gates không được xoá dấu vết đã duyệt"


def test_approve_bao_loi_ro_rang_khi_chua_co_cong(session):
    with pytest.raises(ValueError, match="chưa có cổng"):
        approve(session, render_job_id="job-x", gate=ApprovalGate.FINAL, approved_by="a")


# ---------------------------------------------------------------------------
# Orchestrator — chặn/tiếp tục pipeline thật
# ---------------------------------------------------------------------------


def test_cong_tat_thi_pipeline_chay_xuyen_qua_binh_thuong(setup):
    job, ctx = setup
    ensure_gates(ctx.session, render_job_id=job.id, config={})
    stt, translate = _Counting(StageName.STT), _Counting(StageName.TRANSLATE)
    register(stt)
    register(translate)

    Orchestrator(ctx).run_pipeline(stages=(StageName.STT, StageName.TRANSLATE))

    assert stt.calls == 1 and translate.calls == 1
    assert job.status is JobStatus.SUCCEEDED
    assert job.progress == 1.0


def test_cong_bat_va_chua_duyet_thi_chan_pipeline_ngay_sau_stage_do(setup):
    job, ctx = setup
    ensure_gates(ctx.session, render_job_id=job.id, config={"transcript": True})
    stt, translate = _Counting(StageName.STT), _Counting(StageName.TRANSLATE)
    register(stt)
    register(translate)

    Orchestrator(ctx).run_pipeline(stages=(StageName.STT, StageName.TRANSLATE))

    assert stt.calls == 1, "stage trước cổng vẫn phải chạy"
    assert translate.calls == 0, "cổng transcript chưa duyệt thì translate không được chạy"
    assert job.status is JobStatus.NEEDS_REVIEW
    assert job.progress != 1.0, "pipeline chưa xong thì không được báo progress=100%"


def test_duyet_cong_xong_chay_lai_thi_tiep_tuc_tu_dung_cho_dung(setup):
    job, ctx = setup
    ensure_gates(ctx.session, render_job_id=job.id, config={"transcript": True})
    stt, translate = _Counting(StageName.STT), _Counting(StageName.TRANSLATE)
    register(stt)
    register(translate)

    Orchestrator(ctx).run_pipeline(stages=(StageName.STT, StageName.TRANSLATE))
    assert translate.calls == 0

    approve(ctx.session, render_job_id=job.id, gate=ApprovalGate.TRANSCRIPT, approved_by="qa@x")
    Orchestrator(ctx).run_pipeline(stages=(StageName.STT, StageName.TRANSLATE))

    assert stt.calls == 1, "stt đã cache hit ở lần chạy lại, không được chạy lại thật"
    assert translate.calls == 1, "sau khi duyệt cổng, pipeline phải đi tiếp"
    assert job.status is JobStatus.SUCCEEDED


def test_job_khong_qua_ensure_gates_thi_chay_nhu_khong_co_gate(setup):
    """Đường cũ (mọi test khác trong repo dựng StageContext thẳng, không gọi
    ensure_gates) phải KHÔNG bị approval gates chặn — mặc định an toàn, giống
    nguyên tắc "thiếu cấu hình thì bỏ qua" của diarize/compose."""
    job, ctx = setup
    stt = _Counting(StageName.STT)
    register(stt)

    Orchestrator(ctx).run_pipeline(stages=(StageName.STT,))

    assert stt.calls == 1
    assert job.status is JobStatus.SUCCEEDED
