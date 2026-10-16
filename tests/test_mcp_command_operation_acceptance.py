from __future__ import annotations

from typing import Any, Literal
import pytest

from local_ai_hub import mcp_server


class _CommandBackend:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def post(self, path: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self.calls.append((path, payload, kwargs))
        return self.response


def _enable_command(monkeypatch: Any, backend: _CommandBackend) -> None:
    monkeypatch.setattr(mcp_server, "CLIENT", backend)
    monkeypatch.setattr(mcp_server.FEATURES, "commands", True)
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", False)
    monkeypatch.setattr(mcp_server, "_timeout", lambda kind: 77.0)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    monkeypatch.setattr(
        mcp_server,
        "load_operational_mode",
        lambda _state_dir: mcp_server.OperationalModeSnapshot("active", 1, None),
    )


def _expected_payload(action: str, root: str, command: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": action,
        "command": command,
        "cwd": root,
        "root": root,
        "timeout": 25,
        "force": False,
        "task_id": "",
        "criterion": "",
        "auto_fix": False,
        "max_attempts": 3,
        "stream": False,
        "stream_id": "",
        "execution_id": "",
        "snapshot": False,
        "rollback_on_failure": False,
        "paths": None,
        "patch": "",
        "auto_rollback": True,
        "runs": 5,
        "env": {},
    }
    payload.update(overrides)
    return payload


def _assert_response_fields(
    result: dict[str, Any], expected: dict[str, Any], *, requested_tokens: int | None = None
) -> None:
    for key, value in expected.items():
        assert result.get(key) == value
    budget = result.get("response_budget")
    if budget is not None:
        assert isinstance(budget, dict)
        if requested_tokens is not None:
            assert budget["requested_tokens"] == requested_tokens
        else:
            assert budget["requested_tokens"] >= 128
        assert 0 <= budget["returned_tokens"] <= budget["requested_tokens"]


@pytest.mark.parametrize("explicit_root", [False, True])
def test_mcp_command_keeps_project_root_distinct_from_execution_cwd(
    monkeypatch: Any, tmp_path: Any, explicit_root: bool
) -> None:
    backend = _CommandBackend({"success": True, "allowed": True})
    _enable_command(monkeypatch, backend)
    workspace = tmp_path / "workspace"
    project = tmp_path / "project"
    execution_dir = project / "src"
    workspace.mkdir()
    execution_dir.mkdir(parents=True)
    monkeypatch.setattr(mcp_server, "_workspace", str(workspace))
    root_args = {"root": str(project)} if explicit_root else {}

    result = mcp_server.local_ai_command(
        action="classify", command="git status --short", cwd=str(execution_dir),
        timeout=25, **root_args,
    )

    expected_root = str(project if explicit_root else workspace)
    assert backend.calls == [
        (
            "/api/command",
            _expected_payload("classify", expected_root, "git status --short", cwd=str(execution_dir)),
            {"timeout": 77.0},
        )
    ]
    assert result["success"] is True


def test_mcp_command_auto_fix_forwards_bounded_repair_policy(monkeypatch: Any, tmp_path: Any) -> None:
    response = {"success": True, "status": "fixed", "changed_paths": ["src/parser.py"], "attempts": 2}
    backend = _CommandBackend(response)
    _enable_command(monkeypatch, backend)
    root = str(tmp_path)

    result = mcp_server.local_ai_command(
        action="auto_fix",
        command="pytest tests/test_parser.py",
        cwd=root,
        root=root,
        timeout=25,
        task_id="task-1",
        criterion="parser regression passes",
        auto_fix=True,
        max_attempts=2,
        auto_rollback=False,
    )

    assert len(backend.calls) == 1
    command_call = backend.calls[0]
    assert command_call == (
        "/api/command",
        _expected_payload(
            "auto_fix",
            root,
            "pytest tests/test_parser.py",
            task_id="task-1",
            criterion="parser regression passes",
            auto_fix=True,
            max_attempts=2,
            auto_rollback=False,
        ),
        {"timeout": 77.0},
    )
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_command_cancel_targets_execution_and_returns_cancel_state(monkeypatch: Any, tmp_path: Any) -> None:
    response = {"success": True, "status": "cancelled", "cancelled": True, "execution_id": "exec-42"}
    backend = _CommandBackend(response)
    _enable_command(monkeypatch, backend)
    root = str(tmp_path)

    result = mcp_server.local_ai_command(
        action="cancel", cwd=root, root=root, timeout=25, execution_id="exec-42", stream_id="stream-42"
    )

    assert backend.calls == [
        (
            "/api/command",
            _expected_payload(
                "cancel", root, "", execution_id="exec-42", stream_id="stream-42"
            ),
            {"timeout": 77.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_command_classify_preserves_classification_result(monkeypatch: Any, tmp_path: Any) -> None:
    response = {
        "success": True,
        "classification": {"kind": "read_only", "confidence": 0.98, "requires_confirmation": False},
    }
    backend = _CommandBackend(response)
    _enable_command(monkeypatch, backend)
    root = str(tmp_path)

    result = mcp_server.local_ai_command(
        action="classify",
        command="git status --short",
        cwd=root,
        root=root,
        timeout=25,
    )

    assert backend.calls == [
        ("/api/command", _expected_payload("classify", root, "git status --short"), {"timeout": 77.0})
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_command_discover_returns_command_candidates(monkeypatch: Any, tmp_path: Any) -> None:
    response = {"success": True, "status": "discovered", "candidates": ["ruff check", "ruff format"]}
    backend = _CommandBackend(response)
    _enable_command(monkeypatch, backend)
    root = str(tmp_path)

    result = mcp_server.local_ai_command(action="discover", command="ruff", cwd=root, root=root, timeout=25)

    assert backend.calls == [
        ("/api/command", _expected_payload("discover", root, "ruff"), {"timeout": 77.0})
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_command_flaky_detect_forwards_test_selector_and_attempt_limit(
    monkeypatch: Any, tmp_path: Any
) -> None:
    response = {
        "success": True,
        "status": "analyzed",
        "flaky_tests": [{"selector": "tests/test_cache.py::test_refresh", "failures": 2, "runs": 8}],
    }
    backend = _CommandBackend(response)
    _enable_command(monkeypatch, backend)
    root = str(tmp_path)

    result = mcp_server.local_ai_command(
        action="flaky_detect",
        command="tests/test_cache.py::test_refresh",
        cwd=root,
        root=root,
        timeout=25,
        max_attempts=8,
    )

    assert backend.calls == [
        (
            "/api/command",
            _expected_payload(
                "flaky_detect", root, "tests/test_cache.py::test_refresh", max_attempts=8
            ),
            {"timeout": 77.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_command_format_forwards_source_path_and_accepts_budget_metadata(
    monkeypatch: Any, tmp_path: Any
) -> None:
    response = {
        "success": True,
        "status": "formatted",
        "formatted_paths": ["src/parser.py"],
        "artifact_id": "format-run-9",
    }
    backend = _CommandBackend(response)
    _enable_command(monkeypatch, backend)
    root = str(tmp_path)

    result = mcp_server.local_ai_command(
        action="format",
        command="src/parser.py",
        cwd=root,
        root=root,
        paths=["src/parser.py"],
        timeout=25,
        max_response_tokens=300,
        response_profile="compact",
        reuse_key="command:format:parser",
    )

    assert backend.calls == [
        (
            "/api/command",
            _expected_payload("format", root, "src/parser.py", paths=["src/parser.py"]),
            {"timeout": 77.0},
        )
    ]
    _assert_response_fields(result, response, requested_tokens=300)
    assert result["success"] is True


def test_mcp_command_http_probe_forwards_target_and_returns_probe_status(monkeypatch: Any, tmp_path: Any) -> None:
    response = {"success": True, "status": "reachable", "status_code": 204, "target": "https://hub.test/health"}
    backend = _CommandBackend(response)
    _enable_command(monkeypatch, backend)
    root = str(tmp_path)

    result = mcp_server.local_ai_command(
        action="http_probe", command="https://hub.test/health", cwd=root, root=root, timeout=25, force=True
    )

    assert backend.calls == [
        (
            "/api/command",
            _expected_payload("http_probe", root, "https://hub.test/health", force=True),
            {"timeout": 77.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_command_run_affected_forwards_task_acceptance_context(monkeypatch: Any, tmp_path: Any) -> None:
    response = {
        "success": True,
        "status": "passed",
        "task_id": "task-affected-3",
        "affected_tests": ["tests/test_command.py::test_router"],
        "exit_code": 0,
    }
    backend = _CommandBackend(response)
    _enable_command(monkeypatch, backend)
    root = str(tmp_path)

    result = mcp_server.local_ai_command(
        action="run_affected",
        command="pytest -q",
        cwd=root,
        root=root,
        timeout=25,
        task_id="task-affected-3",
        criterion="command router behavior",
    )

    assert backend.calls == [
        (
            "/api/command",
            _expected_payload(
                "run_affected",
                root,
                "pytest -q",
                task_id="task-affected-3",
                criterion="command router behavior",
            ),
            {"timeout": 77.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


@pytest.mark.parametrize("port_command,expected_port", [("11441", 11441), ("0", 0), ("", 0)])
def test_mcp_command_mock_server_start_uses_dedicated_endpoint_and_port(
    monkeypatch: Any, tmp_path: Any, port_command: str, expected_port: int
) -> None:
    response = {"success": True, "status": "started", "port": 11441, "pid": 912}
    backend = _CommandBackend(response)
    _enable_command(monkeypatch, backend)
    root = str(tmp_path)

    result = mcp_server.local_ai_command(
        action="mock_server_start", command=port_command, cwd=root, root=root, criterion="tests/fixtures/openapi.json"
    )

    assert backend.calls == [
        (
            "/api/command/mock_server",
            {"action": "start", "root": root, "port": expected_port, "spec_path": "tests/fixtures/openapi.json"},
            {"timeout": 77.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_command_stop_daemon_forwards_daemon_identity(monkeypatch: Any, tmp_path: Any) -> None:
    response = {"success": True, "status": "stopped", "daemon_id": "daemon-17"}
    backend = _CommandBackend(response)
    _enable_command(monkeypatch, backend)
    root = str(tmp_path)

    result = mcp_server.local_ai_command(
        action="stop_daemon",
        command="daemon-17",
        cwd=root,
        root=root,
        timeout=25,
    )

    assert backend.calls == [
        (
            "/api/command",
            _expected_payload("stop_daemon", root, "daemon-17"),
            {"timeout": 77.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True


def test_mcp_command_speculative_lint_submits_bounded_paths_and_job_identity(
    monkeypatch: Any, tmp_path: Any
) -> None:
    response = {"success": True, "status": "queued", "lint_job_id": "lint-job-7"}
    backend = _CommandBackend(response)
    _enable_command(monkeypatch, backend)
    monkeypatch.setattr(mcp_server.FEATURES, "speculative_lint", True)
    monkeypatch.setattr(
        mcp_server,
        "CommandAction",
        Literal.__getitem__(tuple((*mcp_server.CommandAction.__args__, "speculative_lint"))),
    )
    monkeypatch.setattr(
        mcp_server,
        "load_operational_mode",
        lambda _state_dir: mcp_server.OperationalModeSnapshot("active", 1, None),
    )
    root = str(tmp_path)

    result = mcp_server.local_ai_command(
        action="speculative_lint",
        command="ruff check",
        cwd=root,
        paths=["src/parser.py", "tests/test_parser.py"],
        lint_action="submit",
        job_id="lint-job-7",
    )

    assert backend.calls == [
        (
            "/api/command/speculative-lint",
            {
                "action": "submit",
                "root": root,
                "paths": ["src/parser.py", "tests/test_parser.py"],
                "command": "ruff check",
                "job_id": "lint-job-7",
            },
            {"timeout": 77.0},
        )
    ]
    _assert_response_fields(result, response)
    assert result["success"] is True
