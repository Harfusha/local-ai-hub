from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import local_ai_hub.project_config as project_config
from local_ai_hub.project_config import PathHint, resolve_project_context
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
    assert "repository_revision" not in observed
    assert "tests/requested" not in repr(observed)
