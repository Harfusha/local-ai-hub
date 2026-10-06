from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
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


def test_run_affected_expands_uncertain_selection_to_complete_test_matrix(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    for relative in ("tests/test_first.py", "tests/test_second.py"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_case(): pass\n", encoding="utf-8")

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(tmp_path / "runtime")}}
    services._repo_cache_state = lambda _root: {
        "fingerprint": "revision-1",
        "stale": False,
        "degraded": False,
    }
    services.deterministic = SimpleNamespace(
        affected_tests=lambda *_args: {
            "success": True,
            "framework": "pytest",
            "changed_files": ["src/unknown.py"],
            "test_files": [],
            "suggested_command": "",
            "confidence": 0.5,
        }
    )
    services.deterministic_operation = lambda _op, _root, _params, compute: {
        **compute(),
        "workspace_cache": {"fingerprint": "revision-1"},
    }
    services.test_matrix = lambda _root: {
        "test_files": [
            {"path": "tests/test_first.py"},
            {"path": "tests/test_second.py"},
        ]
    }

    result = services.affected_tests(str(tmp_path), changed_paths=["src/unknown.py"])

    assert result["test_files"] == ["tests/test_first.py", "tests/test_second.py"]
    assert result["selection_uncertain"] is True
    assert result["selection_fallback"] == "complete_test_matrix"
    assert "tests/test_first.py" in result["suggested_command"]
    assert "tests/test_second.py" in result["suggested_command"]


def test_run_affected_fails_closed_when_uncertain_and_test_matrix_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(tmp_path / "runtime")}}
    services.commands = object()
    services.agent_state = None
    services._repo_cache_state = lambda _root: {
        "fingerprint": "revision-1",
        "stale": False,
        "degraded": False,
    }
    services.deterministic = SimpleNamespace(
        affected_tests=lambda *_args: {
            "success": True,
            "framework": "pytest",
            "changed_files": ["src/unknown.py"],
            "test_files": [],
            "suggested_command": "",
            "confidence": 0.5,
        }
    )
    services.deterministic_operation = lambda _op, _root, _params, compute: {
        **compute(),
        "workspace_cache": {"fingerprint": "revision-1"},
    }
    services.test_matrix = lambda _root: {"test_files": []}

    result = services.command(
        {"action": "run_affected", "cwd": str(tmp_path), "paths": ["src/unknown.py"]},
        tenant="test",
    )

    assert result["success"] is False
    assert result["selection_uncertain"] is True
    assert "no complete test matrix" in result["error"]


def test_run_affected_compares_selected_tests_with_complete_dependency_graph(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    for relative in ("tests/test_first.py", "tests/test_second.py"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_case(): pass\n", encoding="utf-8")
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(tmp_path / "runtime")}}
    services._repo_cache_state = lambda _root: {
        "fingerprint": "revision-1",
        "stale": False,
        "degraded": False,
    }
    services.deterministic = SimpleNamespace(
        affected_tests=lambda *_args: {
            "success": True,
            "framework": "pytest",
            "changed_files": ["src/changed.py"],
            "test_files": ["tests/test_first.py"],
            "suggested_command": "pytest tests/test_first.py",
            "confidence": 0.95,
        }
    )
    services.code_index = SimpleNamespace(
        impact=lambda *_args, **_kwargs: {
            "success": True,
            "confidence": 0.98,
            "indexed_changed_files": 1,
            "changed_files_count": 1,
            "likely_dependents": [
                {"path": "tests/test_first.py"},
                {"path": "tests/test_second.py"},
            ],
            "suggested_tests": [
                {"path": "tests/test_first.py"},
                {"path": "tests/test_second.py"},
            ],
        },
        _is_test_path=lambda path: path.startswith("tests/test_"),
    )
    services.deterministic_operation = lambda _op, _root, _params, compute: {
        **compute(),
        "workspace_cache": {"fingerprint": "revision-1"},
    }
    services.test_matrix = lambda _root: {
        "test_files": [{"path": "tests/test_first.py"}, {"path": "tests/test_second.py"}]
    }

    result = services.affected_tests(str(tmp_path), changed_paths=["src/changed.py"])

    assert result["test_files"] == ["tests/test_first.py", "tests/test_second.py"]
    assert result["dependency_graph_complete"] is True
    assert result["dependency_graph_test_count"] == 2
    assert result["dependency_graph_missing_candidates"] == 1


def test_repo_search_fallback_filters_unsearchable_extensions(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_text("needle", encoding="utf-8")
    preview = tmp_path / "src" / "preview.png"
    preview.write_text("needle", encoding="utf-8")

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
                {"path": "src/main.py", "start_line": 1, "text": "needle"},
                {"path": "src/preview.png", "start_line": 1, "text": "needle"},
            ],
        },
    )

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(tmp_path / "runtime")}}
    services._repo_cache_state = lambda _root: {
        "fingerprint": "revision-1", "stale": False, "degraded": False
    }
    services._repo_cached = lambda _operation, _root, _params, compute: compute()
    services.learner = None
    services.deterministic = SimpleNamespace(
        related_paths=lambda *_args: ["src/main.py"]
    )
    services.code_index = services.preprocessor = None
    services.repo_tools = tools
    services.evidence_store = None

    result = services.repo_search(
        str(tmp_path),
        "needle",
        path_hints=[
            {
                "path": "src/main.py",
                "purpose": "repository_search",
                "scope": "repo_search",
            }
        ],
    )

    assert [hit["path"] for hit in result["results"]] == ["src/main.py"]
