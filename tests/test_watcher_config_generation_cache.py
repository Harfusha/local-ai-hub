"""Tests for watcher config generation caching and Git subprocess elimination (T1 / F01)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.project_config import (
    invalidate_project_context_cache,
    resolve_project_context,
)
from local_ai_hub.repo_tools import RepositoryTools


class _Noop:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def _preprocessor(tmp_path: Path) -> ProjectPreprocessor:
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": False, "fs_watcher_enabled": False},
        "rag": {"extensions": [".py", ".js"]},
        "search": {"extensions": [".py", ".js"], "max_files": 100},
    }
    pre = ProjectPreprocessor(
        cfg, _Noop(), _Noop(), _Noop(), _Noop(), RepositoryTools(cfg)
    )
    pre.repo_tools.extensions = {".py", ".js"}
    return pre


def test_1000_unrecognized_events_do_not_spawn_git_processes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pre = _preprocessor(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print(1)\n", encoding="utf-8")

    git_calls = []
    real_run = subprocess.run

    def tracked_run(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args")
        if isinstance(cmd, (list, tuple)) and "git" in cmd:
            git_calls.append(cmd)
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", tracked_run)

    # Measure 1,000 unknown extension events
    started = time.perf_counter()
    for index in range(1000):
        fake_path = root / f"artifact_{index}.unknownext"
        assert pre._watch_relevant(root, fake_path) is None
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    # 1,000 rejected events must not invoke 1,000 Git processes (at most 1)
    assert len(git_calls) <= 1
    # Average per rejected event must be well under 0.5 ms
    avg_per_event_ms = elapsed_ms / 1000.0
    assert avg_per_event_ms < 0.5, f"Expected < 0.5 ms per rejected event, got {avg_per_event_ms:.3f} ms"


def test_config_edit_invalidates_cache_and_adopts_custom_extensions(tmp_path: Path):
    pre = _preprocessor(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()

    # Initial probe: .custom is not known
    custom_file = root / "report.custom"
    assert pre._watch_relevant(root, custom_file) is None

    # Write .local-ai.toml adding .custom to text_extensions
    config_file = root / ".local-ai.toml"
    config_file.write_text('[custom_extensions]\ntext = [".custom"]\n', encoding="utf-8")

    # The config event itself must be accepted and invalidate the cache
    assert pre._watch_relevant(root, config_file) == ".local-ai.toml"

    # Now report.custom must be accepted
    assert pre._watch_relevant(root, custom_file) == "report.custom"


def test_binary_extensions_override_custom_text_extensions(tmp_path: Path):
    pre = _preprocessor(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()

    config_file = root / ".local-ai.toml"
    config_file.write_text(
        '[custom_extensions]\nbinary = [".custom"]\n',
        encoding="utf-8",
    )
    assert pre._watch_relevant(root, config_file) == ".local-ai.toml"

    custom_file = root / "report.custom"
    assert pre._watch_relevant(root, custom_file) is None


def test_deleted_and_moved_files_handled_without_disk_reads(tmp_path: Path):
    pre = _preprocessor(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()

    # File does not exist on disk (representing deletion or move)
    deleted_path = root / "src" / "removed.py"
    assert not deleted_path.exists()
    assert pre._watch_relevant(root, deleted_path) == "src/removed.py"


def test_out_of_tree_path_rejected(tmp_path: Path):
    pre = _preprocessor(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "other" / "leak.py"
    outside.parent.mkdir(parents=True)
    outside.write_text("code\n", encoding="utf-8")

    assert pre._watch_relevant(root, outside) is None


def test_resolve_project_context_caches_until_config_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".local-ai.toml").write_text('project_type = "python"\n', encoding="utf-8")

    invalidate_project_context_cache()

    ctx1 = resolve_project_context(root, state_dir)
    assert ctx1.settings.project_type == "python"

    # Monkeypatch _git_common_dir to ensure it is not called again while config is unchanged
    def fail_git(*args, **kwargs):
        raise AssertionError("resolve_project_context must reuse cached context when config is unchanged")

    monkeypatch.setattr("local_ai_hub.project_config._git_common_dir", fail_git)
    ctx2 = resolve_project_context(root, state_dir)
    assert ctx2 is ctx1

    # Now edit .local-ai.toml
    monkeypatch.undo()
    time.sleep(0.01)
    (root / ".local-ai.toml").write_text('project_type = "rust"\n', encoding="utf-8")

    ctx3 = resolve_project_context(root, state_dir)
    assert ctx3.settings.project_type == "rust"
