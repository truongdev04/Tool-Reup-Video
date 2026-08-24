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
    #: COMPOSE chỉ áp logo/watermark lên video gốc (§6.14 tối thiểu) — không
    #: phụ thuộc locale, không đọc timeline_assembly/subtitle. Cố ý KHÔNG liệt
    #: kê phụ thuộc nào ở đây: source_checksum đã tự nhiên nằm trong cache key
    #: của mọi stage (xem stage_input_hash), nên compose không cần đi qua
    #: INGEST để bắt thay đổi source. Nếu sau này compose thật sự bắt đầu đọc
    #: dữ liệu từ onscreen_text/lipsync (khi hai stage đó hết là stub), PHẢI
    #: thêm chúng vào đây — thiếu thì partial re-run sẽ im lặng bỏ qua thay
    #: đổi (§16).
    StageName.COMPOSE: (),
    #: RENDER liệt kê TRỰC TIẾP mọi thứ nó thật sự đọc — composed video (hoặc
    #: source nếu compose bị bỏ qua), voice track đã ghép, và file phụ đề.
    #: Không dựa vào COMPOSE để "mang hộ" phụ thuộc vào TIMELINE_ASSEMBLY/
    #: SUBTITLE — compose không còn phụ thuộc hai stage đó nữa (xem trên), nên
    #: làm vậy sẽ khiến sửa bản dịch xong mà render vẫn dùng cache cũ (§16).
    StageName.RENDER: (StageName.COMPOSE, StageName.TIMELINE_ASSEMBLY, StageName.SUBTITLE),
    StageName.QC: (StageName.RENDER,),
    StageName.PUBLISH: (StageName.QC,),
}


class CacheScope(StrEnum):
    """Phạm vi tái dùng kết quả của một stage (§16).

    SOURCE: kết quả không phụ thuộc locale đích (tách nhạc nền, STT, phân tích
    media) nên MỌI bản ngôn ngữ của cùng một video dùng chung. Đây là chỗ tiết
    kiệm lớn nhất: STT một video 60 phút cho 10 locale phải chạy 1 lần, không
    phải 10 lần.

    JOB: kết quả gắn với một job cụ thể (bản dịch, TTS, subtitle) — output_ref
    trỏ tới bản ghi của chính job đó nên không được dùng chéo.
    """

    SOURCE = "source"
    JOB = "job"


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
    PAD_SILENCE = "pad_silence"
    TEMPO_ADJUST = "tempo_adjust"
    VIDEO_STRETCH = "video_stretch"
    MANUAL_REVIEW = "manual_review"


class ArtifactKind(StrEnum):
    """Loại artifact trong storage — quyết định retention (docs §17.2)."""

    SOURCE = "source"
    ANALYSIS = "analysis"
    SEPARATED = "separated"
    #: Video đã áp logo/watermark — KHÔNG phụ thuộc locale (branding giống
    #: nhau cho mọi bản ngôn ngữ của cùng một video), nên nằm ở cấp project
    #: giống SEPARATED, không phải jobs/{job_id}/ (§6.14, §9).
    COMPOSED = "composed"
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
