from __future__ import annotations

import hashlib
import base64
import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.artifacts import ArtifactStore, UnsupportedArtifactSchema


CORE_SCHEMA = """CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY, created_at REAL NOT NULL, tenant TEXT NOT NULL,
    tenant_identity TEXT, kind TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
    mime_type TEXT, encoding TEXT, blob BLOB, size_bytes INTEGER, checksum TEXT,
    identity_json TEXT
)"""


def _current_marker(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE artifact_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO artifact_schema_meta VALUES ('tenant_storage', 'sha256-v1')")


def test_canonical_database_reopens_without_changing_durable_artifact_identity(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    tenant = hashlib.sha256(b"owner").hexdigest()
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(CORE_SCHEMA)
        _current_marker(connection)
        connection.execute(
            "INSERT INTO artifacts(artifact_id, created_at, tenant, tenant_identity, kind, text) "
            "VALUES ('art_fixed', 9999999999, ?, ?, 'text', 'preserved')",
            (tenant, tenant),
        )
        connection.commit()

    store = ArtifactStore(tmp_path)
    assert store.get("art_fixed", tenant="owner")["text"] == "preserved"
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute(
            "SELECT artifact_id, tenant, tenant_identity, text FROM artifacts WHERE artifact_id='art_fixed'"
        ).fetchone() == ("art_fixed", tenant, tenant, "preserved")


@pytest.mark.parametrize("legacy_kind", ["artifacts_v2", "raw_tenant", "missing_marker", "legacy_marker"])
def test_incompatible_existing_database_is_rejected_without_modification(tmp_path, legacy_kind) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    with closing(sqlite3.connect(db_path)) as connection:
        if legacy_kind == "artifacts_v2":
            connection.execute(CORE_SCHEMA.replace("artifacts", "artifacts_v2", 1))
            _current_marker(connection)
            connection.execute(
                "INSERT INTO artifacts_v2 VALUES ('art_keep', 9999999999, 'tenant', 'tenant', "
                "'text', 'durable', NULL, NULL, NULL, NULL, NULL, NULL)"
            )
        else:
            connection.execute(CORE_SCHEMA)
            if legacy_kind == "missing_marker":
                _current_marker(connection)
                connection.execute("DELETE FROM artifact_schema_meta")
            elif legacy_kind == "legacy_marker":
                _current_marker(connection)
                connection.execute(
                    "UPDATE artifact_schema_meta SET value='legacy-raw-v1' WHERE key='tenant_storage'"
                )
            else:
                _current_marker(connection)
                connection.execute(
                    "INSERT INTO artifacts VALUES ('art_keep', 9999999999, 'raw-owner', 'raw-owner', "
                    "'text', 'durable', NULL, NULL, NULL, NULL, NULL, NULL)"
                )
        connection.commit()

    before = db_path.read_bytes()
    with pytest.raises(UnsupportedArtifactSchema):
        ArtifactStore(tmp_path)
    assert db_path.read_bytes() == before
    assert not db_path.with_name(db_path.name + "-wal").exists()
    assert not db_path.with_name(db_path.name + ".pre-tenant-identity.bak").exists()


def test_fresh_store_uses_one_canonical_durable_table(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    artifact_id = store.put_bytes(b"image", "owner", "vision-image", "image/png")
    result = store.get_binary(artifact_id, tenant="owner")
    assert result["success"] is True
    assert base64.b64decode(result["data_base64"]) == b"image"
    with closing(sqlite3.connect(store.path)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "artifacts" in tables
        assert "artifacts_v2" not in tables
