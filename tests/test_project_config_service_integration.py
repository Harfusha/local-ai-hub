from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import subprocess
from types import SimpleNamespace

import local_ai_hub.project_config as project_config
from local_ai_hub.cache import stable_hash
from local_ai_hub.project_config import PathHint, resolve_project_context
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices


def test_run_affected_applies_project_mapping_and_path_hints_safely(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    state_dir = tmp_path / "runtime"
    config_path = tmp_path / ".local-ai.toml"
    config_path.write_text(
        'entry_points = ["tests/entry.py"]\n'
        'exclude_paths = ["tests/secret/**"]\n'
        '[file_limits]\nmax_file_size_bytes = 5\n'
        '[affected_tests_mapping]\n"src/**" = ["tests/custom/**"]\n',
        encoding="utf-8",
    )
    files = (
        "tests/base.py",
        "tests/secret/excluded.py",
        "tests/requested/test_request.py",
        "tests/saved.py",
        "tests/entry.py",
        "tests/custom/test_mapped.py",
        "tests/large.py",
        "tests/odd; name.py",
    )
    for relative in files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("too-large" if relative.endswith("large.py") else "ok", encoding="utf-8")
    context = resolve_project_context(tmp_path, state_dir)
    context.save_path_hint(
        PathHint(
            path="tests/saved.py",
            purpose="affected_tests",
            scope="run_affected",
            evidence_id="evidence-1",
            provenance="verified_search",
            repository_revision="workspace-1",
            config_digest=context.config_digest,
        )
    )

    class Broker:
        command: str | None = None

        def run(self, command: str, *_args, **_kwargs) -> dict[str, object]:
            self.command = command
            return {"success": True}

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(state_dir)}}
    services.commands = Broker()
    services.agent_state = None
    services.preprocessor = None
    services.repo_state = None
    services._repo_cache_state = lambda _root: {
        "fingerprint": "workspace-1",
        "stale": False,
        "degraded": False,
    }
    services.deterministic = SimpleNamespace(
        affected_tests=lambda *_args: {
            "success": True,
            "framework": "pytest",
            "changed_files": ["src/changed.py"],
            "test_files": [
                "tests/base.py",
                "tests/secret/excluded.py",
                "tests/requested/test_request.py",
                "tests/saved.py",
                "tests/entry.py",
                "tests/large.py",
                "tests/odd; name.py",
            ],
            "suggested_command": "pytest tests/base.py",
            "confidence": 0.95,
        }
    )
    observed: dict[str, object] = {}

    def deterministic_operation(_operation, _root, params, compute):
        observed.update(params)
        return {
            **compute(),
            "workspace_cache": {"fingerprint": "workspace-1", "stale": False},
        }

    services.deterministic_operation = deterministic_operation
    services.test_matrix = lambda _root: {
        "test_files": [{"path": "tests/custom/test_mapped.py"}]
    }

    result = services.command(
        {
            "action": "run_affected",
            "cwd": str(tmp_path),
            "paths": ["src/changed.py"],
            "path_hints": [
                {
                    "path": "tests/requested",
                    "purpose": "affected_tests",
                    "scope": "run_affected",
                },
                {
                    "path": "tests/secret",
                    "purpose": "affected_tests",
                    "scope": "run_affected",
                },
            ],
        },
        tenant="test",
    )

    expected = [
        "tests/entry.py",
        "tests/secret/excluded.py",
        "tests/requested/test_request.py",
        "tests/saved.py",
        "tests/base.py",
        "tests/odd; name.py",
        "tests/custom/test_mapped.py",
        "tests/large.py",
    ]
    summary = result["affected_tests_summary"]
    assert summary["test_files"] == [
        path for path in expected if path not in {"tests/secret/excluded.py", "tests/large.py"}
    ]
    assert services.commands.command.startswith("pytest tests/entry.py ")
    assert services.commands.command.endswith("tests/custom/test_mapped.py")
    assert (
        "'tests/odd; name.py'" in services.commands.command
        or '"tests/odd; name.py"' in services.commands.command
    )
    assert summary["path_hint_usage"] == {
        "hint_used": True,
        "fallback_used": False,
        "hint_helped": None,
    }
    assert observed["project_config_digest"] == context.config_digest
    assert observed["path_hints_digest"] == stable_hash(
        [
            asdict(
                PathHint(
                    path="tests/requested",
                    purpose="affected_tests",
                    scope="run_affected",
                )
            ),
            asdict(
                PathHint(
                    path="tests/secret",
                    purpose="affected_tests",
                    scope="run_affected",
                )
            ),
        ]
    )
    assert "repository_revision" not in observed
    assert "tests/requested" not in repr(observed)


def test_repo_search_prioritizes_verified_project_path_hint_without_narrowing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    state_dir = tmp_path / "runtime"
    (tmp_path / "templates" / "element").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "templates" / "element" / "button.php").write_text(
        "button()", encoding="utf-8"
    )
    (tmp_path / "src" / "button.py").write_text("button()", encoding="utf-8")
    context = resolve_project_context(tmp_path, state_dir)
    context.save_path_hint(
        PathHint(
            path="templates/element",
            purpose="repository_search",
            scope="repo_search",
            evidence_id="verified-1",
            provenance="verified_search",
            repository_revision="workspace-1",
            config_digest=context.config_digest,
        )
    )
    class Flight:
        def get_or_compute(self, _key, compute):
            return compute(), False, False

    class Tools:
        observed_paths: list[str] = []
        ignore_dirs: set[str] = set()
        ignore_extensions: set[str] = set()
        extensions: set[str] = set()
        special_filenames: set[str] = set()
        max_file_bytes = 2_000_000

        def _git_files(self, _root):
            return [tmp_path / "templates" / "element" / "button.php"]

        def search(self, *_args, **_kwargs):
            return {"success": True, "results": []}

        def search_paths(self, _root, query, paths, top_k, context_lines=None):
            self.observed_paths = list(paths)
            return {"success": True, "results": [{"path": path} for path in paths[:top_k]]}

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(state_dir)}, "features": {}}
    services.repo_flight = Flight()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {
        "fingerprint": "workspace-1", "kind": "filesystem", "stale": False,
    }
    services.repo_tools = Tools()
    services.learner = None
    services.deterministic = SimpleNamespace(
        related_paths=lambda *_args: ["src/button.py"]
    )
    services.code_index = services.preprocessor = services.evidence_store = None

    result = services.repo_search(str(tmp_path), "button", top_k=10)

    assert services.repo_tools.observed_paths == [
        "templates/element/button.php", "src/button.py"
    ]
    assert {item["path"] for item in result["results"]} == {
        "templates/element/button.php", "src/button.py"
    }
    assert result["path_hint_usage"] == {
        "hint_used": True, "fallback_used": False, "hint_helped": None
    }


def test_repo_search_uses_explicit_request_hint_for_unindexed_file(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    state_dir = tmp_path / "runtime"
    hinted = tmp_path / "templates" / "element" / "button.php"
    hinted.parent.mkdir(parents=True)
    hinted.write_text("button()", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "--", "templates/element/button.php"],
        check=True,
    )

    class Flight:
        def get_or_compute(self, _key, compute):
            return compute(), False, False

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(state_dir)}, "features": {}}
    services.repo_flight = Flight()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {
        "fingerprint": "workspace-1", "kind": "filesystem", "stale": False,
    }
    services.repo_tools = RepositoryTools(
        {"server": {"state_dir": str(state_dir)}, "rag": {}, "search": {}}
    )
    services.learner = None
    services.deterministic = SimpleNamespace(related_paths=lambda *_args: [])
    services.code_index = services.preprocessor = services.evidence_store = None

    result = services.repo_search(
        str(tmp_path),
        "button",
        top_k=10,
        path_hints=[
            {
                "path": "templates/element/button.php",
                "purpose": "repository_search",
                "scope": "repo_search",
            }
        ],
    )

    assert [hit["path"] for hit in result["results"]] == [
        "templates/element/button.php"
    ]
    assert result["results"][0]["text"].find("button()") >= 0
    assert result["path_hint_usage"] == {
        "hint_used": True, "fallback_used": False, "hint_helped": None
    }


def test_repo_search_keeps_full_original_candidate_window_when_adding_hints(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    state_dir = tmp_path / "runtime"
    hinted_dir = tmp_path / "templates"
    hinted_dir.mkdir()
    (hinted_dir / "button.php").write_text("button", encoding="utf-8")
    context = resolve_project_context(tmp_path, state_dir)
    context.save_path_hint(
        PathHint(
            path="templates",
            purpose="repository_search",
            scope="repo_search",
            evidence_id="verified-2",
            provenance="verified_search",
            repository_revision="workspace-1",
            config_digest=context.config_digest,
        )
    )

    class Flight:
        def get_or_compute(self, _key, compute):
            return compute(), False, False

    class Tools:
        observed_paths: list[str] = []
        ignore_dirs: set[str] = set()
        ignore_extensions: set[str] = set()
        extensions: set[str] = set()
        special_filenames: set[str] = set()
        max_file_bytes = 2_000_000

        def _git_files(self, _root):
            return [hinted_dir / "button.php"]

        def search(self, *_args, **_kwargs):
            return {"success": True, "results": []}

        def search_paths(self, _root, _query, paths, _top_k, context_lines=None):
            self.observed_paths = list(paths)
            return {"success": True, "results": []}

    original_paths = [f"src/file_{index:02}.py" for index in range(64)]
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(state_dir)}, "features": {}}
    services.repo_flight = Flight()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {
        "fingerprint": "workspace-1", "kind": "filesystem", "stale": False,
    }
    services.repo_tools = Tools()
    services.learner = None
    services.deterministic = SimpleNamespace(
        related_paths=lambda *_args: original_paths
    )
    services.code_index = services.preprocessor = services.evidence_store = None

    services.repo_search(str(tmp_path), "button", top_k=200)

    assert services.repo_tools.observed_paths[0] == "templates/button.php"
    assert set(services.repo_tools.observed_paths[1:]) == set(original_paths)


def test_repo_search_hint_hit_does_not_skip_broader_results(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    state_dir = tmp_path / "runtime"
    hinted_file = tmp_path / "templates" / "element" / "button.php"
    original_file = tmp_path / "src" / "indexed.py"
    broader_file = tmp_path / "src" / "discovered.py"
    hinted_file.parent.mkdir(parents=True)
    original_file.parent.mkdir(parents=True)
    hinted_file.write_text("button()", encoding="utf-8")
    original_file.write_text("unmatched", encoding="utf-8")
    broader_file.write_text("broader match", encoding="utf-8")
    context = resolve_project_context(tmp_path, state_dir)
    context.save_path_hint(
        PathHint(
            path="templates/element",
            purpose="repository_search",
            scope="repo_search",
            evidence_id="verified-broader-fallback",
            provenance="verified_search",
            repository_revision="workspace-1",
            config_digest=context.config_digest,
        )
    )

    class Flight:
        def get_or_compute(self, _key, compute):
            return compute(), False, False

    class Tools:
        ignore_dirs: set[str] = set()
        ignore_extensions: set[str] = set()
        extensions: set[str] = set()
        special_filenames: set[str] = set()
        max_file_bytes = 2_000_000
        broad_search_calls = 0

        def _git_files(self, _root):
            return [hinted_file, original_file, broader_file]

        def search(self, *_args, **_kwargs):
            self.broad_search_calls += 1
            return {
                "success": True,
                "results": [
                    {
                        "path": "src/discovered.py",
                        "start_line": 1,
                        "score": 8.0,
                    }
                ],
            }

        def search_paths(self, _root, _query, paths, _top_k, context_lines=None):
            self.targeted_paths = list(paths)
            return {
                "success": True,
                "results": [
                    {
                        "path": "templates/element/button.php",
                        "start_line": 1,
                        "score": 5.0,
                    }
                ],
            }

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(state_dir)}, "features": {}}
    services.repo_flight = Flight()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {
        "fingerprint": "workspace-1", "kind": "filesystem", "stale": False,
    }
    services.repo_tools = Tools()
    services.learner = None
    services.deterministic = SimpleNamespace(
        related_paths=lambda *_args: ["src/indexed.py"]
    )
    services.code_index = services.preprocessor = services.evidence_store = None

    result = services.repo_search(str(tmp_path), "button", top_k=10)

    assert services.repo_tools.targeted_paths[:2] == [
        "templates/element/button.php",
        "src/indexed.py",
    ]
    assert "src/discovered.py" not in services.repo_tools.targeted_paths
    assert services.repo_tools.broad_search_calls == 1
    assert {item["path"] for item in result["results"]} == {
        "templates/element/button.php",
        "src/discovered.py",
    }


def test_search_paths_enforces_project_excludes_and_file_size_limit(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    (tmp_path / "public").mkdir()
    (tmp_path / "private").mkdir()
    (tmp_path / "public" / "match.py").write_text("needle", encoding="utf-8")
    (tmp_path / "private" / "match.py").write_text("needle", encoding="utf-8")
    (tmp_path / "public" / "large.py").write_text("needle " * 20, encoding="utf-8")
    (tmp_path / ".local-ai.toml").write_text(
        'exclude_paths = ["private/**"]\n'
        "[file_limits]\nmax_file_size_bytes = 32\n",
        encoding="utf-8",
    )
    tools = RepositoryTools(
        {"server": {"state_dir": str(tmp_path / "runtime")}, "rag": {}, "search": {}}
    )

    result = tools.search_paths(
        str(tmp_path),
        "needle",
        ["public/match.py", "private/match.py", "public/large.py"],
    )

    assert [item["path"] for item in result["results"]] == ["public/match.py"]
    assert result["scanned_files"] == 1


def test_repo_search_hints_respect_gitignore_and_searchable_file_rules(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    hinted_dir = tmp_path / "templates" / "element"
    hinted_dir.mkdir(parents=True)
    (tmp_path / ".gitignore").write_text(
        "templates/element/ignored.php\n", encoding="utf-8"
    )
    (hinted_dir / "button.php").write_text("button", encoding="utf-8")
    (hinted_dir / "ignored.php").write_text("button", encoding="utf-8")
    (hinted_dir / "preview.png").write_text("button", encoding="utf-8")
    state_dir = tmp_path / "runtime"
    context = resolve_project_context(tmp_path, state_dir)
    context.save_path_hint(
        PathHint(
            path="templates/element",
            purpose="repository_search",
            scope="repo_search",
            evidence_id="verified-ignored-filter",
            provenance="verified_search",
            repository_revision="workspace-1",
            config_digest=context.config_digest,
        )
    )
    context.save_path_hint(
        PathHint(
            path="templates",
            purpose="repository_search",
            scope="repo_search",
            evidence_id="verified-ignored-filter-parent",
            provenance="verified_search",
            repository_revision="workspace-1",
            config_digest=context.config_digest,
        )
    )

    class Flight:
        def get_or_compute(self, _key, compute):
            return compute(), False, False

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(state_dir)}, "features": {}}
    services.repo_flight = Flight()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {
        "fingerprint": "workspace-1", "kind": "filesystem", "stale": False,
    }
    services.repo_tools = RepositoryTools(
        {"server": {"state_dir": str(state_dir)}, "rag": {}, "search": {}}
    )
    inventory_calls = 0
    original_inventory = services.repo_tools._git_files

    def counted_inventory(root):
        nonlocal inventory_calls
        inventory_calls += 1
        return original_inventory(root)

    monkeypatch.setattr(services.repo_tools, "_git_files", counted_inventory)
    services.learner = None
    services.deterministic = services.code_index = services.preprocessor = None
    services.evidence_store = None

    result = services.repo_search(str(tmp_path), "button", top_k=10)

    assert [item["path"] for item in result["results"]] == [
        "templates/element/button.php"
    ]
    assert inventory_calls == 2


def test_search_paths_skips_unresolvable_git_inventory_entries(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "src").mkdir()
    good_file = tmp_path / "src" / "match.py"
    good_file.write_text("needle", encoding="utf-8")
    broken_file = tmp_path / "loop.py"
    tools = RepositoryTools(
        {"server": {"state_dir": str(tmp_path / "runtime")}, "rag": {}, "search": {}}
    )
    monkeypatch.setattr(tools, "_git_files", lambda _root: [broken_file, good_file])
    original_resolve = Path.resolve

    def resolve(path: Path, *args, **kwargs) -> Path:
        if path == broken_file:
            raise RuntimeError("symlink loop")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)

    result = tools.search_paths(str(tmp_path), "needle", ["src/match.py"])

    assert result["success"] is True
    assert [item["path"] for item in result["results"]] == ["src/match.py"]


def test_search_paths_declines_git_repo_when_ignore_inventory_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("private/\n", encoding="utf-8")
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "match.py").write_text("needle", encoding="utf-8")
    tools = RepositoryTools(
        {"server": {"state_dir": str(tmp_path / "runtime")}, "rag": {}, "search": {}}
    )
    monkeypatch.setattr(tools, "_git_files", lambda _root: None)

    result = tools.search_paths(str(tmp_path), "needle", ["private/match.py"])

    assert result["success"] is False
    assert result["error"] == "git_inventory_unavailable"
    assert result["results"] == []


def test_repo_search_propagates_unavailable_git_inventory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "match.py").write_text("needle", encoding="utf-8")

    class Flight:
        def get_or_compute(self, _key, compute):
            return compute(), False, False

    tools = RepositoryTools(
        {"server": {"state_dir": str(tmp_path / "runtime")}, "rag": {}, "search": {}}
    )
    monkeypatch.setattr(tools, "_git_files", lambda _root: None)
    full_search_calls = 0

    def full_search(*_args, **_kwargs):
        nonlocal full_search_calls
        full_search_calls += 1
        return {"success": True, "results": [{"path": "src/match.py"}]}

    monkeypatch.setattr(tools, "search", full_search)
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(tmp_path / "runtime")}, "features": {}}
    services.repo_flight = Flight()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {"fingerprint": "rev", "stale": False}
    services.repo_tools = tools
    services.learner = None
    services.deterministic = SimpleNamespace(
        related_paths=lambda *_args: ["src/match.py"]
    )
    services.code_index = services.preprocessor = services.evidence_store = None

    result = services.repo_search(str(tmp_path), "needle")

    assert result["success"] is False
    assert result["error"] == "git_inventory_unavailable"
    assert result["results"] == []
    assert full_search_calls == 0


def test_repo_search_fails_closed_when_project_policy_cannot_load(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    (tmp_path / ".local-ai.toml").write_text("exclude_paths = 7\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "match.py").write_text("needle", encoding="utf-8")

    class Flight:
        def get_or_compute(self, _key, compute):
            return compute(), False, False

    tools = RepositoryTools(
        {"server": {"state_dir": str(tmp_path / "runtime")}, "rag": {}, "search": {}}
    )
    full_search_calls = 0
    original_search = tools.search

    def counted_search(*args, **kwargs):
        nonlocal full_search_calls
        full_search_calls += 1
        return original_search(*args, **kwargs)

    monkeypatch.setattr(tools, "search", counted_search)
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(tmp_path / "runtime")}, "features": {}}
    services.repo_flight = Flight()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {"fingerprint": "rev", "stale": False}
    services.repo_tools = tools
    services.learner = None
    services.deterministic = SimpleNamespace(
        related_paths=lambda *_args: ["src/match.py"]
    )
    services.code_index = services.preprocessor = services.evidence_store = None

    result = services.repo_search(str(tmp_path), "needle")

    assert result["success"] is False
    assert result["error"] == "project_policy_unavailable"
    assert result["results"] == []
    assert full_search_calls == 0


def test_repo_search_filters_project_excludes_from_full_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    (tmp_path / ".local-ai.toml").write_text(
        'exclude_paths = ["private/**"]\n', encoding="utf-8"
    )
    (tmp_path / "private").mkdir()
    (tmp_path / "public").mkdir()
    (tmp_path / "private" / "match.py").write_text("needle", encoding="utf-8")
    (tmp_path / "public" / "match.py").write_text("needle", encoding="utf-8")

    class Flight:
        def get_or_compute(self, _key, compute):
            return compute(), False, False

    tools = RepositoryTools(
        {"server": {"state_dir": str(tmp_path / "runtime")}, "rag": {}, "search": {}}
    )
    monkeypatch.setattr(
        tools,
        "search",
        lambda *_args, **_kwargs: {
            "success": True,
            "root": str(tmp_path),
            "results": [
                {"path": "private/match.py", "start_line": 1, "text": "needle"},
                {"path": "public/match.py", "start_line": 1, "text": "needle"},
            ],
        },
    )
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(tmp_path / "runtime")}, "features": {}}
    services.repo_flight = Flight()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {"fingerprint": "rev", "stale": False}
    services.repo_tools = tools
    services.learner = None
    services.deterministic = SimpleNamespace(related_paths=lambda *_args: [])
    services.code_index = services.preprocessor = services.evidence_store = None

    result = services.repo_search(str(tmp_path), "needle")

    assert [item["path"] for item in result["results"]] == ["public/match.py"]


def test_repo_search_fails_closed_for_invalid_policy_without_index_candidates(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    (tmp_path / ".local-ai.toml").write_text("exclude_paths = 7\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "match.py").write_text("needle", encoding="utf-8")

    class Flight:
        def get_or_compute(self, _key, compute):
            return compute(), False, False

    tools = RepositoryTools(
        {"server": {"state_dir": str(tmp_path / "runtime")}, "rag": {}, "search": {}}
    )
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(tmp_path / "runtime")}, "features": {}}
    services.repo_flight = Flight()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {"fingerprint": "rev", "stale": False}
    services.repo_tools = tools
    services.learner = None
    services.deterministic = SimpleNamespace(related_paths=lambda *_args: [])
    services.code_index = services.preprocessor = services.evidence_store = None

    result = services.repo_search(str(tmp_path), "needle")

    assert result["success"] is False
    assert result["error"] == "project_policy_unavailable"
    assert result["results"] == []
