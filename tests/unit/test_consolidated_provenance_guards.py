"""Reject malformed hardening inputs without fabricating canonical provenance."""

import json

import pytest

from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_consistency import ConsistencyRequest
from local_ai_hub.agent_tasks import GoalContract, TaskState, TaskStatus
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub import json_utils


@pytest.mark.parametrize("value", [None, [], "request", 1])
def test_consistency_request_requires_mapping(value):
    with pytest.raises(TypeError):
        ConsistencyRequest.from_dict(value)


@pytest.mark.parametrize("value", [None, 1, "", " ", "repo\x00", "x" * 401])
def test_consistency_request_does_not_rewrite_repository_identity(value):
    with pytest.raises(ValueError):
        ConsistencyRequest(root=value)


def test_consistency_request_rejects_retired_tenant_field():
    with pytest.raises(TypeError):
        ConsistencyRequest(root="repository", tenant="tenant\x00")


@pytest.mark.parametrize("serialize", [json_utils.dumps, json_utils.dumps_bytes])
@pytest.mark.parametrize("field", ["safe_floats", "handle_cycles"])
@pytest.mark.parametrize("value", [0, 1, "false", None, []])
def test_json_options_require_booleans(serialize, field, value):
    with pytest.raises(TypeError):
        serialize({"value": 1}, **{field: value})


@pytest.mark.parametrize("serialize", [json_utils.dumps, json_utils.dumps_bytes])
@pytest.mark.parametrize("depth", [True, -1, 129, 1.5, "2", 10**100])
def test_json_depth_is_bounded_integer(serialize, depth):
    with pytest.raises(ValueError):
        serialize({"value": 1}, max_depth=depth)


def test_json_supported_inputs_keep_roundtrip():
    value = {"text": "žluťoučký", "values": [1, False, None]}
    assert json_utils.loads(json_utils.dumps_bytes(value)) == value
    assert json_utils.safe_loads(memoryview(json.dumps(value).encode())) == value
    assert json_utils.loads(json_utils.dumps({"nan": float("nan")}, safe_floats=True)) == {"nan": None}
    cycle = []
    cycle.append(cycle)
    assert json_utils.loads(json_utils.dumps(cycle, handle_cycles=True)) == ["[Circular]"]
    assert json_utils.sanitize_value({"value": 1}, max_depth=0) == "[MaxDepthExceeded]"


@pytest.mark.parametrize("prefix", [b"", b"\xef\xbb\xbf"])
def test_json_memoryview_stdlib_fallback(monkeypatch, prefix):
    monkeypatch.setattr(json_utils, "_orjson", None)
    monkeypatch.setattr(json_utils, "_msgspec", None)
    value = memoryview(prefix + b'{"value":1}')
    assert json_utils.loads(value) == {"value": 1}
    assert json_utils.safe_loads(value) == {"value": 1}


def task_payload():
    return TaskState(
        task_id="task-1", status=TaskStatus.DRAFT,
        contract=GoalContract(goal="Preserve provenance"), context=ScopeContext(task_id="task-1"),
        created_at=1.0, updated_at=2.0, heartbeat_expires_at=3.0,
    ).to_dict()


def test_task_state_roundtrip():
    payload = task_payload()
    assert TaskState.from_dict(payload).to_dict() == payload


@pytest.mark.parametrize("field", ["task_id", "status", "contract", "context", "checkpoint",
                                  "verification_receipts", "created_at", "updated_at", "heartbeat_expires_at"])
def test_task_state_missing_provenance_rejects(field):
    payload = task_payload()
    del payload[field]
    with pytest.raises(KeyError):
        TaskState.from_dict(payload)


@pytest.mark.parametrize("field", ["created_at", "updated_at", "heartbeat_expires_at"])
@pytest.mark.parametrize("value", [True, -1, "1", None, float("nan"), float("inf"), 10**1000])
def test_task_state_invalid_time_rejects(field, value):
    payload = task_payload()
    payload[field] = value
    with pytest.raises(ValueError):
        TaskState.from_dict(payload)


@pytest.mark.parametrize("value", [42, None, "task\x00-1", " task-1"])
def test_task_state_identity_rejects(value):
    payload = task_payload()
    payload["task_id"] = value
    with pytest.raises(ValueError):
        TaskState.from_dict(payload)


@pytest.mark.parametrize("field", ["start_line", "end_line"])
@pytest.mark.parametrize("value", [True, "2", 1.5, 0, -1])
def test_artifact_line_bounds_reject_before_storage(field, value):
    # No store initialization or real state access is needed to validate inputs.
    store = object.__new__(ArtifactStore)
    with pytest.raises(ValueError):
        store.get_lines("artifact-1", **{field: value})
