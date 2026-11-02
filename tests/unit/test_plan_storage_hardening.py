from __future__ import annotations

import tempfile
import base64
from pathlib import Path
import pytest

from local_ai_hub.repo_plan.schema_validation import RepoPlanConflictError, RepoPlanValidationError
from local_ai_hub.repo_plan.storage import IntentTarget, OperationIntent, RepoPlanStorage, compute_bytes_sha256


def test_atomic_write_bytes_rejects_escaping_path() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir) / "repo"
        repo_root.mkdir()
        outside_dir = Path(tmpdir) / "outside"
        outside_dir.mkdir()
        storage = RepoPlanStorage(repo_root)

        with pytest.raises(RepoPlanValidationError, match="escapes repository root"):
            storage._atomic_write_bytes(outside_dir / "escaped.json", b"{}")


def test_request_replay_preserves_pending_request_with_missing_intent() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir) / "repo"
        repo_root.mkdir()
        (repo_root / ".local-ai-hub").mkdir()
        storage = RepoPlanStorage(repo_root)
        storage._ensure_intents_dir()

        key = "idemp_test_orphan"
        payload_sha = "abc123payload"
        # Simulate orphaned pending request where intent was never created
        storage._save_request(key, {
            "payload_sha256": payload_sha,
            "status": "pending",
            "intent_id": "intent_non_existent",
        })

        with pytest.raises(RepoPlanConflictError, match="missing intent"):
            storage._request_replay(key, payload_sha)
        assert storage._request_path(key).exists()


def test_completion_cannot_replace_another_payload_or_intent(tmp_path: Path) -> None:
    storage = RepoPlanStorage(tmp_path)
    storage._ensure_intents_dir()
    key = "shared-key"
    intent = OperationIntent("intent_old", "save_plan", key, "payload_old", "agent", 1.0, "pending", [], result={"success": True})
    newer = {"payload_sha256": "payload_new", "status": "completed", "result": {"success": True, "intent_id": "intent_new"}}
    storage._save_request(key, newer)

    with pytest.raises(RepoPlanConflictError, match="different payload"):
        storage._complete_intent(intent)
    assert storage._read_record(storage._request_path(key)) == newer
    assert intent.status == "pending"


def test_recovery_does_not_publish_when_request_belongs_to_another_intent(tmp_path: Path) -> None:
    storage = RepoPlanStorage(tmp_path)
    storage._ensure_intents_dir()
    (tmp_path / "first.md").write_bytes(b"new-first")
    (tmp_path / "second.md").write_bytes(b"old-second")
    targets = [
        IntentTarget("first.md", compute_bytes_sha256(b"old-first"), compute_bytes_sha256(b"new-first"), candidate_base64=base64.b64encode(b"new-first").decode()),
        IntentTarget("second.md", compute_bytes_sha256(b"old-second"), compute_bytes_sha256(b"new-second"), candidate_base64=base64.b64encode(b"new-second").decode()),
    ]
    intent = OperationIntent("intent_old", "save_spec_and_plan", "shared-key", "old-payload", "agent", 1.0, "pending", targets, context=storage._context(), result={"success": True})
    storage._save_intent(intent)
    newer = {"payload_sha256": "new-payload", "status": "completed", "result": {"success": True}}
    storage._save_request("shared-key", newer)

    outcomes = storage.recover_pending_intents()

    assert outcomes[0]["resolution"] == "recovery_blocked"
    assert (tmp_path / "second.md").read_bytes() == b"old-second"
    assert storage._read_record(storage._request_path("shared-key")) == newer
