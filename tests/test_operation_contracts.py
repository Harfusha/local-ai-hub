from __future__ import annotations

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
    assert set(step_properties) == set(generated_properties) - {"steps"} | {"id"}
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


@pytest.mark.parametrize(
    ("status", "payload", "expected_retryable", "expected_terminal"),
    [
        (401, {"error": "unauthorized"}, False, True),
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
