from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.split_changes import run_split_changes


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def _plan(root: Path, paths=None, cache=None):
    return run_split_changes(
        SimpleNamespace(_root=lambda value: value, git_status_timeout=10, _change_summary_cache=cache),
        str(root), paths, path_type=Path, subprocess_module=subprocess,
        hidden_run_kwargs_fn=lambda: {},
    )


def _repo(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "tests").mkdir()
    for path in ("payment.py", "tests/test_payment.py", "cache.py"):
        (root / path).write_text("original\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")


def test_component_groups_and_index_preservation(tmp_path):
    _repo(tmp_path)
    (tmp_path / "payment.py").write_text("staged\n", encoding="utf-8")
    _git(tmp_path, "add", "payment.py")
    (tmp_path / "payment.py").write_text("unstaged\n", encoding="utf-8")
    (tmp_path / "tests/test_payment.py").write_text("test changed\n", encoding="utf-8")
    (tmp_path / "cache.py").write_text("cache changed\n", encoding="utf-8")
    (tmp_path / "new file.py").write_text("new\n", encoding="utf-8")
    before = _git(tmp_path, "diff", "--cached", "--binary")
    result = _plan(tmp_path)
    assert result["success"]
    assert result["total_files"] == 4
    assert result["cluster_count"] == 3
    payment = next(g for g in result["clusters"] if "payment.py" in g["files"])
    assert payment["files"] == ["payment.py", "tests/test_payment.py"]
    assert "mixed_staged_unstaged" in payment["risks"]
    assert payment["changes"][0]["staged_lines"] == [1, 1]
    assert payment["changes"][0]["unstaged_lines"] == [1, 1]
    assert result["commit_ready"] is False
    assert _git(tmp_path, "diff", "--cached", "--binary") == before
    assert _plan(tmp_path)["clusters"] == result["clusters"]


def test_clean_invalid_and_scoped(tmp_path):
    assert not _plan(tmp_path)["success"]
    _repo(tmp_path)
    assert _plan(tmp_path)["clusters"] == []
    (tmp_path / "cache.py").write_text("changed\n", encoding="utf-8")
    assert _plan(tmp_path, ["cache.py"])["total_files"] == 1
    assert not _plan(tmp_path, ["missing.py"])["success"]


def test_ambiguous_test_stays_separate(tmp_path):
    _repo(tmp_path)
    (tmp_path / "other").mkdir()
    (tmp_path / "other/payment.py").write_text("original\n", encoding="utf-8")
    _git(tmp_path, "add", "other/payment.py")
    _git(tmp_path, "commit", "-m", "second")
    for path in ("payment.py", "other/payment.py", "tests/test_payment.py"):
        (tmp_path / path).write_text("changed\n", encoding="utf-8")
    assert _plan(tmp_path)["cluster_count"] == 3


def test_content_identity_changes_with_same_line_counts(tmp_path):
    _repo(tmp_path)
    path = tmp_path / "payment.py"
    path.write_text("first\n", encoding="utf-8")
    first = _plan(tmp_path)
    second = _plan(tmp_path)
    assert second["summary_cache_hits"] >= 1
    assert first["observed_change_set_id"] == second["observed_change_set_id"]
    group = first["clusters"][0]
    assert group["observed_hunk_count"] == 1
    path.write_text("other\n", encoding="utf-8")
    third = _plan(tmp_path)
    assert third["observed_change_set_id"] != first["observed_change_set_id"]
    assert third["clusters"][0]["group_key"] == group["group_key"]
    assert third["clusters"][0]["line_totals"] == group["line_totals"]
    assert third["verification_status"] == "unknown"


def test_patch_scopes_and_partial_coverage(tmp_path):
    _repo(tmp_path)
    path = tmp_path / "payment.py"
    path.write_text("first\n", encoding="utf-8")
    _git(tmp_path, "add", "payment.py")
    path.write_text("other\n", encoding="utf-8")
    (tmp_path / "new.py").write_text("private content\n", encoding="utf-8")
    result = _plan(tmp_path)
    assert not result["patch_coverage_complete"]
    group = next(g for g in result["clusters"] if "payment.py" in g["files"])
    atoms = group["changes"][0]["atoms"]
    assert {a["scope"] for a in atoms} == {"staged", "unstaged"}
    assert len({a["atom_id"] for a in atoms}) == 2
    assert "private content" not in str(result)
    assert "first" not in str(atoms)


def test_persistent_metadata_cache_survives_memory_eviction(tmp_path):
    from local_ai_hub.cache import SQLiteCache
    from local_ai_hub.change_atoms import _CACHE, _LOCK

    root = tmp_path / "repo"
    root.mkdir()
    _repo(root)
    (root / "payment.py").write_text("private new value\n", encoding="utf-8")
    cache_path = tmp_path / "cache.sqlite"
    first = _plan(root, cache=SQLiteCache(cache_path, "test-hunk-cache"))
    assert first["persistent_summary_cache_hits"] == 0
    with _LOCK:
        _CACHE.clear()
    second = _plan(root, cache=SQLiteCache(cache_path, "test-hunk-cache"))
    assert second["persistent_summary_cache_hits"] == 1
    assert first["clusters"] == second["clusters"]
    assert b"private new value" not in cache_path.read_bytes()


def test_unchanged_hunk_id_survives_unrelated_edit(tmp_path):
    _repo(tmp_path)
    path = tmp_path / "payment.py"
    original = [f"line {i}" for i in range(20)]
    path.write_text("\n".join(original) + "\n", encoding="utf-8")
    _git(tmp_path, "add", "payment.py")
    _git(tmp_path, "commit", "-m", "multi-line fixture")
    modified = original.copy()
    modified[2] = "first change"
    modified[17] = "second change"
    path.write_text("\n".join(modified) + "\n", encoding="utf-8")
    first = _plan(tmp_path)["clusters"][0]["changes"][0]["atoms"][0]
    modified[17] = "other change"
    path.write_text("\n".join(modified) + "\n", encoding="utf-8")
    second = _plan(tmp_path)["clusters"][0]["changes"][0]["atoms"][0]
    assert first["atom_id"] != second["atom_id"]
    assert first["hunks"][0]["hunk_id"] == second["hunks"][0]["hunk_id"]
    assert first["hunks"][1]["hunk_id"] != second["hunks"][1]["hunk_id"]


def test_malformed_persistent_cache_is_recomputed(tmp_path):
    from local_ai_hub.change_atoms import _CACHE, _LOCK

    class InvalidCache:
        def get(self, key):
            return {"schema": 2, "rows": [[1, 1, 1, 1, "invalid"]], "count": 1}

        def set(self, key, value):
            assert value["schema"] == 2

    _repo(tmp_path)
    (tmp_path / "payment.py").write_text("different\n", encoding="utf-8")
    with _LOCK:
        _CACHE.clear()
    result = _plan(tmp_path, cache=InvalidCache())
    assert result["success"]
    assert result["persistent_summary_cache_hits"] == 0
    assert result["clusters"][0]["observed_hunk_count"] == 1


def test_staged_python_ast_summary_is_structural_not_verification(tmp_path):
    _repo(tmp_path)
    path = tmp_path / "payment.py"
    path.write_text("def pay():\n    return 1\n", encoding="utf-8")
    _git(tmp_path, "add", "payment.py")
    _git(tmp_path, "commit", "-m", "python fixture")
    path.write_text("def pay():\n    return 2\n\ndef refund():\n    return 0\n", encoding="utf-8")
    _git(tmp_path, "add", "payment.py")
    result = _plan(tmp_path)
    group = result["clusters"][0]
    semantic = group["changes"][0]["atoms"][0]["semantic"]
    assert semantic["status"] == "observed"
    assert semantic["change_counts"] == {"modified": 1, "added": 1}
    assert group["semantic_change_counts"] == semantic["change_counts"]
    assert not semantic["behavior_equivalence_proven"]
    assert result["verification_status"] == "unknown"
