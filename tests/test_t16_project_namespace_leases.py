from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.work_fencing import (
    FencingLeaseStore,
    LeaseLostError,
    LeaseUnavailableError,
    canonical_resource,
    normalize_paths,
)
from local_ai_hub.process_utils import run_hidden
from local_ai_hub.project_config import resolve_project_context


def _linked_worktrees(parent: Path, name: str) -> tuple[Path, Path]:
    primary = parent / name / "primary"
    linked = parent / name / "linked"
    (primary / "src").mkdir(parents=True)
    (primary / "src" / "shared.py").write_text("baseline\n", encoding="utf-8")
    (primary / "src" / "owned.txt").write_text("baseline\n", encoding="utf-8")
    (primary / ".local-ai.toml").write_text('shared_namespace = "team"\n', encoding="utf-8")
    run_hidden(
        ["git", "init", "--quiet", str(primary)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    run_hidden(
        ["git", "-C", str(primary), "add", ".local-ai.toml", "src/shared.py", "src/owned.txt"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    run_hidden(
        [
            "git",
            "-C",
            str(primary),
            "-c",
            "user.name=Lease Fixture",
            "-c",
            "user.email=lease-fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "lease fixture",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    run_hidden(
        ["git", "-C", str(primary), "worktree", "add", "--quiet", "-b", "linked", str(linked)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return primary, linked


def _coordination_id(root: Path, state_dir: Path) -> str | None:
    return resolve_project_context(root, state_dir).coordination_id


def test_linked_worktrees_conflict_on_same_relative_path_across_owners(
    tmp_path: Path,
) -> None:
    worktree_a, worktree_b = _linked_worktrees(tmp_path, "linked-project")
    store = ScopeLeaseStore(tmp_path / "state")
    coordination_id = _coordination_id(worktree_a, tmp_path / "project-state")
    assert coordination_id
    assert _coordination_id(worktree_b, tmp_path / "project-state") == coordination_id

    first = store.claim(owner="owner-a", root=str(worktree_a), paths=["src/shared.py"], coordination_id=coordination_id)
    second = store.claim(owner="owner-b", root=str(worktree_b), paths=["src/shared.py"], coordination_id=coordination_id)

    assert first["success"] is True
    assert second["success"] is False
    assert second.get("conflicts")
    assert [entry["lease_id"] for entry in store.list(coordination_id=coordination_id)] == [
        first["lease_id"]
    ]
    assert store.list(coordination_id=None) == []
    store.release(owner="owner-a", lease_id=str(first["lease_id"]))


def test_same_relative_alias_in_unrelated_git_common_dirs_does_not_conflict(
    tmp_path: Path,
) -> None:
    worktree_a, _ = _linked_worktrees(tmp_path, "repo-a")
    worktree_b, _ = _linked_worktrees(tmp_path, "repo-b")
    store = ScopeLeaseStore(tmp_path / "state")

    first = store.claim(owner="owner-a", root=str(worktree_a), paths=["src/shared.py"], coordination_id=_coordination_id(worktree_a, tmp_path / "project-state"))
    second = store.claim(owner="owner-b", root=str(worktree_b), paths=["src/shared.py"], coordination_id=_coordination_id(worktree_b, tmp_path / "project-state"))

    assert first["success"] is True
    assert second["success"] is True
    store.release(owner="owner-a", lease_id=str(first["lease_id"]))
    store.release(owner="owner-b", lease_id=str(second["lease_id"]))

def test_local_namespace_override_splits_linked_worktree_lease_scope(
    tmp_path: Path,
) -> None:
    worktree_a, worktree_b = _linked_worktrees(tmp_path, "namespace-override")
    store = ScopeLeaseStore(tmp_path / "state")
    inherited_id = _coordination_id(worktree_a, tmp_path / "project-state")
    overridden_config = worktree_b / ".local-ai.worktree.toml"
    overridden_config.write_text('shared_namespace = "separate"\n', encoding="utf-8")
    overridden_id = _coordination_id(worktree_b, tmp_path / "project-state")
    assert inherited_id
    assert overridden_id
    assert inherited_id != overridden_id

    first = store.claim(owner="owner-a", root=str(worktree_a), paths=["src/shared.py"], coordination_id=inherited_id)
    second = store.claim(owner="owner-b", root=str(worktree_b), paths=["src/shared.py"], coordination_id=overridden_id)

    assert first["success"] is True
    assert second["success"] is True
    store.release(owner="owner-a", lease_id=str(first["lease_id"]))
    store.release(owner="owner-b", lease_id=str(second["lease_id"]))

    (worktree_a / ".local-ai.worktree.toml").write_text(
        'shared_namespace = "fence-override"\n', encoding="utf-8"
    )
    fencing_override_id = _coordination_id(worktree_a, tmp_path / "project-state")
    assert fencing_override_id
    assert fencing_override_id != inherited_id
    fences = FencingLeaseStore(tmp_path / "namespace-override" / "fencing.sqlite3")
    inherited_attempt = fences.claim_attempt(
        str(worktree_a),
        "override-work",
        "owner-a",
        ttl_seconds=30,
        coordination_id=inherited_id,
    )
    overridden_attempt = fences.claim_attempt(
        str(worktree_a),
        "override-work",
        "owner-b",
        ttl_seconds=30,
        coordination_id=fencing_override_id,
    )
    assert overridden_attempt.fencing_token > inherited_attempt.fencing_token


def test_missing_project_coordination_id_fails_closed(tmp_path: Path) -> None:
    physical_root, _ = _linked_worktrees(tmp_path, "invalid-config")
    (physical_root / ".local-ai.toml").write_text("shared_namespace = [\n", encoding="utf-8")
    assert _coordination_id(physical_root, tmp_path / "project-state") is None
    store = ScopeLeaseStore(tmp_path / "state")

    result = store.claim(owner="owner-a", root=str(physical_root), paths=["src/shared.py"], coordination_id=None)

    assert result["success"] is False
    assert "coordination" in str(result.get("error", "")).lower()


def test_namespace_bridge_preserves_legacy_active_leases_on_same_root(
    tmp_path: Path,
) -> None:
    physical_root, _ = _linked_worktrees(tmp_path, "legacy-lease")
    coordination_id = _coordination_id(physical_root, tmp_path / "project-state")
    assert coordination_id

    scopes = ScopeLeaseStore(tmp_path / "legacy-state")
    legacy = scopes.claim(owner="owner-a", root=str(physical_root), paths=["src/shared.py"])
    assert legacy["success"] is True
    namespaced = scopes.claim(owner="owner-b", root=str(physical_root), paths=["src/shared.py"], coordination_id=coordination_id)
    assert namespaced["success"] is False
    scopes.release(owner="owner-a", lease_id=str(legacy["lease_id"]))

    now = [100.0]
    fences = FencingLeaseStore(
        tmp_path / "legacy-state" / "fencing.sqlite3", clock=lambda: now[0]
    )
    attempt = fences.claim_attempt(
        str(physical_root), "legacy-work", "owner-a", ttl_seconds=30
    )
    fences.acquire(
        str(physical_root),
        "owner-a",
        ["src/shared.py"],
        ttl_seconds=30,
        attempt=attempt,
    )
    with pytest.raises(LeaseUnavailableError):
        fences.claim_attempt(
            str(physical_root),
            "legacy-work",
            "owner-b",
            ttl_seconds=30,
            coordination_id=coordination_id,
        )

    migrated_db = tmp_path / "pre-namespace.sqlite3"
    physical_id = canonical_resource(physical_root)
    connection = sqlite3.connect(migrated_db)
    try:
        connection.executescript(
            """
            CREATE TABLE writer_fence_counters (
                resource TEXT PRIMARY KEY, last_token INTEGER NOT NULL
            );
            CREATE TABLE writer_fence_leases (
                lease_id TEXT PRIMARY KEY, resource TEXT NOT NULL, owner_id TEXT NOT NULL,
                fencing_token INTEGER NOT NULL, expires_at REAL NOT NULL, paths_json TEXT NOT NULL,
                attempt_id TEXT NOT NULL DEFAULT '', attempt_token INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL
            );
            CREATE TABLE writer_fence_attempts (
                attempt_id TEXT PRIMARY KEY, resource TEXT NOT NULL, work_id TEXT NOT NULL,
                owner_id TEXT NOT NULL, fencing_token INTEGER NOT NULL, expires_at REAL NOT NULL,
                active INTEGER NOT NULL, UNIQUE(resource, work_id, fencing_token)
            );
            """
        )
        connection.execute(
            "INSERT INTO writer_fence_attempts VALUES(?,?,?,?,?,?,1)",
            ("pre-namespace-attempt", physical_id, "migrated-work", "owner-a", 7, 130.0),
        )
        connection.execute(
            "INSERT INTO writer_fence_leases VALUES(?,?,?,?,?,?,?,?,1)",
            (
                "pre-namespace-lease",
                physical_id,
                "owner-a",
                8,
                130.0,
                '["src/shared.py"]',
                "pre-namespace-attempt",
                7,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    migrated = FencingLeaseStore(migrated_db, clock=lambda: 100.0)
    migrated_connection = migrated._connect()
    try:
        legacy_scope = migrated_connection.execute(
            "SELECT scope_id FROM writer_fence_attempts WHERE attempt_id=?",
            ("pre-namespace-attempt",),
        ).fetchone()
        assert legacy_scope == (physical_id,)
    finally:
        migrated_connection.close()
    with pytest.raises(LeaseUnavailableError):
        migrated.claim_attempt(
            str(physical_root),
            "migrated-work",
            "owner-b",
            ttl_seconds=30,
            coordination_id=coordination_id,
        )


def test_shared_namespace_keeps_physical_root_containment(tmp_path: Path) -> None:
    physical_root = tmp_path / "worktree"
    physical_root.mkdir()
    store = ScopeLeaseStore(tmp_path / "state")

    with pytest.raises(ValueError, match="path|root|escape|unsafe"):
        store.claim(owner="owner-a", root=str(physical_root), paths=["../outside.txt"], coordination_id=_coordination_id(physical_root, tmp_path / "project-state"))


def test_fencing_write_and_commit_share_namespace_but_bind_physical_roots(
    tmp_path: Path,
) -> None:
    worktree_a, worktree_b = _linked_worktrees(tmp_path, "fenced-linked-project")
    target_a = worktree_a / "src" / "owned.txt"
    target_b = worktree_b / "src" / "owned.txt"
    target_a.parent.mkdir(parents=True, exist_ok=True)
    target_b.parent.mkdir(parents=True, exist_ok=True)
    target_a.write_text("old workspace", encoding="utf-8")
    target_b.write_text("successor workspace", encoding="utf-8")
    coordination_id = _coordination_id(worktree_a, tmp_path / "project-state")
    assert coordination_id
    assert _coordination_id(worktree_b, tmp_path / "project-state") == coordination_id
    now = [100.0]
    store = FencingLeaseStore(
        tmp_path / "state" / "fencing.sqlite3", clock=lambda: now[0]
    )
    work_id = "work-linked-worktree"
    relative_paths = normalize_paths(["src/owned.txt"], root=worktree_a)
    assert relative_paths == normalize_paths(["src/owned.txt"], root=worktree_b)
    with pytest.raises(ValueError):
        normalize_paths(["../outside.txt"], root=worktree_a)

    stale_attempt = store.claim_attempt(
        str(worktree_a),
        work_id,
        "owner-a",
        ttl_seconds=5,
        coordination_id=coordination_id,
    )
    stale_lease = store.acquire(
        str(worktree_a),
        "owner-a",
        relative_paths,
        ttl_seconds=30,
        attempt=stale_attempt,
        coordination_id=coordination_id,
    )

    now[0] = 106.0
    current_attempt = store.claim_attempt(
        str(worktree_b),
        work_id,
        "owner-b",
        ttl_seconds=30,
        coordination_id=coordination_id,
    )
    current_lease = store.acquire(
        str(worktree_b),
        "owner-b",
        relative_paths,
        ttl_seconds=30,
        attempt=current_attempt,
    )
    with store.commit_guard(current_lease, relative_paths):
        store.assert_current(current_lease, actual_paths=relative_paths)
        target_b.write_text("successor commit", encoding="utf-8")

    assert current_attempt.fencing_token > stale_attempt.fencing_token
    assert current_lease.fencing_token > stale_lease.fencing_token
    with pytest.raises(LeaseLostError):
        with store.commit_guard(stale_lease, relative_paths):
            target_a.write_text("stale commit", encoding="utf-8")
    assert target_a.read_text(encoding="utf-8") == "old workspace"
    assert target_b.read_text(encoding="utf-8") == "successor commit"


def test_linked_worktree_fencing_namespace_is_shared_across_real_processes(
    tmp_path: Path,
) -> None:
    worktree_a, worktree_b = _linked_worktrees(tmp_path, "subprocess-linked-project")
    state_dir = tmp_path / "process-state"
    script = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "src"))
from local_ai_hub.project_config import resolve_project_context
from local_ai_hub.work_fencing import FencingLeaseStore, normalize_paths
root, state, stamp, action = sys.argv[1:]
state = Path(state)
coordination_id = resolve_project_context(root, state).coordination_id
assert coordination_id
store = FencingLeaseStore(state / "fencing.sqlite3", clock=lambda: float(stamp))
paths = normalize_paths(["src/owned.txt"], root=root)
if action == "claim":
    attempt = store.claim_attempt(root, "linked-work", "owner-a", ttl_seconds=5, coordination_id=coordination_id)
    lease = store.acquire(root, "owner-a", paths, ttl_seconds=30, attempt=attempt, coordination_id=coordination_id)
    print(json.dumps({"coordination_id": coordination_id, "attempt": attempt.__dict__, "lease": lease.__dict__}))
elif action == "successor":
    attempt = store.claim_attempt(root, "linked-work", "owner-b", ttl_seconds=30, coordination_id=coordination_id)
    lease = store.acquire(root, "owner-b", paths, ttl_seconds=30, attempt=attempt, coordination_id=coordination_id)
    with store.commit_guard(lease, paths):
        Path(root, "src", "owned.txt").write_text("successor process commit", encoding="utf-8")
    print(json.dumps({"coordination_id": coordination_id, "attempt_token": attempt.fencing_token, "lease_token": lease.fencing_token}))
else:
    raw = json.loads(action)
    attempt = raw["attempt"]
    lease = raw["lease"]
    from local_ai_hub.work_fencing import FencingLease, WorkAttemptFence
    old_attempt = WorkAttemptFence(**attempt)
    old_lease = FencingLease(**{**lease, "paths": tuple(lease["paths"])})
    try:
        with store.commit_guard(old_lease, paths):
            Path(root, "src", "owned.txt").write_text("stale process commit", encoding="utf-8")
    except Exception as exc:
        from local_ai_hub.work_fencing import LeaseLostError
        if not isinstance(exc, LeaseLostError):
            raise
        print("stale-rejected")
    else:
        raise AssertionError("stale process commit unexpectedly succeeded")
"""
    first = run_hidden(
        [sys.executable, "-c", script, str(worktree_a), str(state_dir), "100", "claim"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert first.returncode == 0, f"namespace claim subprocess failed: {first.stderr}"
    stale = json.loads(first.stdout)
    second = run_hidden(
        [sys.executable, "-c", script, str(worktree_b), str(state_dir), "106", "successor"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert second.returncode == 0, f"namespace successor subprocess failed: {second.stderr}"
    successor = json.loads(second.stdout)
    assert successor["coordination_id"] == stale["coordination_id"]
    assert successor["attempt_token"] > stale["attempt"]["fencing_token"]
    last = run_hidden(
        [sys.executable, "-c", script, str(worktree_a), str(state_dir), "106", json.dumps(stale)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert last.returncode == 0, f"stale namespace subprocess failed: {last.stderr}"
    assert last.stdout.strip() == "stale-rejected"
    assert (worktree_a / "src" / "owned.txt").read_text(encoding="utf-8") == "baseline\n"
    assert (worktree_b / "src" / "owned.txt").read_text(encoding="utf-8") == "successor process commit"
