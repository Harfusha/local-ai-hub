import hashlib
import sqlite3
from contextlib import closing

from local_ai_hub.artifacts import ArtifactStore


def test_legacy_artifact_list_filters_hashed_tenant_identity(tmp_path):
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

    store = ArtifactStore(tmp_path)

    assert store._table == "artifacts"
    assert [item["artifact_id"] for item in store.list("tenant-a")] == ["tenant-a-artifact"]
    assert [item["artifact_id"] for item in store.list("tenant-b")] == ["tenant-b-artifact"]
    with closing(sqlite3.connect(db_path)) as con:
        identities = con.execute(
            "SELECT tenant, tenant_identity FROM artifacts ORDER BY artifact_id"
        ).fetchall()
    assert identities == [
        (hashlib.sha256(b"tenant-a").hexdigest(), hashlib.sha256(b"tenant-a").hexdigest()),
        (hashlib.sha256(b"tenant-b").hexdigest(), hashlib.sha256(b"tenant-b").hexdigest()),
    ]
