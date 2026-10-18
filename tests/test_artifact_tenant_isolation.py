import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.artifacts import ArtifactStore, UnsupportedArtifactSchema


def test_legacy_tenant_artifact_schema_rejected_without_rewriting_data(tmp_path):
    db_path = tmp_path / "artifacts.sqlite3"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            """CREATE TABLE artifacts (
                artifact_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                tenant TEXT NOT NULL,
                tenant_identity TEXT,
                kind TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                mime_type TEXT,
                encoding TEXT,
                blob BLOB,
                size_bytes INTEGER,
                checksum TEXT,
                identity_json TEXT
            )"""
        )
        con.executemany(
            "INSERT INTO artifacts(artifact_id, created_at, tenant, tenant_identity, kind, text) VALUES(?, ?, ?, ?, ?, ?)",
            [
                ("tenant-a-artifact", 2.0, "tenant-a", "tenant-a", "text", "a"),
                ("tenant-b-artifact", 1.0, "tenant-b", "tenant-b", "text", "b"),
            ],
        )
        con.commit()

    with pytest.raises(UnsupportedArtifactSchema):
        ArtifactStore(tmp_path)

    with closing(sqlite3.connect(db_path)) as con:
        rows = con.execute("SELECT artifact_id, text FROM artifacts ORDER BY artifact_id").fetchall()
    assert rows == [("tenant-a-artifact", "a"), ("tenant-b-artifact", "b")]


def test_current_artifact_schema_is_owner_global_and_rejects_retired_inputs(tmp_path):
    store = ArtifactStore(tmp_path)
    artifact_a = store.put("shared payload", kind="text")
    artifact_b = store.put("shared payload", kind="text")

    assert artifact_a == artifact_b
    assert [item["artifact_id"] for item in store.list(limit=20)] == [artifact_a]
    assert store.get(artifact_a)["text"] == "shared payload"
    with pytest.raises(TypeError):
        store.put("payload", "old-tenant", "text")
    with pytest.raises(TypeError):
        store.get(artifact_a, tenant=None)
