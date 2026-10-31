from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from local_ai_hub.repo_plan.schema_validation import RepoPlanValidationError
from local_ai_hub.repo_plan.storage import RepoPlanStorage


def test_atomic_write_bytes_rejects_escaping_path() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir) / "repo"
        repo_root.mkdir()
        outside_dir = Path(tmpdir) / "outside"
        outside_dir.mkdir()
        storage = RepoPlanStorage(repo_root)

        with pytest.raises(RepoPlanValidationError, match="escapes repository root"):
            storage._atomic_write_bytes(outside_dir / "escaped.json", b"{}")


def test_request_replay_recovers_orphaned_pending_request() -> None:
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

        # Must clean up orphaned pending record and return None so operation can proceed
        assert storage._request_replay(key, payload_sha) is None
        # Subsequent save must succeed
        assert not storage._request_path(key).exists()
