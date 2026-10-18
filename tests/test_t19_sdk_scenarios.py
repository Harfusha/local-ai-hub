from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest


@pytest.fixture
def scenario_hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    # This integration fixture must not inherit stale process-wide requests
    # from tests that exercise operational-mode draining.
    monkeypatch.setattr(
        http_server, "_ACTIVE_TRANSCRIPTIONS", http_server._ActiveTranscriptionRegistry()
    )
    monkeypatch.setattr(
        http_server, "_ACTIVE_CONVERSATIONS", http_server._ActiveTranscriptionRegistry()
    )

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    state_dir = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{state_dir.as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n"
        f'allowed_roots = ["{tmp_path.as_posix()}"]\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    generations: list[dict[str, str]] = []

    def fake_generate(
        model,
        prompt,
        system,
        max_tokens,
        temperature,
        source,
        priority,
        **kwargs,
    ):
        generations.append({"prompt": prompt, "system": system})
        return {
            "success": True,
            "model": model,
            "text": f"scenario answer {len(generations)}",
        }

    app.services._generate = fake_generate
    app.async_jobs._resource_admission = lambda: {
        "state": "accepted",
        "reason": "capacity_available",
        "retryable": False,
        "pressure_level": "nominal",
        "context_budget_factor": 1.0,
    }
    monkeypatch.setattr(http_server, "APP", app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield app, HubClient(config_path=str(config), auto_start=False), generations
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()


def _observe(client):
    calls: list[dict[str, object]] = []
    original = client._pooled_open

    def observed(method, path, body, headers, timeout):
        payload = json.loads(body.decode("utf-8")) if body else None
        calls.append({"method": method, "path": path, "payload": payload})
        return original(method, path, body, headers, timeout)

    client._pooled_open = observed
    return calls


def test_seven_sdk_workflows_have_measured_production_route_outcomes(
    scenario_hub, tmp_path: Path
):
    app, client, generations = scenario_hub
    calls = _observe(client)
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "sample.py").write_text(
        "def target():\n    return 1\n\ndef caller():\n    return target()\n",
        encoding="utf-8",
    )
    measurements: dict[str, dict[str, object]] = {}

    callers = client.callers(str(workspace), "target", limit=10)
    measurements["caller discovery"] = {
        "success": callers.get("success") is True,
        "calls": len(calls),
    }
    assert callers.get("success") is True
    assert len(calls) == 1
    assert calls[0]["path"] == "/api/repo/callers"
    assert calls[0]["payload"] == {
        "root": str(workspace),
        "symbol": "target",
        "limit": 10,
    }

    calls.clear()
    context = client.post(
        "/api/context/pack",
        {"root": str(workspace), "query": "find target function", "max_tokens": 500},
    )
    measurements["context acquisition"] = {
        "success": context.get("success") is True,
        "calls": len(calls),
    }
    assert context.get("success") is True
    assert len(calls) == 1
    assert calls[0]["path"] == "/api/context/pack"
    assert calls[0]["payload"] == {
        "root": str(workspace),
        "query": "find target function",
        "max_tokens": 500,
    }
    context_payload = json.dumps(context).casefold()
    assert "sample.py" in context_payload
    assert "def target()" in context_payload

    calls.clear()
    criterion = "focused pytest check passes"
    created = client.create_task(
        "Verify sample change",
        acceptance_criteria=[criterion],
        task_id="t19-change-check",
        root=str(workspace),
    )
    assert created.get("success") is True
    task = app.agent_tasks.get("t19-change-check")
    assert task is not None
    repository_revision = app.repo_state.fingerprint(str(workspace), force=True)[
        "fingerprint"
    ]
    source_text = (workspace / "sample.py").read_text(encoding="utf-8")
    evidence_id = app.evidence.put(
        str(workspace),
        {
            "path": "sample.py",
            "text": source_text,
            "file_sha256": hashlib.sha256(
                (workspace / "sample.py").read_bytes()
            ).hexdigest(),
            "start_line": 1,
            "end_line": 1,
        },
    )
    assert evidence_id
    receipt_evidence_id = app.artifacts.put_json(
        {
            "kind": "work_command_verification",
            "passed": True,
            "task_id": "t19-change-check",
            "owner": task.owner,
            "criterion": criterion,
            "command_id": "pytest-focused",
            "command_classification": "test",
            "command": "python -m pytest -q tests/test_t19_scenario.py",
            "repository_revision": repository_revision,
            "mutation_generation": 0,
            "exit_code": 0,
            "cached": False,
            "result": {"success": True, "exit_code": 0},
        },
        kind="command_verification",
    )
    receipt = client.verify_receipt(
        "t19-change-check",
        criterion,
        command_id="pytest-focused",
        evidence_id=receipt_evidence_id,
        details={"exit_code": 0},
        root=str(workspace),
        repository_revision=repository_revision,
    )
    completion = client.verify_completion("t19-change-check", root=str(workspace))
    measurements["change verification"] = {
        "success": receipt.get("success") is True and completion.get("success") is True,
        "calls": len(calls),
    }
    assert receipt.get("success") is True
    assert completion.get("success") is True
    assert len(calls) == 3
    assert calls[0]["path"] == "/api/agent-state/tasks"
    assert calls[0]["payload"] == {
        "action": "create",
        "goal": "Verify sample change",
        "acceptance_criteria": [criterion],
        "task_id": "t19-change-check",
        "scope": "task",
        "root": str(workspace),
    }
    assert calls[1]["path"] == "/api/agent-state/verification"
    assert calls[1]["payload"] == {
        "action": "receipt",
        "receipt": {
            "task_id": "t19-change-check",
            "criterion": criterion,
            "passed": True,
            "command_id": "pytest-focused",
            "evidence_id": receipt_evidence_id,
            "repository_revision": repository_revision,
            "details": {"exit_code": 0},
        },
        "root": str(workspace),
    }
    assert calls[2]["path"] == "/api/agent-state/verification"
    assert calls[2]["payload"] == {
        "action": "completion",
        "task_id": "t19-change-check",
        "root": str(workspace),
    }
    assert calls[1]["payload"]["action"] == "receipt"
    assert calls[2]["payload"]["action"] == "completion"

    calls.clear()
    started = client.post(
        "/api/delegate",
        {
            "task": "first scenario question",
            "context": "grounded facts",
            "conversation": True,
        },
    )
    continued = client.continue_conversation(
        started["conversation_id"], "follow-up question"
    )
    measurements["conversation continuation"] = {
        "success": started.get("success") is True and continued.get("success") is True,
        "calls": len(calls),
    }
    assert started.get("success") is True
    assert continued.get("success") is True
    assert len(calls) == 2
    assert calls[0]["path"] == "/api/delegate"
    assert calls[0]["payload"] == {
        "task": "first scenario question",
        "context": "grounded facts",
        "conversation": True,
    }
    assert calls[1]["path"] == "/api/conversations/continue"
    assert calls[1]["payload"] == {
        "conversation_id": started["conversation_id"],
        "task": "follow-up question",
    }
    assert len(generations) == 2

    calls.clear()
    app.async_jobs._dispatch = lambda _job_id: None
    submitted = client.post(
        "/api/async-jobs",
        {"action": "submit", "job_action": "reason", "task": "cancel me"},
    )
    cancelled = client.post(
        "/api/async-jobs", {"action": "cancel", "job_id": submitted["job_id"]}
    )
    measurements["job cancellation"] = {
        "success": submitted.get("success") is True
        and cancelled.get("state") == "cancelled",
        "calls": len(calls),
    }
    assert submitted.get("success") is True
    assert cancelled.get("success") is True
    assert cancelled.get("state") == "cancelled"
    assert len(calls) == 2
    assert calls[0]["path"] == "/api/async-jobs"
    assert calls[0]["payload"] == {
        "action": "submit",
        "job_action": "reason",
        "task": "cancel me",
    }
    assert calls[1]["path"] == "/api/async-jobs"
    assert calls[1]["payload"] == {
        "action": "cancel",
        "job_id": submitted["job_id"],
    }

    calls.clear()
    resumable = client.create_task(
        "Resume task", task_id="t19-resume", root=str(workspace)
    )
    resumed = client.coord(
        "task_resume", task_id="t19-resume", root=str(workspace)
    )
    measurements["task resume"] = {
        "success": resumable.get("success") is True and resumed.get("success") is True,
        "calls": len(calls),
    }
    assert resumable.get("success") is True
    assert resumed.get("success") is True
    assert resumed["task"]["status"] == "active"
    assert len(calls) == 2
    assert calls[0]["payload"] == {
        "action": "create",
        "goal": "Resume task",
        "acceptance_criteria": [],
        "task_id": "t19-resume",
        "scope": "task",
        "root": str(workspace),
    }
    assert calls[1]["payload"] == {
        "action": "resume",
        "task_id": "t19-resume",
        "root": str(workspace),
    }

    calls.clear()
    evidence = client.post(
        "/api/evidence/get", {"evidence_id": evidence_id, "verify": True}
    )
    measurements["evidence lookup"] = {
        "success": evidence.get("success") is True,
        "calls": len(calls),
    }
    assert evidence.get("success") is True
    assert evidence.get("stale") is False
    assert evidence.get("text") == source_text
    assert len(calls) == 1
    assert calls[0]["path"] == "/api/evidence/get"
    assert calls[0]["payload"] == {"evidence_id": evidence_id, "verify": True}

    calls.clear()
    invalid = client.post(
        "/api/context/pack",
        {"root": str(workspace), "query": "sample", "mode": "adaptive", "max_tokens": -1},
    )
    measurements["error clarity"] = {
        "success": invalid.get("success") is False,
        "calls": len(calls),
        "error": invalid.get("error"),
    }
    assert invalid.get("success") is False
    assert invalid.get("error") == "max_tokens must be non-negative"
    assert invalid.get("terminal") is True
    assert invalid.get("retryable") is False
    assert len(calls) == 1
    assert calls[0]["path"] == "/api/context/pack"
    assert calls[0]["payload"] == {
        "root": str(workspace),
        "query": "sample",
        "mode": "adaptive",
        "max_tokens": -1,
    }

    assert all(row["success"] for row in measurements.values())
    assert {name: row["calls"] for name, row in measurements.items()} == {
        "caller discovery": 1,
        "context acquisition": 1,
        "change verification": 3,
        "conversation continuation": 2,
        "job cancellation": 2,
        "task resume": 2,
        "evidence lookup": 1,
        "error clarity": 1,
    }


def test_sdk_wrappers_match_live_http_handler_contracts(
    scenario_hub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    app, client, _generations = scenario_hub
    root = str(tmp_path / "repo")
    Path(root).mkdir()
    received: dict[str, tuple[tuple[object, ...], dict[str, object]]] = {}

    def capture(service_name: str):
        def call(*args: object, **kwargs: object) -> dict[str, object]:
            received[service_name] = (args, kwargs)
            return {"success": True, "service": service_name}

        return call

    for service_name in (
        "circular_dependencies",
        "code_complexity",
        "extract_api_spec",
        "slice_dependency_graph",
        "find_hotspots",
        "mock_server_start",
        "test_flaky_detect",
    ):
        monkeypatch.setattr(app.services, service_name, capture(service_name))

    cases = [
        (
            "circular_dependencies",
            {"root": root, "language": "python"},
            "/api/repo/circular_dependencies",
            {"root": root, "language": "python"},
            "circular_dependencies",
            (root,),
            {"language": "python"},
        ),
        (
            "complexity",
            {"root": root, "path": None, "max_results": 7},
            "/api/repo/complexity",
            {"root": root, "path": None, "max_results": 7},
            "code_complexity",
            (root,),
            {"path": None, "max_results": 7, "include_tests": False},
        ),
        (
            "api_spec",
            {"root": root, "framework": "fastapi"},
            "/api/repo/api_spec",
            {"root": root, "framework": "fastapi"},
            "extract_api_spec",
            (root,),
            {"framework": "fastapi"},
        ),
        (
            "dependency_slice",
            {
                "root": root,
                "symbol": "HubClient.post",
                "path": "src/client.py",
                "depth": 3,
            },
            "/api/repo/dependency_slice",
            {
                "root": root,
                "symbol": "HubClient.post",
                "path": "src/client.py",
                "depth": 3,
            },
            "slice_dependency_graph",
            (root, "HubClient.post"),
            {"path": "src/client.py", "depth": 3},
        ),
        (
            "hotspots",
            {"root": root, "days": 14, "limit": 5},
            "/api/repo/hotspots",
            {"root": root, "days": 14, "limit": 5},
            "find_hotspots",
            (root,),
            {"days": 14, "limit": 5},
        ),
        (
            "mock_server",
            {"action": "start", "root": root, "spec_path": None, "port": 51440},
            "/api/command/mock_server",
            {"action": "start", "root": root, "spec_path": None, "port": 51440},
            "mock_server_start",
            (root,),
            {"spec_path": None, "port": 51440},
        ),
        (
            "flaky_detect",
            {"cwd": root, "command": "pytest -q", "runs": 4, "timeout": 20},
            "/api/command/flaky_detect",
            {
                "cwd": root,
                "root": root,
                "command": "pytest -q",
                "runs": 4,
                "timeout": 20,
            },
            "test_flaky_detect",
            (root, "pytest -q"),
            {"runs": 4, "timeout_per_run": 20},
        ),
    ]
    calls = _observe(client)
    for method, kwargs, route, payload, service_name, args, service_kwargs in cases:
        calls.clear()
        result = getattr(client, method)(**kwargs)
        assert result["success"] is True
        assert result["service"] == service_name
        assert isinstance(result.get("request_id"), str) and result["request_id"]
        assert set(result) == {"success", "service", "request_id"}
        assert calls == [{"method": "POST", "path": route, "payload": payload}]
        assert received[service_name] == (args, service_kwargs)
