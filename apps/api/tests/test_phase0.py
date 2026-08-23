"""Nghiệm thu Phase 0 — data model, storage layout, ingest, ffmpeg (docs §20)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect

from core.config import get_settings
from core.hashing import file_checksum, stage_input_hash
from core.types import PIPELINE_ORDER, STAGE_DEPENDENCIES, ArtifactKind, StageName
from db.base import Base
from db.models import Project, SourceVideo, VoiceConsent
from services.ffmpeg import FilterGraph, probe
from services.storage import RETENTION_DAYS, Storage
from workers.ingest.stage import register_source


# --- data model -------------------------------------------------------------

def test_du_23_bang(session):
    tables = set(Base.metadata.tables)
    assert len(tables) == 23, f"kỳ vọng 23 bảng (§10), có {len(tables)}"
    for t in ("stt_segments", "translation_units", "tts_chunks", "subtitle_cues",
              "segment_links", "segment_timing", "approval_gates", "voice_consents",
              "onscreen_text", "stage_runs"):
        assert t in tables, f"thiếu bảng {t}"


def test_khong_con_bang_segments_gop():
    """v2 dùng 1 bảng `segments` cho 4 loại đơn vị — v3 phải tách (§5)."""
    assert "segments" not in Base.metadata.tables


def test_sqlite_bat_foreign_key():
    """SQLite mặc định TẮT foreign key, khiến ràng buộc im lặng vô hiệu."""
    from db.base import engine
    with engine.connect() as conn:
        from sqlalchemy import text
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


# --- lineage & compliance ---------------------------------------------------

def test_rights_note_la_bat_buoc(session, storage, sample_video):
    p = Project(name="P"); session.add(p); session.flush()
    with pytest.raises(ValueError, match="rights_note"):
        register_source(session, storage, project_id=p.id,
                        file_path=sample_video, rights_note="   ")


def test_voice_consent_han_su_dung():
    now = datetime.now(UTC)
    c = VoiceConsent(subject_name="A", scope="quảng cáo",
                     granted_at=now - timedelta(days=10),
                     expires_at=now + timedelta(days=10))
    assert c.is_valid_at(now)
    assert not c.is_valid_at(now + timedelta(days=20)), "hết hạn phải chặn"
    c.is_revoked = True
    assert not c.is_valid_at(now), "đã thu hồi phải chặn"


# --- ingest idempotent ------------------------------------------------------

def test_ingest_idempotent(session, storage, sample_video):
    p = Project(name="P"); session.add(p); session.flush()
    note = "test"
    a = register_source(session, storage, project_id=p.id, file_path=sample_video, rights_note=note)
    b = register_source(session, storage, project_id=p.id, file_path=sample_video, rights_note=note)
    assert a.id == b.id, "cùng file không được tạo bản ghi trùng (§11.1)"
    assert session.query(SourceVideo).count() == 1


# --- storage ----------------------------------------------------------------

def test_artifact_theo_locale_phai_tach_theo_job(storage):
    """Layout phẳng của §12 sẽ khiến bản ES và JA ghi đè nhau."""
    es = storage.tts_chunk_path(project_id="P", job_id="J-es", unit_idx=1, chunk_idx=0)
    ja = storage.tts_chunk_path(project_id="P", job_id="J-ja", unit_idx=1, chunk_idx=0)
    assert es != ja

    with pytest.raises(ValueError, match="job_id"):
        storage.path_for(ArtifactKind.TTS, project_id="P")


def test_retention_phu_het_artifact():
    assert set(RETENTION_DAYS) == set(ArtifactKind)


# --- cache key --------------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("provider_version", "v99"),
    ("config_version", "9.9.9"),
    ("source_checksum", "khac"),
])
def test_cache_key_doi_theo_tung_thanh_phan(field, value):
    base = dict(stage="tts", source_checksum="abc", config_version="0.1.0",
                provider="p", provider_version="v1")
    assert stage_input_hash(**base) != stage_input_hash(**{**base, field: value})


# --- dependency graph -------------------------------------------------------

def test_dependency_graph_khong_vong_lap():
    seen: set[StageName] = set()
    for s in PIPELINE_ORDER:
        for d in STAGE_DEPENDENCIES[s]:
            assert d in seen, f"{s} phụ thuộc {d} nhưng {d} chạy sau"
        seen.add(s)


# --- ffmpeg -----------------------------------------------------------------

def test_ffmpeg_du_kha_nang():
    """Bản ffmpeg thường của brew thiếu libass/freetype -> không burn được
    hardsub, không vẽ được text branding (§13.2)."""
    assert get_settings().verify_ffmpeg() == []


def test_probe_doc_dung_fixture(sample_video):
    info = probe(sample_video)
    assert info.duration_ms == pytest.approx(10_000, abs=200)
    assert (info.width, info.height) == (1080, 1920), "fixture phải là 9:16"
    assert info.has_audio, "fixture phải có audio để test STT/TTS"


def test_filter_graph_builder():
    g = FilterGraph()
    g.add(["0:v"], "scale=1080:1920", ["v1"])
    g.add(["v1", "1:v"], "overlay=10:10", ["out"])
    assert g.build() == "[0:v]scale=1080:1920[v1];[v1][1:v]overlay=10:10[out]"
    with pytest.raises(Exception):
        FilterGraph().build()
