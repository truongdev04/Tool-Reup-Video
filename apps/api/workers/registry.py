"""Đăng ký toàn bộ 18 stage vào registry.

Đã implement thật: ingest, analyze, separate, stt, segment_plan, translate,
duration_fit, tts, forced_align, timeline_assembly, subtitle, compose, render, qc.
Các stage còn lại là NotImplementedStage giữ đúng contract — harness chạy hết
pipeline mà không sập, và mỗi stub ghi rõ nó thuộc phase nào theo lộ trình §20.

`render` phụ thuộc COMPOSE trong dependency graph (§11.3) nhưng KHÔNG gọi
compose — nó tự kiểm tra composed.mp4 có tồn tại theo quy ước đường dẫn cố
định hay không, đúng nguyên tắc "stage không gọi stage khác" (§11.1). compose
chỉ áp logo/watermark (Phase 1 tối thiểu); CTA/intro-outro động vẫn là Phase 2.
"""

from __future__ import annotations

from core.stage import NotImplementedStage, register, registry
from core.types import StageName
from workers.analyzer.stage import AnalyzeStage
from workers.audio.stage import SeparateStage
from workers.compose.stage import ComposeStage
from workers.duration_fit.stage import DurationFitStage
from workers.forced_align.stage import ForcedAlignStage
from workers.ingest.stage import IngestStage
from workers.qc.stage import QCStage
from workers.render.stage import RenderStage
from workers.segment_planner.stage import SegmentPlanStage
from workers.stt.stage import STTStage
from workers.subtitle.stage import SubtitleStage
from workers.timeline.stage import TimelineAssemblyStage
from workers.translation.stage import TranslateStage
from workers.tts.stage import TTSStage

#: Stage nào đến ở phase nào — theo docs §20.
_PLANNED_PHASE: dict[StageName, str] = {
    StageName.DIARIZE: "Phase 2",
    StageName.ONSCREEN_TEXT: "Phase 6",
    StageName.LIPSYNC: "Phase 6",
    StageName.PUBLISH: "Phase 5",
}


def register_all() -> None:
    register(IngestStage())
    register(AnalyzeStage())
    register(SeparateStage())
    register(ComposeStage())
    register(STTStage())
    register(SegmentPlanStage())
    register(TranslateStage())
    register(DurationFitStage())
    register(TTSStage())
    register(ForcedAlignStage())
    register(TimelineAssemblyStage())
    register(SubtitleStage())
    register(RenderStage())
    register(QCStage())
    for name, phase in _PLANNED_PHASE.items():
        register(NotImplementedStage(name, phase))


register_all()

__all__ = ["register_all", "registry"]
