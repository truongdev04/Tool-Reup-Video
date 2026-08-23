"""Đăng ký toàn bộ 18 stage vào registry.

Phase 0 implement thật 2 stage (ingest, analyze) để trục pipeline chạy thông
end-to-end. 16 stage còn lại là NotImplementedStage giữ đúng contract —
harness chạy hết pipeline mà không sập, và mỗi stub ghi rõ nó thuộc phase nào
theo lộ trình §20.
"""

from __future__ import annotations

from core.stage import NotImplementedStage, register, registry
from core.types import StageName
from workers.analyzer.stage import AnalyzeStage
from workers.ingest.stage import IngestStage

#: Stage nào đến ở phase nào — theo docs §20.
_PLANNED_PHASE: dict[StageName, str] = {
    StageName.SEPARATE: "Phase 1",
    StageName.STT: "Phase 1",
    StageName.DIARIZE: "Phase 2",
    StageName.SEGMENT_PLAN: "Phase 1",
    StageName.TRANSLATE: "Phase 1",
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
    for name, phase in _PLANNED_PHASE.items():
        register(NotImplementedStage(name, phase))


register_all()

__all__ = ["register_all", "registry"]
