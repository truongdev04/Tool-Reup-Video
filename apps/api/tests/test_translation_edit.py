"""Sửa inline một `translation_unit` (§19 Video Workspace) —
`services/translation_edit.py`.

Test cốt lõi: sửa bản dịch KHÔNG chạy lại `TranslateStage` (không gọi lại
provider dịch, tốn tiền vô ích) nhưng VẪN khiến downstream cache miss đúng —
cùng cơ chế `(input_hash, output_digest)` mà `.claude/rules/caching.md` mô tả,
áp dụng thủ công thay vì qua `Stage.run()` thật.
"""

from __future__ import annotations

import pytest

import workers.translation.stage as translate_stage_module
from core.orchestrator import Orchestrator
from core.stage import Stage, StageContext, StageResult, register
from core.types import StageName
from db.models import Project, RenderJob, SourceVideo, Translation, TranslationUnit
from services.providers.base import (
    ProviderConfig,
    TranslationProvider,
    TranslationRequest,
    TranslationResponse,
)
from services.translation_edit import edit_unit_translation
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


class _Counting(Stage):
    def __init__(self, name: StageName) -> None:
        self.name = name
        self.calls = 0

    def run(self, ctx: StageContext, stage_input: dict) -> StageResult:
        self.calls += 1
        return StageResult(output_ref={"run": self.calls})


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
    unit = TranslationUnit(render_job_id=job.id, idx=0, source_text="hello", start_ms=0, end_ms=900)
    session.add(unit)
    session.flush()
    ctx = StageContext(
        session=session, job_id=job.id, project_id=project.id,
        source_checksum=source.checksum, locale="es-ES", storage=storage,
    )
    return ctx, unit


def test_edit_tao_version_moi_va_vo_hieu_ban_cu(session, storage, monkeypatch):
    ctx, unit = _setup(session, storage)
    monkeypatch.setattr(
        translate_stage_module, "get_provider", lambda pid: _FakeProvider(_config(), {0: "hola"}),
    )
    TranslateStage().run(ctx, {})

    edit_unit_translation(session, unit_id=unit.id, locale="es-ES", text="hola sửa", edited_by="qa@x")

    rows = session.query(Translation).filter_by(translation_unit_id=unit.id).all()
    active = [r for r in rows if r.is_active]
    assert len(active) == 1
    assert active[0].text == "hola sửa"
    assert active[0].version == 2, "phải tăng version, không ghi đè bản cũ (§10.4 lineage)"
    assert active[0].approved_by == "qa@x"
    old = [r for r in rows if not r.is_active]
    assert old[0].text == "hola", "bản cũ phải còn lại, chỉ tắt is_active"


def test_edit_unit_khong_ton_tai_bao_loi(session, storage):
    with pytest.raises(ValueError, match="translation_unit"):
        edit_unit_translation(session, unit_id="not-exist", locale="es-ES", text="x", edited_by="a")


def test_sua_inline_lam_downstream_cache_miss_nhung_translate_van_cache_hit(
    session, storage, monkeypatch,
):
    ctx, unit = _setup(session, storage)
    monkeypatch.setattr(
        translate_stage_module, "get_provider", lambda pid: _FakeProvider(_config(), {0: "hola"}),
    )
    # Qua Orchestrator (không gọi TranslateStage().run() trực tiếp như 2 test
    # trên) — CHỈ Orchestrator.run_stage() mới ghi StageRun, và _bump_translate_
    # cache cần một StageRun TRANSLATE thật đã tồn tại để lấy input_hash gốc.
    Orchestrator(ctx).run_stage(StageName.TRANSLATE)

    fit = _Counting(StageName.DURATION_FIT)
    register(fit)
    Orchestrator(ctx).run_stage(StageName.DURATION_FIT)
    assert fit.calls == 1

    edit_unit_translation(session, unit_id=unit.id, locale="es-ES", text="hola sửa", edited_by="qa@x")

    orch = Orchestrator(ctx)  # instance mới — không dùng cache _keys trong bộ nhớ của lần chạy trước
    fit_outcome = orch.run_stage(StageName.DURATION_FIT)
    assert fit.calls == 2, "sửa bản dịch phải làm downstream chạy lại — không thì audio cũ vẫn được dùng"
    assert not fit_outcome.cached

    translate_outcome = orch.run_stage(StageName.TRANSLATE)
    assert translate_outcome.cached, (
        "TRANSLATE vẫn phải cache-hit sau khi sửa inline — không được gọi lại provider dịch"
    )
