"""Project search settings must reach the real lexical search consumers."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import local_ai_hub.project_config as project_config
import local_ai_hub.repo_tools as repo_tools
import local_ai_hub.services as services_module
from local_ai_hub.project_config import PathHint
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices


def _search_service(tmp_path: Path, settings: str) -> tuple[Path, LocalAIServices]:
    expected = os.environ.get("T21_EXPECT_SOURCE_ROOT")
    if expected:
        for module in (project_config, repo_tools, services_module):
            assert Path(module.__file__).resolve().is_relative_to(Path(expected).resolve())
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, timeout=10)
    (root / ".local-ai.toml").write_text(settings, encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "visible.py").write_text("needle = 1\n", encoding="utf-8")
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "search": {"max_files": 100},
        "rag": {"extensions": [".py", ".php"]},
    }
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = config
    service.repo_tools = RepositoryTools(config)
    service.learner = service.code_index = service.preprocessor = None
    service.deterministic = service.evidence_store = None
    service._repo_cache_state = lambda _root: {"fingerprint": "current", "stale": False}
    service._repo_cached = lambda _operation, _root, _params, compute: compute()
    return root, service


@pytest.mark.parametrize("explicit_hint", [False, True])
def test_search_honors_project_custom_text_extensions(tmp_path: Path, explicit_hint: bool) -> None:
    root, service = _search_service(tmp_path, '[custom_extensions]\ntext = [".shader"]\n')
    (root / "src" / "button.shader").write_text("needle shader\n", encoding="utf-8")
    hints = [PathHint(path="src/button.shader", purpose="repository_search", scope="repo_search")] if explicit_hint else []
    result = service.repo_search(str(root), "needle", path_hints=hints)
    assert result["success"] is True, result
    assert {hit["path"] for hit in result["results"]} == {"src/visible.py", "src/button.shader"}


@pytest.mark.parametrize("explicit_hint", [False, True])
def test_search_honors_forced_gitignored_directory(tmp_path: Path, explicit_hint: bool) -> None:
    root, service = _search_service(tmp_path, 'force_include_paths = ["node_modules/@my-org/**"]\n')
    (root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    forced = root / "node_modules" / "@my-org" / "button.php"
    forced.parent.mkdir(parents=True)
    forced.write_text("needle forced dependency\n", encoding="utf-8")
    hints = [PathHint(path="node_modules/@my-org/button.php", purpose="repository_search", scope="repo_search")] if explicit_hint else []
    result = service.repo_search(str(root), "needle", path_hints=hints)
    assert result["success"] is True, result
    assert {hit["path"] for hit in result["results"]} == {"src/visible.py", "node_modules/@my-org/button.php"}


def test_force_include_does_not_override_project_binary_policy(tmp_path: Path) -> None:
    root, service = _search_service(
        tmp_path, 'force_include_paths = ["src/**"]\n[custom_extensions]\nbinary = [".php"]\n'
    )
    (root / "src" / "opaque.php").write_text("needle must remain binary\n", encoding="utf-8")
    result = service.repo_search(str(root), "needle", path_hints=[
        PathHint(path="src/opaque.php", purpose="repository_search", scope="repo_search")
    ])
    assert result["success"] is True, result
    assert {hit["path"] for hit in result["results"]} == {"src/visible.py"}
