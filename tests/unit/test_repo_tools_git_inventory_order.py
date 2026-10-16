import shutil
import subprocess

import pytest

import local_ai_hub.repo_tools as repo_tools
from local_ai_hub.repo_tools import _BoundedSortedPaths
from local_ai_hub.repo_tools import RepositoryTools


def test_bounded_git_inventory_sorts_and_deduplicates_within_limit():
    inventory = _BoundedSortedPaths(3)
    for path in ("z.py", "b.py", "a.py", "b.py"):
        inventory.add(path)

    assert inventory.finish() == (["a.py", "b.py", "z.py"], True)


def test_bounded_git_inventory_keeps_lexically_first_paths_and_marks_incomplete():
    inventory = _BoundedSortedPaths(3)
    for path in ("z.py", "d.py", "b.py", "a.py", "b.py"):
        inventory.add(path)

    assert inventory.finish() == (["a.py", "b.py", "d.py"], False)


def test_bounded_git_inventory_zero_limit_reports_eligible_paths():
    inventory = _BoundedSortedPaths(0)
    inventory.add("a.py")

    assert inventory.finish() == ([], False)


def test_git_inventory_sorts_tracked_and_untracked_paths_with_bounded_result(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("Git is required for the Git inventory integration test")

    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, timeout=10)
    (root / "z-tracked.txt").write_text("tracked", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "add", "--", "z-tracked.txt"],
        check=True,
        timeout=10,
    )
    (root / "a-untracked.txt").write_text("untracked", encoding="utf-8")

    inventory = RepositoryTools({})._git_files(root, max_files=1)

    assert inventory is not None
    assert [path.name for path in inventory] == ["a-untracked.txt"]
    assert inventory.complete is False


@pytest.mark.parametrize(
    ("cap_name", "cap_value"),
    [("MAX_EXACT_GIT_PATHS", 1), ("MAX_EXACT_GIT_PATH_BYTES", 1)],
)
def test_git_inventory_marks_scan_caps_incomplete(tmp_path, monkeypatch, cap_name, cap_value):
    if shutil.which("git") is None:
        pytest.skip("Git is required for the Git inventory integration test")

    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, timeout=10)
    (root / "z-tracked.txt").write_text("tracked", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "add", "--", "z-tracked.txt"],
        check=True,
        timeout=10,
    )
    (root / "a-untracked.txt").write_text("untracked", encoding="utf-8")
    monkeypatch.setattr(repo_tools, cap_name, cap_value)

    inventory = RepositoryTools({})._git_files(root, max_files=5)

    assert inventory is not None
    assert len(inventory) <= 1
    assert inventory.complete is False
