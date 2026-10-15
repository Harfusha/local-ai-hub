from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from local_ai_hub.work_fencing import (
    FencingLeaseStore,
    LeaseUnavailableError,
    WorkAttemptFence,
    canonical_resource,
    normalize_paths,
)


class _NoAccessStore(FencingLeaseStore):
    def __init__(self) -> None:
        self.clock_calls = 0
        self.connect_calls = 0
        self._clock = self._unexpected_clock

    def _unexpected_clock(self) -> float:
        self.clock_calls += 1
        raise AssertionError("invalid input reached the clock")

    def _connect(self) -> sqlite3.Connection:
        self.connect_calls += 1
        raise AssertionError("invalid input reached the store")


@pytest.mark.parametrize("value", [None, [], 7])
def test_claim_attempt_rejects_non_string_authority_before_store(value: object) -> None:
    store = _NoAccessStore()

    with pytest.raises(ValueError):
        store.claim_attempt("repo", value, "writer", ttl_seconds=60)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        store.claim_attempt("repo", "work", value, ttl_seconds=60)  # type: ignore[arg-type]

    assert store.clock_calls == 0
    assert store.connect_calls == 0


@pytest.mark.parametrize("coordination_id", [None, [], 7])
def test_claim_attempt_rejects_coercive_coordination_id_before_store(
    coordination_id: object,
) -> None:
    store = _NoAccessStore()

    with pytest.raises(ValueError):
        store.claim_attempt(
            "repo",
            "work",
            "writer",
            ttl_seconds=60,
            coordination_id=coordination_id,  # type: ignore[arg-type]
        )

    assert store.clock_calls == 0
    assert store.connect_calls == 0


@pytest.mark.parametrize(
    ("owner", "paths"),
    [([], ["src/a.py"]), ("writer", "src/a.py"), ("writer", [None]),
     ("writer", {"src/a.py": True}), ("writer", {"src/a.py"})],
)
def test_acquire_rejects_coercive_owner_or_paths_before_store(
    owner: object, paths: object
) -> None:
    store = _NoAccessStore()

    with pytest.raises(ValueError):
        store.acquire(
            object(),  # type: ignore[arg-type]
            owner,  # type: ignore[arg-type]
            paths,  # type: ignore[arg-type]
            ttl_seconds=60,
            attempt=None,  # type: ignore[arg-type]
        )

    assert store.clock_calls == 0
    assert store.connect_calls == 0


def test_normalize_paths_preserves_valid_relative_paths_and_rejects_string() -> None:
    assert normalize_paths(("src/a.py", "src/b.py")) == ("src/a.py", "src/b.py")
    with pytest.raises(ValueError, match="sequence of exact paths"):
        normalize_paths("src/a.py")  # type: ignore[arg-type]


class _CorruptLiveLeaseStore(FencingLeaseStore):
    def __init__(self, root: str, now: float = 100.0) -> None:
        self.root = root
        self._clock = lambda: now

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(":memory:", isolation_level=None)
        con.executescript(
            """
            CREATE TABLE writer_fence_attempts (
                attempt_id TEXT, resource TEXT, scope_id TEXT, work_id TEXT,
                owner_id TEXT, fencing_token INTEGER, expires_at REAL, active INTEGER
            );
            CREATE TABLE writer_fence_leases (
                lease_id TEXT, resource TEXT, owner_id TEXT, fencing_token INTEGER,
                expires_at REAL, paths_json TEXT, attempt_id TEXT, attempt_token INTEGER,
                scope_id TEXT, active INTEGER
            );
            """
        )
        con.execute(
            "INSERT INTO writer_fence_attempts VALUES(?,?,?,?,?,?,?,1)",
            ("attempt", self.root, self.root, "work", "writer", 1, 500.0),
        )
        con.execute(
            "INSERT INTO writer_fence_leases VALUES(?,?,?,?,?,?,?,?,?,1)",
            ("bad-lease", self.root, "other", 2, 500.0, "{bad-json", "", 0, self.root),
        )
        return con


def test_acquire_fails_closed_on_corrupt_live_lease_paths() -> None:
    root = canonical_resource("repo")
    store = _CorruptLiveLeaseStore(root)
    attempt = WorkAttemptFence(root, "work", "attempt", "writer", 1, 500.0)

    with pytest.raises(LeaseUnavailableError, match="corrupt path scope"):
        store.acquire(root, "writer", ["src/a.py"], ttl_seconds=60, attempt=attempt)


def test_root_relative_path_containment_remains_valid(tmp_path: Path) -> None:
    assert normalize_paths(["src/a.py"], root=tmp_path) == ("src/a.py",)
