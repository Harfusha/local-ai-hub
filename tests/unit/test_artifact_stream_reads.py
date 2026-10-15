from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import closing

import pytest

from local_ai_hub.artifacts import ArtifactStore


def _identity(tenant: str) -> str:
    return hashlib.sha256(tenant.encode("utf-8")).hexdigest()


def _insert_text(store: ArtifactStore, artifact_id: str, text: str, *, tenant: str = "owner", age: float = 0) -> None:
    with closing(sqlite3.connect(store.path)) as connection:
        connection.execute(
            f"INSERT INTO {store._table} "
            "(artifact_id, created_at, tenant, tenant_identity, kind, text) VALUES(?,?,?,?,?,?)",
            (artifact_id, time.time() - age, tenant, _identity(tenant), "text", text),
        )
        connection.commit()


@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16le", "UTF-16be"])
def test_streaming_reads_round_trip_unicode_nul_and_distant_spans(tmp_path, encoding) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    if encoding != "UTF-8":
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute(f"PRAGMA encoding='{encoding}'")
    store = ArtifactStore(tmp_path)
    text = "x" * 65_530 + "界😀\x00tail" + "z" * 70_000
    _insert_text(store, "art_stream", text)

    result = store.get_slices(
        "art_stream",
        [
            {"offset": 65_530, "max_chars": 8},
            {"offset": len(text) - 9, "max_chars": 9},
        ],
        tenant="owner",
    )
    assert result["success"] is True
    assert result["slices"] == [
        {"offset": 65_530, "text": text[65_530:65_538]},
        {"offset": len(text) - 9, "text": text[-9:]},
    ]
    assert result["total_chars"] == len(text)

    single = store.get("art_stream", offset=65_531, max_chars=256, tenant="owner")
    assert single["success"] is True
    assert single["text"] == text[65_531:65_531 + 256]
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute(
            "SELECT 1 FROM artifact_paging_metadata WHERE artifact_id='art_stream'",
        ).fetchone() is None


def test_streaming_read_uses_one_snapshot_and_does_not_backfill(tmp_path, monkeypatch) -> None:
    store = ArtifactStore(tmp_path)
    original = "A" * 100_000 + "old"
    _insert_text(store, "art_snapshot", original)
    stream = store._stream_text
    changed = False

    def update_after_snapshot(connection, rowid, encoding, spans=None, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            with closing(sqlite3.connect(store.path)) as writer:
                writer.execute(
                    f"UPDATE {store._table} SET text=? WHERE artifact_id=?",
                    ("new", "art_snapshot"),
                )
                writer.commit()
        return stream(connection, rowid, encoding, spans, **kwargs)

    monkeypatch.setattr(store, "_stream_text", update_after_snapshot)
    result = store.get("art_snapshot", offset=100_000, max_chars=256, tenant="owner")
    assert result["success"] is True
    assert result["text"] == "old"
    with closing(sqlite3.connect(store.path)) as connection:
        assert connection.execute(
            "SELECT text FROM artifacts WHERE artifact_id='art_snapshot'",
        ).fetchone() == ("new",)
        assert connection.execute(
            "SELECT 1 FROM artifact_paging_metadata WHERE artifact_id='art_snapshot'",
        ).fetchone() is None


def test_section_scan_caps_names_and_header_retention(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    text = "\n".join([f"## Heading {index}" for index in range(55)])
    text += "\n## " + ("H" * 100_000) + "\nbody"
    _insert_text(store, "art_sections", text)

    result = store.get("art_sections", max_chars=256, tenant="owner")
    assert result["success"] is True
    assert len(result["sections"]) == 50
    assert result["sections_truncated"] is True
    assert result["text"] == text[:256]


def test_json_section_over_admission_limit_returns_bounded_error(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    _insert_text(store, "art_large_json", '{"large":"' + ("x" * 1_100_000) + '"}')

    result = store.get("art_large_json", section="json:large", tenant="owner")
    assert result["success"] is False
    assert result["error_code"] == "artifact_section_too_large"


def test_expired_wrong_tenant_and_binary_rows_do_not_stream_text(tmp_path, monkeypatch) -> None:
    store = ArtifactStore(tmp_path, ttl_hours=1)
    _insert_text(store, "art_expired", "expired", age=7_200)
    _insert_text(store, "art_private", "private", tenant="other")
    binary_id = store.put_bytes(b"image-data", "owner", "vision-image", "image/png")
    monkeypatch.setattr(
        store,
        "_stream_text",
        lambda *_args, **_kwargs: pytest.fail("unauthorized or binary row reached text reader"),
    )

    assert store.get("art_expired", tenant="owner")["success"] is False
    assert store.get("art_private", tenant="owner")["success"] is False
    assert store.get(binary_id, tenant="owner")["success"] is False
