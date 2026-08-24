"""Stage `qc` — docs §15.

Kiểm tra tự động trước khi cho phép export/publish. Đây là stage cuối cùng
trước publish nên đọc dữ liệu từ TẤT CẢ các stage trước — nhưng vẫn theo đúng
nguyên tắc "stage không gọi stage khác" (§11.1): mọi thứ lấy từ DB/storage
theo quy ước cố định, không qua output_ref.

Kết quả ghi vào `OutputFile.qc_verdict` — output §9 giữ nguyên, chỉ verdict
được cập nhật (không tạo bản ghi FINAL mới, QC không sinh output).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.hashing import file_checksum
from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import ArtifactKind, QCVerdict, StageName
from db.models import (
    OutputFile,
    SegmentTiming,
    SourceVideo,
    SubtitleCue,
    Translation,
    TranslationUnit,
)
from services.audio_mix import TARGET_I, measure_loudnorm
from services.ffmpeg import probe
from services.fonts import resolve as resolve_fonts
from services.presets import load_locale
from services.qc_media import detect_black_segments, mean_volume_db, missing_glyphs
from workers.qc.checks import (
    check_background_retained,
    check_cue_cps,
    check_cue_overlap,
    check_cumulative_drift,
    check_font_coverage,
    check_forced_alignment_used,
    check_loudness,
    check_no_clipping,
    check_output_playable,
    check_tempo_bounds,
    check_translation_completeness,
    overall_verdict,
)


class QCStage(Stage):
    name = StageName.QC

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        source = ctx.session.scalars(
            select(SourceVideo).where(SourceVideo.checksum == ctx.source_checksum)
        ).first()
        if source is None:
            raise NonRetryableError("chưa chạy stage ingest")

        final = ctx.session.scalars(
            select(OutputFile).where(
                OutputFile.render_job_id == ctx.job_id, OutputFile.kind == ArtifactKind.FINAL,
            )
        ).first()
        if final is None:
            raise NonRetryableError("chưa có output cuối — chạy stage render trước")

        units = ctx.session.scalars(
            select(TranslationUnit)
            .where(TranslationUnit.render_job_id == ctx.job_id)
            .order_by(TranslationUnit.idx)
        ).all()
        timings = ctx.session.scalars(
            select(SegmentTiming).join(TranslationUnit).where(
                TranslationUnit.render_job_id == ctx.job_id
            )
        ).all()
        cues = ctx.session.scalars(
            select(SubtitleCue).where(SubtitleCue.render_job_id == ctx.job_id)
        ).all()
        translated_count = ctx.session.scalars(
            select(Translation.translation_unit_id).where(
                Translation.translation_unit_id.in_([u.id for u in units]),
                Translation.locale == ctx.locale,
                Translation.is_active.is_(True),
            )
        ).all()

        final_path = ctx.storage.root / final.storage_path
        info = probe(final_path)
        expected_duration = (source.media_info or {}).get("duration_ms", info.duration_ms)
        preset = load_locale(ctx.locale)
        settings = ctx.settings

        findings = [
            check_cumulative_drift(
                timings[-1].cumulative_drift_ms if timings else 0,
                max_drift_ms=settings.max_cumulative_drift_ms,
            ),
            check_forced_alignment_used(
                len(cues), all(c.from_forced_alignment for c in cues) if cues else False
            ),
            check_cue_overlap([(c.start_ms, c.end_ms) for c in cues]),
            check_cue_cps([c.cps for c in cues if c.cps], cps_max=preset.cps_max),
            check_tempo_bounds(
                [t.tempo_ratio for t in timings],
                tempo_min=settings.tempo_min, tempo_max=settings.tempo_max,
            ),
            check_translation_completeness(len(units), len(translated_count)),
            check_font_coverage(self._missing_glyphs(ctx, cues, preset.font_stack)),
            check_output_playable(
                duration_ms=info.duration_ms, expected_duration_ms=expected_duration,
                has_audio=info.has_audio, has_video=info.width is not None,
                checksum_matches=file_checksum(final_path) == final.checksum,
            ),
        ]

        try:
            measured = measure_loudnorm(final_path)
            findings.append(check_loudness(float(measured["input_i"]), target_lufs=TARGET_I))
            findings.append(check_no_clipping(float(measured["input_tp"])))
        except Exception as exc:  # noqa: BLE001 — đo hỏng không được chặn cả job, chỉ FAIL check này
            from workers.qc.checks import QCFinding

            findings.append(
                QCFinding(
                    check="loudness", verdict=QCVerdict.FAIL,
                    message=f"không đo được loudness: {exc}",
                )
            )

        gap = self._find_silence_gap(units)
        if gap is not None:
            gap_db = mean_volume_db(final_path, start_ms=gap[0], end_ms=gap[1])
            findings.append(check_background_retained(gap_db))

        black = detect_black_segments(final_path, min_duration_s=1.0)
        if black:
            from workers.qc.checks import QCFinding

            findings.append(
                QCFinding(
                    check="black_frames", verdict=QCVerdict.FAIL,
                    message=f"{len(black)} đoạn gần như đen hoàn toàn: {black[:3]}",
                )
            )

        verdict = overall_verdict(findings)
        final.qc_verdict = verdict
        ctx.session.flush()

        fails = [f for f in findings if f.verdict == QCVerdict.FAIL]
        warns = [f for f in findings if f.verdict == QCVerdict.WARN]

        return StageResult(
            output_ref={
                "verdict": str(verdict),
                "findings": [
                    {"check": f.check, "verdict": str(f.verdict), "message": f.message}
                    for f in findings
                ],
            },
            needs_review=verdict != QCVerdict.PASS,
            note=(
                f"{len(fails)} FAIL, {len(warns)} WARN: "
                + "; ".join(f.message for f in fails + warns)
                if fails or warns
                else None
            ),
        )

    def _find_silence_gap(self, units: list[TranslationUnit]) -> tuple[int, int] | None:
        """Khoảng lặng lớn nhất giữa hai unit liên tiếp — nơi kiểm tra nhạc
        nền còn nguyên (§9) mà không bị giọng đọc che mất."""
        best: tuple[int, int] | None = None
        for a, b in zip(units, units[1:]):
            gap = (a.end_ms, b.start_ms)
            if gap[1] - gap[0] < 300:
                continue
            if best is None or (gap[1] - gap[0]) > (best[1] - best[0]):
                best = gap
        return best

    def _missing_glyphs(
        self, ctx: StageContext, cues: list[SubtitleCue], font_stack: tuple[str, ...],
    ) -> list[str]:
        """Đo glyph coverage thật trên đúng font sẽ dùng để burn hardsub
        (§13.2, §14) — cùng `services/fonts.py` mà `render` dùng, để QC không
        kiểm tra một bộ font khác với bộ font thật sự lên hình."""
        text = "".join("".join(cue.lines) for cue in cues)
        if not text:
            return []
        fonts = resolve_fonts(font_stack, ctx.settings.fonts_dir)
        return sorted(missing_glyphs(text, list(fonts.available.values())))
