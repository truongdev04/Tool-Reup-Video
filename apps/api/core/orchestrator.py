"""Điều phối pipeline — docs §4, §11.3, §16.

Phase 0: chạy tuần tự trong tiến trình (không queue). Vì stage tuân contract ở
core/stage.py nên Phase 3 chỉ cần thay vòng lặp này bằng Celery task, không phải
sửa worker (§20).

Ba việc orchestrator làm mà stage không được tự làm:
  1. Cache: cùng input_hash thì tái dùng kết quả, không chạy lại (§16).
  2. Dirty propagation: đánh dấu stage nào phải chạy lại khi có thay đổi (§11.3).
  3. Retry + ghi stage_runs / error_logs (§16).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from core.hashing import output_digest, stage_input_hash
from core.stage import NonRetryableError, StageContext, StageResult, get_stage
from core.types import (
    PIPELINE_ORDER,
    STAGE_DEPENDENCIES,
    CacheScope,
    JobStatus,
    StageName,
)
from db.base import utcnow
from db.models import ErrorLog, RenderJob, StageRun

log = logging.getLogger("vla.orchestrator")


def dependents_of(stage: StageName) -> set[StageName]:
    """Mọi stage phải chạy lại (trực tiếp hoặc gián tiếp) khi `stage` đổi kết quả.

    Đây là phần lan truyền dirty-flag của partial re-run (§11.3): sửa 1 câu dịch
    -> translate dirty -> duration_fit, tts, forced_align... dirty theo,
    nhưng analyze/separate/stt thì KHÔNG, nên không phải chạy lại phần đắt tiền.
    """
    out: set[StageName] = set()
    frontier = {stage}
    while frontier:
        current = frontier.pop()
        for candidate, deps in STAGE_DEPENDENCIES.items():
            if current in deps and candidate not in out:
                out.add(candidate)
                frontier.add(candidate)
    return out


@dataclass
class StageOutcome:
    stage: StageName
    status: JobStatus
    cached: bool
    duration_ms: int
    output_ref: dict[str, Any] = field(default_factory=dict)
    note: str | None = None


@dataclass
class PipelineReport:
    job_id: str
    locale: str
    outcomes: list[StageOutcome] = field(default_factory=list)

    @property
    def total_ms(self) -> int:
        return sum(o.duration_ms for o in self.outcomes)

    @property
    def ok(self) -> bool:
        return all(o.status is not JobStatus.FAILED for o in self.outcomes)

    @property
    def cached_count(self) -> int:
        return sum(1 for o in self.outcomes if o.cached)


class Orchestrator:
    def __init__(self, ctx: StageContext, *, max_retries: int = 2) -> None:
        self.ctx = ctx
        self.max_retries = max_retries
        #: (input_hash, output_digest) của từng stage trong lần chạy hiện tại,
        #: dùng để nối cache key giữa các stage (xem _effective_key_of).
        self._keys: dict[StageName, tuple[str, str]] = {}

    # -- cache -------------------------------------------------------------

    def _lookup_cache(
        self, stage: StageName, input_hash: str, scope: CacheScope
    ) -> StageRun | None:
        """Tra cache theo phạm vi của stage (§16).

        Stage SOURCE tra theo input_hash trên MỌI job: input_hash đã gồm
        source checksum, provider, provider version và config version nên đủ
        định danh, và kết quả không phụ thuộc locale. Nhờ vậy bản ES và JA của
        cùng một video dùng chung một lần tách nhạc nền và một lần STT.

        Stage JOB tra trong phạm vi job vì output_ref trỏ tới bản ghi của
        chính job đó.
        """
        conditions = [
            StageRun.stage == stage,
            StageRun.input_hash == input_hash,
            StageRun.status == JobStatus.SUCCEEDED,
        ]
        if scope is CacheScope.JOB:
            conditions.append(StageRun.render_job_id == self.ctx.job_id)

        return self.ctx.session.scalars(
            select(StageRun).where(*conditions).order_by(StageRun.created_at.desc()).limit(1)
        ).first()

    def _effective_key_of(self, stage: StageName) -> str:
        """Khoá đại diện cho một stage = (input_hash, output_digest).

        Dùng CẢ HAI vì mỗi cái bắt một loại thay đổi khác nhau:
          - `output_digest` bắt trường hợp stage chạy lại và cho kết quả khác
            (vd. người vận hành sửa câu dịch — input không đổi, output đổi).
          - `input_hash` bắt trường hợp stage trả output HẰNG SỐ. Một stage như
            vậy sẽ nuốt mất thay đổi từ upstream và âm thầm phá vỡ invalidation
            của toàn bộ downstream — lỗi nghiêm trọng nhất mà cache có thể gây ra.

        Nguyên tắc chọn: cache sai (dùng lại kết quả cũ) thì xuất ra video có
        audio cũ mà không ai biết; cache trượt thì chỉ tốn thêm thời gian. Luôn
        nghiêng về phía chạy lại (§16).
        """
        if stage in self._keys:
            input_hash, digest = self._keys[stage]
        else:
            conditions = [
                StageRun.stage == stage,
                StageRun.status.in_((JobStatus.SUCCEEDED, JobStatus.NEEDS_REVIEW)),
            ]
            if get_stage(stage).cache_scope is CacheScope.JOB:
                conditions.append(StageRun.render_job_id == self.ctx.job_id)
            row = self.ctx.session.scalars(
                select(StageRun).where(*conditions).order_by(StageRun.created_at.desc()).limit(1)
            ).first()
            input_hash = row.input_hash if row else ""
            digest = output_digest(row.output_ref) if row else ""
            self._keys[stage] = (input_hash, digest)
        return output_digest({"i": input_hash, "o": digest})

    def _upstream_keys(self, stage: StageName) -> dict[str, str]:
        """Cache key của một stage PHẢI phụ thuộc các stage nó phụ thuộc (§16).

        Thiếu phần này thì partial re-run (§11.3) im lặng tái dùng kết quả cũ:
        sửa câu dịch xong mà TTS vẫn trả audio cũ.
        """
        return {str(dep): self._effective_key_of(dep) for dep in STAGE_DEPENDENCIES[stage]}

    # -- chạy 1 stage ------------------------------------------------------

    def run_stage(
        self,
        stage_name: StageName,
        stage_input: dict[str, Any] | None = None,
        *,
        force: bool = False,
    ) -> StageOutcome:
        stage = get_stage(stage_name)
        session = self.ctx.session
        stage_input = stage_input or {}

        input_hash = stage_input_hash(
            stage=str(stage_name),
            source_checksum=self.ctx.source_checksum,
            config_version=self.ctx.settings.config_version,
            provider=stage.provider,
            provider_version=stage.provider_version,
            params={
                **stage.cache_params(self.ctx),
                **stage_input,
                "__upstream__": self._upstream_keys(stage_name),
            },
        )

        if not force and (hit := self._lookup_cache(stage_name, input_hash, stage.cache_scope)):
            log.info("cache hit: %s", stage_name)
            self._keys[stage_name] = (input_hash, output_digest(hit.output_ref))
            return StageOutcome(
                stage=stage_name, status=JobStatus.SUCCEEDED, cached=True,
                duration_ms=0, output_ref=hit.output_ref, note="tái dùng cache",
            )

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            run = StageRun(
                render_job_id=self.ctx.job_id, stage=stage_name,
                status=JobStatus.RUNNING, input_hash=input_hash,
                attempt=attempt, started_at=utcnow(),
            )
            session.add(run)
            session.flush()

            started = time.perf_counter()
            try:
                result: StageResult = stage.run(self.ctx, stage_input)
            except Exception as exc:  # noqa: BLE001 — ghi lại rồi retry
                elapsed = int((time.perf_counter() - started) * 1000)
                run.status = JobStatus.FAILED
                run.finished_at = utcnow()
                run.duration_ms = elapsed
                run.error_message = str(exc)[:2000]
                retryable = not isinstance(exc, NonRetryableError)
                session.add(ErrorLog(
                    render_job_id=self.ctx.job_id, stage=stage_name,
                    message=str(exc)[:2000], attempt=attempt,
                    detail={"type": type(exc).__name__},
                    is_retryable=retryable,
                ))
                session.flush()
                last_error = exc
                if not retryable:
                    log.error("stage %s lỗi không thể retry: %s", stage_name, exc)
                    break
                log.warning("stage %s lỗi (lần %d): %s", stage_name, attempt, exc)
                continue

            elapsed = int((time.perf_counter() - started) * 1000)
            run.status = JobStatus.NEEDS_REVIEW if result.needs_review else JobStatus.SUCCEEDED
            run.finished_at = utcnow()
            run.duration_ms = elapsed
            run.output_ref = result.output_ref
            self._keys[stage_name] = (input_hash, output_digest(result.output_ref))
            session.flush()

            return StageOutcome(
                stage=stage_name, status=run.status, cached=False,
                duration_ms=elapsed, output_ref=result.output_ref, note=result.note,
            )

        return StageOutcome(
            stage=stage_name, status=JobStatus.FAILED, cached=False,
            duration_ms=0, note=f"thất bại sau {self.max_retries + 1} lần: {last_error}",
        )

    # -- chạy cả pipeline --------------------------------------------------

    def run_pipeline(
        self,
        *,
        stages: tuple[StageName, ...] = PIPELINE_ORDER,
        stop_on_failure: bool = True,
    ) -> PipelineReport:
        report = PipelineReport(job_id=self.ctx.job_id, locale=self.ctx.locale)
        job = self.ctx.session.get(RenderJob, self.ctx.job_id)

        for i, stage_name in enumerate(stages, start=1):
            if job:
                job.current_stage = stage_name
                job.status = JobStatus.RUNNING
                job.progress = round(i / len(stages), 3)
                self.ctx.session.flush()

            outcome = self.run_stage(stage_name)
            report.outcomes.append(outcome)

            if outcome.status is JobStatus.FAILED and stop_on_failure:
                if job:
                    job.status = JobStatus.FAILED
                    job.error_message = outcome.note
                break

        if job and report.ok:
            job.status = (
                JobStatus.NEEDS_REVIEW
                if any(o.status is JobStatus.NEEDS_REVIEW for o in report.outcomes)
                else JobStatus.SUCCEEDED
            )
            job.progress = 1.0

        self.ctx.session.flush()
        return report

    def rerun_from(self, stage: StageName) -> PipelineReport:
        """Partial re-run (§11.3): chạy lại `stage` và mọi stage phụ thuộc nó.

        Các stage không phụ thuộc giữ nguyên cache — đó là điểm mấu chốt khiến
        sửa một câu dịch không kéo theo chạy lại STT/separate.
        """
        dirty = {stage} | dependents_of(stage)
        ordered = tuple(s for s in PIPELINE_ORDER if s in dirty)
        log.info("partial re-run từ %s: %d stage", stage, len(ordered))
        # force=True cho chính stage bị sửa; các stage sau vẫn qua cache bình thường
        # nhưng input_hash của chúng đổi theo nên tự nhiên cache miss.
        for s in dirty:
            self._keys.pop(s, None)
        self.run_stage(stage, force=True)
        return self.run_pipeline(stages=tuple(s for s in ordered if s != stage))
