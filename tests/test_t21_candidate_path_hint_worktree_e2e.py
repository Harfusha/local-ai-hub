from __future__ import annotations

import asyncio
import json
import subprocess
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from local_ai_hub import http_server, mcp_server, project_config
from local_ai_hub.client import HubClient
from local_ai_hub.project_config import resolve_project_config
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.resilience import RecoveryJournal
from local_ai_hub.services import LocalAIServices


def test_registered_search_path_hints_use_candidate_worktree_config(
    monkeypatch, tmp_path: Path
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()

    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(primary), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, (
            args,
            completed.stdout,
            completed.stderr,
        )
        return completed.stdout.strip()

    git("init", "-q")
    (primary / ".gitignore").write_text(
        "templates/element/ignored.py\n", encoding="utf-8"
    )
    (primary / ".local-ai.toml").write_text(
        'exclude_paths = ["templates/element/private.py"]\n'
        "[path_overrides]\n"
        '"templates/element/private.py" = "include"\n',
        encoding="utf-8",
    )
    element = primary / "templates" / "element"
    hard_denied = primary / "templates" / ".local-ai-hub"
    element.mkdir(parents=True)
    hard_denied.mkdir()
    token = "T21_CANDIDATE_PATH_HINT_WORKTREE_TOKEN"
    for file in (
        element / "button.py",
        element / "private.py",
        hard_denied / "hard.py",
    ):
        file.write_text(f"marker = '{token}'\n", encoding="utf-8")
    git("add", ".")
    git(
        "-c",
        "user.name=T21 Test",
        "-c",
        "user.email=t21@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )

    worktree = tmp_path / "worktree"
    git("worktree", "add", "--detach", str(worktree), "HEAD")
    (worktree / ".local-ai.worktree.toml").write_text(
        'force_include_paths = ["templates/element/ignored.py", '
        '"templates/element/private.py", "templates/.local-ai-hub/hard.py"]\n',
        encoding="utf-8",
    )
    (worktree / "templates" / "element" / "ignored.py").write_text(
        f"marker = '{token}'\n", encoding="utf-8"
    )

    resolution = resolve_project_config(worktree)
    assert "primary_project" in resolution.active_sources
    assert "worktree" in resolution.active_sources
    assert resolution.settings.exclude_paths == ("templates/element/private.py",)
    assert resolution.settings.force_include_paths == (
        "templates/element/ignored.py",
        "templates/element/private.py",
        "templates/.local-ai-hub/hard.py",
    )

    state_dir = tmp_path / "hub-state"
    config = {
        "server": {"state_dir": str(state_dir)},
        "features": {},
        "rag": {"extensions": [".py"]},
        "search": {
            "prefer_git_files": True,
            "use_git_grep_fallback": False,
            "use_ripgrep_if_available": False,
            "max_files": 100,
            "max_hits": 100,
        },
    }
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = config
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {
        "fingerprint": "revision-1",
        "stale": False,
        "degraded": False,
    }
    services._repo_cached = lambda _operation, _root, _params, compute: compute()
    services.repo_tools = RepositoryTools(config)
    services.learner = None
    services.deterministic = None
    services.code_index = None
    services.preprocessor = None
    services.evidence_store = None

    app = type(
        "TestApp",
        (),
        {
            "config": config,
            "debug_traces": None,
            "recovery": RecoveryJournal(state_dir),
            "services": services,
        },
    )()

    class AuthorizedHandler(http_server.Handler):
        def _require_authorized(self):
            return True

        def _tenant(self):
            return "t21-candidate"

        def _agent(self):
            return "t21-candidate-test"

        def log_message(self, *_args):
            return None

    monkeypatch.setattr(http_server, "APP", app)
    server = ThreadingHTTPServer(("127.0.0.1", 0), AuthorizedHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    client_config = tmp_path / "client.toml"
    client_config.write_text(
        f"[server]\nport={server.server_port}\n"
        f"state_dir='{state_dir.as_posix()}'\n",
        encoding="utf-8",
    )
    client = HubClient(

        config_path=str(client_config),
        auto_start=False,
    )
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    wire_payloads: list[dict[str, object]] = []
    accepted_hints: list[tuple[str, str]] = []
    original_open = client._pooled_open
    original_validate = project_config.validate_path_hint

    def capture_open(method, path, body, headers, timeout, *, cancel_event=None):
        if path == "/api/search" and body is not None:
            wire_payloads.append(json.loads(body.decode("utf-8")))
        return original_open(method, path, body, headers, timeout, cancel_event=cancel_event)

    def capture_validate(root, hint, **kwargs):
        resolved = original_validate(root, hint, **kwargs)
        if resolved is not None:
            accepted_hints.append((hint.path, hint.scope))
        return resolved

    client._pooled_open = capture_open
    monkeypatch.setattr(project_config, "validate_path_hint", capture_validate)
    try:
        async def call_tool(arguments):
            result = await mcp_server.mcp.call_tool("local_ai_repo", arguments)
            contents = result[0] if isinstance(result, tuple) else result
            content = next(item for item in contents if getattr(item, "type", None) == "text")
            return json.loads(content.text)

        hint = {
            "path": "templates/element",
            "purpose": "repository_search",
            "scope": "repo_search",
        }
        result = asyncio.run(
            call_tool(
                {
                    "action": "search",
                    "root": str(worktree),
                    "query": token,
                    "path_hints": [hint],
                }
            )
        )
        assert result.get("success") is True, result
        paths = {item.get("path") for item in result.get("results", [])}
        assert "templates/element/button.py" in paths, paths
        assert "templates/element/ignored.py" in paths, paths
        assert "templates/element/private.py" not in paths, paths
        assert "templates/.local-ai-hub/hard.py" not in paths, paths
        assert wire_payloads == [
            {
                "root": str(worktree.resolve()),
                "query": token,
                "top_k": 12,
                "enrich": False,
                "limit": 24,
                "offset": 0,
                "path_hints": [hint],
            }
        ]
        assert ("templates/element", "repo_search") in accepted_hints

        before_invalid = len(wire_payloads)
        invalid = asyncio.run(
            call_tool(
                {
                    "action": "search",
                    "root": str(worktree),
                    "query": token,
                    "path_hints": [
                        {
                            "path": "../outside.py",
                            "purpose": "repository_search",
                            "scope": "repo_search",
                        }
                    ],
                }
            )
        )
        assert invalid.get("success") is False, invalid
        assert invalid.get("status_code") == 400, invalid
        assert invalid.get("terminal") is True
        assert invalid.get("retryable") is False
        assert len(wire_payloads) == before_invalid
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=3)
