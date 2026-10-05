from __future__ import annotations

import io
import json
from threading import Barrier, BrokenBarrierError, Lock
import time
from typing import Any

import pytest


def _resolve_schema(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    name = ref.rsplit("/", 1)[-1]
    definitions = root.get("$defs", root.get("definitions", {}))
    return definitions[name]


def _schema_shape(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    schema = _resolve_schema(schema, root)
    keys = ("type", "enum", "default", "minimum", "maximum", "minLength", "maxLength", "required", "additionalProperties")
    shape = {
        key: schema[key]
        for key in keys
        if key in schema and not (key == "additionalProperties" and schema[key] is True)
    }
    if isinstance(shape.get("type"), list):
        shape["type"] = sorted(shape["type"])
    if isinstance(schema.get("properties"), dict):
        shape["properties"] = {
            key: _schema_shape(value, root) for key, value in schema["properties"].items()
        }
    if isinstance(schema.get("items"), dict):
        shape["items"] = _schema_shape(schema["items"], root)
    if isinstance(schema.get("anyOf"), list):
        shape["anyOf"] = [_schema_shape(value, root) for value in schema["anyOf"]]
    return shape


@pytest.mark.parametrize(
    ("status_code", "payload", "expected_retryable"),
    [
        (400, {"error": "bad request", "detail": "preserved"}, False),
        (429, {"error": "slow down"}, True),
        (503, {"error": "backend unavailable", "retryable": False}, False),
    ],
)
def test_normalize_transport_error_exposes_client_retry_contract(
    status_code: int, payload: Any, expected_retryable: bool
) -> None:
    from local_ai_hub.operation_contracts import normalize_transport_error

    result = normalize_transport_error(status_code, payload)

    assert result["success"] is False
    assert result["status_code"] == status_code
    assert result["retryable"] is expected_retryable
    assert result["terminal"] is not expected_retryable
    if isinstance(payload, dict) and "detail" in payload:
        assert result["detail"] == payload["detail"]


def test_http_mutation_registry_journals_only_explicit_mutations() -> None:
    from local_ai_hub.operation_contracts import http_operation_needs_replay

    cases = [
        ("POST", "/api/rag/index", {}, True),
        ("POST", "/api/rag/ingest_document", {}, True),
        ("POST", "/api/ingest_document", {}, True),
        ("POST", "/api/command", {"command": "python -m pytest"}, True),
        ("POST", "/api/command", {"command": "   "}, False),
        ("POST", "/api/command", {}, False),
        ("POST", "/api/command", {"command": None}, False),
        ("POST", "/api/command", {"command": 0}, False),
        ("POST", "/api/command", {"command": []}, False),
        ("POST", "/api/command", {"command": {"argv": ["pytest"]}}, False),
        ("POST", "/api/coord/pubsub_publish", {}, True),
        ("POST", "/api/pubsub_publish", {}, True),
        ("POST", "/api/coord/pubsub_poll", {}, False),
        ("POST", "/api/agent-state/tasks", {"action": "checkpoint"}, True),
        ("POST", "/api/agent-state/tasks", {"action": "complete"}, False),
        ("POST", "/api/work-orders", {}, True),
        ("POST", "/api/work-orders", {"action": "list"}, False),
        ("GET", "/api/rag/index", {}, False),
        ("POST", "/api/context/pack", {"query": "fresh context"}, False),
    ]

    for method, path, payload, expected in cases:
        assert http_operation_needs_replay(method, path, payload) is expected, (method, path, payload)


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/rag/index", {"root": "."}),
        ("/api/rag/ingest_document", {"content": "document"}),
        ("/api/ingest_document", {"content": "document"}),
        ("/api/command", {"command": "python -m pytest"}),
        ("/api/coord/pubsub_publish", {"topic": "t03", "message": {"value": 1}}),
        ("/api/pubsub_publish", {"topic": "t03", "message": {"value": 1}}),
        ("/api/agent-state/tasks", {"action": "checkpoint", "task_id": "t03"}),
        ("/api/work-orders", {}),
        ("/api/work-orders", {"action": "submit"}),
    ],
)
def test_registered_http_mutation_routes_enter_recovery_before_dispatch(
    path: str, payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from local_ai_hub import http_server

    class Recovery:
        def __init__(self) -> None:
            self.begin_calls: list[tuple[str, str, dict[str, Any]]] = []

        def validate_request_id(self, _request_id: str) -> None:
            return None

        def begin(
            self,
            request_id: str,
            tenant: str,
            action: str,
            *,
            identity: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            assert identity == "agent-a"
            self.begin_calls.append((request_id, action, payload))
            return {"claimed": False, "state": "conflict", "error": "replayed by test"}

    recovery = Recovery()
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={}, recovery=recovery),
    )
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = path
    handler.headers = {
        "Content-Type": "application/json",
        "X-LocalAI-Request-ID": "t03-route-recovery",
    }
    handler._begin_trace = lambda _path: setattr(handler, "_trace_request_id", "t03-route-recovery")
    handler._require_authorized = lambda: True
    handler._tenant = lambda: "tenant-a"
    handler._agent = lambda: "agent-a"
    handler._read_json = lambda limit=None: payload
    handler._validate_payload = lambda _path, _payload: None
    responses: list[tuple[int, dict[str, Any]]] = []
    handler._send = lambda status, body: responses.append((status, body))

    handler.do_POST()

    assert responses == [
        (
            409,
            {
                "success": False,
                "error": "replayed by test",
                "request_id": "t03-route-recovery",
            },
        )
    ]
    assert recovery.begin_calls == [("t03-route-recovery", path, payload)]


def test_repo_pipeline_schema_exposes_runtime_step_contract() -> None:
    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.generator import generate_mcp_tool_schemas

    runtime = mcp_server.mcp._tool_manager._tools["local_ai_repo"].parameters
    generated = generate_mcp_tool_schemas({})["local_ai_repo"]["parameters"]
    runtime_properties = runtime["properties"]
    generated_properties = generated["properties"]
    assert "steps" in runtime_properties
    assert "steps" in generated_properties
    runtime_steps = _resolve_schema(runtime_properties["steps"]["items"], runtime)
    generated_steps = _resolve_schema(generated_properties["steps"]["items"], generated)
    assert runtime_steps["required"] == generated_steps["required"] == ["action"]
    assert runtime_steps["additionalProperties"] is generated_steps["additionalProperties"] is False
    assert set(runtime_steps["properties"]) == set(generated_steps["properties"])
    for field in runtime_steps["properties"]:
        assert _schema_shape(runtime_steps["properties"][field], runtime) == _schema_shape(
            generated_steps["properties"][field], generated
        ), f"pipeline step schema differs for {field}"
    step_properties = generated_steps["properties"]
    assert set(step_properties["action"]["enum"]) == set(generated_properties["action"]["enum"]) - {"pipeline"}
    assert set(step_properties) == set(generated_properties) - {"steps", "path_hints"} | {"id"}
    assert runtime_steps["additionalProperties"] is False


def test_repo_pipeline_preserves_duplicate_results_and_nested_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import local_ai_hub.mcp_server as mcp_server

    failure = {
        "success": False,
        "terminal": True,
        "retryable": False,
        "degraded": True,
        "stale": True,
        "evidence": [{"id": "E-failure"}],
        "cancel": {"requested": False},
        "error": "verification failed",
    }

    class FakeClient:
        def post(self, endpoint: str, payload: dict[str, Any], timeout: int | None = None):
            if endpoint == "/api/evidence/verify":
                return failure
            if endpoint == "/api/repo/affected_tests":
                paths = payload.get("paths") or ["test.py"]
                return {"success": True, "affected": paths}
            raise AssertionError(f"unexpected endpoint: {endpoint}")

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    result = mcp_server._local_ai_repo_impl(
        action="pipeline",
        root=str(tmp_path),
        steps=[
            {"action": "affected_tests", "path": "a.py"},
            {"action": "verify", "evidence": [{"id": "E-failure"}]},
            {"action": "affected_tests", "path": "b.py"},
        ],
    )

    assert result["success"] is False
    assert result["steps_total"] == result["steps_attempted"] == 3
    assert result["steps_completed"] == 3
    assert result["steps_failed"] == 1
    assert [step["index"] for step in result["step_results"]] == [0, 1, 2]
    assert [step["action"] for step in result["step_results"]] == [
        "affected_tests",
        "verify",
        "affected_tests",
    ]
    assert [step["id"] for step in result["step_results"]] == [
        "step-0",
        "step-1",
        "step-2",
    ]
    assert result["step_results"][0]["result"]["affected"] == ["a.py"]
    for key, expected in failure.items():
        assert result["step_results"][1]["result"][key] == expected
    assert result["step_results"][2]["result"]["affected"] == ["b.py"]
    assert result["results"]["affected_tests"]["affected"] == ["b.py"]


def test_pipeline_compaction_preserves_failure_and_cancel_metadata(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import local_ai_hub.mcp_server as mcp_server

    metadata = {
        "success": False,
        "terminal": True,
        "retryable": False,
        "degraded": True,
        "stale": True,
        "evidence": [{"id": "E-step"}],
        "cancel": {"requested": False, "cancelled": False},
    }
    class FakeClient:
        def post(self, endpoint: str, payload: dict[str, Any], timeout: int | None = None):
            assert endpoint == "/api/evidence/verify"
            return metadata

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    pipeline = mcp_server._local_ai_repo_impl(
        action="pipeline",
        root=str(tmp_path),
        steps=[{"action": "verify", "evidence": [{"id": "E-step"}]}],
    )
    result = mcp_server._compact(pipeline, "repo")

    step_metadata = result["step_results"][0]["result"]
    for key, expected in metadata.items():
        assert step_metadata[key] == expected


@pytest.mark.parametrize(
    "step",
    [
        None,
        [],
        "affected_tests",
        {},
        {"action": "not_supported"},
        {"action": "affected_tests", "unknown": True},
        {"action": "affected_tests", "max_tokens": "many"},
        {"action": "affected_tests", "max_tokens": -1},
    ],
)
def test_repo_pipeline_malformed_steps_become_bounded_per_step_errors(
    step: Any, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import local_ai_hub.mcp_server as mcp_server

    calls: list[str] = []

    class FakeClient:
        def post(self, endpoint: str, payload: dict[str, Any], timeout: int | None = None):
            calls.append(endpoint)
            if endpoint == "/api/repo/affected_tests":
                return {"success": True, "affected": payload.get("paths") or []}
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    result = mcp_server._local_ai_repo_impl(
        action="pipeline",
        root=str(tmp_path),
        steps=[step, {"action": "affected_tests", "path": "healthy.py"}],
    )

    assert result["success"] is False
    assert result["steps_total"] == 2
    assert result["steps_attempted"] == 2
    assert result["steps_completed"] == 2
    assert result["steps_failed"] == 1
    step_result = result["step_results"][0]
    assert step_result["index"] == 0
    assert step_result["id"] == "step-0"
    assert step_result["result"]["status_code"] == 400
    assert step_result["result"]["terminal"] is True
    assert step_result["result"]["retryable"] is False
    assert step_result["result"]["error"]
    assert result["step_results"][1]["result"]["affected"] == ["healthy.py"]
    assert calls == ["/api/repo/affected_tests"]


def test_repo_pipeline_caps_parallel_steps_at_four(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import local_ai_hub.mcp_server as mcp_server

    original = mcp_server._local_ai_repo_impl
    lock = Lock()
    barrier = Barrier(4)
    active = 0
    peak = 0

    def fake_impl(*, action: str, **kwargs: Any) -> dict[str, Any]:
        nonlocal active, peak
        if action == "pipeline":
            return original(action=action, **kwargs)
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            step_index = int(kwargs.get("path", "step-0").removeprefix("step-"))
            if step_index < 4:
                barrier.wait(timeout=2)
            else:
                time.sleep(0.02)
            return {"success": True, "step": step_index}
        except BrokenBarrierError:
            return {"success": False, "error": "concurrency rendezvous failed"}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(mcp_server, "_local_ai_repo_impl", fake_impl)
    result = fake_impl(
        action="pipeline",
        root=str(tmp_path),
        steps=[{"action": "affected_tests", "path": f"step-{i}"} for i in range(6)],
    )

    assert peak == 4
    assert result["steps_attempted"] == 6
    assert len(result["step_results"]) == 6


@pytest.mark.parametrize(
    "mutation_action",
    (
        "batch_replace",
        "ast_refactor",
        "preprocess",
        "preprocess_refresh",
        "preprocess_pause",
        "preprocess_resume",
        "preprocess_cancel",
        "preprocess_unregister",
    ),
)
def test_repo_pipeline_serializes_mutating_steps(
    tmp_path, monkeypatch: pytest.MonkeyPatch, mutation_action: str
) -> None:
    import local_ai_hub.mcp_server as mcp_server

    original = mcp_server._local_ai_repo_impl
    lock = Lock()
    active = 0
    peak = 0

    def fake_impl(*, action: str, **kwargs: Any) -> dict[str, Any]:
        nonlocal active, peak
        if action == "pipeline":
            return original(action=action, **kwargs)
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.02)
            return {"success": True, "action": action}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(mcp_server, "_local_ai_repo_impl", fake_impl)
    supported_actions = mcp_server.FEATURES.supported_repo_actions()
    monkeypatch.setattr(
        mcp_server.FEATURES,
        "supported_repo_actions",
        lambda: [*supported_actions, mutation_action],
    )
    result = fake_impl(
        action="pipeline",
        root=str(tmp_path),
        steps=[
            {"action": mutation_action},
            {"action": "affected_tests"},
        ],
    )

    assert peak == 1
    assert result["steps_attempted"] == 2
    assert len(result["step_results"]) == 2


def test_mcp_rejects_malformed_pipeline_before_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import local_ai_hub.mcp_server as mcp_server

    class NeverCallClient:
        def post(self, *args: Any, **kwargs: Any):
            raise AssertionError("malformed pipeline reached the backend")

    monkeypatch.setattr(mcp_server, "CLIENT", NeverCallClient())
    blocks, payload = asyncio.run(
        mcp_server.mcp.call_tool(
            "local_ai_repo",
            {"action": "pipeline", "steps": [{"action": "affected_tests", "unknown": True}]},
        )
    )

    assert payload["status_code"] == 400
    assert payload["terminal"] is True
    assert payload["retryable"] is False
    assert "unsupported fields" in payload["error"]
    assert blocks[0].type == "text"


@pytest.mark.parametrize("include_code", [False, True])
def test_repo_investigate_preserves_include_code_flag(
    include_code: bool, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import local_ai_hub.mcp_server as mcp_server

    requests: list[dict[str, Any]] = []

    class FakeClient:
        def post(self, path: str, payload: dict[str, Any], **kwargs: Any):
            requests.append({"path": path, "payload": payload})
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    mcp_server._local_ai_repo_impl(
        action="investigate", root=str(tmp_path), include_code=include_code
    )
    assert requests[0]["payload"]["include_code"] is include_code


@pytest.mark.parametrize(
    "override",
    [{"phase": "explore"}, {"max_tokens": -1}, {"max_response_tokens": 100001}],
)
def test_mcp_rejects_invalid_phase_and_numeric_bounds_before_handler(
    override: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import local_ai_hub.mcp_server as mcp_server

    class NeverCallClient:
        def post(self, *args: Any, **kwargs: Any):
            raise AssertionError("invalid arguments reached the backend")

    monkeypatch.setattr(mcp_server, "CLIENT", NeverCallClient())
    arguments = {
        "action": "pipeline",
        "steps": [{"action": "affected_tests"}],
        **override,
    }
    _blocks, payload = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", arguments))
    assert payload["status_code"] == 400
    assert payload["terminal"] is True
    assert payload["retryable"] is False


def test_mcp_repo_rejects_pipeline_steps_for_non_pipeline_action_before_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio
    import local_ai_hub.mcp_server as mcp_server

    class NeverCallClient:
        def post(self, *args: Any, **kwargs: Any):
            raise AssertionError("cross-action pipeline fields reached the backend")

    monkeypatch.setattr(mcp_server, "CLIENT", NeverCallClient())
    _blocks, payload = asyncio.run(
        mcp_server.mcp.call_tool(
            "local_ai_repo",
            {
                "action": "context",
                "root": str(tmp_path),
                "query": "valid context query",
                "steps": [{"action": "affected_tests"}],
            },
        )
    )

    assert payload["status_code"] == 400
    assert payload["terminal"] is True
    assert payload["retryable"] is False


def test_mcp_repo_action_schema_scopes_pipeline_steps() -> None:
    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.operation_contracts import validate_action_specific_fields

    schema = mcp_server._mcp_contract_schema("local_ai_repo")
    assert schema is not None
    action_rule = next(
        rule for rule in schema.get("allOf", [])
        if rule.get("then", {}).get("properties") == {"steps": {}}
    )
    assert action_rule["if"]["properties"]["action"]["const"] == "pipeline"
    assert validate_action_specific_fields(
        "local_ai_repo", {"action": "context", "steps": []}
    ) == "arguments.steps is only valid for action pipeline"
    assert validate_action_specific_fields(
        "local_ai_repo", {"action": "pipeline", "steps": []}
    ) is None


def test_repo_path_hints_schema_is_bounded_and_scoped() -> None:
    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.generator import generate_mcp_tool_schemas
    from local_ai_hub.operation_contracts import (
        validate_action_specific_fields,
        validate_schema_object,
    )

    live_schema = mcp_server._mcp_contract_schema("local_ai_repo")
    generated_schema = generate_mcp_tool_schemas({})["local_ai_repo"]["parameters"]
    assert live_schema is not None

    for schema in (live_schema, generated_schema):
        field = schema["properties"]["path_hints"]
        assert field["type"] == "array"
        assert field["maxItems"] == 64
        item = field["items"]
        assert item["required"] == ["path", "purpose", "scope"]
        assert set(item["properties"]) == {
            "path", "purpose", "scope", "evidence_id", "provenance",
            "repository_revision", "config_digest", "expires_at",
        }
        assert item["properties"]["purpose"]["enum"] == ["repository_search"]
        assert item["properties"]["scope"]["enum"] == ["repo_search"]
        assert item["properties"]["path"]["minLength"] == 1
        assert item["properties"]["path"]["maxLength"] == 1024
        assert item["additionalProperties"] is False
        assert "path_hints" not in schema["properties"]["steps"]["items"]["properties"]

    valid = {
        "action": "search",
        "path_hints": [{
            "path": "src/auth.py",
            "purpose": "repository_search",
            "scope": "repo_search",
        }],
    }
    assert validate_schema_object(valid, live_schema) is None
    assert validate_action_specific_fields("local_ai_repo", valid, schema=live_schema) is None
    assert validate_schema_object(
        {"action": "search", "path_hints": [{
            "path": "src/auth.py", "purpose": "internal_context", "scope": "repo_search",
        }]},
        live_schema,
    ) is not None
    assert validate_schema_object(
        {"action": "search", "path_hints": [{
            "path": "src/auth.py", "purpose": "repository_search", "scope": "context",
        }]},
        live_schema,
    ) is not None
    context_hint = {"action": "context", "mode": "adaptive", "path_hints": []}
    assert validate_action_specific_fields(
        "local_ai_repo", context_hint, schema=live_schema
    ) == "arguments.path_hints is only valid for action search"
    assert validate_schema_object(
        {"action": "search", "path_hints": [{"path": "src/auth.py", "purpose": "repository_search"}]},
        live_schema,
    ) is not None
    assert validate_schema_object(
        {"action": "search", "path_hints": [{"path": "x" * 1025, "purpose": "repository_search", "scope": "repo_search"}]},
        live_schema,
    ) is not None
    assert validate_schema_object(
        {"action": "search", "path_hints": [{"path": "x", "purpose": "repository_search", "scope": "repo_search", "other": "value"}]},
        live_schema,
    ) is not None
    assert validate_schema_object(
        {"action": "search", "path_hints": [{"path": "x"}] * 65}, live_schema
    ) is not None


def test_repo_context_hint_fields_are_adaptive_context_only() -> None:
    from local_ai_hub.operation_contracts import validate_action_specific_fields

    context_fields = ("directory_hints", "exclude_paths", "force_include_paths")
    for field in context_fields:
        assert validate_action_specific_fields(
            "local_ai_repo", {"action": "context", "mode": "adaptive", field: []}
        ) is None
        assert validate_action_specific_fields(
            "local_ai_repo", {"action": "context", field: []}
        ) is None

    assert validate_action_specific_fields(
        "local_ai_repo", {"action": "search", "directory_hints": []}
    ) == "arguments.directory_hints is only valid for action context"
    assert validate_action_specific_fields(
        "local_ai_repo", {"action": "context", "mode": "fast", "exclude_paths": []}
    ) == "arguments.exclude_paths requires mode adaptive for action context"
    assert validate_action_specific_fields(
        "local_ai_repo", {"action": "context", "mode": "custom", "path_hints": []}
    ) == "arguments.path_hints is only valid for action search"
    for field in context_fields:
        assert validate_action_specific_fields(
            "local_ai_repo", {"action": "context", "mode": "fast", field: None}
        ) == f"arguments.{field} requires mode adaptive for action context"


def test_local_ai_repo_path_hints_forward_only_when_consumer_supports_them(monkeypatch) -> None:
    import inspect

    from local_ai_hub import mcp_server

    hints = [{"path": "src/auth.py", "purpose": "repository_search", "scope": "repo_search"}]
    captured = {}

    def supported_consumer(*args, path_hints=None):
        captured["args"] = args
        captured["path_hints"] = path_hints
        return {"success": True}

    monkeypatch.setattr(mcp_server, "_local_ai_repo_impl", supported_consumer)
    assert "path_hints" in inspect.signature(mcp_server.local_ai_repo).parameters
    assert mcp_server.local_ai_repo("search", path_hints=hints)["success"] is True
    assert captured["path_hints"] == hints

    def unsupported_consumer(*args):
        raise AssertionError("unsupported consumer must not be called")

    monkeypatch.setattr(mcp_server, "_local_ai_repo_impl", unsupported_consumer)
    response = mcp_server.local_ai_repo("search", path_hints=hints)
    assert response["success"] is False
    assert response["unsupported"] is True

    def positional_only_consumer(path_hints, /, **kwargs):
        raise AssertionError("positional-only consumer must not receive keyword hints")

    monkeypatch.setattr(mcp_server, "_local_ai_repo_impl", positional_only_consumer)
    response = mcp_server.local_ai_repo("search", path_hints=hints)
    assert response["success"] is False
    assert response["unsupported"] is True


@pytest.mark.parametrize(
    ("root", "hint_path"),
    [
        ("C:/docs", r"C:\docs\sub"),
        (r"C:\docs", "C:/docs/sub"),
    ],
)
def test_local_ai_repo_search_normalizes_windows_path_hints_within_root(
    root: str, hint_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from local_ai_hub import mcp_server

    captured: dict[str, Any] = {}

    def supported_consumer(*args: Any, path_hints: list[dict[str, str]] | None = None):
        captured["args"] = args
        captured["path_hints"] = path_hints
        return {"success": True}

    monkeypatch.setattr(mcp_server, "_local_ai_repo_impl", supported_consumer)
    result = mcp_server.local_ai_repo(
        "search",
        root=root,
        path_hints=[{"path": hint_path, "purpose": "repository_search", "scope": "repo_search"}],
    )

    assert result["success"] is True
    assert captured["path_hints"][0]["path"] == "sub"


@pytest.mark.parametrize(
    "hint_path",
    ["../secret", "C:/outside/secret", r"C:\docs\..\outside\secret"],
)
def test_local_ai_repo_search_rejects_path_hints_outside_root_before_dispatch(
    hint_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from local_ai_hub import mcp_server

    calls: list[tuple[Any, ...]] = []

    def supported_consumer(*args: Any, path_hints: list[dict[str, str]] | None = None):
        calls.append(args)
        return {"success": True}

    monkeypatch.setattr(mcp_server, "_local_ai_repo_impl", supported_consumer)
    result = mcp_server.local_ai_repo(
        "search",
        root="C:/docs",
        path_hints=[{"path": hint_path, "purpose": "repository_search", "scope": "repo_search"}],
    )

    assert result["success"] is False
    assert result["status_code"] == 400
    assert calls == []


def test_local_ai_repo_search_rejects_backslash_traversal_for_posix_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from local_ai_hub import mcp_server

    calls: list[tuple[Any, ...]] = []

    def supported_consumer(*args: Any, path_hints: list[dict[str, str]] | None = None):
        calls.append(args)
        return {"success": True}

    monkeypatch.setattr(mcp_server, "_client_root", lambda _root: "/repo/docs")
    monkeypatch.setattr(mcp_server, "_local_ai_repo_impl", supported_consumer)
    result = mcp_server.local_ai_repo(
        "search",
        root="/repo/docs",
        path_hints=[{"path": r"..\secret", "purpose": "repository_search", "scope": "repo_search"}],
    )

    assert result["success"] is False
    assert result["status_code"] == 400
    assert calls == []


def test_repo_verify_receipt_schema_is_typed_and_action_scoped() -> None:
    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.generator import generate_mcp_tool_schemas
    from local_ai_hub.operation_contracts import validate_action_specific_fields, validate_schema_object

    live_schema = mcp_server._mcp_contract_schema("local_ai_repo")
    generated_schema = generate_mcp_tool_schemas({})["local_ai_repo"]["parameters"]
    assert live_schema is not None

    for schema in (live_schema, generated_schema):
        receipt_schema = schema["properties"]["receipt"]
        assert receipt_schema["type"] == "object"
        assert receipt_schema["required"] == ["task_id", "criterion", "passed"]
        assert receipt_schema["properties"]["passed"]["type"] == "boolean"
        assert receipt_schema["properties"]["observed_at"]["type"] == "number"
        assert receipt_schema["properties"]["expires_at"]["type"] == ["number", "null"]
        assert "verify_receipt" in schema["properties"]["action"]["enum"]

        valid = {
            "action": "verify_receipt",
            "receipt": {"task_id": "task-1", "criterion": "focused test", "passed": False},
        }
        assert validate_schema_object(valid, schema) is None
        assert validate_action_specific_fields("local_ai_repo", valid, schema=schema) is None

        missing_passed = {"action": "verify_receipt", "receipt": {"task_id": "task-1", "criterion": "focused test"}}
        assert validate_schema_object(missing_passed, schema) is not None
        wrong_passed = {
            "action": "verify_receipt",
            "receipt": {"task_id": "task-1", "criterion": "focused test", "passed": "false"},
        }
        assert validate_schema_object(wrong_passed, schema) is not None
        passed_without_evidence = {
            "action": "verify_receipt",
            "receipt": {"task_id": "task-1", "criterion": "focused test", "passed": True},
        }
        assert validate_action_specific_fields(
            "local_ai_repo", passed_without_evidence, schema=schema
        ) == "arguments.receipt.evidence_id is required for passed verification receipts"
        wrong_action = {
            "action": "search",
            "receipt": {"task_id": "task-1", "criterion": "focused test", "passed": False},
        }
        assert validate_action_specific_fields(
            "local_ai_repo", wrong_action, schema=schema
        ) == "arguments.receipt is only valid for action verify_receipt"


def test_action_specific_rules_follow_active_schema_fields_and_actions() -> None:
    from local_ai_hub.generator import generate_mcp_tool_schemas
    from local_ai_hub.operation_contracts import (
        action_specific_schema_constraints,
        validate_action_specific_fields,
    )

    schema = {
        "type": "object",
        "properties": {"action": {"enum": ["context", "pipeline"]}, "steps": {}},
        "additionalProperties": True,
    }
    assert validate_action_specific_fields(
        "local_ai_repo", {"action": "context", "edits": []}, schema=schema
    ) == "arguments.edits is not supported by this configuration"
    rules = action_specific_schema_constraints(
        "local_ai_repo",
        available_fields={"action", "steps"},
        available_actions={"context", "pipeline"},
    )
    assert all("edits" not in str(rule) and "dry_run" not in str(rule) for rule in rules)
    disabled_receipt_schema = {
        "type": "object",
        "properties": {"action": {"enum": ["context", "pipeline"]}, "receipt": {"type": "object"}},
        "allOf": action_specific_schema_constraints(
            "local_ai_repo",
            available_fields={"action", "receipt"},
            available_actions={"context", "pipeline"},
        ),
    }
    assert validate_action_specific_fields(
        "local_ai_repo", {"action": "context", "receipt": {}}, schema=disabled_receipt_schema
    ) == "arguments.receipt is not supported by this configuration"
    assert {"not": {"required": ["receipt"]}} in disabled_receipt_schema["allOf"]

    generated_disabled = generate_mcp_tool_schemas({"features": {"agent_os": False}})["local_ai_repo"]["parameters"]
    assert "verify_receipt" not in generated_disabled["properties"]["action"]["enum"]
    assert "receipt" in generated_disabled["properties"]
    assert {"not": {"required": ["receipt"]}} in generated_disabled.get("allOf", [])
    assert validate_action_specific_fields(
        "local_ai_repo", {"action": "context", "receipt": {}}, schema=generated_disabled
    ) == "arguments.receipt is not supported by this configuration"


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("local_ai_status", {"action": "full", "detail": "brief"}),
        ("local_ai_task", {"action": "reason", "image_artifact_id": "image-1"}),
        ("local_ai_rag", {"action": "search", "content": "unexpected ingest body"}),
        ("local_ai_command", {"action": "format", "rollback_on_failure": True}),
        ("local_ai_coord", {"action": "pubsub_publish", "after_seq": 7}),
        ("local_ai_coord", {"action": "pubsub_poll", "ttl_seconds": 1001}),
        ("local_ai_artifact", {"action": "list", "artifact_id": "artifact-1"}),
        ("local_ai_work", {"action": "status", "work_id": "work-1", "task": "ignored task"}),
    ],
)
def test_mcp_action_scoped_fields_reject_conflicts_before_handler(
    tool_name: str, arguments: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    from types import SimpleNamespace

    import local_ai_hub.mcp_server as mcp_server

    calls: list[str] = []

    async def fake_call_tool(name: str, _arguments: dict[str, Any], *, convert_result: bool = False):
        calls.append(name)
        return {"success": True}

    monkeypatch.setattr(mcp_server, "FEATURES", SimpleNamespace(enabled_tools={tool_name}))
    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    result = asyncio.run(mcp_server._compact_mcp_call_tool(tool_name, arguments))
    payload = result[1]

    assert payload["success"] is False
    assert payload["status_code"] == 400
    assert payload["terminal"] is True
    assert payload["retryable"] is False
    assert calls == []


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("local_ai_task", {"action": "continue"}),
        ("local_ai_artifact", {"action": "get"}),
        ("local_ai_work", {"action": "submit", "task": "  "}),
        ("local_ai_work", {"action": "status"}),
        ("local_ai_work", {"action": "continue", "work_id": "work-1"}),
    ],
)
def test_mcp_action_required_fields_reject_before_handler(
    tool_name: str, arguments: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    from types import SimpleNamespace

    import local_ai_hub.mcp_server as mcp_server

    calls: list[str] = []

    async def fake_call_tool(name: str, _arguments: dict[str, Any], *, convert_result: bool = False):
        calls.append(name)
        return {"success": True}

    monkeypatch.setattr(mcp_server, "FEATURES", SimpleNamespace(enabled_tools={tool_name}))
    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    result = asyncio.run(mcp_server._compact_mcp_call_tool(tool_name, arguments))
    payload = result[1]

    assert payload["success"] is False
    assert payload["status_code"] == 400
    assert payload["terminal"] is True
    assert payload["retryable"] is False
    assert calls == []


def test_action_scoped_input_defaults_and_omitted_default_actions_remain_valid() -> None:
    from local_ai_hub.operation_contracts import validate_action_specific_fields

    assert validate_action_specific_fields("local_ai_status", {"detail": "brief"}) is None
    assert validate_action_specific_fields(
        "local_ai_artifact", {"artifact_id": "artifact-1"}
    ) is None
    assert validate_action_specific_fields(
        "local_ai_rag", {"action": "search", "content": ""}
    ) is None
    assert validate_action_specific_fields(
        "local_ai_task", {"action": "reason", "image_artifact_id": ""}
    ) is None
    assert validate_action_specific_fields(
        "local_ai_coord", {"action": "pubsub_publish", "after_seq": 0}
    ) is None
    assert validate_action_specific_fields(
        "local_ai_work", {"action": "status", "work_id": "work-1", "task": "", "root": "."}
    ) is None


def test_default_action_appears_exactly_once_in_generated_schema() -> None:
    from local_ai_hub.generator import generate_mcp_tool_schemas
    from local_ai_hub.operation_contracts import ACTION_DEFAULTS

    generated = generate_mcp_tool_schemas({})
    for tool_name, default_action in ACTION_DEFAULTS.items():
        actions = generated[tool_name]["parameters"]["properties"]["action"]["enum"]
        assert actions.count(default_action) == 1, tool_name


def test_omitted_default_action_missing_field_rejects_before_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from types import SimpleNamespace

    import local_ai_hub.mcp_server as mcp_server

    calls: list[str] = []

    async def fake_call_tool(name: str, _arguments: dict[str, Any], *, convert_result: bool = False):
        calls.append(name)
        return {"success": True}

    monkeypatch.setattr(mcp_server, "FEATURES", SimpleNamespace(enabled_tools={"local_ai_artifact"}))
    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    _, payload = asyncio.run(mcp_server._compact_mcp_call_tool("local_ai_artifact", {}))

    assert payload["success"] is False
    assert payload["status_code"] == 400
    assert payload["terminal"] is True
    assert payload["retryable"] is False
    assert calls == []


def test_repo_context_rejects_empty_query_before_backend(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import local_ai_hub.mcp_server as mcp_server

    class NeverCallClient:
        def post(self, *args: Any, **kwargs: Any):
            raise AssertionError("empty context query reached the backend")

    monkeypatch.setattr(mcp_server, "CLIENT", NeverCallClient())
    result = mcp_server._local_ai_repo_impl(action="context", root=str(tmp_path))
    assert result["status_code"] == 400
    assert result["terminal"] is True
    assert result["retryable"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [("focus", "not-an-array"), ("changed_paths", 12), ("include_tests", "yes")],
)
def test_mcp_validates_nullable_top_level_field_types(field: str, value: Any) -> None:
    import local_ai_hub.mcp_server as mcp_server

    schema = mcp_server._mcp_contract_schema("local_ai_repo")
    assert schema is not None
    error = mcp_server.validate_schema_object(
        {"action": "context", field: value}, schema
    )
    assert error is not None
    assert field in error


def test_mcp_disabled_tool_returns_structured_403_before_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import local_ai_hub.mcp_server as mcp_server

    class NeverCallClient:
        def get(self, *args: Any, **kwargs: Any):
            raise AssertionError("disabled status tool reached the backend")

    monkeypatch.setattr(mcp_server.FEATURES, "status", False)
    monkeypatch.setattr(mcp_server, "CLIENT", NeverCallClient())
    blocks, payload = asyncio.run(mcp_server.mcp.call_tool("local_ai_status", {}))

    assert blocks[0].type == "text"
    assert payload["success"] is False
    assert payload["status_code"] == 403
    assert payload["terminal"] is True
    assert payload["retryable"] is False
    assert payload["unsupported"] is True


def test_mcp_backend_unavailable_preserves_retry_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import local_ai_hub.mcp_server as mcp_server

    class UnavailableClient:
        def get(self, path: str):
            return {
                "success": False,
                "hub_online": False,
                "status_code": 503,
                "terminal": False,
                "retryable": True,
                "degraded": True,
                "stale": True,
                "error": "backend unavailable",
                "runtime_stats": {},
            }

    monkeypatch.setattr(mcp_server.FEATURES, "status", True)
    monkeypatch.setattr(mcp_server, "CLIENT", UnavailableClient())
    _blocks, payload = asyncio.run(mcp_server.mcp.call_tool("local_ai_status", {}))

    assert payload["success"] is False
    assert payload["status_code"] == 503
    assert payload["terminal"] is False
    assert payload["retryable"] is True
    assert payload["degraded"] is True
    assert payload["stale"] is True
    assert payload["error"] == "backend unavailable"


def test_http_disabled_agent_state_returns_structured_403_before_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    import local_ai_hub.http_server as http_server

    class DisabledTasks:
        state_store = SimpleNamespace(enabled=False)

        def list_tasks(self, **_kwargs: Any) -> list[Any]:
            raise AssertionError("disabled HTTP task route reached the backend")

    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={}, agent_tasks=DisabledTasks()),
    )
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/agent-state/tasks"
    handler.headers = {}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    responses: list[tuple[int, dict[str, Any]]] = []
    handler._send = lambda status, payload: responses.append((status, payload))

    handler.do_GET()

    assert responses == [
        (
            403,
            {
                "success": False,
                "error": "agent_state is disabled",
                "terminal": True,
                "retryable": False,
            },
        )
    ]


def test_http_post_without_hub_returns_retryable_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import local_ai_hub.http_server as http_server
    from local_ai_hub.operation_contracts import normalize_transport_error

    monkeypatch.setattr(http_server, "APP", None)
    handler = http_server.Handler.__new__(http_server.Handler)
    responses: list[tuple[int, dict[str, Any]]] = []
    handler._send = lambda status, payload: responses.append(
        (status, normalize_transport_error(status, payload))
    )

    handler.do_POST()

    assert responses == [
        (
            503,
            {
                "success": False,
                "error": "hub starting up; please retry",
                "status_code": 503,
                "retryable": True,
                "terminal": False,
            },
        )
    ]


def test_http_missing_agent_task_returns_structured_404(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import local_ai_hub.http_server as http_server
    from local_ai_hub.operation_contracts import normalize_transport_error

    class TaskStore:
        state_store = SimpleNamespace(enabled=True)

        def get(self, _task_id: str):
            return None

    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={}, agent_tasks=TaskStore()),
    )
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/agent-state/tasks?task_id=missing"
    handler.headers = {}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    responses: list[tuple[int, dict[str, Any]]] = []
    handler._send = lambda status, payload: responses.append(
        (status, normalize_transport_error(status, payload))
    )

    handler.do_GET()

    assert responses == [
        (
            404,
            {
                "success": False,
                "error": "task not found",
                "status_code": 404,
                "terminal": True,
                "retryable": False,
            },
        )
    ]


def test_http_oversized_validated_payload_returns_structured_413(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    import local_ai_hub.http_server as http_server
    from local_ai_hub.operation_contracts import normalize_transport_error

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={}))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/chat/completions"
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {"messages": [{"role": "user", "content": "x" * 1_000_001}]}
    handler._validate_payload = http_server.Handler._validate_payload
    responses: list[tuple[int, dict[str, Any]]] = []
    handler._send = lambda status, payload: responses.append(
        (status, normalize_transport_error(status, payload))
    )

    handler.do_POST()

    assert responses == [
        (
            413,
            {
                "success": False,
                "error": "messages exceed 1000000 characters",
                "status_code": 413,
                "terminal": True,
                "retryable": False,
            },
        )
    ]


def test_http_bundle_import_requires_raw_zip_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import local_ai_hub.http_server as http_server
    from local_ai_hub.operation_contracts import normalize_transport_error

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={}))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/bundle/import"
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    responses: list[tuple[int, dict[str, Any]]] = []
    handler._send = lambda status, payload: responses.append(
        (status, normalize_transport_error(status, payload))
    )

    handler.do_POST()

    assert responses == [
        (
            415,
            {
                "success": False,
                "error": "bundle import requires raw ZIP content",
                "status_code": 415,
                "retryable": False,
                "terminal": True,
            },
        )
    ]


def test_status_alias_schema_and_runtime_match() -> None:
    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.generator import generate_mcp_tool_schemas
    from local_ai_hub.operation_contracts import STATUS_ACTIONS, STATUS_DETAILS

    runtime = mcp_server.mcp._tool_manager._tools["local_ai_status"].parameters
    generated = generate_mcp_tool_schemas({})["local_ai_status"]["parameters"]
    for field in ("action", "detail"):
        assert _schema_shape(runtime["properties"][field], runtime) == _schema_shape(
            generated["properties"][field], generated
        )
    assert tuple(runtime["properties"]["action"]["enum"]) == STATUS_ACTIONS
    assert tuple(runtime["properties"]["detail"]["enum"]) == STATUS_DETAILS


def test_status_output_schema_publishes_shared_error_envelope() -> None:
    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.operation_contracts import STATUS_ACTIONS, operation_tool_output_schema

    output_schema = mcp_server.mcp._tool_manager._tools["local_ai_status"].output_schema
    assert output_schema == operation_tool_output_schema("local_ai_status", list(STATUS_ACTIONS))
    assert output_schema["properties"]["success"] == {"type": "boolean"}
    assert output_schema["properties"]["status_code"] == {"type": "integer"}
    assert output_schema["additionalProperties"] is True
    assert "anyOf" not in output_schema


def test_mcp_foreground_client_uses_bounded_hub_autostart_on_connection_refusal(
    tmp_path, monkeypatch
) -> None:
    from urllib.error import URLError

    from local_ai_hub import client as client_module
    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.client import HubClient

    config = tmp_path / "mcp-autostart.toml"
    state_dir = (tmp_path / "state").resolve()
    config.write_text(
        "[server]\nbind='127.0.0.1'\nport=39124\nstate_dir='"
        + state_dir.as_posix()
        + "'\n[client]\nstartup_wait_seconds=1\nstartup_poll_seconds=0.05\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=True)
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    opened: list[float] = []
    spawned: list[object] = []

    def pooled_open(_method, _path, _body, _headers, timeout):
        opened.append(float(timeout))
        if len(opened) == 1:
            raise URLError("Hub daemon is not listening")
        return b'{"success":true,"hub_online":true}'

    class FakeProcess:
        @staticmethod
        def poll():
            return None

    def popen(*_args, **_kwargs):
        process = FakeProcess()
        spawned.append(process)
        return process

    assert client.auto_start is True
    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    monkeypatch.setattr(client, "_online", lambda _timeout=None: bool(spawned))
    monkeypatch.setattr(client_module.subprocess, "Popen", popen)
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)

    response = client.get("/api/live/status", timeout=0.8)

    assert response == {"success": True, "hub_online": True}
    assert len(opened) == 2
    assert len(spawned) == 1
    assert opened[1] <= 0.8


def test_client_spawn_failure_returns_false_and_cleans_start_lock(
    tmp_path, monkeypatch
) -> None:
    from local_ai_hub import client as client_module
    from local_ai_hub.client import HubClient

    state_dir = (tmp_path / "state").resolve()
    config = tmp_path / "mcp-autostart-spawn-failure.toml"
    config.write_text(
        "[server]\nbind='127.0.0.1'\nport=39125\nstate_dir='"
        + state_dir.as_posix()
        + "'\n[client]\nstartup_wait_seconds=1\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=True)

    monkeypatch.setattr(client, "_online", lambda _timeout=None: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: None)

    def fail_to_spawn(*_args, **_kwargs):
        raise OSError("python executable unavailable")

    monkeypatch.setattr(client_module.subprocess, "Popen", fail_to_spawn)

    assert client.ensure_server(timeout=0.5) is False
    assert not (state_dir / "hub.start.lock").exists()


def test_status_alias_enums_are_present_in_mcp_tools_list_response() -> None:
    import asyncio

    import mcp.types as mcp_types

    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.generator import generate_mcp_tool_schemas
    from local_ai_hub.operation_contracts import STATUS_ACTIONS, STATUS_DETAILS

    request = mcp_types.ListToolsRequest(method="tools/list")
    response = asyncio.run(
        mcp_server.mcp._mcp_server.request_handlers[mcp_types.ListToolsRequest](request)
    )
    assert hasattr(response, "root")
    wire_result = response.root.model_dump(mode="json", by_alias=True)
    status_tool = next(tool for tool in wire_result["tools"] if tool["name"] == "local_ai_status")
    wire_parameters = status_tool["inputSchema"]
    wire_output_schema = status_tool["outputSchema"]
    generated_parameters = generate_mcp_tool_schemas(mcp_server.CFG)["local_ai_status"]["parameters"]

    assert wire_parameters["properties"]["action"]["enum"] == list(STATUS_ACTIONS)
    assert wire_parameters["properties"]["detail"]["enum"] == list(STATUS_DETAILS)
    assert wire_parameters["properties"]["action"]["enum"] == generated_parameters["properties"]["action"]["enum"]
    assert wire_parameters["properties"]["detail"]["enum"] == generated_parameters["properties"]["detail"]["enum"]
    assert wire_output_schema == mcp_server.mcp._tool_manager._tools["local_ai_status"].output_schema


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("local_ai_task", {
            "action": "reason", "phase": "review", "focus": ["src/local_ai_hub"],
            "preload_profile": "balanced", "repository_revision": "abc123",
            "changed_paths": ["src/local_ai_hub/mcp_server.py"],
        }),
        ("local_ai_repo", {
            "action": "context_compile", "include_diagnostics": True,
            "clone_id": "clone", "worktree_id": "worktree", "branch": "main",
            "repository_id": "repo", "session_id": "session",
            "repository_revision": "abc123",
        }),
        ("local_ai_repo", {
            "action": "pipeline", "steps": [{"action": "profile"}],
        }),
        ("local_ai_repo", {
            "action": "preprocess", "is_worktree": True, "parent_root": ".",
        }),
        ("local_ai_rag", {"action": "search", "query": "known indexed fact"}),
        ("local_ai_command", {"action": "classify", "command": "python -m pytest"}),
        ("local_ai_coord", {"action": "memo_search", "query": "T03"}),
        ("local_ai_work", {"action": "submit", "task": "contract smoke"}),
        ("local_ai_artifact", {"artifact_id": "artifact-1"}),
        ("local_ai_status", {
            "adoption_signal": "bypassed", "target_tool": "local_ai_repo",
            "target_action": "search",
        }),
    ],
)
def test_registered_mcp_dispatch_accepts_contract_context_inputs(
    monkeypatch, tool_name: str, arguments: dict[str, Any]
) -> None:
    import asyncio

    import local_ai_hub.mcp_server as mcp_server

    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_call_tool(name, received, *, convert_result=False):
        calls.append((name, received))
        return {"success": True}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    _blocks, payload = asyncio.run(mcp_server._compact_mcp_call_tool(tool_name, arguments))

    assert payload["success"] is True
    assert calls == [(tool_name, arguments)]


@pytest.mark.parametrize(
    ("tool_name", "arguments", "field"),
    [
        ("local_ai_task", {"action": "cancel", "phase": "review"}, "phase"),
        ("local_ai_repo", {"action": "search", "clone_id": "clone"}, "clone_id"),
        ("local_ai_repo", {"action": "preprocess", "include_diagnostics": True}, "include_diagnostics"),
        ("local_ai_repo", {"action": "context_compile", "is_worktree": True}, "is_worktree"),
        ("local_ai_status", {"action": "unknown"}, "action"),
        ("local_ai_rag", {"action": "search", "content": "unexpected"}, "content"),
        ("local_ai_command", {"action": "format", "rollback_on_failure": True}, "rollback_on_failure"),
        ("local_ai_coord", {"action": "pubsub_publish", "after_seq": 3}, "after_seq"),
        ("local_ai_work", {"action": "status", "work_id": "work-1", "task": "unexpected"}, "task"),
        ("local_ai_artifact", {"action": "list", "artifact_id": "artifact-1"}, "artifact_id"),
    ],
)
def test_registered_mcp_dispatch_rejects_context_inputs_for_wrong_action(
    monkeypatch, tool_name: str, arguments: dict[str, Any], field: str
) -> None:
    import asyncio

    import local_ai_hub.mcp_server as mcp_server

    calls: list[str] = []

    async def fake_call_tool(name, _arguments, *, convert_result=False):
        calls.append(name)
        return {"success": True}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    _blocks, payload = asyncio.run(mcp_server._compact_mcp_call_tool(tool_name, arguments))

    assert payload["status_code"] == 400
    assert field in payload["error"]
    assert calls == []


def test_registered_status_dispatch_rejects_incomplete_adoption_pair(monkeypatch) -> None:
    import asyncio

    import local_ai_hub.mcp_server as mcp_server

    class NeverCallClient:
        def get(self, *_args, **_kwargs):
            raise AssertionError("incomplete adoption report reached the backend")

    monkeypatch.setattr(mcp_server, "CLIENT", NeverCallClient())
    _blocks, payload = asyncio.run(
        mcp_server.mcp.call_tool("local_ai_status", {"adoption_signal": "bypassed"})
    )

    assert payload["success"] is False
    assert "supported target_tool and safe target_action" in payload["error"]


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("local_ai_status", {}),
        ("local_ai_task", {"action": "reason", "task": "smoke"}),
        ("local_ai_repo", {"action": "search", "query": "smoke"}),
        ("local_ai_rag", {"action": "search", "query": "smoke"}),
        ("local_ai_command", {"action": "classify", "command": "python"}),
        ("local_ai_coord", {"action": "memo_search", "query": "smoke"}),
        ("local_ai_work", {"action": "submit", "task": "smoke"}),
        ("local_ai_artifact", {"artifact_id": "artifact-1"}),
    ],
)
def test_output_validation_failure_does_not_replay_registered_handler(
    monkeypatch, tool_name: str, arguments: dict[str, Any]
) -> None:
    import asyncio

    import local_ai_hub.mcp_server as mcp_server

    calls: list[str] = []

    class ValidationError(Exception):
        pass

    async def fail_output_validation(name, _arguments, *, convert_result=False):
        calls.append(name)
        raise ValidationError("output envelope rejected")

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fail_output_validation)
    _blocks, payload = asyncio.run(
        mcp_server._compact_mcp_call_tool(tool_name, arguments)
    )

    assert payload["success"] is False
    assert payload["status_code"] == 400
    assert "output envelope rejected" in payload["error"]
    assert calls == [tool_name]


@pytest.mark.parametrize(
    ("tool_name", "arguments", "field"),
    [
        ("local_ai_task", {"action": "continue"}, "conversation_id"),
        ("local_ai_repo", {"action": "verify_receipt"}, "receipt"),
        ("local_ai_work", {"action": "submit"}, "task"),
        ("local_ai_work", {"action": "status"}, "work_id"),
        ("local_ai_artifact", {}, "artifact_id"),
    ],
)
def test_registered_mcp_dispatch_enforces_action_required_fields(
    monkeypatch, tool_name: str, arguments: dict[str, Any], field: str
) -> None:
    import asyncio

    import local_ai_hub.mcp_server as mcp_server

    calls: list[str] = []

    async def fake_call_tool(name, _arguments, *, convert_result=False):
        calls.append(name)
        return {"success": True}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    _blocks, payload = asyncio.run(mcp_server._compact_mcp_call_tool(tool_name, arguments))

    assert payload["success"] is False
    assert payload["status_code"] == 400
    assert field in payload["error"]
    assert calls == []


def test_daemon_off_keeps_live_mcp_contracts_in_generator_parity(monkeypatch) -> None:
    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.generator import generate_mcp_tool_schemas

    monkeypatch.setattr(mcp_server.CLIENT, "auto_start", False)
    generated = generate_mcp_tool_schemas(mcp_server.CFG)

    for name in mcp_server.FEATURES.enabled_tools:
        runtime_tool = mcp_server.mcp._tool_manager._tools[name]
        assert runtime_tool.output_schema == generated[name]["output_schema"], name
        runtime_input = mcp_server._mcp_contract_schema(name)
        assert runtime_input == generated[name]["parameters"], name


def test_disabled_batch_fields_are_hidden_from_live_mcp_catalog() -> None:
    import inspect
    from typing import Any

    import local_ai_hub.mcp_server as mcp_server

    fresh_mcp = mcp_server.FastMCP("disabled-batch-contract")

    def repo_tool(action: str, edits: list[dict[str, Any]], dry_run: bool = False) -> dict[str, Any]:
        return {"success": True}

    fresh_mcp.tool(name="local_ai_repo")(repo_tool)
    registered = fresh_mcp._tool_manager._tools["local_ai_repo"]
    mcp_server._hide_disabled_batch_schema(fresh_mcp, repo_tool)

    properties = registered.parameters["properties"]
    assert "edits" not in properties
    assert "dry_run" not in properties
    assert "edits" not in inspect.signature(repo_tool).parameters
    assert "dry_run" not in inspect.signature(repo_tool).parameters


def test_mcp_dispatch_rejects_unknown_action_before_handler_dispatch(monkeypatch) -> None:
    import asyncio

    import local_ai_hub.mcp_server as mcp_server

    calls: list[str] = []

    async def fake_call_tool(name, _arguments, *, convert_result=False):
        calls.append(name)
        return {"success": True}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    result = asyncio.run(
        mcp_server._compact_mcp_call_tool("local_ai_status", {"action": "not-supported"})
    )

    payload = result[1]
    assert payload["success"] is False
    assert payload["status_code"] == 400
    assert "action" in payload["error"]
    assert calls == []


def test_status_detail_rejects_conflicting_action_before_handler_dispatch(monkeypatch) -> None:
    import asyncio

    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.generator import generate_mcp_tool_schemas

    calls: list[str] = []

    async def fake_call_tool(name, _arguments, *, convert_result=False):
        calls.append(name)
        return {"success": True}

    monkeypatch.setattr(mcp_server.mcp._tool_manager, "call_tool", fake_call_tool)
    runtime = mcp_server._mcp_contract_schema("local_ai_status")
    generated = generate_mcp_tool_schemas({})["local_ai_status"]["parameters"]
    assert runtime is not None
    assert runtime["allOf"] == generated["allOf"]

    result = asyncio.run(mcp_server._compact_mcp_call_tool(
        "local_ai_status", {"action": "full", "detail": "brief"}
    ))
    payload = result[1]
    assert payload["success"] is False
    assert payload["status_code"] == 400
    assert "detail" in payload["error"]
    assert calls == []


def test_status_alias_enums_survive_mcp_stdio_tools_list(tmp_path) -> None:
    import json
    import os
    from pathlib import Path
    import sys

    from local_ai_hub.external_tools import MCPStdioClient
    from local_ai_hub.operation_contracts import STATUS_ACTIONS, STATUS_DETAILS

    repository_root = Path(__file__).resolve().parents[1]
    config_path = tmp_path / "mcp-stdio.toml"
    state_dir = (tmp_path / "hub-state").resolve()
    config_path.write_text(
        "[server]\nstate_dir = " + json.dumps(state_dir.as_posix()) + "\n",
        encoding="utf-8",
    )
    python_paths = [str(repository_root / "src")]
    python_paths.extend(filter(None, os.environ.get("PYTHONPATH", "").split(os.pathsep)))
    client = MCPStdioClient(
        [sys.executable, "-m", "local_ai_hub.mcp_server"],
        cwd=str(repository_root),
        env={
            "LOCAL_AI_CONFIG": str(config_path),
            "PYTHONPATH": os.pathsep.join(python_paths),
        },
        startup_timeout=15.0,
        call_timeout=8.0,
    )
    try:
        client._spawn()
        wire_result = client._request("tools/list", {}, timeout=8.0, ensure_started=False)
    finally:
        client.close()

    status_tool = next(tool for tool in wire_result["tools"] if tool["name"] == "local_ai_status")
    input_schema = status_tool["inputSchema"]
    assert input_schema["properties"]["action"]["enum"] == list(STATUS_ACTIONS)
    assert input_schema["properties"]["detail"]["enum"] == list(STATUS_DETAILS)


def test_rag_ingest_fields_match_live_and_generated_schemas() -> None:
    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.generator import generate_mcp_tool_schemas

    runtime = mcp_server.mcp._tool_manager._tools["local_ai_rag"].parameters["properties"]
    generated = generate_mcp_tool_schemas({})["local_ai_rag"]["parameters"]["properties"]
    expected = {"content", "title", "metadata", "image_path", "caption"}
    assert expected <= runtime.keys()
    assert expected <= generated.keys()
    assert runtime["metadata"].get("type") == generated["metadata"].get("type") == "object"


def test_rag_ingest_explicit_fields_reach_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import local_ai_hub.mcp_server as mcp_server
    monkeypatch.setattr(mcp_server.FEATURES, "rag", True)
    monkeypatch.setattr(mcp_server, "_mcp_operational_mode_block", lambda *_args: None)

    requests: list[tuple[str, dict[str, Any]]] = []

    class FakeClient:
        def post(self, path: str, payload: dict[str, Any], **kwargs: Any):
            requests.append((path, payload))
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    mcp_server.local_ai_rag(
        action="ingest_document",
        workspace="docs",
        content="source text",
        title="Guide",
        metadata={"owner": "team"},
    )
    mcp_server.local_ai_rag(
        action="ingest_diagram",
        workspace="docs",
        image_path="diagram.svg",
        caption="Flow",
        metadata={"owner": "team"},
    )

    assert requests[0][0] == "/api/rag/ingest_document"
    assert requests[0][1]["content"] == "source text"
    assert requests[0][1]["title"] == "Guide"
    assert requests[0][1]["metadata"] == {"owner": "team"}
    assert requests[1][0] == "/api/rag/ingest_diagram"
    assert requests[1][1]["image_path"] == "diagram.svg"
    assert requests[1][1]["caption"] == "Flow"
    assert requests[1][1]["metadata"] == {"owner": "team"}


def test_pubsub_poll_cursor_matches_schema_and_reaches_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.generator import generate_mcp_tool_schemas

    runtime = mcp_server.mcp._tool_manager._tools["local_ai_coord"].parameters["properties"]
    generated = generate_mcp_tool_schemas({})["local_ai_coord"]["parameters"]["properties"]
    assert _schema_shape(runtime["after_seq"], runtime) == _schema_shape(
        generated["after_seq"], generated
    )
    requests: list[dict[str, Any]] = []

    class FakeClient:
        def coord(self, **kwargs: Any):
            requests.append(kwargs)
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    mcp_server.local_ai_coord(action="pubsub_poll", after_seq=17)
    assert requests[0]["after_seq"] == 17


def test_pubsub_http_routes_replay_cursor_through_agent_state(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai_hub import http_server
    from local_ai_hub import mcp_server
    from local_ai_hub.agent_events import AgentStateStore, SwarmPubSub

    monkeypatch.setattr(SwarmPubSub, "_instance", None)
    state_store = AgentStateStore(tmp_path / "agent-state.sqlite")

    class Recovery:
        def __init__(self) -> None:
            self.begin_paths: list[str] = []

        def begin(
            self,
            request_id: str,
            tenant: str,
            action: str,
            *,
            identity: str,
            payload: Any,
        ) -> dict[str, Any]:
            self.begin_paths.append(action)
            return {"claimed": True, "state": "running", "payload_fingerprint": "test"}

    class Services:
        def pubsub_publish(self, topic: str, message: dict[str, Any], sender: str) -> dict[str, Any]:
            return SwarmPubSub.get_default().publish(topic, message, sender=sender)

    class App:
        agent_state = state_store
        recovery = Recovery()
        services = Services()
        config: dict[str, Any] = {}

    monkeypatch.setattr(http_server, "APP", App())

    def post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        handler = http_server.Handler.__new__(http_server.Handler)
        handler.path = path
        handler.headers = {"Content-Type": "application/json"}
        handler._begin_trace = lambda _path: setattr(handler, "_trace_request_id", "t03-sequence-test")
        handler._require_authorized = lambda: True
        handler._read_json = lambda limit=None: payload
        handler._validate_payload = lambda _path, _payload: None
        responses: list[tuple[int, dict[str, Any]]] = []
        handler._send = lambda status, body: responses.append((status, body))

        handler.do_POST()
        assert len(responses) == 1
        assert responses[0][0] == 200
        return responses[0][1]

    class HttpTransport:
        def coord(self, action: str, **kwargs: Any) -> dict[str, Any]:
            assert action == "pubsub_poll"
            return post(
                "/api/coord/pubsub_poll",
                {
                    "topic": kwargs["topic"],
                    "after_seq": kwargs["after_seq"],
                    "limit": kwargs["limit"],
                },
            )

    published = post(
        "/api/coord/pubsub_publish",
        {"topic": "t03-sequence", "message": {"value": 17}, "publisher": "test"},
    )
    monkeypatch.setattr(mcp_server, "CLIENT", HttpTransport())
    polled = mcp_server.local_ai_coord(
        action="pubsub_poll", key="t03-sequence", after_seq=0, ttl_seconds=50
    )

    assert published["success"] is True
    assert polled["count"] == 1
    assert polled["messages"][0]["seq"] == 1
    assert polled["messages"][0]["payload"] == {"value": 17}
    assert polled["after_seq"] == 0
    assert polled["next_after_seq"] == 1
    assert polled["limit"] == 50
    assert polled["has_more"] is False
    assert polled["gap"] is False
    assert App.recovery.begin_paths == ["/api/coord/pubsub_publish"]
    next_poll = post(
        "/api/coord/pubsub_poll",
        {"topic": "t03-sequence", "after_seq": polled["next_after_seq"], "limit": 50},
    )
    assert next_poll["messages"] == []


def test_context_pack_http_post_bypasses_recovery_and_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai_hub import http_server

    class Recovery:
        def __init__(self) -> None:
            self.begin_calls = 0

        def validate_request_id(self, _request_id: str) -> None:
            return None

        def begin(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            self.begin_calls += 1
            return {"claimed": True, "state": "running"}

    class Services:
        def __init__(self) -> None:
            self.context_calls: list[tuple[str, str, int]] = []

        def fast_context(self, root: str, query: str, max_tokens: int) -> dict[str, Any]:
            self.context_calls.append((root, query, max_tokens))
            return {"success": True, "context": f"computed context {len(self.context_calls)}"}

    class App:
        config: dict[str, Any] = {}
        recovery = Recovery()
        services = Services()

    payload = {"root": ".", "query": "fresh context", "mode": "fast", "max_tokens": 32}
    monkeypatch.setattr(http_server, "APP", App())

    def context_post() -> dict[str, Any]:
        handler = http_server.Handler.__new__(http_server.Handler)
        handler.path = "/api/context/pack"
        handler.headers = {"Content-Type": "application/json", "X-LocalAI-Request-ID": "context-pack-test"}
        handler._begin_trace = lambda _path: setattr(handler, "_trace_request_id", "context-pack-test")
        handler._require_authorized = lambda: True
        handler._read_json = lambda limit=None: payload
        handler._validate_payload = lambda _path, _payload: None
        responses: list[tuple[int, dict[str, Any]]] = []
        handler._send = lambda status, body: responses.append((status, body))
        handler.do_POST()
        assert len(responses) == 1
        assert responses[0][0] == 200
        return responses[0][1]

    first = context_post()
    second = context_post()

    assert first == {"success": True, "context": "computed context 1", "delivery_mode": "fast"}
    assert second == {"success": True, "context": "computed context 2", "delivery_mode": "fast"}
    assert App.services.context_calls == [(".", "fresh context", 32), (".", "fresh context", 32)]
    assert App.recovery.begin_calls == 0


@pytest.mark.parametrize("recovery_state", ["claimed", "done", "running", "conflict"])
def test_mutating_http_post_uses_t07_recovery_contract(
    recovery_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from local_ai_hub import http_server

    request_id = "t03-journal-adapter"
    fingerprint = "a" * 64
    payload = {
        "topic": "t03-replay",
        "message": {"value": 1},
        "publisher": "agent-a",
        "_hub_journal": {"payload_fingerprint": "b" * 64},
    }
    replay_response = {"success": True, "published_id": "journaled"}

    class Recovery:
        def __init__(self) -> None:
            self.begin_calls: list[tuple[str, str, str, str, dict[str, Any]]] = []
            self.wait_calls: list[tuple[str, str]] = []
            self.finish_calls: list[tuple[str, bool, int, dict[str, Any]]] = []

        def validate_request_id(self, _request_id: str) -> None:
            return None

        def begin(
            self,
            current_id: str,
            tenant: str,
            action: str,
            *,
            identity: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            self.begin_calls.append((current_id, tenant, action, identity, payload))
            if recovery_state == "conflict":
                return {"claimed": False, "state": "conflict", "error": "payload differs"}
            if recovery_state == "claimed":
                return {"claimed": True, "state": "running", "payload_fingerprint": fingerprint}
            if recovery_state == "running":
                return {
                    "claimed": False,
                    "state": "running",
                    "response": None,
                    "payload_fingerprint": fingerprint,
                }
            return {
                "claimed": False,
                "state": "done",
                "status_code": 200,
                "response": replay_response,
                "payload_fingerprint": fingerprint,
            }

        def wait_for(
            self,
            current_id: str,
            tenant: str,
            action: str,
            *,
            timeout_seconds: float,
            identity: str,
            payload_fingerprint: str,
        ) -> dict[str, Any]:
            assert (current_id, tenant, action) == (request_id, "tenant-a", "/api/coord/pubsub_publish")
            assert timeout_seconds > 0
            self.wait_calls.append((identity, payload_fingerprint))
            return {"state": "done", "status_code": 200, "response": replay_response}

        def finish(
            self,
            current_id: str,
            success: bool,
            _detail: str = "",
            *,
            status_code: int,
            response: dict[str, Any],
        ) -> None:
            self.finish_calls.append((current_id, success, status_code, response))

    class Services:
        def __init__(self) -> None:
            self.publish_calls: list[dict[str, Any]] = []

        def pubsub_publish(self, topic: str, message: dict[str, Any], sender: str) -> dict[str, Any]:
            self.publish_calls.append({"topic": topic, "message": message, "sender": sender})
            return {"success": True, "published_id": "fresh"}

    class TraceStore:
        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []

        def update(self, _trace_id: str, **fields: Any) -> bool:
            if isinstance(fields.get("request"), dict):
                self.requests.append(dict(fields["request"]))
            return True

        def event(self, *_args: Any) -> None:
            return None

    recovery = Recovery()
    services = Services()
    trace_store = TraceStore()
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={}, recovery=recovery, services=services, debug_traces=trace_store),
    )

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/coord/pubsub_publish"
    handler.headers = {"Content-Type": "application/json", "X-LocalAI-Request-ID": request_id}
    handler._begin_trace = lambda _path: setattr(handler, "_trace_request_id", request_id)
    handler._debug_trace_id = "trace-1"
    handler._require_authorized = lambda: True
    handler._tenant = lambda: "tenant-a"
    handler._agent = lambda: "agent-a"
    handler._read_json = lambda limit=None: payload
    handler._validate_payload = lambda _path, _payload: None
    sent_statuses: list[int] = []
    handler.send_response = lambda status: sent_statuses.append(status)
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None
    handler._common_headers = lambda: None
    handler._finish_debug_trace = lambda *_args, **_kwargs: None
    handler._close_trace_context = lambda: None
    handler._debug_trace_finished = True
    handler._telemetry_finished = True
    handler.wfile = io.BytesIO()

    handler.do_POST()

    body = json.loads(handler.wfile.getvalue())
    assert len(sent_statuses) == 1
    if recovery_state == "conflict":
        assert sent_statuses == [409]
        assert body["success"] is False
        assert body["error"] == "payload differs"
        assert body["request_id"] == request_id
    else:
        assert sent_statuses == [200]
        expected_response = {"success": True, "published_id": "fresh"} if recovery_state == "claimed" else replay_response
        assert body == expected_response
    assert recovery.begin_calls == [(request_id, "tenant-a", "/api/coord/pubsub_publish", "agent-a", payload)]
    expected_wait = [("agent-a", fingerprint)] if recovery_state == "running" else []
    assert recovery.wait_calls == expected_wait
    if recovery_state == "conflict":
        assert trace_store.requests[-1].get("_hub_journal") is None
    else:
        assert trace_store.requests[-1]["_hub_journal"] == {"payload_fingerprint": fingerprint}
    if recovery_state == "claimed":
        assert services.publish_calls == [{"topic": "t03-replay", "message": {"value": 1}, "sender": "agent-a"}]
        assert recovery.finish_calls == [(request_id, True, 200, {"success": True, "published_id": "fresh"})]
    else:
        assert services.publish_calls == []
        assert recovery.finish_calls == []


def test_mutating_http_post_uses_identity_bound_recovery_journal(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from local_ai_hub import http_server
    from local_ai_hub.resilience import RecoveryJournal

    recovery = RecoveryJournal(tmp_path, stale_seconds=30)

    class Services:
        def __init__(self) -> None:
            self.publish_calls: list[dict[str, Any]] = []

        def pubsub_publish(self, topic: str, message: Any, sender: str) -> dict[str, Any]:
            self.publish_calls.append({"topic": topic, "message": message, "sender": sender})
            return {"success": True, "published_id": "fresh"}

    services = Services()
    app = SimpleNamespace(
        config={"resilience": {"singleflight_wait_timeout_seconds": 0.05}},
        recovery=recovery,
        services=services,
        agent_state=None,
    )
    monkeypatch.setattr(http_server, "APP", app)
    request_id = "t03-real-recovery-journal"
    payload = {"topic": "t03-real", "message": {"value": 1}, "publisher": "agent-a"}

    def post(identity: str, request_payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        import json

        handler = http_server.Handler.__new__(http_server.Handler)
        handler.path = "/api/coord/pubsub_publish"
        handler.headers = {
            "Content-Type": "application/json",
            "X-LocalAI-Request-ID": request_id,
        }
        handler._begin_trace = lambda _path: setattr(handler, "_trace_request_id", request_id)
        handler._require_authorized = lambda: True
        handler._tenant = lambda: "tenant-a"
        handler._agent = lambda: identity
        handler._read_json = lambda limit=None: request_payload
        handler._validate_payload = lambda _path, _payload: None
        responses: list[tuple[int, dict[str, Any]]] = []
        response_status: dict[str, int] = {}
        handler.send_response = lambda status: response_status.update(status=status)
        handler.send_header = lambda *_args: None
        handler.end_headers = lambda: None
        handler._common_headers = lambda: None
        handler._finish_debug_trace = lambda *_args, **_kwargs: None
        handler._close_trace_context = lambda: None
        handler.wfile = SimpleNamespace(
            write=lambda body: responses.append((response_status["status"], json.loads(body.decode("utf-8"))))
        )
        handler.do_POST()
        assert len(responses) == 1
        return responses[0]

    first = post("agent-a", payload)
    duplicate = post("agent-a", payload)
    wrong_identity = post("agent-b", payload)
    wrong_payload = post("agent-a", {**payload, "topic": "other"})

    assert first[0] == 200
    assert duplicate[0] == 200 and duplicate[1] == first[1]
    assert wrong_identity[0] == 409
    assert wrong_payload[0] == 409
    assert len(services.publish_calls) == 1


def test_local_ai_coord_max_tokens_bounds_match_live_and_generated() -> None:
    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.generator import generate_mcp_tool_schemas

    runtime = mcp_server.mcp._tool_manager._tools["local_ai_coord"].parameters
    generated = generate_mcp_tool_schemas({})["local_ai_coord"]["parameters"]
    expected = {"type": "integer", "default": 0, "minimum": 0, "maximum": 100000}
    assert _schema_shape(runtime["properties"]["max_tokens"], runtime) == expected
    assert _schema_shape(generated["properties"]["max_tokens"], generated) == expected


def test_pubsub_poll_rejects_out_of_range_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    import local_ai_hub.mcp_server as mcp_server

    class NeverCallClient:
        def coord(self, **kwargs: Any):
            raise AssertionError("invalid cursor reached the backend")

    monkeypatch.setattr(mcp_server, "CLIENT", NeverCallClient())
    result = mcp_server.local_ai_coord(action="pubsub_poll", after_seq=-1)
    assert result["status_code"] == 400
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_http_send_applies_optional_response_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import local_ai_hub.http_server as http_server

    monkeypatch.setattr(http_server, "APP", None)
    sent_headers: list[tuple[str, str]] = []
    written: list[bytes] = []
    handler = SimpleNamespace(
        _debug_trace_finished=True,
        _finish_debug_trace=lambda *_: None,
        _close_trace_context=lambda: None,
        send_response=lambda *_: None,
        send_header=lambda name, value: sent_headers.append((name, value)),
        _common_headers=lambda: None,
        end_headers=lambda: None,
        wfile=SimpleNamespace(write=written.append),
    )

    http_server.Handler._send(
        handler,
        405,
        {"success": False, "error": "method not allowed"},
        headers={"Allow": "POST"},
    )

    response = json.loads(written[0].decode("utf-8"))
    assert ("Allow", "POST") in sent_headers
    assert response["status_code"] == 405
    assert response["retryable"] is False


@pytest.mark.parametrize(
    ("status", "payload", "expected_retryable", "expected_terminal"),
    [
        (401, {"error": "unauthorized"}, False, True),
        (409, {"error": "conflict"}, False, True),
        (429, {"error": "rate limited"}, True, False),
        (503, {"success": True, "error": "backend down", "retryable": False, "terminal": True, "degraded": True}, False, True),
    ],
)
def test_http_error_responses_have_transport_state(
    status: int,
    payload: dict[str, Any],
    expected_retryable: bool,
    expected_terminal: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from types import SimpleNamespace

    import local_ai_hub.http_server as http_server

    monkeypatch.setattr(http_server, "APP", None)
    written: list[bytes] = []
    fake = SimpleNamespace(
        _debug_trace_finished=True,
        _finish_debug_trace=lambda *_: None,
        _close_trace_context=lambda: None,
        send_response=lambda *_: None,
        send_header=lambda *_: None,
        _common_headers=lambda: None,
        end_headers=lambda: None,
        wfile=SimpleNamespace(write=written.append),
    )
    http_server.Handler._send(fake, status, payload)
    result = json.loads(written[0].decode("utf-8"))

    assert result["success"] is False
    assert result["status_code"] == status
    assert result["retryable"] is expected_retryable
    assert result["terminal"] is expected_terminal
    if status == 503:
        assert result["degraded"] is True


@pytest.mark.parametrize(
    ("status", "payload", "expected_retryable", "expected_terminal"),
    [
        (400, {"success": True, "error": "bad input"}, False, True),
        (409, {"error": "conflict"}, False, True),
        (429, {"error": "rate limited"}, True, False),
        (503, {"success": True, "error": "offline", "retryable": False, "terminal": True, "degraded": True}, False, True),
    ],
)
def test_client_http_errors_normalize_status_and_preserve_details(
    status: int,
    payload: dict[str, Any],
    expected_retryable: bool,
    expected_terminal: bool,
) -> None:
    import json
    from io import BytesIO
    from urllib.error import HTTPError

    from local_ai_hub.client import HubClient

    error = HTTPError(
        "http://localhost/api/test",
        status,
        "failure",
        {},
        BytesIO(json.dumps(payload).encode("utf-8")),
    )
    result = HubClient._error_response(error, "req-t03")

    assert result["success"] is False
    assert result["status_code"] == status
    assert result["retryable"] is expected_retryable
    assert result["terminal"] is expected_terminal
    assert result["request_id"] == "req-t03"
    if status == 503:
        assert result["degraded"] is True


@pytest.mark.parametrize("alias", ["status", "health", "check", "info"])
def test_status_aliases_resolve_to_brief_and_unknown_rejects(
    alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import local_ai_hub.mcp_server as mcp_server

    requests: list[str] = []

    class FakeClient:
        def get(self, path: str):
            requests.append(path)
            return {"success": True, "runtime_stats": {}}

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    mcp_server.local_ai_status(action=alias)
    assert len(requests) == 1 and requests[0].startswith("/api/live/status?light=1"), requests

    class NeverCallClient:
        def get(self, path: str):
            raise AssertionError("invalid status action reached the backend")

    monkeypatch.setattr(mcp_server, "CLIENT", NeverCallClient())
    invalid = mcp_server.local_ai_status(action="unknown")
    assert invalid["status_code"] == 400
    assert invalid["terminal"] is True
    assert invalid["retryable"] is False


@pytest.mark.parametrize("detail", ["brief", "cache", "telemetry", "full"])
def test_status_wrappers_preserve_backend_contract_state(
    detail: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import local_ai_hub.mcp_server as mcp_server

    backend_error = {
        "success": False,
        "hub_online": False,
        "status_code": 503,
        "terminal": False,
        "retryable": True,
        "degraded": True,
        "stale": True,
        "evidence": [{"id": "E-status"}],
        "cancelled": False,
        "runtime_stats": {},
        "observability": {},
        "scheduler": {},
    }

    class FakeClient:
        def get(self, path: str):
            if path.startswith("/api/telemetry/"):
                return dict(backend_error)
            if path == "/api/capabilities":
                return {"success": True, "capabilities": []}
            return dict(backend_error)

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    result = mcp_server.local_ai_status(detail=detail)

    for key in ("status_code", "terminal", "retryable", "degraded", "stale", "evidence", "cancelled"):
        assert result.get(key) == backend_error[key]


def test_status_details_use_distinct_light_full_and_agent_state_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import local_ai_hub.mcp_server as mcp_server

    requests: list[str] = []

    class FakeClient:
        def get(self, path: str):
            requests.append(path)
            return {"success": True, "hub_online": True, "full_snapshot": True, "runtime_stats": {}}

        def status(self, detail: str, scope: str = "process"):
            requests.append(f"status:{detail}:{scope}")
            return {"success": True, "active_tasks": ["task-1"]}

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    full = mcp_server.local_ai_status(detail="full")
    assert requests == ["/api/status?scope=process", "/api/capabilities"]
    assert full["full_snapshot"] is True

    requests.clear()
    agent_state = mcp_server.local_ai_status(detail="agent_state")
    assert requests == ["status:agent_state:process"]
    assert agent_state["active_tasks"] == ["task-1"]


def test_artifact_schema_supports_listing_without_id_and_binary_mode() -> None:
    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.generator import generate_mcp_tool_schemas

    runtime = mcp_server.mcp._tool_manager._tools["local_ai_artifact"].parameters
    generated = generate_mcp_tool_schemas({})["local_ai_artifact"]["parameters"]
    for schema in (runtime, generated):
        properties = schema["properties"]
        assert "list" in properties["action"]["enum"]
        assert "action" not in schema.get("required", [])
        assert "artifact_id" not in schema.get("required", [])
        assert properties["artifact_id"].get("default", "") == ""
        assert properties["binary"]["type"] == "boolean"
    for field in ("action", "artifact_id", "binary", "offset", "max_chars", "section"):
        assert _schema_shape(runtime["properties"][field], runtime) == _schema_shape(
            generated["properties"][field], generated
        ), f"artifact schema differs for {field}"


def test_artifact_list_needs_no_id_and_binary_result_stays_out_of_mcp_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import local_ai_hub.mcp_server as mcp_server

    requested: list[tuple[str, dict[str, Any]]] = []

    class FakeClient:
        def post(self, endpoint: str, payload: dict[str, Any], timeout: int | None = None):
            requested.append((endpoint, payload))
            if endpoint == "/api/artifact/list":
                return {"success": True, "artifacts": [{"artifact_id": "art-1"}]}
            if endpoint == "/api/artifact/get":
                return {"success": True, "artifact_id": "art-1", "data_base64": "secret-bytes"}
            raise AssertionError(f"unexpected endpoint: {endpoint}")

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    listed = mcp_server.local_ai_artifact(action="list")
    binary = mcp_server.local_ai_artifact(action="get", artifact_id="art-1", binary=True)

    assert listed["success"] is True
    assert listed["artifacts"][0]["artifact_id"] == "art-1"
    assert requested[0] == ("/api/artifact/list", {"limit": 20})
    assert requested[1][1]["binary"] is True
    assert "data_base64" not in binary
    assert binary["binary_payload"] == "available through /api/artifact/get with binary=true"


def test_artifact_rejects_out_of_bounds_numbers_before_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    import local_ai_hub.mcp_server as mcp_server

    class NeverCallClient:
        def post(self, *args: Any, **kwargs: Any):
            raise AssertionError("invalid artifact numbers reached the backend")

    monkeypatch.setattr(mcp_server, "CLIENT", NeverCallClient())
    result = mcp_server.local_ai_artifact(action="list", offset=-1)
    assert result["status_code"] == 400
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_operation_registry_is_the_feature_gate_source() -> None:
    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.features import FeatureSet
    from local_ai_hub.generator import generate_mcp_tool_schemas
    from local_ai_hub.operation_contracts import (
        MCP_OPERATION_CONTRACTS,
        disabled_tool_names,
        enabled_tool_names,
        operation_description,
    )

    features = FeatureSet.from_config({})
    names = [contract.name for contract in MCP_OPERATION_CONTRACTS]
    assert len(names) == 8
    assert len(set(names)) == 8
    assert features.enabled_tools == enabled_tool_names(features)
    assert features.disabled_tools == disabled_tool_names(features)
    schemas = generate_mcp_tool_schemas({})
    assert set(schemas) == set(features.enabled_tools)
    for contract in MCP_OPERATION_CONTRACTS:
        if contract.name not in schemas:
            continue
        expected = operation_description(contract)
        live_description = mcp_server.mcp._tool_manager._tools[contract.name].description
        assert expected in live_description
        assert expected in schemas[contract.name]["description"]


def test_operation_registry_schema_keys_bind_to_live_and_generated_schemas() -> None:
    import local_ai_hub.mcp_server as mcp_server
    from local_ai_hub.generator import generate_mcp_tool_schemas
    from local_ai_hub.operation_contracts import MCP_OPERATION_CONTRACTS, enabled_schema_keys

    features = mcp_server.FEATURES
    generated = generate_mcp_tool_schemas(mcp_server.CFG)
    schema_keys = [contract.schema_key for contract in MCP_OPERATION_CONTRACTS]
    assert len(schema_keys) == 8
    assert len(set(schema_keys)) == 8
    enabled = set(enabled_schema_keys(features))
    assert set(generated) == enabled

    manager = getattr(mcp_server.mcp, "_tool_manager", None)
    runtime_tools = getattr(manager, "_tools", {}) if manager is not None else {}
    runtime_keys = {
        contract.schema_key
        for contract in MCP_OPERATION_CONTRACTS
        if contract.name in runtime_tools
    }
    assert runtime_keys == enabled

    def normalize(schema):
        if isinstance(schema, dict):
            return {
                key: normalize(value)
                for key, value in schema.items()
                if key not in {"description", "title", "$defs", "definitions"}
            }
        if isinstance(schema, list):
            return [normalize(value) for value in schema]
        return schema

    for contract in MCP_OPERATION_CONTRACTS:
        schema_key = contract.schema_key
        live_schema = mcp_server._mcp_contract_schema(schema_key)
        if schema_key not in enabled:
            assert schema_key not in generated
            assert contract.name not in runtime_tools
            assert live_schema is None
            continue

        assert isinstance(live_schema, dict)
        assert isinstance(live_schema.get("properties"), dict)
        generated_parameters = generated[schema_key].get("parameters")
        assert isinstance(generated_parameters, dict)
        assert normalize(live_schema) == normalize(generated_parameters)


def test_generated_repo_schema_scopes_steps_without_runtime_mcp() -> None:
    import sys

    from local_ai_hub import generator

    module_name = f"{generator.__package__}.mcp_server"
    runtime_mcp = sys.modules.pop(module_name, None)
    try:
        generated = generator.generate_mcp_tool_schemas({})
        assert module_name not in sys.modules
    finally:
        if runtime_mcp is not None:
            sys.modules[module_name] = runtime_mcp

    parameters = generated["local_ai_repo"]["parameters"]
    action_rule = next(
        rule for rule in parameters.get("allOf", [])
        if rule.get("then", {}).get("properties") == {"steps": {}}
    )
    assert action_rule["if"]["properties"]["action"]["const"] == "pipeline"
    assert action_rule["then"]["properties"] == {"steps": {}}
    assert "edits" not in parameters["properties"]
    assert "dry_run" not in parameters["properties"]
    assert all("batch_replace" not in str(rule) for rule in parameters.get("allOf", []))

    enabled = generator.generate_mcp_tool_schemas({"features": {"batch_replacement": True}})
    enabled_parameters = enabled["local_ai_repo"]["parameters"]
    assert "batch_replace" not in parameters["properties"]["action"]["enum"]
    assert enabled_parameters["properties"]["action"]["enum"].count("batch_replace") == 1
    assert "edits" in enabled_parameters["properties"]
    assert "dry_run" in enabled_parameters["properties"]
    assert any("batch_replace" in str(rule) for rule in enabled_parameters.get("allOf", []))


def test_schema_generation_does_not_import_runtime_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    from local_ai_hub import generator

    original_import = builtins.__import__

    def reject_runtime_import(name, globals=None, locals=None, fromlist=(), level=0):
        if "mcp_server" in fromlist and level:
            raise AssertionError("schema generation must not import the runtime MCP server")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", reject_runtime_import)
    generated = generator.generate_mcp_tool_schemas({})

    assert "local_ai_status" in generated


def test_http_send_rejects_transfer_encoding_override() -> None:
    from types import SimpleNamespace

    import local_ai_hub.http_server as http_server

    sent_statuses: list[int] = []
    handler = SimpleNamespace(
        send_response=sent_statuses.append,
        send_header=lambda *_args: None,
        _common_headers=lambda: None,
        end_headers=lambda: None,
        wfile=SimpleNamespace(write=lambda _body: None),
    )

    with pytest.raises(ValueError, match="invalid or reserved response header name"):
        http_server.Handler._send(
            handler,
            200,
            {"success": True},
            headers={"Transfer-Encoding": "chunked"},
        )

    assert sent_statuses == []


def test_task_list_query_is_action_scoped_and_task_create_keeps_query_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import local_ai_hub.mcp_server as mcp_server
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "_mcp_operational_mode_block", lambda *_args: None)

    calls: list[dict[str, Any]] = []

    class FakeClient:
        def coord(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    mcp_server.local_ai_coord(action="task_list", query="  Alpha  beta  ", status="active")
    mcp_server.local_ai_coord(action="task_list", query="")
    mcp_server.local_ai_coord(action="task_create", task_id="task-query", query="Goal from query")
    mcp_server.local_ai_coord(
        action="task_create", task_id="task-explicit", task="Explicit goal", query="Ignored query"
    )

    assert calls[0]["query"] == "  Alpha  beta  "
    assert "query" not in calls[1]
    assert calls[2]["query"] == "Goal from query"
    assert "query" not in calls[3]


def test_task_list_query_is_forwarded_by_http_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import local_ai_hub.http_server as http_server

    query_text = "alpha beta"
    list_calls: list[dict[str, Any]] = []

    class TaskStore:
        state_store = SimpleNamespace(enabled=True)

        def list_tasks(self, **kwargs: Any) -> list[Any]:
            list_calls.append(kwargs)
            return []

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(agent_tasks=TaskStore(), config={}))

    def handler_for(path: str):
        handler = http_server.Handler.__new__(http_server.Handler)
        handler.path = path
        handler.headers = {"Content-Type": "application/json"}
        handler._begin_trace = lambda _path: None
        handler._require_authorized = lambda: True
        responses: list[tuple[int, dict[str, Any]]] = []
        handler._send = lambda status, body: responses.append((status, body))
        return handler, responses

    get_handler, get_responses = handler_for(
        "/api/agent-state/tasks?status=active&limit=7&query=alpha+beta"
    )
    get_handler.do_GET()
    assert get_responses[0][0] == 200
    assert list_calls[-1]["query"] == query_text

    post_handler, post_responses = handler_for("/api/agent-state/tasks")
    post_handler._read_json = lambda: {
        "action": "list", "status": "active", "limit": 7, "query": query_text
    }
    post_handler._validate_payload = lambda _path, _payload: None
    post_handler.do_POST()
    assert post_responses[0][0] == 200
    assert list_calls[-1]["query"] == query_text

    invalid_handler, invalid_responses = handler_for("/api/agent-state/tasks")
    invalid_handler._read_json = lambda: {"action": "list", "query": {"bad": True}}
    invalid_handler._validate_payload = lambda _path, _payload: None
    invalid_handler.do_POST()
    assert invalid_responses[0][0] == 400


def _contract_client(tmp_path):
    from local_ai_hub.client import HubClient

    config = tmp_path / "client.toml"
    config.write_text(
        "[server]\nport=39123\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n"
        "[client]\nmax_request_timeout_seconds=5\n",
        encoding="utf-8",
    )
    return HubClient(config_path=str(config), auto_start=False)


def test_client_coord_pubsub_poll_forwards_after_seq_contract(tmp_path, monkeypatch) -> None:
    client = _contract_client(tmp_path)
    requests: list[tuple[str, dict[str, Any]]] = []

    def fake_post(path: str, payload: dict[str, Any]):
        requests.append((path, payload))
        return {"success": True}

    monkeypatch.setattr(client, "post", fake_post)
    result = client.coord("pubsub_poll", root="C:/repo", topic="events", after_seq=17, limit=12)

    assert result["success"] is True
    assert requests == [(
        "/api/coord/pubsub_poll",
        {"root": "C:/repo", "topic": "events", "after_seq": 17, "limit": 12},
    )]


@pytest.mark.parametrize("after_seq", [True, -1, 1.5, (1 << 63)])
def test_client_coord_pubsub_poll_rejects_invalid_cursor_before_http(
    after_seq: Any, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _contract_client(tmp_path)
    requests: list[str] = []
    monkeypatch.setattr(client, "post", lambda path, _payload: requests.append(path))

    result = client.coord("pubsub_poll", after_seq=after_seq)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert requests == []


@pytest.mark.parametrize("limit", [True, 0, 1001, 1.5])
def test_client_coord_pubsub_poll_rejects_invalid_limit_before_http(
    limit: Any, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _contract_client(tmp_path)
    requests: list[str] = []
    monkeypatch.setattr(client, "post", lambda path, _payload: requests.append(path))

    result = client.coord("pubsub_poll", after_seq=0, limit=limit)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert requests == []


def test_stream_events_normalizes_http_error_with_status_and_body_metadata(tmp_path, monkeypatch):
    from urllib.error import HTTPError

    from local_ai_hub import client as client_module

    client = _contract_client(tmp_path)
    body = (
        b'{"success":false,"error":"backend unavailable","degraded":true,'
        b'"stale":true,"evidence":[{"id":"E-stream"}],"cancelled":true}'
    )

    def fail_open(*_args, **_kwargs):
        raise HTTPError("http://localhost/api/agent-state/events/stream", 503, "Unavailable", {}, io.BytesIO(body))

    monkeypatch.setattr(client_module, "urlopen", fail_open)
    events = list(client.stream_events(timeout=1))

    assert events[-1][0] == "error"
    error = events[-1][1]
    assert error["status_code"] == 503
    assert error["retryable"] is True
    assert error["terminal"] is False
    assert error["request_id"].startswith("req_")
    assert error["degraded"] is True
    assert error["stale"] is True
    assert error["evidence"] == [{"id": "E-stream"}]
    assert error["cancelled"] is True


def test_get_non_object_json_returns_normalized_protocol_error(tmp_path, monkeypatch):
    client = _contract_client(tmp_path)
    monkeypatch.setattr(client, "_pooled_open", lambda *_args, **_kwargs: b"[]")

    result = client.get("/api/test")

    assert result["success"] is False
    assert result["error"] == "invalid JSON response"
    assert result["status_code"] == 502
    assert result["retryable"] is True
    assert result["terminal"] is False
    assert result["request_id"].startswith("req_")


def test_post_non_object_json_returns_normalized_protocol_error(tmp_path, monkeypatch):
    client = _contract_client(tmp_path)
    monkeypatch.setattr(client, "_pooled_open", lambda *_args, **_kwargs: b'["unexpected"]')

    result = client.request("/api/test", {"value": 1})

    assert isinstance(result, dict)
    assert result["success"] is False
    assert result["error"] == "invalid JSON response"
    assert result["status_code"] == 502
    assert result["outcome_unknown"] is True
    assert result["retryable"] is False
    assert result["terminal"] is True
    assert result["request_id"].startswith("req_")


def test_get_invalid_json_returns_normalized_protocol_error(tmp_path, monkeypatch):
    client = _contract_client(tmp_path)
    monkeypatch.setattr(client, "_pooled_open", lambda *_args, **_kwargs: b"{")

    result = client.get("/api/test")

    assert result["success"] is False
    assert result["error"] == "invalid JSON response"
    assert result["status_code"] == 502
    assert result["retryable"] is True
    assert result["terminal"] is False
    assert result["request_id"].startswith("req_")


def test_replay_safe_post_invalid_json_remains_retryable(tmp_path, monkeypatch):
    client = _contract_client(tmp_path)
    monkeypatch.setattr(client, "_pooled_open", lambda *_args, **_kwargs: b"[]")

    result = client.request("/api/test", {"action": "read"}, replay_safe=True)

    assert result["success"] is False
    assert result["error"] == "invalid JSON response"
    assert result["status_code"] == 502
    assert result["retryable"] is True
    assert result["terminal"] is False
    assert "outcome_unknown" not in result


def test_mutating_post_invalid_json_reports_unknown_outcome(tmp_path, monkeypatch):
    client = _contract_client(tmp_path)
    monkeypatch.setattr(client, "_pooled_open", lambda *_args, **_kwargs: b"{")

    result = client.request("/api/test", {"action": "write"})

    assert result["success"] is False
    assert result["error"] == "invalid JSON response"
    assert result["status_code"] == 502
    assert result["outcome_unknown"] is True
    assert result["retryable"] is False
    assert result["terminal"] is True
    assert result["request_id"].startswith("req_")


def test_contract_state_metadata_survives_mcp_compaction(monkeypatch):
    import local_ai_hub.mcp_server as mcp_server

    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", mcp_server.OrderedDict())
    expected = {
        "success": False,
        "status_code": 503,
        "error": "backend unavailable",
        "terminal": False,
        "retryable": True,
        "degraded": True,
        "stale": True,
        "evidence": [{"evidence_id": "E1", "source": "indexed"}],
        "cancel": {"cancelled": True, "reason": "client_disconnect"},
        "cancelled": True,
        "timed_out": False,
    }
    value = {
        **expected,
        "summary": "compact this response",
        "results": [{"path": f"src/{index}.py", "text": "x" * 500} for index in range(30)],
    }
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(
        {
            "max_response_tokens": 220,
            "response_profile": "compact",
            "reuse_key": "contract-state-compaction",
            "tool": "local_ai_repo",
        }
    )
    try:
        result = mcp_server._compact(value, "search")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)

    assert result["response_budget"]["truncated"] is True
    for key, expected_value in expected.items():
        assert result[key] == expected_value


def test_operation_contract_policy_is_synced_to_both_prompts():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    policy = (
        "For operation contract changes, treat `src/local_ai_hub/operation_contracts.py` as canonical; "
        "keep generated schemas and live MCP `tools/list` aligned. Keep MCP output schemas general until "
        "source-backed contracts cover every enabled action; then type stable fields and leave variable "
        "payload extensions open. Sync this rule into both prompt files."
    )
    for name in ("INSTALL_PROMPT.md", "UPDATE_PROMPT.md"):
        prompt = (root / "docs" / name).read_text(encoding="utf-8")
        assert prompt.count(policy) == 1
