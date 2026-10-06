from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from local_ai_hub.process_utils import run_hidden


def _linked_worktrees(parent: Path, name: str) -> tuple[Path, Path]:
    primary = parent / name / "primary"
    linked = parent / name / "linked"
    (primary / "src").mkdir(parents=True)
    (primary / "src" / "owned.txt").write_text("baseline\n", encoding="utf-8")
    (primary / ".local-ai.toml").write_text('shared_namespace = "team"\n', encoding="utf-8")
    run_hidden(["git", "init", "--quiet", str(primary)], check=True, capture_output=True, text=True, timeout=10)
    run_hidden(["git", "-C", str(primary), "add", ".local-ai.toml", "src/owned.txt"], check=True, capture_output=True, text=True, timeout=10)
    run_hidden(
        ["git", "-C", str(primary), "-c", "user.name=Lease Fixture", "-c", "user.email=lease-fixture@example.invalid", "commit", "--quiet", "-m", "lease fixture"],
        check=True, capture_output=True, text=True, timeout=10,
    )
    run_hidden(
        ["git", "-C", str(primary), "worktree", "add", "--quiet", "-b", "linked", str(linked)],
        check=True, capture_output=True, text=True, timeout=10,
    )
    return primary, linked


_CHILD = r"""
import json, sys
from dataclasses import asdict
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "src"))
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.project_config import resolve_project_context
from local_ai_hub.work_fencing import FencingLease, FencingLeaseStore, LeaseLostError, normalize_paths
mode, root_s, state_s, receipt_s = sys.argv[1:]
root, state, receipt = Path(root_s), Path(state_s), Path(receipt_s)
coordination_id = resolve_project_context(root, state).coordination_id
if not coordination_id:
    raise AssertionError("server-derived coordination identity missing")
scopes = ScopeLeaseStore(state)
if mode in {"claim", "busy", "independent", "reclaim"}:
    owner = {"claim": "owner-a", "busy": "owner-b", "independent": "owner-c", "reclaim": "owner-b"}[mode]
    claim = scopes.claim(owner, str(root), ["src/owned.txt"], ttl_seconds=90, coordination_id=coordination_id)
    if mode == "busy":
        print(json.dumps({"coordination_id": coordination_id, "claim": claim}))
        raise SystemExit(0)
    if not claim.get("success"):
        raise AssertionError(f"{mode} lease claim failed: {claim}")
    result = {"coordination_id": coordination_id, "claim": claim}
    if mode in {"claim", "reclaim"}:
        now = 100.0 if mode == "claim" else 106.0
        fences = FencingLeaseStore(state / "work_fencing.sqlite3", clock=lambda: now)
        attempt = fences.claim_attempt(root, "shared-work", owner, ttl_seconds=5 if mode == "claim" else 60, coordination_id=coordination_id)
        paths = normalize_paths(["src/owned.txt"], root=root)
        lease = fences.acquire(root, owner, paths, ttl_seconds=60, attempt=attempt, coordination_id=coordination_id)
        result.update({"attempt": asdict(attempt), "fence": {**asdict(lease), "paths": list(lease.paths)}})
        if mode == "reclaim":
            result["successor_lease_id"] = claim["lease_id"]
            with fences.commit_guard(lease, paths):
                (root / "src" / "owned.txt").write_text("successor write\n", encoding="utf-8")
                (root / "commit-receipt.json").write_text(json.dumps({"owner": owner, "token": attempt.fencing_token}), encoding="utf-8")
    receipt.write_text(json.dumps(result), encoding="utf-8")
    print(json.dumps(result))
elif mode == "refresh_release":
    previous = json.loads(receipt.read_text(encoding="utf-8"))
    lease_id = str(previous["claim"]["lease_id"])
    scopes = ScopeLeaseStore(state)
    renew = scopes.renew("owner-a", lease_id, ttl_seconds=120)
    release = scopes.release("owner-a", lease_id)
    print(json.dumps({"renew": renew, "release": release}))
elif mode == "stale":
    old = json.loads(receipt.read_text(encoding="utf-8"))
    fence_data = dict(old["fence"])
    fence_data["paths"] = tuple(fence_data["paths"])
    stale_fence = FencingLease(**fence_data)
    paths = normalize_paths(["src/owned.txt"], root=root)
    fences = FencingLeaseStore(state / "work_fencing.sqlite3", clock=lambda: 106.0)
    try:
        with fences.commit_guard(stale_fence, paths):
            (root / "src" / "owned.txt").write_text("stale owner write\n", encoding="utf-8")
            (root / "commit-receipt.json").write_text("stale owner commit", encoding="utf-8")
    except LeaseLostError:
        stale_rejected = True
    else:
        raise AssertionError("expired old owner committed a stale write")
    renew = scopes.renew("owner-a", str(old["successor_lease_id"]), ttl_seconds=120)
    release = scopes.release("owner-a", str(old["successor_lease_id"]))
    print(json.dumps({"stale_rejected": stale_rejected, "wrong_owner_renew": renew, "wrong_owner_release": release}))
else:
    raise AssertionError(f"unknown mode: {mode}")
"""


def _run_child(mode: str, root: Path, state: Path, receipt: Path) -> dict:
    result = run_hidden(
        [sys.executable, "-c", _CHILD, mode, str(root), str(state), str(receipt)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, f"{mode} process failed: {result.stderr}"
    return json.loads(result.stdout)


def test_two_process_linked_worktree_lease_expiry_reclaim_rejects_stale_commit(
    tmp_path: Path,
) -> None:
    worktree_a, worktree_b = _linked_worktrees(tmp_path, "process-linked")
    unrelated_c, _ = _linked_worktrees(tmp_path, "process-unrelated")
    state_dir = tmp_path / "shared-state"
    state_dir.mkdir()
    old_receipt = tmp_path / "old-owner.json"
    successor_receipt = tmp_path / "successor-owner.json"

    old = _run_child("claim", worktree_a, state_dir, old_receipt)
    blocked = _run_child("busy", worktree_b, state_dir, tmp_path / "blocked.json")
    isolated = _run_child("independent", unrelated_c, state_dir, tmp_path / "independent.json")
    assert old["coordination_id"] == blocked["coordination_id"]
    assert old["coordination_id"] != isolated["coordination_id"]
    assert old["claim"]["success"] is True
    assert blocked["claim"]["success"] is False
    assert blocked["claim"]["conflicts"]
    assert isolated["claim"]["success"] is True

    # Expire the persisted advisory lease deterministically; no wall-clock sleep.
    con = sqlite3.connect(state_dir / "leases.sqlite3")
    try:
        updated = con.execute(
            "UPDATE leases SET expires_at=0 WHERE lease_id=? AND tenant='owner-a'",
            (old["claim"]["lease_id"],),
        )
        assert updated.rowcount == 1
        con.commit()
    finally:
        con.close()

    successor = _run_child("reclaim", worktree_b, state_dir, successor_receipt)
    stale_receipt = tmp_path / "stale-with-successor.json"
    stale_receipt.write_text(
        json.dumps({"fence": old["fence"], "successor_lease_id": successor["claim"]["lease_id"]}),
        encoding="utf-8",
    )
    stale = _run_child("stale", worktree_a, state_dir, stale_receipt)

    assert successor["coordination_id"] == old["coordination_id"]
    assert successor["attempt"]["fencing_token"] > old["attempt"]["fencing_token"]
    assert successor["fence"]["fencing_token"] > old["fence"]["fencing_token"]
    assert successor["claim"]["success"] is True
    assert stale["stale_rejected"] is True
    assert stale["wrong_owner_renew"]["success"] is False
    assert stale["wrong_owner_release"]["released_rows"] == 0
    assert (worktree_a / "src" / "owned.txt").read_text(encoding="utf-8") == "baseline\n"
    assert not (worktree_a / "commit-receipt.json").exists()
    assert (worktree_b / "src" / "owned.txt").read_text(encoding="utf-8") == "successor write\n"
    assert json.loads((worktree_b / "commit-receipt.json").read_text(encoding="utf-8")) == {
        "owner": "owner-b", "token": successor["attempt"]["fencing_token"]
    }


def test_cross_process_lease_refresh_and_release_survive_sqlite_reopen(
    tmp_path: Path,
) -> None:
    root, _ = _linked_worktrees(tmp_path, "process-refresh-release")
    state_dir = tmp_path / "shared-refresh-state"
    state_dir.mkdir()
    receipt = tmp_path / "owner-lease.json"

    acquired = _run_child("claim", root, state_dir, receipt)
    assert acquired["claim"]["success"] is True

    refreshed = _run_child("refresh_release", root, state_dir, receipt)
    assert refreshed["renew"]["success"] is True
    assert refreshed["renew"]["expires_at"] > acquired["claim"]["expires_at"]
    assert refreshed["release"]["released_rows"] == 1

    successor = _run_child("busy", root, state_dir, tmp_path / "after-release.json")
    assert successor["claim"]["success"] is True
