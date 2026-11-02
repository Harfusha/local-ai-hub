from __future__ import annotations

import tempfile
import base64
import io
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
import pytest

from local_ai_hub.repo_plan.schema_validation import MAX_PLAN_FILE_BYTES, RepoPlanConflictError, RepoPlanError, RepoPlanValidationError
from local_ai_hub.repo_plan.storage import IntentTarget, OperationIntent, RepoPlanStorage, compute_bytes_sha256, compute_file_sha256


def test_recovery_guards_intents_directory_that_appears_after_initial_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = RepoPlanStorage(tmp_path)
    storage.intents_dir.mkdir(parents=True)
    original_exists = Path.exists
    original_lock = storage._lock_storage
    first = True

    def appeared(path: Path) -> bool:
        nonlocal first
        if path == storage.intents_dir and first:
            first = False
            return False
        return original_exists(path)

    @contextmanager
    def guarded_lock():
        assert storage._storage_path_guard.active
        with original_lock():
            yield

    monkeypatch.setattr(Path, "exists", appeared)
    monkeypatch.setattr(storage, "_lock_storage", guarded_lock)
    assert storage.recover_pending_intents() == []
    assert not first


def test_atomic_write_bytes_rejects_escaping_path() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir) / "repo"
        repo_root.mkdir()
        outside_dir = Path(tmpdir) / "outside"
        outside_dir.mkdir()
        storage = RepoPlanStorage(repo_root)

        with pytest.raises(RepoPlanValidationError, match="escapes repository root"):
            storage._atomic_write_bytes(outside_dir / "escaped.json", b"{}")


def test_read_plan_bounds_bytes_before_rejecting_oversized_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = tmp_path / "large.plan.json"
    plan.write_bytes(b"{}")
    reads: list[int] = []
    original_open = Path.open

    class ObservedStream(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            reads.append(size)
            return super().read(size)

    def open_observed(path: Path, *args, **kwargs):
        if path == plan and args == ("rb",):
            return ObservedStream(b"x" * (MAX_PLAN_FILE_BYTES + 2))
        return original_open(path, *args, **kwargs)

    if os.name == "nt":
        monkeypatch.setattr(Path, "open", open_observed)
    else:
        def fdopen_observed(descriptor: int, *_args, **_kwargs):
            os.close(descriptor)
            return ObservedStream(b"x" * (MAX_PLAN_FILE_BYTES + 2))

        monkeypatch.setattr(os, "fdopen", fdopen_observed)
    with pytest.raises(RepoPlanValidationError, match="maximum size"):
        RepoPlanStorage(tmp_path).read_plan_file("large.plan.json")
    assert reads == [MAX_PLAN_FILE_BYTES + 1]


def test_read_record_bounds_bytes_even_if_file_grows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = tmp_path / "record.json"
    record.write_bytes(b"{}")
    limit = 12 * 1024 * 1024
    reads: list[int] = []

    class ObservedStream(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            reads.append(size)
            return super().read(size)

    def open_observed(descriptor: int, mode: str):
        assert mode == "rb"
        os.close(descriptor)
        return ObservedStream(b"x" * (limit + 2))

    monkeypatch.setattr(os, "fdopen", open_observed)
    with pytest.raises(RepoPlanError, match="12 MiB"):
        RepoPlanStorage(tmp_path)._read_record(record)
    assert reads == [limit + 1]


def test_hash_large_target_without_unbounded_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "large.md"
    payload = b"plan-data" * 300000
    target.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()

    def forbid_full_read(_path: Path) -> bytes:
        pytest.fail("target hashing must stream rather than read the entire file")

    monkeypatch.setattr(Path, "read_bytes", forbid_full_read)
    assert compute_file_sha256(target) == expected
    assert compute_file_sha256(tmp_path / "missing.md") == ""


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


def test_crash_after_key_reservation_cannot_retry_or_change_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = RepoPlanStorage(tmp_path)
    target = [("plan.md", b"new-content", None)]

    def fail_before_intent(_intent: OperationIntent) -> None:
        raise OSError("simulated crash after reservation")

    monkeypatch.setattr(storage, "_save_intent", fail_before_intent)
    with pytest.raises(OSError, match="simulated crash"):
        storage._save_targets("save_plan", target, "agent", "reserved-key", None)

    assert not (tmp_path / "plan.md").exists()
    assert storage._request_path("reserved-key").exists()
    assert list(storage.intents_dir.glob("*.intent.json")) == []
    with pytest.raises(RepoPlanConflictError, match="missing intent"):
        storage._save_targets("save_plan", target, "agent", "reserved-key", None)
    with pytest.raises(RepoPlanConflictError, match="different payload"):
        storage._save_targets("save_plan", [("plan.md", b"other", None)], "agent", "reserved-key", None)
