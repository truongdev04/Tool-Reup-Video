#!/usr/bin/env python
"""Đo tốc độ đọc thật của một provider TTS — docs §7.2.

char_budget (số ký tự bản dịch được phép có) tính từ tốc độ đọc. Đoán sai con số
này là drift sai ngay từ đầu, và mọi chiến lược ép thời lượng phía sau chỉ đang
chữa hậu quả. Vì tốc độ đọc phụ thuộc CẢ provider lẫn ngôn ngữ, phải đo lại mỗi
khi đổi provider TTS.

    python scripts/calibrate_speech_rate.py                     # xem kết quả đo
    python scripts/calibrate_speech_rate.py --write             # ghi vào config
    python scripts/calibrate_speech_rate.py --provider elevenlabs --locales es-ES
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from pathlib import Path

_API = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(_API))

from services.presets import load_locale  # noqa: E402
from services.tts.base import SynthesisRequest  # noqa: E402
from services.tts.registry import TTS_ROOT, get_tts, load_config  # noqa: E402

#: Câu đo. Cần đủ dài để tốc độ ổn định và đủ đa dạng để không lệch theo một
#: kiểu câu. Nội dung trung tính, không dấu câu lạ.
CALIBRATION_TEXTS: dict[str, tuple[str, ...]] = {
    "en-US": (
        "This tool takes one source video and turns it into many language versions.",
        "You can change the voice, the subtitles, and the branding for each market.",
        "Everything runs on your own machine, so nothing leaves your computer.",
    ),
    "es-ES": (
        "Esta herramienta convierte un video original en muchas versiones de idioma.",
        "Puedes cambiar la voz, los subtítulos y la marca para cada mercado.",
        "Todo se ejecuta en tu propia máquina, así que nada sale de tu ordenador.",
    ),
    "ja-JP": (
        "このツールは一本の元動画を多くの言語バージョンに変換します。",
        "市場ごとに音声、字幕、ブランドを変更することができます。",
        "すべて自分のパソコンで動くので、データは外に出ません。",
    ),
    "vi-VN": (
        "Công cụ này chuyển một video gốc thành nhiều phiên bản ngôn ngữ khác nhau.",
        "Bạn có thể đổi giọng đọc, phụ đề và thương hiệu cho từng thị trường.",
        "Mọi thứ chạy ngay trên máy của bạn nên dữ liệu không đi ra ngoài.",
    ),
}


def measure(provider_id: str, locales: list[str]) -> dict[str, float]:
    provider = get_tts(provider_id)
    results: dict[str, float] = {}

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for locale in locales:
            texts = CALIBRATION_TEXTS.get(locale)
            if not texts:
                print(f"  {locale:<8} bỏ qua — chưa có câu đo cho locale này")
                continue

            rates: list[float] = []
            for i, text in enumerate(texts):
                try:
                    result = provider.synthesize(
                        SynthesisRequest(
                            text=text, locale=locale, out_path=tmpdir / f"{locale}_{i}.wav"
                        )
                    )
                except Exception as exc:  # noqa: BLE001 — báo rồi đi tiếp locale khác
                    print(f"  {locale:<8} lỗi: {str(exc)[:70]}")
                    rates.clear()
                    break
                if result.duration_ms > 0:
                    rates.append(len(text) / (result.duration_ms / 1000))

            if not rates:
                continue

            measured = statistics.median(rates)
            estimate = load_locale(locale).speech_rate_cps if _has_preset(locale) else None
            results[locale] = round(measured, 2)

            note = ""
            if estimate:
                diff = (measured - estimate) / estimate * 100
                note = f"  (ước lượng {estimate} → lệch {diff:+.0f}%)"
            print(f"  {locale:<8} {measured:>6.2f} cps{note}")

    return results


def _has_preset(locale: str) -> bool:
    try:
        load_locale(locale)
        return True
    except KeyError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Đo tốc độ đọc của provider TTS")
    parser.add_argument("--provider", default="macos_say")
    parser.add_argument("--locales", nargs="+", default=sorted(CALIBRATION_TEXTS))
    parser.add_argument("--write", action="store_true",
                        help="ghi kết quả vào config/tts/<provider>.json")
    args = parser.parse_args()

    print(f"Đo tốc độ đọc của provider `{args.provider}`:\n")
    results = measure(args.provider, args.locales)

    if not results:
        print("\nKhông đo được locale nào.")
        return 1

    if not args.write:
        print(f"\nChạy lại với --write để ghi {len(results)} giá trị vào config.")
        return 0

    path = TTS_ROOT / f"{args.provider}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["speech_rate_cps"] = {**data.get("speech_rate_cps", {}), **results}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\nĐã ghi {len(results)} giá trị vào {path.relative_to(Path.cwd())}")
    print("Lưu ý: đây là số đo của RIÊNG provider này. Đổi provider phải đo lại.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
