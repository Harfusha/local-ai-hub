import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from local_ai_hub.work_fencing import FencingLease, FencingLeaseStore, LeaseLostError, LeaseScopeError, WorkAttemptFence


def test_explicit_namespace_write_set_stale_owner_cannot_commit_after_sqlite_restart(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir()
    receipt = state / "old-owner.json"
    script = r"""
import json, pathlib, sys
from dataclasses import asdict
from local_ai_hub.work_fencing import FencingLease, FencingLeaseStore, LeaseLostError, LeaseScopeError, WorkAttemptFence
mode, root_s, state_s, receipt_s = sys.argv[1:]
root, state, receipt = pathlib.Path(root_s), pathlib.Path(state_s), pathlib.Path(receipt_s)
db = state / "work_fencing.sqlite3"
namespace = "team-shared"
if mode == "old":
    store = FencingLeaseStore(db, clock=lambda: 100.0)
    attempt = store.claim_attempt(root, "write-set-work", "old", ttl_seconds=5, coordination_id=namespace)
    lease = store.acquire(root, "old", ["src/owned.txt"], ttl_seconds=30, attempt=attempt, coordination_id=namespace)
    receipt.write_text(json.dumps({"attempt": asdict(attempt), "lease": {**asdict(lease), "paths": list(lease.paths)}}), encoding="utf-8")
elif mode == "successor":
    store = FencingLeaseStore(db, clock=lambda: 106.0)
    old = json.loads(receipt.read_text(encoding="utf-8"))
    attempt = store.claim_attempt(root, "write-set-work", "new", ttl_seconds=30, coordination_id=namespace)
    lease = store.acquire(root, "new", ["src/owned.txt"], ttl_seconds=30, attempt=attempt, coordination_id=namespace)
    outside_rejected = False
    try:
        with store.commit_guard(lease, ["src/owned.txt", "src/outside.txt"]):
            (root / "src/outside.txt").write_text("escape", encoding="utf-8")
    except LeaseScopeError:
        outside_rejected = True
    with store.commit_guard(lease, ["src/owned.txt"]):
        (root / "src/owned.txt").write_text("successor\n", encoding="utf-8")
        (root / "commit-receipt.json").write_text(json.dumps({"owner": "new", "token": attempt.fencing_token}), encoding="utf-8")
    proof = {"attempt_scope": attempt.scope_id, "lease_scope": lease.scope_id, "attempt_token": attempt.fencing_token, "path_token": lease.fencing_token, "outside_rejected": outside_rejected}
    (state / "successor.json").write_text(json.dumps(proof), encoding="utf-8")
    print(json.dumps(proof))
elif mode == "stale":
    store = FencingLeaseStore(db, clock=lambda: 106.0)
    old = json.loads(receipt.read_text(encoding="utf-8"))
    attempt = WorkAttemptFence(**old["attempt"])
    lease_data = dict(old["lease"]); lease_data["paths"] = tuple(lease_data["paths"]); lease = FencingLease(**lease_data)
    attempt_rejected = commit_rejected = False
    try:
        store.assert_attempt_current(attempt)
    except LeaseLostError:
        attempt_rejected = True
    try:
        with store.commit_guard(lease, ["src/owned.txt"]):
            (root / "src/owned.txt").write_text("stale\n", encoding="utf-8")
            (root / "commit-receipt.json").write_text("stale commit", encoding="utf-8")
    except LeaseLostError:
        commit_rejected = True
    proof = {"attempt_scope": attempt.scope_id, "lease_scope": lease.scope_id, "attempt_token": attempt.fencing_token, "path_token": lease.fencing_token, "attempt_rejected": attempt_rejected, "commit_rejected": commit_rejected, "file": (root / "src/owned.txt").read_text(encoding="utf-8"), "commit": json.loads((root / "commit-receipt.json").read_text(encoding="utf-8"))}
    print(json.dumps(proof))
else:
    raise ValueError(mode)
"""
    project_root = Path(__file__).resolve().parents[1]
    def run(mode: str) -> dict:
        result = subprocess.run([sys.executable, "-B", "-c", script, mode, str(root), str(state), str(receipt)], cwd=project_root, capture_output=True, text=True, timeout=15, check=True)
        return json.loads(result.stdout) if result.stdout.strip() else {}
    run("old")
    successor = run("successor")
    stale = run("stale")
    assert successor["attempt_scope"] == successor["lease_scope"] == "project:team-shared"
    assert successor["outside_rejected"] is True
    assert stale["attempt_scope"] == stale["lease_scope"] == "project:team-shared"
    assert successor["attempt_token"] > stale["attempt_token"]
    assert successor["path_token"] > stale["path_token"]
    assert stale["attempt_rejected"] and stale["commit_rejected"]
    assert stale["file"] == "successor\n"
    assert stale["commit"] == {"owner": "new", "token": successor["attempt_token"]}
    assert not (root / "src/outside.txt").exists()
