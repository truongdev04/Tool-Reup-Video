"""Enum và kiểu dùng chung toàn pipeline.

Tập trung ở một chỗ để không hard-code chuỗi rải rác trong source (kế hoạch §2.2).
"""

from __future__ import annotations

from enum import StrEnum


class StageName(StrEnum):
    """17 stage của pipeline — khớp đúng thứ tự bảng ở docs §4.

    `INGEST` tương ứng bước "import" trong kế hoạch; đổi tên vì `import` là
    từ khoá Python (xem README).
    """

    INGEST = "ingest"
    ANALYZE = "analyze"
    SEPARATE = "separate"
    STT = "stt"
    DIARIZE = "diarize"
    SEGMENT_PLAN = "segment_plan"
    TRANSLATE = "translate"
    DURATION_FIT = "duration_fit"
    TTS = "tts"
    FORCED_ALIGN = "forced_align"
    TIMELINE_ASSEMBLY = "timeline_assembly"
    SUBTITLE = "subtitle"
    ONSCREEN_TEXT = "onscreen_text"
    LIPSYNC = "lipsync"
    COMPOSE = "compose"
    RENDER = "render"
    QC = "qc"
    PUBLISH = "publish"


#: Thứ tự thực thi mặc định của harness tuần tự (docs §4).
PIPELINE_ORDER: tuple[StageName, ...] = (
    StageName.INGEST,
    StageName.ANALYZE,
    StageName.SEPARATE,
    StageName.STT,
    StageName.DIARIZE,
    StageName.SEGMENT_PLAN,
    StageName.TRANSLATE,
    StageName.DURATION_FIT,
    StageName.TTS,
    StageName.FORCED_ALIGN,
    StageName.TIMELINE_ASSEMBLY,
    StageName.SUBTITLE,
    StageName.ONSCREEN_TEXT,
    StageName.LIPSYNC,
    StageName.COMPOSE,
    StageName.RENDER,
    StageName.QC,
    StageName.PUBLISH,
)

#: Stage nào phụ thuộc stage nào — dùng để lan truyền dirty-flag khi partial
#: re-run (docs §11.3, §16). Key phụ thuộc vào các stage trong value.
STAGE_DEPENDENCIES: dict[StageName, tuple[StageName, ...]] = {
    StageName.INGEST: (),
    StageName.ANALYZE: (StageName.INGEST,),
    StageName.SEPARATE: (StageName.INGEST,),
    StageName.STT: (StageName.SEPARATE,),
    StageName.DIARIZE: (StageName.SEPARATE, StageName.STT),
    StageName.SEGMENT_PLAN: (StageName.STT, StageName.DIARIZE),
    StageName.TRANSLATE: (StageName.SEGMENT_PLAN,),
    StageName.DURATION_FIT: (StageName.TRANSLATE,),
    StageName.TTS: (StageName.DURATION_FIT,),
    StageName.FORCED_ALIGN: (StageName.TTS,),
    StageName.TIMELINE_ASSEMBLY: (StageName.TTS, StageName.FORCED_ALIGN),
    StageName.SUBTITLE: (StageName.FORCED_ALIGN, StageName.TIMELINE_ASSEMBLY),
    StageName.ONSCREEN_TEXT: (StageName.ANALYZE, StageName.TRANSLATE),
    StageName.LIPSYNC: (StageName.TIMELINE_ASSEMBLY,),
    StageName.COMPOSE: (
        StageName.TIMELINE_ASSEMBLY,
        StageName.SUBTITLE,
        StageName.ONSCREEN_TEXT,
        StageName.LIPSYNC,
    ),
    StageName.RENDER: (StageName.COMPOSE,),
    StageName.QC: (StageName.RENDER,),
    StageName.PUBLISH: (StageName.QC,),
}


class JobStatus(StrEnum):
    """Trạng thái job/stage — docs §16."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_REVIEW = "needs_review"


class FitStrategy(StrEnum):
    """Chiến lược ép thời lượng — docs §7.2, áp theo đúng thứ tự này."""

    NONE = "none"
    CONSTRAINED_TRANSLATION = "constrained_translation"
    BORROW_SILENCE = "borrow_silence"
    TEMPO_ADJUST = "tempo_adjust"
    VIDEO_STRETCH = "video_stretch"
    MANUAL_REVIEW = "manual_review"


class ArtifactKind(StrEnum):
    """Loại artifact trong storage — quyết định retention (docs §17.2)."""

    SOURCE = "source"
    ANALYSIS = "analysis"
    SEPARATED = "separated"
    TRANSCRIPT = "transcript"
    TRANSLATION = "translation"
    TTS = "tts"
    ASSEMBLED = "assembled"
    SUBTITLE = "subtitle"
    PREVIEW = "preview"
    FINAL = "final"


class ApprovalGate(StrEnum):
    """Bốn cổng duyệt — docs §11.2."""

    TRANSCRIPT = "transcript"
    TRANSLATION = "translation"
    AUDIO = "audio"
    FINAL = "final"


class QCVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
