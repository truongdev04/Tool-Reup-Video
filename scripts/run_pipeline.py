#!/usr/bin/env python
"""Harness chạy pipeline tuần tự trên 1 clip — Phase 0 (docs §20, §21).

Mục tiêu DoD: clip mẫu 10 giây chạy hết pipeline dưới 2 phút (docs §21).
Không dùng queue ở giai đoạn này — gọi thẳng từng Stage theo thứ tự docs §4.

    python scripts/run_pipeline.py                    # fixture 10s, 2 locale
    python scripts/run_pipeline.py --video path.mp4 --locales es-ES ja-JP
    python scripts/run_pipeline.py --rerun-from translate   # partial re-run §11.3

Logic tạo project/job dùng chung với dev server ở `services/pipeline_runner.py`.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

_API = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(_API))

from core.config import get_settings  # noqa: E402
from core.orchestrator import PipelineReport  # noqa: E402
from core.types import JobStatus  # noqa: E402
from services.pipeline_runner import run_for_video  # noqa: E402

GREEN, YELLOW, RED, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"


def _print_report(report: PipelineReport) -> None:
    print(f"\n  Job {report.job_id[:8]}  ·  locale {report.locale}")
    print(f"  {DIM}{'stage':<20}{'trạng thái':<14}{'thời gian':>10}   ghi chú{RESET}")
    for o in report.outcomes:
        colour = {
            JobStatus.SUCCEEDED: GREEN,
            JobStatus.NEEDS_REVIEW: YELLOW,
            JobStatus.FAILED: RED,
        }.get(o.status, "")
        timing = "cache" if o.cached else f"{o.duration_ms} ms"
        note = o.note or ""
        print(f"  {o.stage:<20}{colour}{o.status:<14}{RESET}{timing:>10}   {DIM}{note}{RESET}")
    print(f"  {DIM}{'─' * 62}{RESET}")
    print(f"  tổng {report.total_ms} ms · {report.cached_count} stage dùng cache")


def main() -> int:
    parser = argparse.ArgumentParser(description="Harness pipeline Phase 0")
    parser.add_argument("--video", type=Path, help="video nguồn (mặc định: fixture 10s)")
    parser.add_argument("--locales", nargs="+", default=["es-ES", "ja-JP"],
                        help="locale đích (mặc định 2 locale khác hệ chữ — docs §23)")
    parser.add_argument("--project", default="Demo Phase 0")
    parser.add_argument("--translation-provider", dest="translation_provider")
    parser.add_argument("--tts-provider", dest="tts_provider")
    parser.add_argument("--rerun-from", dest="rerun_from",
                        help="chạy lại từ stage này và mọi stage phụ thuộc (§11.3)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    settings = get_settings()
    if missing := settings.verify_ffmpeg():
        print(f"{RED}ffmpeg thiếu khả năng cần thiết:{RESET}")
        for m in missing:
            print(f"  - {m}")
        print(f"\n  Cài: {DIM}brew install ffmpeg-full{RESET}")
        return 1

    video = args.video
    if video is None:
        from tests.fixtures.make_fixture import make_sample
        video = make_sample()
        print(f"{DIM}dùng fixture: {video.name}{RESET}")

    wall_start = time.perf_counter()
    result = run_for_video(
        video, args.locales, project_name=args.project,
        rights_note="Fixture tự sinh bằng ffmpeg lavfi / say — dùng cho test nội bộ.",
        translation_provider=args.translation_provider,
        tts_provider=args.tts_provider,
        rerun_from=args.rerun_from,
    )
    wall = time.perf_counter() - wall_start

    for r in result.reports:
        _print_report(r)

    budget = 120.0  # DoD §21: dưới 2 phút
    status = f"{GREEN}ĐẠT{RESET}" if wall < budget else f"{RED}VƯỢT{RESET}"
    print(f"\n  Tổng thời gian thực: {wall:.2f}s / {budget:.0f}s  →  {status}  {DIM}(DoD §21){RESET}")
    return 0 if all(r.ok for r in result.reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
