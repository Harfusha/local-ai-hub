from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract
from local_ai_hub.app import LocalAIApp


@pytest.mark.parametrize("revision", [True, 7, None, "   ", " x", "x ", "x" * 257])
def test_completion_rejects_malformed_repository_revision_pin(revision):
    with pytest.raises(http_server.RequestBodyError):
        http_server.Handler._validate_payload(
            "/api/agent-state/verification",
            {"action": "completion", "repository_revision": revision},
        )


def test_completion_missing_empty_and_exact_pin_are_valid():
    http_server.Handler._validate_payload(
        "/api/agent-state/verification", {"action": "completion"}
    )
    http_server.Handler._validate_payload(
        "/api/agent-state/verification",
        {"action": "completion", "repository_revision": ""},
    )
    http_server.Handler._validate_payload(
        "/api/agent-state/verification",
        {"action": "completion", "repository_revision": "opaque-current-id"},
    )


@pytest.mark.parametrize(
    ("pin", "expected_status", "should_complete"),
    [
        (None, 200, True),
        ("", 200, True),
        ("opaque-current-id", 200, True),
        ("opaque-stale-id", 409, False),
        (7, 400, False),
    ],
    ids=["missing", "empty", "exact", "stale", "malformed"],
)
def test_completion_revision_pin_http_contract(
    tmp_path, monkeypatch, pin, expected_status, should_complete
):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    project_root = tmp_path / "repo"
    project_root.mkdir()
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nstate_dir = "{state_dir.as_posix()}"\n'
        "[agent_state]\nenabled = true\n[prewarm]\nenabled = false\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    task_id = "completion-pin-task"
    tenant = "api-token-default"
    app.agent_tasks.create(
        GoalContract(goal="test pinned completion", acceptance_criteria=("test",)),
        ScopeContext(repository_id=str(project_root), task_id=task_id, session_id=tenant),
        task_id=task_id,
        actor=tenant,
        repo_root=str(project_root),
    )
    task_before = app.agent_tasks.get(task_id)
    verifier_calls = []
    def completion(*args, **kwargs):
        verifier_calls.append((args, kwargs))
        return SimpleNamespace(receipts=(), to_dict=lambda: {"complete": True})

    monkeypatch.setattr(
        app.agent_verification,
        "completion",
        completion,
    )
    monkeypatch.setattr(
        http_server,
        "_completion_revision_or_stop",
        lambda *_args: ("opaque-current-id", None),
    )
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = {
            "action": "completion",
            "task_id": task_id,
            "root": str(project_root),
        }
        if pin is not None:
            body["repository_revision"] = pin
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/agent-state/verification",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-LocalAI-Agent": tenant,
                "X-LocalAI-Tenant": tenant,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status = response.status
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            status = error.code
            payload = json.loads(error.read().decode("utf-8"))
        assert status == expected_status
        assert bool(verifier_calls) is should_complete
        if expected_status == 409:
            assert payload["stop_code"] == "completion_repository_revision_mismatch"
            assert payload["terminal"] is True
            assert payload["retryable"] is False
        if should_complete:
            assert verifier_calls[0][1]["current_revision"] == "opaque-current-id"
        assert app.agent_tasks.get(task_id) == task_before
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous_app
        app.close()


def test_completion_fingerprint_typeerror_does_not_retry_old_signature():
    class RepoState:
        calls = 0

        def fingerprint(self, root, *, force):
            self.calls += 1
            assert root == "repo"
            assert force is True
            raise TypeError("fingerprint failed internally")

    class Snapshot:
        revision = "snapshot-current"
        degraded = False
        error = None

    class RepoTools:
        calls = 0

        def git_snapshot(self, root):
            self.calls += 1
            assert root == "repo"
            return Snapshot()

    state = RepoState()
    tools = RepoTools()
    revision, stop = http_server._completion_revision_or_stop("repo", tools, state)

    assert revision == "snapshot-current"
    assert stop is None
    assert state.calls == 1
    assert tools.calls == 1
