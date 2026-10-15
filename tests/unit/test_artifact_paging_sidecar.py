from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import closing

import pytest

from local_ai_hub.artifacts import ArtifactStore


def _tenant_identity(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def test_canonical_core_uses_sidecar_and_preserves_nul_slices_and_id(tmp_path) -> None:
    artifact_id = "art_durable_canonical"
    text = "A\x00BCDEF\x00GHI"
    tenant = _tenant_identity("owner")
    db_path = tmp_path / "artifacts.sqlite3"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """CREATE TABLE artifacts (
                artifact_id TEXT PRIMARY KEY, created_at REAL NOT NULL,
                tenant TEXT NOT NULL, tenant_identity TEXT, kind TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '', mime_type TEXT, encoding TEXT, blob BLOB,
                size_bytes INTEGER, checksum TEXT, identity_json TEXT
            )"""
        )
        connection.execute(
            "CREATE TABLE artifact_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO artifact_schema_meta(key, value) VALUES('tenant_storage', 'sha256-v1')"
        )
        connection.execute(
            "INSERT INTO artifacts(artifact_id, created_at, tenant, tenant_identity, kind, text) "
            "VALUES(?,?,?,?,?,?)",
            (artifact_id, time.time(), tenant, tenant, "text", text),
        )
        connection.commit()

    store = ArtifactStore(tmp_path)
    result = store.get_slices(
        artifact_id,
        [{"offset": 0, "max_chars": 7}, {"offset": 5, "max_chars": 6}],
        tenant="owner",
    )
    assert result["success"] is True
    assert result["slices"] == [
        {"offset": 0, "text": text[0:7]},
        {"offset": 5, "text": text[5:11]},
    ]
    assert result["total_chars"] == len(text)

    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute(
            "SELECT artifact_id, text FROM artifacts WHERE artifact_id=?", (artifact_id,),
        ).fetchone() == (artifact_id, text)
        core_columns = {row[1] for row in connection.execute("PRAGMA table_info(artifacts)")}
        assert not {"char_count", "section_names", "page_text", "nul_mask"} & core_columns
        sidecar_id = connection.execute(
            "SELECT artifact_id FROM artifact_paging_metadata WHERE artifact_id=?", (artifact_id,),
        ).fetchone()
    assert sidecar_id == (artifact_id,)


def test_unindexed_canonical_row_is_read_without_sidecar_write_after_batch_limit(tmp_path) -> None:
    artifact_id = "art_z_deferred"
    text = "before\x00after\x00end"
    tenant = _tenant_identity("owner")
    db_path = tmp_path / "artifacts.sqlite3"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """CREATE TABLE artifacts (
                artifact_id TEXT PRIMARY KEY, created_at REAL NOT NULL,
                tenant TEXT NOT NULL, tenant_identity TEXT, kind TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '', mime_type TEXT, encoding TEXT, blob BLOB,
                size_bytes INTEGER, checksum TEXT, identity_json TEXT
            )"""
        )
        connection.execute(
            "CREATE TABLE artifact_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO artifact_schema_meta(key, value) VALUES('tenant_storage', 'sha256-v1')"
        )
        now = time.time()
        connection.executemany(
            "INSERT INTO artifacts(artifact_id, created_at, tenant, tenant_identity, kind, text) "
            "VALUES(?,?,?,?,?,?)",
            [
                (f"art_{index:03d}", now + index, tenant, tenant, "text", f"row-{index}")
                for index in range(128)
            ] + [(artifact_id, now + 128, tenant, tenant, "text", text)],
        )
        connection.commit()

    store = ArtifactStore(tmp_path)
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifact_paging_metadata").fetchone() == (128,)
        assert connection.execute(
            "SELECT 1 FROM artifact_paging_metadata WHERE artifact_id=?", (artifact_id,),
        ).fetchone() is None

    result = store.get_slices(
        artifact_id,
        [{"offset": 0, "max_chars": 8}, {"offset": 7, "max_chars": 8}],
        tenant="owner",
    )
    assert result["success"] is True
    assert result["slices"] == [
        {"offset": 0, "text": text[0:8]},
        {"offset": 7, "text": text[7:15]},
    ]
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifact_paging_metadata").fetchone() == (128,)
        assert connection.execute(
            "SELECT 1 FROM artifact_paging_metadata WHERE artifact_id=?", (artifact_id,),
        ).fetchone() is None


def test_core_and_sidecar_write_roll_back_together_on_failed_batch(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    artifact_id = ""
    with pytest.raises(RuntimeError, match="abort batch"):
        with store.batch("owner") as batch:
            artifact_id = batch.put("batch payload", "text")
            raise RuntimeError("abort batch")

    with closing(sqlite3.connect(tmp_path / "artifacts.sqlite3")) as connection:
        assert connection.execute(
            "SELECT 1 FROM artifacts WHERE artifact_id=?", (artifact_id,),
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM artifact_paging_metadata WHERE artifact_id=?", (artifact_id,),
        ).fetchone() is None


def test_binary_replacement_removes_stale_paging_sidecar(tmp_path, monkeypatch) -> None:
    store = ArtifactStore(tmp_path)
    artifact_id = store.put("text payload", "owner", "text")
    monkeypatch.setattr(
        store, "_scoped_artifact_id", lambda connection, base_id, tenant_identity: artifact_id,
    )

    assert store.put_bytes(b"image bytes", "owner", "vision-image", "image/png") == artifact_id
    with closing(sqlite3.connect(tmp_path / "artifacts.sqlite3")) as connection:
        assert connection.execute(
            "SELECT mime_type FROM artifacts WHERE artifact_id=?", (artifact_id,),
        ).fetchone() == ("image/png",)
        assert connection.execute(
            "SELECT 1 FROM artifact_paging_metadata WHERE artifact_id=?", (artifact_id,),
        ).fetchone() is None


def test_new_core_schema_keeps_paging_fields_out_of_artifacts(tmp_path) -> None:
    ArtifactStore(tmp_path)
    with closing(sqlite3.connect(tmp_path / "artifacts.sqlite3")) as connection:
        core_columns = {row[1] for row in connection.execute("PRAGMA table_info(artifacts)")}
        sidecar_columns = {row[1] for row in connection.execute("PRAGMA table_info(artifact_paging_metadata)")}
    assert not {"char_count", "section_names", "page_text", "nul_mask"} & core_columns
    assert {"artifact_id", "char_count", "section_names", "page_text", "nul_mask"} <= sidecar_columns


def test_existing_core_paging_extras_are_ignored_and_rebuilt_in_sidecar(tmp_path) -> None:
    artifact_id = "art_durable_current_core"
    text = "head\x00middle\x00tail"
    tenant = _tenant_identity("owner")
    db_path = tmp_path / "artifacts.sqlite3"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            "CREATE TABLE artifact_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO artifact_schema_meta(key, value) VALUES('tenant_storage', 'sha256-v1')"
        )
        connection.execute(
            """CREATE TABLE artifacts (
                artifact_id TEXT PRIMARY KEY, created_at REAL NOT NULL, tenant TEXT NOT NULL,
                tenant_identity TEXT, kind TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
                mime_type TEXT, encoding TEXT, blob BLOB, size_bytes INTEGER, checksum TEXT,
                identity_json TEXT, char_count INTEGER, section_names TEXT,
                page_text TEXT, nul_mask BLOB
            )"""
        )
        connection.execute(
            """INSERT INTO artifacts(
                artifact_id, created_at, tenant, tenant_identity, kind, text,
                char_count, section_names, page_text, nul_mask
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (artifact_id, time.time(), tenant, tenant, "text", text, 0, "[]", "stale", b""),
        )
        connection.commit()

    store = ArtifactStore(tmp_path)
    result = store.get(artifact_id, offset=4, max_chars=6, tenant="owner")
    assert result["success"] is True
    assert result["text"] == text[4:10]
    assert result["total_chars"] == len(text)
    with closing(sqlite3.connect(db_path)) as connection:
        core_row = connection.execute(
            "SELECT artifact_id, text, char_count, section_names, page_text FROM artifacts WHERE artifact_id=?",
            (artifact_id,),
        ).fetchone()
        sidecar = connection.execute(
            "SELECT char_count, section_names, page_text, nul_mask FROM artifact_paging_metadata WHERE artifact_id=?",
            (artifact_id,),
        ).fetchone()
    assert core_row == (artifact_id, text, 0, "[]", "stale")
    assert sidecar[0] == len(text)
    assert sidecar[3] is not None
