from __future__ import annotations

import json
import importlib.util
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from local_ai_hub import commands as command_module
from local_ai_hub import http_server
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract
from local_ai_hub.app import LocalAIApp


def _setup(tmp_path: Path, task_id: str) -> tuple[LocalAIApp, Path, str]:
    expected_commands = (Path(__file__).parents[1] / "src/local_ai_hub/commands.py").resolve()
    assert Path(command_module.__file__).resolve() == expected_commands
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "lint_target.py"
    source.write_text("value = 1\n", encoding="utf-8")
    configured_lint = f'"{sys.executable}" -m pyflakes "{source.name}"'
    (repo / ".local-ai.toml").write_text(
        f"[commands]\nlint = {json.dumps(configured_lint)}\n"
        "[verification_rules]\nrequired_commands = [\"lint\"]\n",
        encoding="utf-8",
    )
    state = tmp_path / "state"
    state.mkdir()
    config = tmp_path / "hub.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state.as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    app.agent_tasks.create(
        GoalContract(goal="validate configured lint", acceptance_criteria=("lint",)),
        ScopeContext(task_id=task_id, repository_id=str(repo)),
        task_id=task_id,
        actor="agent",
        repo_root=str(repo),
    )
    return app, repo, configured_lint


def _post(port: int, payload: dict) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/agent-state/tasks",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode("utf-8"))


def _serve(app: LocalAIApp):
    previous = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return previous, server, thread


def test_generic_run_cannot_mint_project_lint_receipt(tmp_path: Path):
    if importlib.util.find_spec("pyflakes") is None:
        pytest.skip("configured pyflakes lint runner is unavailable")
    task_id = "t06-configured-lint"
    app, repo, configured_lint = _setup(tmp_path, task_id)
    previous, server, thread = _serve(app)
    try:
        result = app.commands.run(
            configured_lint,
            str(repo),
            tenant="agent",
            task_id=task_id,
            criterion="lint",
            force=True,
        )
        assert result["success"] is True
        assert "verification_receipt" not in result
        completion = _post(
            server.server_address[1],
            {"action": "complete", "task_id": task_id, "actor": "agent"},
        )
        assert completion["success"] is False, completion
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        http_server.APP = previous
        app.close()


def test_generic_pytest_help_cannot_mint_test_receipt(tmp_path: Path):
    task_id = "t06-pytest-help"
    app, repo, _configured_lint = _setup(tmp_path, task_id)
    try:
        result = app.commands.run(
            f'"{sys.executable}" -m pytest --help',
            str(repo),
            tenant="agent",
            task_id=task_id,
            criterion="test",
            force=True,
        )
        assert result["success"] is True
        assert "verification_receipt" not in result
    finally:
        app.close()


def test_run_rejects_caller_supplied_project_receipt_identity(tmp_path: Path):
    if importlib.util.find_spec("pyflakes") is None:
        pytest.skip("configured pyflakes lint runner is unavailable")
    task_id = "t06-untrusted-project-receipt"
    app, repo, configured_lint = _setup(tmp_path, task_id)
    try:
        with pytest.raises(TypeError, match="_project_alias"):
            app.commands.run(
                configured_lint,
                str(repo),
                tenant="agent",
                task_id=task_id,
                criterion="lint",
                force=True,
                _project_alias="lint",
                _project_config_digest="caller-controlled",
            )
    finally:
        app.close()


