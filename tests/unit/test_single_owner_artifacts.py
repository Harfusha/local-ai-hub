from __future__ import annotations

import hashlib
import inspect
import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.artifacts import (
    ArtifactBatchCancelled,
    ArtifactStore,
    UnsupportedArtifactSchema,
)


def _store(state_dir) -> ArtifactStore:
    return ArtifactStore(state_dir)


def test_artifact_schema_has_no_owner_partition_or_marker(tmp_path) -> None:
    store = _store(tmp_path / "state")
    with closing(sqlite3.connect(store.path)) as connection, connection:
        objects = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert objects == {"artifacts", "artifact_paging_metadata"}
        columns = {row[1] for row in connection.execute("PRAGMA table_info(artifacts)")}
        assert columns == {
            "artifact_id", "created_at", "kind", "text", "mime_type", "encoding",
            "blob", "size_bytes", "checksum", "identity_json",
        }


def test_artifact_apis_retire_tenant_arguments_and_require_keyword_kind() -> None:
    no_tenant = ("batch", "put", "put_json", "put_bytes", "compact", "get", "get_binary", "get_slices", "get_lines", "list")
    for name in no_tenant:
        assert "tenant" not in inspect.signature(getattr(ArtifactStore, name)).parameters
    for name in ("put", "put_json", "put_bytes", "compact"):
        assert inspect.signature(getattr(ArtifactStore, name)).parameters["kind"].kind is inspect.Parameter.KEYWORD_ONLY
    assert inspect.signature(ArtifactStore.list).parameters["limit"].kind is inspect.Parameter.KEYWORD_ONLY


def test_artifact_ids_use_content_identity_and_retired_calls_reject(tmp_path) -> None:
    store = _store(tmp_path / "state")
    first = store.put("same content", kind="report")
    second = store.put("same content", kind="report")
    assert first == second
    assert len(store.list(limit=10)) == 1

    with pytest.raises(TypeError):
        store.batch("legacy-owner")
    with pytest.raises(TypeError):
        store.put("text", "legacy-owner", "report")
    with pytest.raises(TypeError):
        store.put("text", kind="report", tenant=None)
    with pytest.raises(TypeError):
        store.list("legacy-owner", 10)
    with pytest.raises(TypeError):
        store.get(first, 0, 6000, "", None)


def test_cancelled_artifact_batch_rolls_back_all_artifacts(tmp_path) -> None:
    store = _store(tmp_path / "state")
    state = {"cancel": False}
    with pytest.raises(ArtifactBatchCancelled):
        with store.batch(cancel_check=lambda: state["cancel"]) as batch:
            batch.put("first", kind="bundle-item")
            state["cancel"] = True
    assert store.list(limit=10) == []


def test_old_tenant_schema_marker_refuses_without_rewriting_database(tmp_path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    database = state_dir / "artifacts.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript(
            "CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY, created_at REAL NOT NULL, "
            "tenant TEXT NOT NULL, tenant_identity TEXT, kind TEXT NOT NULL, text TEXT NOT NULL DEFAULT '', "
            "mime_type TEXT, encoding TEXT, blob BLOB, size_bytes INTEGER, checksum TEXT, identity_json TEXT);"
            "CREATE TABLE artifact_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE artifact_paging_metadata (artifact_id TEXT PRIMARY KEY, char_count INTEGER NOT NULL, "
            "section_json TEXT NOT NULL, section_checksum TEXT NOT NULL, page_text TEXT, nul_mask BLOB);"
            "INSERT INTO artifacts VALUES ('art_legacy', 1, 'owner', 'identity', 'report', 'preserve me', "
            "NULL, NULL, NULL, NULL, NULL, NULL);"
            "INSERT INTO artifact_schema_meta VALUES ('tenant_storage', 'sha256-v1');"
        )
    before = hashlib.sha256(database.read_bytes()).digest()
    with pytest.raises(UnsupportedArtifactSchema, match="unsupported artifact database schema"):
        _store(state_dir)
    assert hashlib.sha256(database.read_bytes()).digest() == before
    with closing(sqlite3.connect(database)) as connection, connection:
        row = connection.execute("SELECT text FROM artifacts WHERE artifact_id='art_legacy'").fetchone()
        marker = connection.execute("SELECT value FROM artifact_schema_meta WHERE key='tenant_storage'").fetchone()
    assert row == ("preserve me",)
    assert marker == ("sha256-v1",)
