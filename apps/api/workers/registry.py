"""Đăng ký toàn bộ 18 stage vào registry.

Đã implement thật: ingest, analyze, separate, stt, segment_plan, translate.
Các stage còn lại là NotImplementedStage giữ đúng contract — harness chạy hết
pipeline mà không sập, và mỗi stub ghi rõ nó thuộc phase nào theo lộ trình §20.
"""

from __future__ import annotations

from core.stage import NotImplementedStage, register, registry
from core.types import StageName
from workers.analyzer.stage import AnalyzeStage
from workers.audio.stage import SeparateStage
from workers.ingest.stage import IngestStage
from workers.segment_planner.stage import SegmentPlanStage
from workers.stt.stage import STTStage
from workers.translation.stage import TranslateStage

#: Stage nào đến ở phase nào — theo docs §20.
_PLANNED_PHASE: dict[StageName, str] = {
    StageName.DIARIZE: "Phase 2",
    StageName.DURATION_FIT: "Phase 1",
    StageName.TTS: "Phase 1",
    StageName.FORCED_ALIGN: "Phase 1",
    StageName.TIMELINE_ASSEMBLY: "Phase 1",
    StageName.SUBTITLE: "Phase 1",
    StageName.ONSCREEN_TEXT: "Phase 6",
    StageName.LIPSYNC: "Phase 6",
    StageName.COMPOSE: "Phase 2",
    StageName.RENDER: "Phase 1",
    StageName.QC: "Phase 3",
    StageName.PUBLISH: "Phase 5",
}


def register_all() -> None:
    register(IngestStage())
    register(AnalyzeStage())
    register(SeparateStage())
    register(STTStage())
    register(SegmentPlanStage())
    register(TranslateStage())
    for name, phase in _PLANNED_PHASE.items():
        register(NotImplementedStage(name, phase))


register_all()

__all__ = ["register_all", "registry"]
