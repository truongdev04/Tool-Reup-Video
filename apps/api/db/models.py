"""Toàn bộ bảng của hệ thống — docs §10.

Nhóm theo đúng tài liệu:
  §10.1  bảng giữ từ v2
  §10.2  segment 4 tầng (thay cho bảng `segments` gộp của v2)
  §10.3  bảng mới của v3
  §10.4  lineage
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.types import (
    ApprovalGate,
    ArtifactKind,
    FitStrategy,
    JobStatus,
    QCVerdict,
    StageName,
)
from db.base import Base, PKMixin, TimestampMixin

# ---------------------------------------------------------------------------
# §10.1 — Project, brand, preset, voice
# ---------------------------------------------------------------------------


class Project(Base, PKMixin, TimestampMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    brand_profile_id: Mapped[str | None] = mapped_column(ForeignKey("brand_profiles.id"))
    #: Preset mặc định, có thể override ở cấp job. Không hard-code (§2.2).
    default_presets: Mapped[dict] = mapped_column(JSON, default=dict)
    target_locales: Mapped[list] = mapped_column(JSON, default=list)

    source_videos: Mapped[list[SourceVideo]] = relationship(back_populates="project")


class BrandProfile(Base, PKMixin, TimestampMixin):
    __tablename__ = "brand_profiles"

    name: Mapped[str] = mapped_column(String(200))
    logo_path: Mapped[str | None] = mapped_column(String(500))
    colors: Mapped[dict] = mapped_column(JSON, default=dict)
    font_family: Mapped[str | None] = mapped_column(String(200))
    intro_path: Mapped[str | None] = mapped_column(String(500))
    outro_path: Mapped[str | None] = mapped_column(String(500))
    cta_config: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Vị trí đặt logo: top_left/top_right/bottom_left/bottom_right/center (§6.14).
    logo_position: Mapped[str] = mapped_column(String(20), default="bottom_right")
    logo_opacity: Mapped[float] = mapped_column(Float, default=0.85)
    #: Bề rộng logo tính theo % bề rộng video, cao tự co giãn đúng tỉ lệ.
    logo_scale_pct: Mapped[float] = mapped_column(Float, default=12.0)
    #: True khi đây là brand tự sinh cho demo (chưa có asset thật của người
    #: dùng) — để không lẫn với brand profile thật khi liệt kê/dọn dẹp.
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False)


class SubtitlePreset(Base, PKMixin, TimestampMixin):
    __tablename__ = "subtitle_presets"

    name: Mapped[str] = mapped_column(String(200))
    font_family: Mapped[str] = mapped_column(String(200), default="Noto Sans")
    #: Chuỗi font dự phòng. Thiếu glyph là ra ô vuông — bug hay gặp với
    #: AR/HI/TH mà ít ai test trước (§13.2).
    font_fallback_chain: Mapped[list] = mapped_column(JSON, default=list)
    font_size: Mapped[int] = mapped_column(Integer, default=48)
    position: Mapped[str] = mapped_column(String(50), default="bottom")
    safe_area_pct: Mapped[float] = mapped_column(Float, default=0.9)
    animation: Mapped[str | None] = mapped_column(String(50))
    keyword_highlight: Mapped[bool] = mapped_column(Boolean, default=False)
    style: Mapped[dict] = mapped_column(JSON, default=dict)


class Voice(Base, PKMixin, TimestampMixin):
    """Voice profile của provider TTS (§6.9)."""

    __tablename__ = "voices"

    name: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(100))
    provider_voice_id: Mapped[str] = mapped_column(String(200))
    #: Nằm trong cache key (§16) — provider đổi model mà key không đổi là hỏng.
    provider_version: Mapped[str | None] = mapped_column(String(100))
    locale: Mapped[str] = mapped_column(String(20))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    is_cloned: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Bắt buộc khi is_cloned=True — chặn ở tầng TTS (§18.2).
    consent_id: Mapped[str | None] = mapped_column(ForeignKey("voice_consents.id"))

    consent: Mapped[VoiceConsent | None] = relationship(back_populates="voices")


# ---------------------------------------------------------------------------
# §10.1 — Source
# ---------------------------------------------------------------------------


class SourceVideo(Base, PKMixin, TimestampMixin):
    __tablename__ = "source_videos"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    filename: Mapped[str] = mapped_column(String(500))
    storage_path: Mapped[str] = mapped_column(String(1000))
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    #: Trường BẮT BUỘC, không để trống — quyền sử dụng nguồn (§18.2).
    rights_note: Mapped[str] = mapped_column(Text)
    #: Kết quả Analyzer (§6.2): duration, fps, resolution, codec, scenes...
    media_info: Mapped[dict] = mapped_column(JSON, default=dict)
    source_locale: Mapped[str | None] = mapped_column(String(20))

    project: Mapped[Project] = relationship(back_populates="source_videos")

    __table_args__ = (UniqueConstraint("project_id", "checksum", name="uq_source_per_project"),)


# ---------------------------------------------------------------------------
# §10.1 — Transcript & speaker
# ---------------------------------------------------------------------------


class Transcript(Base, PKMixin, TimestampMixin):
    __tablename__ = "transcripts"

    source_video_id: Mapped[str] = mapped_column(ForeignKey("source_videos.id"))
    locale: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(100))
    provider_version: Mapped[str | None] = mapped_column(String(100))
    #: Word-level timestamp là BẮT BUỘC, không phải tuỳ chọn — Duration Fitting
    #: (§7) và Subtitle (§8) đều phụ thuộc vào nó.
    has_word_timestamps: Mapped[bool] = mapped_column(Boolean, default=False)
    full_text: Mapped[str] = mapped_column(Text, default="")

    segments: Mapped[list[STTSegment]] = relationship(back_populates="transcript")


class Speaker(Base, PKMixin, TimestampMixin):
    __tablename__ = "speakers"

    source_video_id: Mapped[str] = mapped_column(ForeignKey("source_videos.id"))
    label: Mapped[str] = mapped_column(String(50))
    #: Map speaker -> voice profile theo từng locale (§6.5).
    voice_mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    total_speech_ms: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# §10.2 — Segment 4 tầng (thay bảng `segments` gộp của v2)
# ---------------------------------------------------------------------------


class STTSegment(Base, PKMixin, TimestampMixin):
    """Tầng 1 — đoạn thô từ STT, cắt theo khoảng lặng. Vụn, hay cắt giữa câu."""

    __tablename__ = "stt_segments"

    transcript_id: Mapped[str] = mapped_column(ForeignKey("transcripts.id"))
    speaker_id: Mapped[str | None] = mapped_column(ForeignKey("speakers.id"))
    idx: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    #: [{"word": str, "start_ms": int, "end_ms": int}, ...]
    words: Mapped[list] = mapped_column(JSON, default=list)

    transcript: Mapped[Transcript] = relationship(back_populates="segments")

    __table_args__ = (Index("ix_stt_seg_transcript_idx", "transcript_id", "idx"),)


class TranslationUnit(Base, PKMixin, TimestampMixin):
    """Tầng 2 — đơn vị dịch trọn nghĩa, gộp từ nhiều STT segment.

    Thiếu ngữ cảnh là dịch sai, nên đây phải là câu/ý hoàn chỉnh chứ không phải
    đoạn cắt theo khoảng lặng (§5).
    """

    __tablename__ = "translation_units"

    render_job_id: Mapped[str] = mapped_column(ForeignKey("render_jobs.id"))
    idx: Mapped[int] = mapped_column(Integer)
    speaker_id: Mapped[str | None] = mapped_column(ForeignKey("speakers.id"))
    source_text: Mapped[str] = mapped_column(Text)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    #: Budget ký tự truyền vào prompt LLM — chiến lược fit #1 (§7.2).
    char_budget: Mapped[int | None] = mapped_column(Integer)
    #: Hook/CTA cần dịch thoáng (transcreation), không dịch sát (§6.7).
    needs_transcreation: Mapped[bool] = mapped_column(Boolean, default=False)
    has_face: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Dirty flag cho partial re-run (§11.3).
    is_dirty: Mapped[bool] = mapped_column(Boolean, default=False)

    translations: Mapped[list[Translation]] = relationship(back_populates="unit")
    timing: Mapped[SegmentTiming | None] = relationship(back_populates="unit", uselist=False)

    __table_args__ = (Index("ix_tu_job_idx", "render_job_id", "idx"),)

    @property
    def duration_ms(self) -> int:
        """Khung thời gian gốc mà bản dịch phải đọc vừa (§7)."""
        return self.end_ms - self.start_ms


class TTSChunk(Base, PKMixin, TimestampMixin):
    """Tầng 3 — chunk TTS, cắt theo ngữ điệu tự nhiên.

    Mỗi chunk là MỘT FILE AUDIO RIÊNG có địa chỉ. Đây là điều kiện bắt buộc để
    partial re-run hoạt động (§6.9, §11.3): sửa 1 câu chỉ TTS lại chunk đó rồi
    remux, không encode lại cả video.
    """

    __tablename__ = "tts_chunks"

    translation_unit_id: Mapped[str] = mapped_column(ForeignKey("translation_units.id"))
    idx: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    voice_id: Mapped[str | None] = mapped_column(ForeignKey("voices.id"))
    audio_path: Mapped[str | None] = mapped_column(String(1000))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    #: Hệ số atempo đã áp — phải nằm trong [tempo_min, tempo_max] (§7.2).
    tempo_ratio: Mapped[float] = mapped_column(Float, default=1.0)
    cache_key: Mapped[str | None] = mapped_column(String(64), index=True)
    #: Mốc thời gian (ms, TƯƠNG ĐỐI so với đầu file audio của chính chunk này)
    #: cho từng ký tự của `text` — độ dài luôn là len(text)+1 (điểm biên).
    #: Ghi bởi stage forced_align (§8), đọc bởi stage subtitle để cắt cue.
    char_boundaries_ms: Mapped[list] = mapped_column(JSON, default=list)

    __table_args__ = (Index("ix_chunk_unit_idx", "translation_unit_id", "idx"),)


class SubtitleCue(Base, PKMixin, TimestampMixin):
    """Tầng 4 — cue hiển thị, cắt theo giới hạn đọc.

    Timestamp PHẢI đến từ forced alignment trên audio mới (§8.3), không phải
    từ transcript nguồn.
    """

    __tablename__ = "subtitle_cues"

    render_job_id: Mapped[str] = mapped_column(ForeignKey("render_jobs.id"))
    idx: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    lines: Mapped[list] = mapped_column(JSON, default=list)
    cps: Mapped[float | None] = mapped_column(Float)
    #: Cờ kiểm chứng nguyên tắc §2.9 — QC đọc trường này thay vì kiểm tra bằng mắt.
    from_forced_alignment: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (Index("ix_cue_job_idx", "render_job_id", "idx"),)


class SegmentLink(Base, PKMixin):
    """Mapping N:M giữa 4 tầng segment (§5) — không phải khoá ngoại 1:1."""

    __tablename__ = "segment_links"

    from_kind: Mapped[str] = mapped_column(String(50))
    from_id: Mapped[str] = mapped_column(String(36))
    to_kind: Mapped[str] = mapped_column(String(50))
    to_id: Mapped[str] = mapped_column(String(36))

    __table_args__ = (
        UniqueConstraint("from_kind", "from_id", "to_kind", "to_id", name="uq_segment_link"),
        Index("ix_link_from", "from_kind", "from_id"),
        Index("ix_link_to", "to_kind", "to_id"),
    )


# ---------------------------------------------------------------------------
# §10.1 — Translation (có version + approved_by, §10.4)
# ---------------------------------------------------------------------------


class Translation(Base, PKMixin, TimestampMixin):
    __tablename__ = "translations"

    translation_unit_id: Mapped[str] = mapped_column(ForeignKey("translation_units.id"))
    locale: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    #: Version + approved_by để lineage truy vết được (§10.4).
    version: Mapped[int] = mapped_column(Integer, default=1)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str | None] = mapped_column(String(100))
    provider_version: Mapped[str | None] = mapped_column(String(100))
    glossary_applied: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    unit: Mapped[TranslationUnit] = relationship(back_populates="translations")

    __table_args__ = (
        UniqueConstraint("translation_unit_id", "locale", "version", name="uq_translation_version"),
    )


# ---------------------------------------------------------------------------
# §10.3 — Bảng mới của v3
# ---------------------------------------------------------------------------


class SegmentTiming(Base, PKMixin, TimestampMixin):
    """Cốt lõi của Duration Fitting (§7.4) và là dữ liệu để QC bắt lỗi trôi tiếng.

    `cumulative_drift_ms` là chỉ số QC quan trọng nhất của hệ thống — nó bắt
    được lỗi mà mọi kiểm tra khác bỏ sót (§15).
    """

    __tablename__ = "segment_timing"

    translation_unit_id: Mapped[str] = mapped_column(
        ForeignKey("translation_units.id"), unique=True
    )
    target_duration_ms: Mapped[int] = mapped_column(Integer)
    actual_duration_ms: Mapped[int | None] = mapped_column(Integer)
    fit_strategy: Mapped[FitStrategy] = mapped_column(String(50), default=FitStrategy.NONE)
    tempo_ratio: Mapped[float] = mapped_column(Float, default=1.0)
    borrowed_silence_ms: Mapped[int] = mapped_column(Integer, default=0)
    drift_ms: Mapped[int] = mapped_column(Integer, default=0)
    cumulative_drift_ms: Mapped[int] = mapped_column(Integer, default=0)
    needs_manual_review: Mapped[bool] = mapped_column(Boolean, default=False)

    unit: Mapped[TranslationUnit] = relationship(back_populates="timing")


class ApprovalGateRecord(Base, PKMixin, TimestampMixin):
    """Biến "manual review" thành quy trình có vết (§11.2)."""

    __tablename__ = "approval_gates"

    render_job_id: Mapped[str] = mapped_column(ForeignKey("render_jobs.id"))
    gate: Mapped[ApprovalGate] = mapped_column(String(50))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("render_job_id", "gate", name="uq_gate_per_job"),)


class VoiceConsent(Base, PKMixin, TimestampMixin):
    """Chuyển ràng buộc pháp lý từ câu chữ thành dữ liệu kiểm tra được (§18.2)."""

    __tablename__ = "voice_consents"

    subject_name: Mapped[str] = mapped_column(String(200))
    scope: Mapped[str] = mapped_column(Text)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_path: Mapped[str | None] = mapped_column(String(1000))
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    voices: Mapped[list[Voice]] = relationship(back_populates="consent")

    def is_valid_at(self, when: datetime) -> bool:
        if self.is_revoked or self.granted_at > when:
            return False
        return self.expires_at is None or self.expires_at > when


class OnscreenText(Base, PKMixin, TimestampMixin):
    """Nối Analyzer với QC thay vì để kết quả phân tích trôi đi (§6.12).

    MVP: chỉ OCR + gắn cờ + CHẶN QC, đẩy manual review. Không tự động che/vẽ lại.
    """

    __tablename__ = "onscreen_text"

    source_video_id: Mapped[str] = mapped_column(ForeignKey("source_videos.id"))
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    #: Bounding box [x, y, w, h] — không chỉ là cờ boolean (§6.2).
    bbox: Mapped[list] = mapped_column(JSON, default=list)
    source_text: Mapped[str] = mapped_column(Text)
    translated_text: Mapped[str | None] = mapped_column(Text)
    #: pending -> QC FAIL (§15). Chỉ resolved/ignored mới cho qua.
    status: Mapped[str] = mapped_column(String(50), default="pending")
    ocr_confidence: Mapped[float | None] = mapped_column(Float)


class StageRun(Base, PKMixin, TimestampMixin):
    """Nền tảng của cache, partial re-run và lineage (§10.3, §11, §16)."""

    __tablename__ = "stage_runs"

    render_job_id: Mapped[str] = mapped_column(ForeignKey("render_jobs.id"))
    stage: Mapped[StageName] = mapped_column(String(50))
    status: Mapped[JobStatus] = mapped_column(String(50), default=JobStatus.PENDING)
    #: Cache key (§16). Cùng hash = tái dùng kết quả, không chạy lại.
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    output_ref: Mapped[dict] = mapped_column(JSON, default=dict)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    was_cached: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_stage_run_job_stage", "render_job_id", "stage"),)


# ---------------------------------------------------------------------------
# §10.1 — Job, output, publishing, ops
# ---------------------------------------------------------------------------


class RenderJob(Base, PKMixin, TimestampMixin):
    """Một job = một tổ hợp `video × locale × pipeline` (§16)."""

    __tablename__ = "render_jobs"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    source_video_id: Mapped[str] = mapped_column(ForeignKey("source_videos.id"))
    locale: Mapped[str] = mapped_column(String(20))
    status: Mapped[JobStatus] = mapped_column(String(50), default=JobStatus.PENDING)
    current_stage: Mapped[StageName | None] = mapped_column(String(50))
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    #: Snapshot preset lúc tạo job — để chạy lại sau này ra cùng kết quả.
    presets: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("source_video_id", "locale", name="uq_job_per_video_locale"),
    )


class OutputFile(Base, PKMixin, TimestampMixin):
    __tablename__ = "output_files"

    render_job_id: Mapped[str] = mapped_column(ForeignKey("render_jobs.id"))
    kind: Mapped[ArtifactKind] = mapped_column(String(50))
    storage_path: Mapped[str] = mapped_column(String(1000))
    checksum: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    media_info: Mapped[dict] = mapped_column(JSON, default=dict)
    #: LINEAGE (§10.4): trỏ về ĐÚNG VERSION của từng input đã tạo ra file này,
    #: không chỉ job_id. Nhờ đó trả lời được "video này dùng bản dịch nào,
    #: giọng nào, preset nào, ai duyệt".
    lineage: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Nghĩa vụ công bố nội dung AI (§18.2).
    ai_disclosure: Mapped[bool] = mapped_column(Boolean, default=True)
    qc_verdict: Mapped[QCVerdict | None] = mapped_column(String(20))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublishingJob(Base, PKMixin, TimestampMixin):
    __tablename__ = "publishing_jobs"

    output_file_id: Mapped[str] = mapped_column(ForeignKey("output_files.id"))
    platform: Mapped[str] = mapped_column(String(50))
    account_ref: Mapped[str] = mapped_column(String(200))
    status: Mapped[JobStatus] = mapped_column(String(50), default=JobStatus.PENDING)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platform_video_id: Mapped[str | None] = mapped_column(String(200))
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Quota nền tảng là nút thắt thật của batch (§18.3) — ghi lại để tính lịch.
    quota_units_used: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)


class ApiUsage(Base, PKMixin, TimestampMixin):
    """Đo usage thực tế thay vì dùng con số chi phí cố định (§17)."""

    __tablename__ = "api_usage"

    render_job_id: Mapped[str | None] = mapped_column(ForeignKey("render_jobs.id"))
    stage: Mapped[StageName] = mapped_column(String(50))
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    characters: Mapped[int] = mapped_column(Integer, default=0)
    audio_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    gpu_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    storage_gb_hours: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    #: True = ước tính dry-run trước khi chạy (§17.1), False = usage thực.
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=False)


class ErrorLog(Base, PKMixin, TimestampMixin):
    __tablename__ = "error_logs"

    render_job_id: Mapped[str | None] = mapped_column(ForeignKey("render_jobs.id"))
    stage: Mapped[StageName | None] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    #: Log KHÔNG được chứa secret/API key (§18.1) — sanitize trước khi ghi.
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    is_retryable: Mapped[bool] = mapped_column(Boolean, default=True)
