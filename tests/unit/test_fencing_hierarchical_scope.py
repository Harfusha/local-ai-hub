from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.work_fencing import (
    FencingLeaseStore,
    LeaseScopeError,
)


def test_directory_lease_covers_child_file_in_assert_current(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    store = FencingLeaseStore(tmp_path / "fences.sqlite3")

    attempt = store.claim_attempt(str(root), "work-dir", "writer-1", ttl_seconds=60)
    lease = store.acquire(str(root), "writer-1", ["src/models"], ttl_seconds=60, attempt=attempt)

    # A write to a child file inside the leased directory must be accepted
    store.assert_current(lease, ["src/models/user.py"])


def test_directory_lease_covers_deeply_nested_file_in_commit_guard(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target_dir = root / "src" / "a" / "b"
    target_dir.mkdir(parents=True)
    target_file = target_dir / "deep.py"

    store = FencingLeaseStore(tmp_path / "fences.sqlite3")
    attempt = store.claim_attempt(str(root), "work-deep", "writer-2", ttl_seconds=60)
    lease = store.acquire(str(root), "writer-2", ["src"], ttl_seconds=60, attempt=attempt)

    with store.commit_guard(lease, ["src/a/b/deep.py"]):
        target_file.write_text("ok\n", encoding="utf-8")

    assert target_file.read_text(encoding="utf-8") == "ok\n"


def test_directory_lease_rejects_unrelated_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    store = FencingLeaseStore(tmp_path / "fences.sqlite3")

    attempt = store.claim_attempt(str(root), "work-unrelated", "writer-3", ttl_seconds=60)
    lease = store.acquire(str(root), "writer-3", ["src/models"], ttl_seconds=60, attempt=attempt)

    with pytest.raises(LeaseScopeError, match="write escaped fenced lease scope"):
        store.assert_current(lease, ["src/views/index.py"])


def test_directory_lease_rejects_prefix_sibling(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    store = FencingLeaseStore(tmp_path / "fences.sqlite3")

    attempt = store.claim_attempt(str(root), "work-sibling", "writer-4", ttl_seconds=60)
    # Leased "src/model"
    lease = store.acquire(str(root), "writer-4", ["src/model"], ttl_seconds=60, attempt=attempt)

    # "src/models/user.py" shares prefix but is in a different directory ("src/models" vs "src/model")
    with pytest.raises(LeaseScopeError, match="write escaped fenced lease scope"):
        store.assert_current(lease, ["src/models/user.py"])
