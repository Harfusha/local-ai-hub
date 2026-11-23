from __future__ import annotations

import subprocess
from pathlib import Path

from local_ai_hub.repo_state import RepoStateTracker


def test_changed_file_signature_reads_metadata_once(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    source = root / "changed.py"
    source.write_bytes(b"value = 1\n")
    stat = Path.stat
    expected = stat(source)
    calls = []

    def tracked_stat(path, *args, **kwargs):
        if path == source:
            calls.append(path)
        return stat(path, *args, **kwargs)

    # Isolate metadata reads from platform-specific work in path resolution.
    monkeypatch.setattr(Path, "resolve", lambda path, **_kwargs: path)
    monkeypatch.setattr(Path, "stat", tracked_stat)
    result = RepoStateTracker({})._path_signature(root, "changed.py")

    assert result == (expected.st_mtime_ns, expected.st_size, expected.st_ctime_ns, expected.st_ino)
    assert calls == [source]


def test_fingerprint_collapses_git_probes_and_detects_immediate_change(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)

    tracker = RepoStateTracker({"workspace_cache": {"fingerprint_ttl_seconds": 60.0}})
    original_run_git = tracker._run_git
    calls: list[tuple[str, ...]] = []

    def record_run_git(root, *args, timeout=8.0):
        calls.append(tuple(args))
        return original_run_git(root, *args, timeout=timeout)

    monkeypatch.setattr(tracker, "_run_git", record_run_git)
    baseline = tracker.fingerprint(str(repo), force=True)
    expected_status = ("status", "--porcelain=v2", "-z", "--untracked-files=normal", "--branch")
    assert calls == [expected_status]
    assert baseline["head"] == subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    assert baseline["dirty"] is False

    source.write_text("value = 2\n", encoding="utf-8")
    changed = tracker.fingerprint(str(repo), force=True)

    assert calls == [expected_status, expected_status]
    assert changed["dirty"] is True
    assert changed["changed_paths"] == ["app.py"]
    assert changed["fingerprint"] != baseline["fingerprint"]


def test_porcelain_v2_parser_keeps_rename_paths_and_unborn_identity() -> None:
    raw = (
        b"# branch.oid (initial)\0# branch.head (initial)\0"
        b"2 R. N... 100644 100644 100644 abc abc R100 new name.py\0old name.py\0"
        b"? loose file.txt\0"
    )

    head, status, changed = RepoStateTracker._parse_porcelain_v2(raw)

    assert head == ""
    assert status == (
        b"2 R. N... 100644 100644 100644 abc abc R100 new name.py\0"
        b"old name.py\0? loose file.txt\0"
    )
    assert changed == ["loose file.txt", "new name.py", "old name.py"]
