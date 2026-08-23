"""Stage contract dùng chung cho mọi worker — docs §11.1.

Mỗi stage phải:
  - Là hàm thuần `run(ctx, stage_input) -> StageResult`
  - Ghi kết quả xuống DB và storage ngay khi chạy
  - KHÔNG gọi trực tiếp stage khác — điều phối là việc của orchestrator
  - Idempotent: chạy lại cùng input không tạo output trùng

Nhờ contract này, việc gắn Celery/RQ ở Phase 3 chỉ là đổi cách gọi, không phải
viết lại worker (§11.1, §20).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.types import CacheScope, StageName
from services.storage import Storage


class NonRetryableError(Exception):
    """Lỗi chạy lại bao nhiêu lần cũng vậy: cấu hình sai, thiếu file nguồn,
    thiếu stage phụ thuộc. Orchestrator thấy lỗi loại này thì dừng ngay thay vì
    đốt thêm hai lượt retry (§16)."""


@dataclass
class StageContext:
    """Mọi thứ một stage cần. Truyền vào thay vì để stage tự dựng —
    nhờ đó test bơm được session/storage riêng."""

    session: Session
    job_id: str
    project_id: str
    source_checksum: str
    locale: str
    storage: Storage = field(default_factory=Storage)
    settings: Settings = field(default_factory=get_settings)
    presets: dict[str, Any] = field(default_factory=dict)


@dataclass
class StageResult:
    """Output chuẩn hoá của một stage."""

    #: Con trỏ tới kết quả (đường dẫn, id bản ghi...). Lưu vào stage_runs.output_ref.
    output_ref: dict[str, Any] = field(default_factory=dict)
    #: Usage thực tế để tính chi phí (§17).
    usage: dict[str, Any] = field(default_factory=dict)
    #: Stage tự báo cần người xem lại (vd. duration fit không ép được — §7.2).
    needs_review: bool = False
    note: str | None = None


class Stage(ABC):
    """Một bước xử lý trong pipeline (§4)."""

    #: Khớp danh sách stage ở docs §4.
    name: StageName
    #: Provider bên ngoài, nếu có — vào cache key (§16).
    provider: str | None = None
    provider_version: str | None = None
    #: Mặc định JOB cho an toàn: dùng chéo nhầm thì output trỏ sang job khác.
    #: Stage nào thật sự không phụ thuộc locale mới khai báo SOURCE.
    cache_scope: CacheScope = CacheScope.JOB

    def cache_params(self, ctx: StageContext) -> dict[str, Any]:
        """Tham số ảnh hưởng tới kết quả, đưa vào cache key.

        Stage JOB kèm locale; stage SOURCE thì KHÔNG — kèm vào là mỗi locale ra
        một hash khác nhau, và cache_scope=SOURCE mất hết tác dụng dù đã khai
        báo đúng. Sai lầm này lan theo chuỗi: hash của một stage upstream đổi
        thì mọi stage sau nó cũng trượt cache.

        Stage nào phụ thuộc thêm preset thì override — thiếu tham số ở đây
        khiến cache trả kết quả của cấu hình khác (§16).
        """
        if self.cache_scope is CacheScope.SOURCE:
            return {}
        return {"locale": ctx.locale}

    @abstractmethod
    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        """Chạy stage. Phải idempotent (§11.1, §16)."""
        raise NotImplementedError


class NotImplementedStage(Stage):
    """Stage chưa implement — giữ đúng contract để harness chạy hết pipeline.

    Phase 0 chỉ cần trục chạy thông; logic từng stage đến ở Phase 1–2 (§20).
    """

    def __init__(self, name: StageName, phase: str) -> None:
        self.name = name
        self.phase = phase

    def run(self, ctx: StageContext, stage_input: dict[str, Any]) -> StageResult:
        return StageResult(
            output_ref={"stub": True, "planned_phase": self.phase},
            note=f"chưa implement — dự kiến {self.phase}",
        )


_REGISTRY: dict[StageName, Stage] = {}


def register(stage: Stage) -> Stage:
    _REGISTRY[stage.name] = stage
    return stage


def get_stage(name: StageName) -> Stage:
    if name not in _REGISTRY:
        raise KeyError(f"chưa đăng ký stage: {name}")
    return _REGISTRY[name]


def registry() -> dict[StageName, Stage]:
    return dict(_REGISTRY)
