"""Stage `render` — docs §6.15, §9.

Mux video (đã có logo nếu `compose` chạy trước, xem `_pick_video_source`) với
audio đã tái dựng (§9: TTS + background gốc, chuẩn hoá loudness) và burn phụ
đề. Encode bằng VideoToolbox (§13.1).

Filter graph dựng bằng FilterGraph builder, không nối chuỗi string (§6.15).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from core.hashing import file_checksum
from core.stage import NonRetryableError, Stage, StageContext, StageResult
from core.types import ArtifactKind, StageName
from db.models import OutputFile, SourceVideo
from services.audio_mix import loudnorm_two_pass, mix_voice_and_background
from services.ffmpeg import FilterGraph, probe, run_ffmpeg
from services.fonts import resolve as resolve_fonts
from services.presets import load_locale

#: Bitrate cố định cho MVP — chưa có render preset (§14) để chọn theo aspect
#: ratio/resolution. Ghi nhận như nợ kỹ thuật, hợp lý để làm ở Phase 2.
_VIDEO_BITRATE = "6000k"


def _escape_for_subtitles_filter(value: Path | str) -> str:
    """ffmpeg filter `subtitles=` coi `:` là ký tự phân cách tham số và `\\`,
    `'` có ý nghĩa escape riêng — phải thoát trước khi chèn vào filter graph.
    Dùng chung cho cả đường dẫn (`filename`, `fontsdir`) lẫn giá trị style
    (`force_style`)."""
    s = str(value)
    s = s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return s


def _subtitles_filter_expr(ctx: StageContext, srt_path: Path) -> str:
    """Dựng filter `subtitles` kèm font fallback theo `font_stack` của locale
    preset (§13.2, §14) — xem `services/fonts.py`. `font_stack` rỗng hoặc
    chưa bundle font nào cho locale này thì bỏ qua `fontsdir`/`force_style`,
    để libass tự chọn font như hành vi trước khi có tính năng này (không chặn
    render vì thiếu font bundle)."""
    preset = load_locale(ctx.locale)
    fonts = resolve_fonts(preset.font_stack, ctx.settings.fonts_dir)

    expr = f"subtitles='{_escape_for_subtitles_filter(srt_path)}'"
    if fonts.available:
        expr += f":fontsdir='{_escape_for_subtitles_filter(fonts.fonts_dir)}'"
    if fonts.primary_family:
        expr += f":force_style='{_escape_for_subtitles_filter(f'FontName={fonts.primary_family}')}'"
    return expr


class RenderStage(Stage):
    name = StageName.RENDER

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        source = ctx.session.scalars(
            select(SourceVideo).where(SourceVideo.checksum == ctx.source_checksum)
        ).first()
        if source is None:
            raise NonRetryableError("chưa chạy stage ingest")

        assembled = ctx.session.scalars(
            select(OutputFile).where(
                OutputFile.render_job_id == ctx.job_id,
                OutputFile.kind == ArtifactKind.ASSEMBLED,
            )
        ).first()
        if assembled is None:
            raise NonRetryableError("chưa có voice track — chạy stage timeline_assembly trước")

        background = ctx.storage.path_for(
            ArtifactKind.SEPARATED, project_id=ctx.project_id, filename="background.wav"
        )
        if not background.exists():
            raise NonRetryableError("chưa có background.wav — chạy stage separate trước")

        # Đường dẫn SRT: quy ước xác định (Storage.path_for) — cùng cách tts_chunk_path
        # được suy lại thay vì truyền qua output_ref giữa các stage (§11.1: stage
        # không gọi stage khác, chia sẻ qua DB/storage theo quy ước cố định).
        srt_path = ctx.storage.path_for(
            ArtifactKind.SUBTITLE, project_id=ctx.project_id, job_id=ctx.job_id,
            filename=f"{ctx.locale}.srt",
        )
        if not srt_path.exists():
            raise NonRetryableError("chưa có file phụ đề — chạy stage subtitle trước")

        video_path = self._pick_video_source(ctx, source)
        voice_path = ctx.storage.root / assembled.storage_path

        # Cùng thư mục với voice.wav (ASSEMBLED) — đây vẫn là audio trung gian
        # của quá trình tái dựng §9, không phải bản preview cho người xem duyệt.
        audio_dir = ctx.storage.path_for(
            ArtifactKind.ASSEMBLED, project_id=ctx.project_id, job_id=ctx.job_id
        )
        mixed_path = audio_dir / "mixed.wav"
        normalized_path = audio_dir / "normalized.wav"

        mix_voice_and_background(voice_path, background, mixed_path)
        loudnorm_two_pass(mixed_path, normalized_path)

        graph = FilterGraph()
        graph.add(["0:v"], _subtitles_filter_expr(ctx, srt_path), ["vout"])

        out_path = ctx.storage.path_for(
            ArtifactKind.FINAL, project_id=ctx.project_id, job_id=ctx.job_id,
            filename=f"{ctx.locale}.mp4",
        )
        run_ffmpeg([
            "-i", str(video_path), "-i", str(normalized_path),
            "-filter_complex", graph.build(),
            "-map", "[vout]", "-map", "1:a",
            "-c:v", "h264_videotoolbox", "-b:v", _VIDEO_BITRATE, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(out_path),
        ], timeout=1800)

        info = probe(out_path)
        self._save_output_file(ctx, out_path, info.duration_ms)

        return StageResult(
            output_ref={
                "path": ctx.storage.relative(out_path),
                "duration_ms": info.duration_ms,
                "resolution": f"{info.width}x{info.height}",
            },
        )

    def _pick_video_source(self, ctx: StageContext, source: SourceVideo) -> Path:
        """Ưu tiên video đã composite (logo/watermark) nếu `compose` đã chạy
        thật; fallback về video gốc nếu compose còn là stub hoặc brand không
        có logo (§11.1: quy ước đường dẫn cố định, không qua output_ref)."""
        composed = ctx.storage.path_for(
            ArtifactKind.COMPOSED, project_id=ctx.project_id, filename="composed.mp4"
        )
        return composed if composed.exists() else ctx.storage.root / source.storage_path

    def _save_output_file(self, ctx: StageContext, path: Path, duration_ms: int) -> None:
        """Idempotent (§11.1): thay bản ghi FINAL cũ của job này."""
        existing = ctx.session.scalars(
            select(OutputFile).where(
                OutputFile.render_job_id == ctx.job_id,
                OutputFile.kind == ArtifactKind.FINAL,
            )
        ).all()
        for row in existing:
            ctx.session.delete(row)

        ctx.session.add(
            OutputFile(
                render_job_id=ctx.job_id,
                kind=ArtifactKind.FINAL,
                storage_path=ctx.storage.relative(path),
                checksum=file_checksum(path),
                size_bytes=path.stat().st_size,
                media_info={"duration_ms": duration_ms},
                # Chưa có stage qc thật — để None thay vì tự nhận PASS (§15:
                # "chỉ publish khi QC = PASS"; None rõ ràng hơn là giả PASS).
                qc_verdict=None,
                ai_disclosure=True,  # §18.2 — nghĩa vụ công bố nội dung tổng hợp
            )
        )
        ctx.session.flush()
