import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.artifacts import ArtifactStore, UnsupportedArtifactSchema


def test_legacy_artifact_schema_rejected_without_rewriting_tenant_identity(tmp_path):
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
        identities = con.execute(
            "SELECT tenant, tenant_identity FROM artifacts ORDER BY artifact_id"
        ).fetchall()
    assert identities == [
        ("tenant-a", "tenant-a"),
        ("tenant-b", "tenant-b"),
    ]


def test_current_artifact_schema_isolates_tenant_listing(tmp_path):
    store = ArtifactStore(tmp_path)
    artifact_a = store.put("tenant a payload", "tenant-a", "text")
    artifact_b = store.put("tenant b payload", "tenant-b", "text")

    assert [item["artifact_id"] for item in store.list("tenant-a")] == [artifact_a]
    assert [item["artifact_id"] for item in store.list("tenant-b")] == [artifact_b]
