from contextlib import closing
import hashlib
import sqlite3

from local_ai_hub import evidence as evidence_module
from local_ai_hub.evidence import EvidenceStore
from local_ai_hub.evidence_contract import evidence_meta


def test_evidence_meta_is_bounded_and_does_not_store_payload():
    result = evidence_meta(
        source="repo.search", repository_revision="abc123", evidence_ids=["E1"],
        stale=False, status="success", payload={"text": "secret source"},
    )
    assert result == {
        "source": "repo.search", "repository_revision": "abc123",
        "evidence_ids": ["E1"], "stale": False, "status": "success",
    }


def test_stale_evidence_cannot_claim_verified():
    result = evidence_meta("repo.search", "abc123", ["E1"], True, "success")
    assert result["status"] == "stale"
    assert result["stale"] is True


def test_current_evidence_identity_requires_current_source_and_stored_row(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    file_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    store = EvidenceStore(tmp_path / "state")
    evidence_id = store.put(
        str(root),
        {
            "path": "sample.py",
            "file_sha256": file_hash,
            "start_line": 1,
            "end_line": 1,
            "text": "value = 1",
        },
    )

    assert evidence_id is not None
    id_validator = getattr(evidence_module, "is_evidence_id", None)
    current_validator = getattr(evidence_module, "is_current_evidence_id", None)
    store_validator = getattr(store, "validate_current", None)
    assert callable(id_validator), "is_evidence_id API missing"
    assert callable(current_validator), "is_current_evidence_id API missing"
    assert callable(store_validator), "EvidenceStore.validate_current API missing"
    assert id_validator(evidence_id)
    assert current_validator(evidence_id, store) is True
    assert store_validator(evidence_id) is True

    assert id_validator("EFFFFFFFFFFFFFFFFFFFF")
    assert store_validator("EFFFFFFFFFFFFFFFFFFFF") is False
    assert current_validator("malformed", store) is False
    assert current_validator(evidence_id, object()) is False

    source.write_text("value = 2\n", encoding="utf-8")
    assert store_validator(evidence_id) is False

    source.write_text("value = 1\n", encoding="utf-8")
    with closing(sqlite3.connect(store.db_path)) as connection, connection:
        connection.execute(
            "UPDATE evidence SET text=? WHERE id=?",
            ("forged evidence", evidence_id),
        )
    assert store_validator(evidence_id) is False


def test_put_many_does_not_return_unpersisted_evidence_ids(tmp_path, caplog):
    store = EvidenceStore(tmp_path / "evidence")

    class FailingConnection:
        @staticmethod
        def executemany(*_args, **_kwargs):
            raise sqlite3.OperationalError(f"private storage path: {tmp_path}")

        @staticmethod
        def close():
            return None

    store._connect = lambda: FailingConnection()
    item = {
        "path": "src/example.py",
        "file_sha256": "a" * 64,
        "start_line": 1,
        "end_line": 1,
        "text": "source snippet",
    }

    with caplog.at_level("DEBUG", logger="local_ai_hub.evidence"):
        result = store.put_many(str(tmp_path), [item])

    assert result == [item]
    messages = [record.getMessage() for record in caplog.records]
    assert any("Evidence batch persistence skipped (OperationalError)" in message for message in messages)
    assert all(str(tmp_path) not in message for message in messages)


def test_get_does_not_return_database_error_details(tmp_path):
    store = EvidenceStore(tmp_path / "evidence")

    class FailingConnection:
        @staticmethod
        def execute(*_args, **_kwargs):
            raise sqlite3.OperationalError(f"database locked at {tmp_path}")

        @staticmethod
        def close():
            return None

    store._connect = lambda: FailingConnection()

    result = store.get("evidence-id")

    assert result == {"success": False, "error": "evidence store unavailable"}
    assert str(tmp_path) not in repr(result)
