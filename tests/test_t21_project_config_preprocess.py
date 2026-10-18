from __future__ import annotations

from contextlib import closing
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


class _Noop:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


class _Rag(_Noop):
    index_reset = False


class _Scheduler:
    def foreground_busy(self):
        return False


def _config(tmp_path: Path) -> dict:
    return {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": False, "fs_watcher_enabled": False},
        "search": {"extensions": [".py"], "max_files": 100},
    }


def _preprocessor(tmp_path: Path, config: dict | None = None) -> ProjectPreprocessor:
    cfg = config or _config(tmp_path)
    return ProjectPreprocessor(
        cfg, _Noop(), _Rag(), _Scheduler(), _Noop(), RepositoryTools(cfg)
    )


def _insert_project(pre: ProjectPreprocessor, root: Path, phase: str) -> None:
    with closing(pre._connect()) as con:
        con.execute(
            "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at) VALUES(?,?,?,?,?,?)",
            (str(root.resolve()), "test", "registered", phase, 0.0, 0.0),
        )
        con.commit()


def test_inventory_applies_project_exclusions_and_force_includes_ignored_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "build").mkdir()
    (root / "src" / "main.py").write_text("main = True\n", encoding="utf-8")
    (root / "src" / "private.py").write_text("private = True\n", encoding="utf-8")
    (root / "docs" / "guide.py").write_text("guide = True\n", encoding="utf-8")
    (root / "build" / "generated.py").write_text("generated = True\n", encoding="utf-8")
    (root / ".gitignore").write_text("build/generated.py\n", encoding="utf-8")
    (root / ".local-ai.toml").write_text(
        'exclude_paths = ["src/private.py", ".gitignore"]\n'
        'force_include_paths = ["build/generated.py"]\n'
        '[preprocess]\nexclude_paths = ["docs/**"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    pre = _preprocessor(tmp_path)
    try:
        _insert_project(pre, root, "inventory")

        assert pre._step_inventory({"root": str(root.resolve()), "generation": 0})

        with closing(pre._connect()) as con:
            paths = {
                str(row[0])
                for row in con.execute(
                    "SELECT path FROM file_refs WHERE root=?", (str(root.resolve()),)
                )
            }
        assert paths == {"src/main.py", "build/generated.py"}
    finally:
        pre.close()


@pytest.mark.parametrize(
    ("configured_skip", "stored_phase", "next_phase"),
    [
        ("rag", "rag", "files"),
        ("call_graph", "code_index", "deterministic"),
        ("modules", "modules", "project"),
    ],
)
def test_preprocessing_skips_configured_optional_phases(
    tmp_path: Path,
    configured_skip: str,
    stored_phase: str,
    next_phase: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai.toml").write_text(
        f'skip_phases = ["{configured_skip}"]\n', encoding="utf-8"
    )
    pre = _preprocessor(tmp_path)
    try:
        _insert_project(pre, root, stored_phase)

        assert pre._step(
            {"root": str(root.resolve()), "workspace": "test", "phase": stored_phase}
        )

        row = pre._project_row(str(root.resolve()))
        assert row is not None
        assert row["phase"] == next_phase
    finally:
        pre.close()


def test_inventory_rechecks_when_only_project_configuration_changes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("main = True\n", encoding="utf-8")
    config_path = root / ".local-ai.toml"
    config_path.write_text('skip_phases = ["modules"]\n', encoding="utf-8")
    pre = _preprocessor(tmp_path)
    try:
        _insert_project(pre, root, "inventory")
        pre._step_inventory({"root": str(root.resolve()), "generation": 0})
        initial = pre._project_row(str(root.resolve()))
        assert initial is not None
        first_generation = int(initial["generation"])
        with closing(pre._connect()) as con:
            con.execute(
                "UPDATE file_refs SET card_key='cached',rag_hash=content_hash WHERE root=?",
                (str(root.resolve()),),
            )
            con.execute(
                "UPDATE projects SET phase='inventory',status='complete',last_complete_at=1 WHERE root=?",
                (str(root.resolve()),),
            )
            con.commit()

        config_path.write_text('skip_phases = ["call_graph"]\n', encoding="utf-8")
        current = pre._project_row(str(root.resolve()))
        assert current is not None
        pre._step_inventory(dict(current))

        updated = pre._project_row(str(root.resolve()))
        assert updated is not None
        assert int(updated["generation"]) == first_generation + 1
        assert updated["phase"] == "hash"
    finally:
        pre.close()


def test_candidate_paths_filter_exclusions_and_prioritize_configured_entry_points(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "vendor").mkdir()
    for relative in ("src/a.py", "src/entry.py", "vendor/forced.py"):
        (root / relative).write_text("needle = True\n", encoding="utf-8")
    (root / ".local-ai.toml").write_text(
        'exclude_paths = ["src/a.py"]\n'
        'force_include_paths = ["vendor/forced.py"]\n'
        'entry_points = ["src/entry.py"]\n',
        encoding="utf-8",
    )
    pre = _preprocessor(tmp_path)
    try:
        pre.lookup = lambda *_args, **_kwargs: {
            "files": [
                {"path": "src/a.py"},
                {"path": "vendor/forced.py"},
                {"path": "src/entry.py"},
            ]
        }

        paths = pre.candidate_paths(str(root), "needle")

        assert paths == ["src/entry.py", "vendor/forced.py"]
    finally:
        pre.close()


def test_python_search_fallback_has_independent_file_cap_and_metric(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("needle = 1\n", encoding="utf-8")
    (root / "b.py").write_text("needle = 2\n", encoding="utf-8")
    cfg = _config(tmp_path)
    cfg["search"].update(
        {"python_fallback_max_files": 1, "ripgrep_timeout_seconds": 0.01}
    )
    tools = RepositoryTools(cfg)
    monkeypatch.setattr(tools, "_ripgrep_candidates", lambda *_args: (None, False))
    monkeypatch.setattr(tools, "_git_grep_candidates", lambda *_args: (None, False))

    result = tools.search(str(root), "needle")

    assert result["engine"] == "python"
    assert result["python_fallback_limit"] == 1
    assert result["python_fallback_scanned_files"] == 1
    assert result["python_fallback_truncated"] is True


@pytest.mark.parametrize(("candidate_count", "expected_truncated"), [(1, False), (2, True)])
def test_python_fallback_truncation_requires_omitted_candidate_sentinel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_count: int,
    expected_truncated: bool,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    candidates = []
    for index in range(candidate_count):
        path = root / f"{index}.py"
        path.write_text(f"needle = {index}\n", encoding="utf-8")
        candidates.append(path)
    cfg = _config(tmp_path)
    cfg["search"].update({"python_fallback_max_files": 1})
    tools = RepositoryTools(cfg)
    iterated = []

    def iter_files(_root: str, *, max_files: int | None = None):
        for candidate in candidates:
            iterated.append(candidate)
            yield candidate

    monkeypatch.setattr(tools, "iter_files", iter_files)
    monkeypatch.setattr(tools, "_ripgrep_candidates", lambda *_args: (None, False))
    monkeypatch.setattr(tools, "_git_grep_candidates", lambda *_args: (None, False))

    result = tools.search(str(root), "needle")

    assert result["python_fallback_scanned_files"] == 1
    assert result["python_fallback_truncated"] is expected_truncated
    assert len(iterated) == candidate_count


def test_watcher_skips_project_config_resolution_for_default_source_extensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pre = _preprocessor(tmp_path)
    pre.repo_tools.extensions = {".py"}
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    path = root / "src" / "current.py"
    path.write_text("value = 1\n", encoding="utf-8")

    def unexpected_config_resolution(_root: str):
        pytest.fail("default source extension should not resolve project config")

    monkeypatch.setattr(pre, "_project_config_context", unexpected_config_resolution)

    assert pre._watch_relevant(root, path) == "src/current.py"


def test_watcher_still_resolves_project_config_for_custom_text_extensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pre = _preprocessor(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    path = root / "notes.custom"
    path.write_text("content\n", encoding="utf-8")
    context = SimpleNamespace(
        settings=SimpleNamespace(
            text_extensions={".custom"}, language_overrides={}, binary_extensions=set()
        )
    )
    calls: list[str] = []
    monkeypatch.setattr(
        pre,
        "_project_config_context",
        lambda value: (calls.append(value) or object(), context),
    )

    assert pre._watch_relevant(root, path) == "notes.custom"
    assert calls == [str(root)]
