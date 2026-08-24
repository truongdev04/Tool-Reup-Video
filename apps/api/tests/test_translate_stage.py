"""Stage `translate` (§6.7) — chỉ test phần cache liên quan tới `output_ref`.

Bug đã bắt được khi soát lại cơ chế cho tính năng "sửa inline" ở dashboard
(§19): `output_ref` trước đây chỉ chứa SỐ LƯỢNG (units_translated,
over_budget...), không chứa NỘI DUNG bản dịch. Dịch lại ra chữ khác nhưng
cùng số đơn vị (vd. sửa thuật ngữ, `rerun_from(translate)`) thì
`output_digest` không đổi -> downstream (`duration_fit`/`tts`/...) cache hit
nhầm bản dịch CŨ — đúng kiểu lỗi nghiêm trọng nhất mà caching.md cảnh báo
(xuất video với audio cũ mà không ai biết)."""

from __future__ import annotations

import workers.translation.stage as translate_stage_module
from core.hashing import output_digest
from core.stage import StageContext
from db.models import Project, RenderJob, SourceVideo, TranslationUnit
from services.providers.base import (
    ProviderConfig,
    TranslationProvider,
    TranslationRequest,
    TranslationResponse,
)
from workers.translation.stage import TranslateStage


class _FakeProvider(TranslationProvider):
    def __init__(self, config: ProviderConfig, texts: dict[int, str]) -> None:
        super().__init__(config)
        self._texts = texts

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        return TranslationResponse(
            translations={item.idx: self._texts[item.idx] for item in request.items},
        )


def _config() -> ProviderConfig:
    return ProviderConfig(id="fake", name="fake", adapter="mock", model="fake-1")


def _setup(session, storage):
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
    session.add(TranslationUnit(
        render_job_id=job.id, idx=0, source_text="hello", start_ms=0, end_ms=900,
    ))
    session.flush()
    return StageContext(
        session=session, job_id=job.id, project_id=project.id,
        source_checksum=source.checksum, locale="es-ES", storage=storage,
    )


def test_output_digest_doi_khi_noi_dung_dich_doi_dau_cung_so_luong(session, storage, monkeypatch):
    """Cùng 1 đơn vị, cùng over_budget=0 ở cả hai lần dịch — chỉ nội dung khác
    nhau (giả lập sửa thuật ngữ) — output_digest PHẢI khác, nếu không
    downstream sẽ không biết bản dịch đã đổi."""
    ctx = _setup(session, storage)

    monkeypatch.setattr(
        translate_stage_module, "get_provider",
        lambda pid: _FakeProvider(_config(), {0: "hola"}),
    )
    first = TranslateStage().run(ctx, {})

    monkeypatch.setattr(
        translate_stage_module, "get_provider",
        lambda pid: _FakeProvider(_config(), {0: "buenos días"}),
    )
    second = TranslateStage().run(ctx, {})

    assert first.output_ref["units_translated"] == second.output_ref["units_translated"]
    assert first.output_ref["over_budget"] == second.output_ref["over_budget"]
    assert output_digest(first.output_ref) != output_digest(second.output_ref), (
        "nội dung bản dịch đổi mà output_digest không đổi -> cache trả audio cũ (§16)"
    )


def test_output_digest_giong_het_khi_dich_lai_ra_dung_noi_dung_cu(session, storage, monkeypatch):
    """Ngược lại: dịch lại ra ĐÚNG nội dung cũ thì digest phải giống hệt —
    downstream vẫn được dùng cache (caching.md: 'output giống hệt thì vẫn
    dùng được cache')."""
    ctx = _setup(session, storage)

    monkeypatch.setattr(
        translate_stage_module, "get_provider",
        lambda pid: _FakeProvider(_config(), {0: "hola"}),
    )
    first = TranslateStage().run(ctx, {})
    second = TranslateStage().run(ctx, {})

    assert output_digest(first.output_ref) == output_digest(second.output_ref)
