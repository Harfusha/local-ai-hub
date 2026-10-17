from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing

import pytest

from local_ai_hub.artifacts import ArtifactStore, UnsupportedArtifactSchema


def _tenant_identity(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def test_fresh_schema_uses_sidecar_and_preserves_nul_slices(tmp_path) -> None:
    text = "A\x00BCDEF\x00GHI"
    store = ArtifactStore(tmp_path)
    artifact_id = store.put(text, "owner", "text")
    db_path = tmp_path / "artifacts.sqlite3"
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


def test_existing_schema_with_missing_paging_row_fails_without_mutation(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    tenant = _tenant_identity("owner")
    db_path = tmp_path / "artifacts.sqlite3"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            "INSERT INTO artifacts(artifact_id, created_at, tenant, tenant_identity, kind, text) "
            "VALUES(?,?,?,?,?,?)",
            ("art_missing_paging", time.time(), tenant, tenant, "text", "unindexed"),
        )
        connection.commit()

    before = db_path.read_bytes()
    with pytest.raises(UnsupportedArtifactSchema, match="incomplete artifact paging metadata"):
        ArtifactStore(tmp_path)
    assert db_path.read_bytes() == before


@pytest.mark.parametrize("corruption", ["missing", "malformed", "inconsistent"])
def test_reads_reject_missing_or_inconsistent_paging_metadata(tmp_path, corruption) -> None:
    store = ArtifactStore(tmp_path)
    artifact_id = store.put("# Heading\n\nbody", "owner", "text")
    db_path = tmp_path / "artifacts.sqlite3"
    with closing(sqlite3.connect(db_path)) as connection:
        if corruption == "missing":
            connection.execute(
                "DELETE FROM artifact_paging_metadata WHERE artifact_id=?", (artifact_id,),
            )
        else:
            if corruption == "malformed":
                section_json = "{invalid"
            else:
                metadata = json.loads(connection.execute(
                    "SELECT section_json FROM artifact_paging_metadata WHERE artifact_id=?",
                    (artifact_id,),
                ).fetchone()[0])
                metadata["names"] = ["stale_but_shape_valid"]
                section_json = json.dumps(metadata, separators=(",", ":"))
            connection.execute(
                "UPDATE artifact_paging_metadata SET section_json=? WHERE artifact_id=?",
                (section_json, artifact_id),
            )
        connection.commit()

    read_result = store.get(artifact_id, tenant="owner")
    slices_result = store.get_slices(
        artifact_id, [{"offset": 0, "max_chars": 10}], tenant="owner",
    )

    for result in (read_result, slices_result):
        assert result["success"] is False
        assert result["error_code"] == "artifact_paging_metadata_invalid"


def test_rebuilds_derived_paging_metadata_and_preserves_artifact_text(tmp_path) -> None:
    text = "heading\n\nbody\x00tail"
    store = ArtifactStore(tmp_path)
    artifact_id = store.put(text, "owner", "text")
    db_path = tmp_path / "artifacts.sqlite3"
    previous_paging_schema = """CREATE TABLE artifact_paging_metadata (
        artifact_id TEXT PRIMARY KEY,
        char_count INTEGER NOT NULL,
        section_names TEXT NOT NULL,
        page_text TEXT,
        nul_mask BLOB
    )"""

    with closing(sqlite3.connect(db_path)) as connection:
        durable_before = connection.execute(
            "SELECT text, tenant, tenant_identity FROM artifacts WHERE artifact_id=?",
            (artifact_id,),
        ).fetchone()
        connection.execute("DROP TABLE artifact_paging_metadata")
        connection.execute(previous_paging_schema)
        connection.execute(
            "INSERT INTO artifact_paging_metadata VALUES(?,?,?,?,?)",
            (artifact_id, len(text), "malformed derived data", None, None),
        )
        connection.commit()

    reopened = ArtifactStore(tmp_path)
    result = reopened.get_slices(
        artifact_id, [{"offset": 0, "max_chars": len(text)}], tenant="owner",
    )

    assert result["success"] is True
    assert result["slices"] == [{"offset": 0, "text": text}]
    with closing(sqlite3.connect(db_path)) as connection:
        durable_after = connection.execute(
            "SELECT text, tenant, tenant_identity FROM artifacts WHERE artifact_id=?",
            (artifact_id,),
        ).fetchone()
        paging_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_xinfo(artifact_paging_metadata)")
        }
    assert durable_after == durable_before
    assert {"section_json", "section_checksum"} <= paging_columns


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
    assert not {"char_count", "section_json", "section_checksum", "page_text", "nul_mask"} & core_columns
    assert {
        "artifact_id", "char_count", "section_json", "section_checksum", "page_text", "nul_mask",
    } <= sidecar_columns


def test_noncanonical_core_paging_schema_is_rejected(tmp_path) -> None:
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

    with pytest.raises(UnsupportedArtifactSchema, match="unsupported artifact"):
        ArtifactStore(tmp_path).get(artifact_id, offset=4, max_chars=6, tenant="owner")
