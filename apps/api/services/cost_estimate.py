"""Ước tính chi phí trước khi chạy batch — §17.1.

    Trước khi batch khởi động:
      - đếm ký tự cần dịch (× số locale)
      - đếm giây audio cần TTS
      -> hiện TỔNG TIỀN DỰ KIẾN + yêu cầu người dùng xác nhận

Không có bước này thì lệnh batch N video chỉ được phát hiện là sai lầm SAU
khi đã tiêu tiền — đây là ĐIỂM CHÍNH của §17.1, khác `ApiUsage.is_estimate`
(đã có sẵn từ Phase 0 nhưng chưa có gì ghi `is_estimate=True`).

Nguyên tắc "tự đo usage thực tế" (§17): ưu tiên NGUỒN SỐ THẬT theo thứ tự:
1. `ApiUsage` thật (`is_estimate=False`) của ĐÚNG provider đó, đã chạy trước
   đây trong DB này — cost/char đo thực tế, gồm cả overhead/retry thật đã
   xảy ra, chính xác hơn giá niêm yết trong config.
2. Giá niêm yết trong `ProviderConfig`/`TTSConfig` (`usd_per_1m_*`) — dùng khi
   chưa có lịch sử (lần chạy đầu tiên với provider đó).
3. `None`/0 nếu provider không khai giá (vd. `mock`, `macos_say` free) — không
   suy đoán giá không biết.

Ký tự nguồn (để ước KÝ TỰ CẦN DỊCH) cũng ưu tiên số THẬT nếu source video đã
qua STT (`Transcript.full_text`); chỉ rơi về ước lượng thô theo
`duration_ms × speech_rate_cps` khi CHƯA transcribe — luôn đánh dấu rõ trong
`warnings` để người xem biết đâu là số đo, đâu là suy đoán.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from core.types import JobStatus, StageName
from db.models import ApiUsage, RenderJob, SourceVideo, StageRun, Transcript
from services.presets import PresetNotFound, effective_speech_rate, load_locale
from services.providers.base import ProviderError
from services.providers.registry import ProviderNotFound, get_provider
from services.tts.base import TTSError
from services.tts.registry import TTSProviderNotFound, get_tts

#: Tốc độ đọc mặc định khi KHÔNG biết locale nguồn (không có preset tương
#: ứng, vd. `SourceVideo.source_locale` để trống) — trung vị thô giữa các
#: locale hiện có trong `config/presets/locale/`, chỉ dùng làm phao cứu hộ
#: cuối cùng, luôn kèm cảnh báo.
_FALLBACK_SOURCE_CPS = 15.0


@dataclass
class VideoLocaleEstimate:
    source_video_id: str
    filename: str
    locale: str
    #: True = số ký tự lấy từ `Transcript.full_text` thật; False = suy đoán
    #: thô từ `duration_ms`.
    source_chars_measured: bool
    source_chars: int
    translated_chars_estimate: int
    tts_audio_seconds_estimate: float
    translation_cost_usd: float
    tts_cost_usd: float
    #: True = job (video, locale) này ĐÃ có RenderJob với TRANSLATE/TTS thành
    #: công — chạy lại nhiều khả năng cache-hit (§16), chi phí thêm ≈ 0. Vẫn
    #: hiện số ước tính đầy đủ để biết "nếu phải chạy lại từ đầu thì tốn bao
    #: nhiêu", không tự ý coi là 0.
    already_done: bool


@dataclass
class BatchCostEstimate:
    translation_provider: str
    tts_provider: str
    items: list[VideoLocaleEstimate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_translation_cost_usd(self) -> float:
        return sum(i.translation_cost_usd for i in self.items)

    @property
    def total_tts_cost_usd(self) -> float:
        return sum(i.tts_cost_usd for i in self.items)

    @property
    def total_cost_usd(self) -> float:
        return self.total_translation_cost_usd + self.total_tts_cost_usd

    @property
    def total_tts_audio_seconds(self) -> float:
        return sum(i.tts_audio_seconds_estimate for i in self.items)

    @property
    def total_translated_chars(self) -> int:
        return sum(i.translated_chars_estimate for i in self.items)


def _historical_cost_per_char(session, *, stage: StageName, provider_id: str) -> float | None:
    rows = session.scalars(
        select(ApiUsage).where(
            ApiUsage.stage == stage,
            ApiUsage.provider == provider_id,
            ApiUsage.is_estimate.is_(False),
            ApiUsage.characters > 0,
        )
    ).all()
    total_chars = sum(r.characters for r in rows)
    if total_chars == 0:
        return None
    return sum(r.cost_usd for r in rows) / total_chars


def _source_chars(session, video: SourceVideo) -> tuple[int, bool]:
    """Trả `(số ký tự, đã đo thật hay chưa)`."""
    transcript = session.scalars(
        select(Transcript).where(Transcript.source_video_id == video.id)
    ).first()
    if transcript is not None and transcript.full_text:
        return len(transcript.full_text), True

    duration_ms = (video.media_info or {}).get("duration_ms")
    if not duration_ms:
        return 0, False

    cps = _FALLBACK_SOURCE_CPS
    if video.source_locale:
        try:
            cps = load_locale(video.source_locale).speech_rate_cps
        except PresetNotFound:
            pass
    return round(duration_ms / 1000 * cps), False


def _translation_cost(
    session, *, provider_id: str, source_chars: int
) -> tuple[int, float, list[str]]:
    """Bản dịch thường lệch ±20% ký tự so với nguồn — coi bằng nguồn là xấp xỉ
    hợp lý cho MỌI locale (không có hệ số riêng theo locale đích, vì hướng
    lệch phụ thuộc cặp ngôn ngữ cụ thể, không có số đo chung đáng tin)."""
    warnings: list[str] = []
    translated_chars = source_chars

    hist = _historical_cost_per_char(session, stage=StageName.TRANSLATE, provider_id=provider_id)
    if hist is not None:
        return translated_chars, translated_chars * hist, warnings

    try:
        provider = get_provider(provider_id)
    except (ProviderNotFound, ProviderError):
        warnings.append(f"không nạp được provider dịch `{provider_id}` — bỏ qua ước tính chi phí")
        return translated_chars, 0.0, warnings

    cfg = provider.config
    if cfg.usd_per_1m_input is None or cfg.usd_per_1m_output is None:
        # None khác 0.0 — 0.0 là local/mock THẬT SỰ free (khai rõ trong JSON),
        # None là "chưa ai điền giá" (vd. openai/claude/gemini hiện tại). Báo
        # rõ ra warning để không đọc nhầm "$0.0000" thành "provider này free".
        warnings.append(
            f"provider dịch `{provider_id}` chưa khai `usd_per_1m_input`/`usd_per_1m_output` "
            f"trong config — KHÔNG ước tính được chi phí, không phải provider này miễn phí"
        )
        return translated_chars, 0.0, warnings

    # Chưa có lịch sử THẬT lẫn cách đếm token trước khi gọi model — xấp xỉ thô
    # 1 token ≈ 4 ký tự (kinh nghiệm chung cho văn bản La-tinh/BPE, KHÔNG đúng
    # cho CJK — nói rõ trong warning để không ai coi đây là số chính xác).
    tokens_in = round(source_chars / 4)
    tokens_out = round(translated_chars / 4)
    cost = tokens_in / 1_000_000 * cfg.usd_per_1m_input + tokens_out / 1_000_000 * cfg.usd_per_1m_output
    warnings.append(
        f"provider dịch `{provider_id}` chưa có lịch sử usage thật trong DB này — "
        f"ước tính bằng giá niêm yết + suy đoán token≈ký_tự/4 (thô, đặc biệt kém chính xác cho locale CJK)"
    )
    return translated_chars, cost, warnings


def _tts_cost(
    session, *, provider_id: str, locale: str, translated_chars: int
) -> tuple[float, float, list[str]]:
    warnings: list[str] = []
    rate = effective_speech_rate(locale, provider_id)
    audio_seconds = translated_chars / rate if rate > 0 else 0.0

    hist = _historical_cost_per_char(session, stage=StageName.TTS, provider_id=provider_id)
    if hist is not None:
        return audio_seconds, translated_chars * hist, warnings

    try:
        provider = get_tts(provider_id)
    except (TTSProviderNotFound, TTSError):
        warnings.append(f"không nạp được provider TTS `{provider_id}` — bỏ qua ước tính chi phí")
        return audio_seconds, 0.0, warnings

    cost = provider.estimate_cost_usd(translated_chars)
    if cost is None:
        # Cùng lý do với nhánh dịch ở trên — None (chưa khai giá) khác 0.0
        # (free thật, vd. macos_say).
        warnings.append(
            f"provider TTS `{provider_id}` chưa khai `usd_per_1m_chars` trong config — "
            f"KHÔNG ước tính được chi phí, không phải provider này miễn phí"
        )
        cost = 0.0
    return audio_seconds, cost, warnings


def _already_done(session, *, source_video_id: str, locale: str) -> bool:
    job = session.scalars(
        select(RenderJob).where(
            RenderJob.source_video_id == source_video_id, RenderJob.locale == locale,
        )
    ).first()
    if job is None:
        return False
    succeeded = session.scalars(
        select(StageRun).where(
            StageRun.render_job_id == job.id,
            StageRun.stage.in_([StageName.TRANSLATE, StageName.TTS]),
            StageRun.status == JobStatus.SUCCEEDED,
        )
    ).all()
    return len(succeeded) >= 2


def estimate_batch(
    session,
    *,
    source_videos: list[SourceVideo],
    target_locales: list[str],
    translation_provider_id: str,
    tts_provider_id: str,
) -> BatchCostEstimate:
    """Ước tính chi phí dịch + TTS cho tổ hợp `source_videos × target_locales`.

    KHÔNG gọi mạng, KHÔNG tốn tiền — chỉ đọc dữ liệu đã có trong DB + config
    (§17.1: phải biết TRƯỚC khi batch khởi động, không phải trong lúc chạy).
    """
    result = BatchCostEstimate(translation_provider=translation_provider_id, tts_provider=tts_provider_id)
    seen_warnings: set[str] = set()

    for video in source_videos:
        source_chars, measured = _source_chars(session, video)
        if not measured:
            seen_warnings.add(
                f"video `{video.filename}` chưa có transcript — ước ký tự nguồn thô theo thời lượng"
            )
        for locale in target_locales:
            translated_chars, translation_cost, t_warn = _translation_cost(
                session, provider_id=translation_provider_id, source_chars=source_chars,
            )
            audio_seconds, tts_cost, tts_warn = _tts_cost(
                session, provider_id=tts_provider_id, locale=locale, translated_chars=translated_chars,
            )
            for w in (*t_warn, *tts_warn):
                seen_warnings.add(w)

            result.items.append(
                VideoLocaleEstimate(
                    source_video_id=video.id,
                    filename=video.filename,
                    locale=locale,
                    source_chars_measured=measured,
                    source_chars=source_chars,
                    translated_chars_estimate=translated_chars,
                    tts_audio_seconds_estimate=audio_seconds,
                    translation_cost_usd=translation_cost,
                    tts_cost_usd=tts_cost,
                    already_done=_already_done(session, source_video_id=video.id, locale=locale),
                )
            )

    result.warnings = sorted(seen_warnings)
    return result
