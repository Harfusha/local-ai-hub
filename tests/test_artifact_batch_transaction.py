from __future__ import annotations

from local_ai_hub import artifacts
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.sqlite_support import write_transaction


def test_artifact_schema_setup_uses_bounded_write_transaction(monkeypatch, tmp_path):
    observed: list[dict[str, object]] = []

    def record_transaction(connection, **kwargs):
        observed.append(kwargs)
        return write_transaction(connection, **kwargs)

    monkeypatch.setattr(artifacts, "write_transaction", record_transaction, raising=False)

    ArtifactStore(tmp_path)

    assert observed == [
        {"max_duration_seconds": 5.0, "rollback_label": "artifact schema initialization"}
    ]


def test_artifact_batch_uses_bounded_write_transaction(monkeypatch, tmp_path):
    store = ArtifactStore(tmp_path)
    observed: list[dict[str, object]] = []

    def record_transaction(connection, **kwargs):
        observed.append(kwargs)
        return write_transaction(connection, **kwargs)

    monkeypatch.setattr(artifacts, "write_transaction", record_transaction, raising=False)

    with store.batch() as batch:
        artifact_id = batch.put("bounded artifact", kind="test")

    assert artifact_id.startswith("art_")
    assert len(observed) == 1
    assert observed[0]["max_duration_seconds"] == 5.0
    assert observed[0]["rollback_label"] == "artifact batch"


def test_browser_capture_purge_uses_bounded_write_transaction(monkeypatch, tmp_path):
    store = ArtifactStore(tmp_path)
    with store.batch() as batch:
        child_id = batch.put("capture payload", kind="browser-dom")
        bundle_id = batch.put_json(
            {
                "source": "current-tab",
                "capture_id": "capture-1",
                "dom": {"artifact_id": child_id},
            },
            kind="frontend-review-bundle",
        )
    observed: list[dict[str, object]] = []

    def record_transaction(connection, **kwargs):
        observed.append(kwargs)
        return write_transaction(connection, **kwargs)

    monkeypatch.setattr(artifacts, "write_transaction", record_transaction, raising=False)

    result = store.purge_browser_capture(bundle_id)

    assert result["success"] is True
    assert result["deleted_count"] == 2
    assert len(observed) == 1
    assert observed[0]["max_duration_seconds"] == 5.0
    assert observed[0]["rollback_label"] == "artifact purge"
