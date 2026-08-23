"""Cache key phải nối theo nội dung giữa các stage — docs §16, §11.3.

Đây là cơ chế chống lỗi "sửa câu dịch xong mà TTS vẫn trả audio cũ".
"""

from __future__ import annotations

from typing import Any

import pytest

from core.orchestrator import Orchestrator, dependents_of
from core.stage import Stage, StageContext, StageResult, register
from core.types import PIPELINE_ORDER, JobStatus, StageName
from db.models import Project, RenderJob, SourceVideo


@pytest.fixture
def ctx(session, storage) -> StageContext:
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
    return StageContext(
        session=session, job_id=job.id, project_id=project.id,
        source_checksum=source.checksum, locale="es-ES", storage=storage,
    )


class _Mutable(Stage):
    """Stage giả lập translate: output đổi được để test lan truyền cache."""

    name = StageName.TRANSLATE

    def __init__(self) -> None:
        self.payload = "bản dịch v1"
        self.calls = 0

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        self.calls += 1
        return StageResult(output_ref={"text": self.payload})


class _Passthrough(Stage):
    """Stage trung gian trả output HẰNG SỐ.

    Đây chính là kịch bản mà việc nối `input_hash` sinh ra để xử lý: nếu chuỗi
    cache chỉ dựa vào output_digest thì stage này nuốt mất thay đổi từ upstream
    và mọi stage sau nó im lặng dùng kết quả cũ.
    """

    def __init__(self, name: StageName) -> None:
        self.name = name

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        return StageResult(output_ref={"passthrough": True})


class _Counting(Stage):
    """Stage giả lập tts: đếm số lần thực sự chạy (không tính cache hit)."""

    name = StageName.TTS

    def __init__(self) -> None:
        self.calls = 0

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        self.calls += 1
        return StageResult(output_ref={"audio": f"run-{self.calls}"})


def test_dependents_khong_gom_stage_dat_tien():
    """Sửa câu dịch KHÔNG được kéo theo chạy lại STT/separate (§11.3)."""
    dirty = dependents_of(StageName.TRANSLATE)
    for cheap_to_keep in (StageName.INGEST, StageName.ANALYZE, StageName.SEPARATE,
                          StageName.STT, StageName.DIARIZE, StageName.SEGMENT_PLAN):
        assert cheap_to_keep not in dirty, f"{cheap_to_keep} không được dirty"
    for must_rerun in (StageName.DURATION_FIT, StageName.TTS, StageName.FORCED_ALIGN,
                       StageName.SUBTITLE, StageName.RENDER):
        assert must_rerun in dirty


def test_cache_hit_khi_khong_doi_gi(ctx):
    tts = _Counting()
    register(_Mutable())
    register(_Passthrough(StageName.DURATION_FIT))
    register(tts)
    orch = Orchestrator(ctx)

    orch.run_stage(StageName.TRANSLATE)
    orch.run_stage(StageName.DURATION_FIT)
    first = orch.run_stage(StageName.TTS)
    assert not first.cached and tts.calls == 1

    second = orch.run_stage(StageName.TTS)
    assert second.cached, "chạy lại y nguyên phải dùng cache"
    assert tts.calls == 1, "cache hit không được gọi vào stage"


def test_upstream_doi_thi_downstream_mat_cache(ctx):
    """Cốt lõi: translate ra kết quả khác -> TTS PHẢI chạy lại.

    Không có nối cache key theo nội dung thì test này fail và tool sẽ im lặng
    xuất video có audio cũ.
    """
    translate = _Mutable()
    tts = _Counting()
    register(translate)
    register(_Passthrough(StageName.DURATION_FIT))
    register(tts)
    orch = Orchestrator(ctx)

    orch.run_stage(StageName.TRANSLATE)
    orch.run_stage(StageName.DURATION_FIT)
    orch.run_stage(StageName.TTS)
    assert tts.calls == 1

    # Người vận hành sửa câu dịch
    translate.payload = "bản dịch v2 — đã sửa thuật ngữ"
    report = orch.rerun_from(StageName.TRANSLATE)

    assert tts.calls == 2, "upstream đổi mà TTS vẫn dùng cache — lỗi nghiêm trọng (§16)"
    ran = {o.stage: o for o in report.outcomes}
    assert not ran[StageName.TTS].cached


def test_output_giong_het_thi_van_duoc_dung_cache(ctx):
    """Chạy lại upstream nhưng output y hệt -> downstream vẫn cache được.

    Nối theo NỘI DUNG chứ không theo thời điểm — đây là hành vi đúng, giúp
    không phải render lại khi sửa rồi hoàn tác.
    """
    register(_Mutable())
    tts = _Counting()
    register(tts)
    orch = Orchestrator(ctx)

    orch.run_stage(StageName.TRANSLATE)
    orch.run_stage(StageName.DURATION_FIT)
    orch.run_stage(StageName.TTS)
    assert tts.calls == 1

    orch.rerun_from(StageName.TRANSLATE)  # payload không đổi
    assert tts.calls == 1, "output không đổi thì không cần chạy lại downstream"


def test_stage_loi_duoc_retry_va_ghi_error_log(ctx):
    from db.models import ErrorLog

    class _Flaky(Stage):
        name = StageName.RENDER

        def __init__(self) -> None:
            self.calls = 0

        def run(self, c, i):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("API tạm thời lỗi")
            return StageResult(output_ref={"ok": True})

    flaky = _Flaky()
    register(flaky)
    outcome = Orchestrator(ctx, max_retries=2).run_stage(StageName.RENDER)

    assert outcome.status is JobStatus.SUCCEEDED
    assert flaky.calls == 3
    assert ctx.session.query(ErrorLog).count() == 2


def test_moi_stage_deu_dang_ky(ctx):
    from core.stage import registry

    assert set(registry()) >= set(PIPELINE_ORDER)


def test_stage_source_scope_cho_hash_giong_nhau_moi_locale(session, storage):
    """Stage không phụ thuộc locale phải ra CÙNG cache key cho mọi locale.

    Kèm locale vào cache_params của stage SOURCE là vô hiệu hoá cache_scope dù
    đã khai báo đúng — và sai lầm đó lan xuống toàn bộ chuỗi phía sau. Với video
    60 phút × 10 locale, đây là chênh lệch giữa chạy STT 1 lần và 10 lần.
    """
    from core.hashing import stage_input_hash
    from core.stage import get_stage
    from core.types import CacheScope

    project = Project(name="T")
    session.add(project)
    session.flush()
    source = SourceVideo(
        project_id=project.id, filename="a.mp4", storage_path="a.mp4",
        checksum="c0ffee", rights_note="test",
    )
    session.add(source)
    session.flush()

    contexts = {}
    for locale in ("es-ES", "ja-JP"):
        job = RenderJob(project_id=project.id, source_video_id=source.id, locale=locale)
        session.add(job)
        session.flush()
        contexts[locale] = StageContext(
            session=session, job_id=job.id, project_id=project.id,
            source_checksum=source.checksum, locale=locale, storage=storage,
        )

    def key_for(stage_name, locale):
        ctx = contexts[locale]
        stage = get_stage(stage_name)
        return stage_input_hash(
            stage=str(stage_name), source_checksum=source.checksum,
            config_version="0.1.0", provider=stage.provider,
            provider_version=stage.provider_version,
            params=stage.cache_params(ctx),
        )

    source_scoped = [
        s for s in PIPELINE_ORDER
        if get_stage(s).cache_scope is CacheScope.SOURCE
    ]
    assert source_scoped, "phải có ít nhất vài stage khai báo SOURCE scope"

    for stage_name in source_scoped:
        assert key_for(stage_name, "es-ES") == key_for(stage_name, "ja-JP"), (
            f"{stage_name} khai báo SOURCE scope nhưng cache key vẫn đổi theo locale"
        )
