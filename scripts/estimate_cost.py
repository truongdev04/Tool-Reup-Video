#!/usr/bin/env python
"""CLI ước tính chi phí trước khi batch chạy (§17.1).

`services/cost_estimate.py::estimate_batch()` KHÔNG gọi mạng, KHÔNG tốn
tiền — chỉ đọc DB + config để ước TỔNG TIỀN DỰ KIẾN trước khi thật sự chạy
`scripts/run_pipeline.py` cho một loạt video × locale. Xem
`.claude/rules/tech-debt.md` mục §17.1 và `apps/api/services/cost_estimate.py`
cho nguyên tắc ưu tiên số liệu thật.

    # Ước tính dịch + TTS cho MỌI video của project, 2 locale
    python scripts/estimate_cost.py --project "Demo Phase 0" --locales es-ES,ja-JP

    # Chỉ định provider (mặc định mock/macos_say — free, luôn is_configured)
    python scripts/estimate_cost.py --project "Demo Phase 0" --locales es-ES \
        --translation-provider openai --tts-provider elevenlabs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_API = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(_API))

from sqlalchemy import select  # noqa: E402

from db.base import create_all, session_scope  # noqa: E402
from db.models import Project, SourceVideo  # noqa: E402
from services.cost_estimate import estimate_batch  # noqa: E402

GREEN, YELLOW, DIM, RESET, BOLD = "\033[32m", "\033[33m", "\033[2m", "\033[0m", "\033[1m"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True, help="tên project")
    parser.add_argument("--locales", required=True, help="danh sách locale, phân tách bởi dấu phẩy")
    parser.add_argument("--translation-provider", default="mock")
    parser.add_argument("--tts-provider", default="macos_say")
    args = parser.parse_args()

    create_all()
    locales = [l.strip() for l in args.locales.split(",") if l.strip()]
    if not locales:
        print(f"{YELLOW}cần ít nhất 1 locale trong --locales{RESET}")
        return 1

    with session_scope() as session:
        project = session.query(Project).filter_by(name=args.project).one_or_none()
        if project is None:
            print(f"{YELLOW}không có project `{args.project}`{RESET}")
            return 1
        videos = session.scalars(
            select(SourceVideo).where(SourceVideo.project_id == project.id)
        ).all()
        if not videos:
            print(f"{YELLOW}project `{args.project}` chưa có video nguồn nào{RESET}")
            return 1

        result = estimate_batch(
            session, source_videos=list(videos), target_locales=locales,
            translation_provider_id=args.translation_provider,
            tts_provider_id=args.tts_provider,
        )

        print(f"{BOLD}Ước tính chi phí — project `{args.project}`{RESET}")
        print(f"  provider dịch: {result.translation_provider} · provider TTS: {result.tts_provider}")
        print(f"  {len(videos)} video × {len(locales)} locale = {len(result.items)} tổ hợp\n")

        header = f"{'video':<24}{'locale':<8}{'ký tự nguồn':<14}{'ký tự dịch':<12}{'audio(s)':<10}{'$ dịch':<10}{'$ tts':<10}"
        print(header)
        print("-" * len(header))
        for item in result.items:
            marker = f" {DIM}(đã chạy — có thể cache-hit){RESET}" if item.already_done else ""
            measured = "" if item.source_chars_measured else "~"
            print(
                f"{item.filename:<24}{item.locale:<8}{measured + str(item.source_chars):<14}"
                f"{item.translated_chars_estimate:<12}{item.tts_audio_seconds_estimate:<10.1f}"
                f"{item.translation_cost_usd:<10.4f}{item.tts_cost_usd:<10.4f}{marker}"
            )

        print(f"\n{BOLD}Tổng dịch:{RESET}   ${result.total_translation_cost_usd:.4f}")
        print(f"{BOLD}Tổng TTS:{RESET}     ${result.total_tts_cost_usd:.4f} "
              f"({result.total_tts_audio_seconds:.1f}s audio)")
        print(f"{BOLD}TỔNG CỘNG:{RESET}    ${result.total_cost_usd:.4f}")

        if result.warnings:
            print(f"\n{YELLOW}Cảnh báo:{RESET}")
            for w in result.warnings:
                print(f"  {YELLOW}- {w}{RESET}")

        print(f"\n{DIM}`~` trước ký tự nguồn = suy đoán thô từ thời lượng, chưa có transcript thật.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
