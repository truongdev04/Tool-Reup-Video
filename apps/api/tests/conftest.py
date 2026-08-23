from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.base import Base  # noqa: E402
from services.storage import Storage  # noqa: E402
from workers.registry import register_all  # noqa: E402

register_all()


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = maker()
    yield s
    s.close()


@pytest.fixture
def storage(tmp_path) -> Storage:
    return Storage(tmp_path)


@pytest.fixture
def sample_video(tmp_path) -> Path:
    from tests.fixtures.make_fixture import make_sample

    return make_sample(tmp_path / "sample.mp4")
