from __future__ import annotations

import asyncio

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operational_mode import OperationalModeSnapshot
from local_ai_hub.operation_contracts import validate_operation_arguments


@pytest.fixture(autouse=True)
def _active_task_mode(monkeypatch):
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)
    monkeypatch.setattr(mcp_server.FEATURES, "vision", True)
    snapshot = OperationalModeSnapshot("active", 1, None)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: snapshot)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_args, **_kwargs: None)


class DummyClient:
    def __init__(self):
        self.calls = []

    def post(self, path, payload, **kwargs):
        self.calls.append((path, payload))
        return {"success": True}


@pytest.mark.parametrize(("action", "canonical", "retired"), [
    ("hardware_benchmark", {"prompt": "benchmark prompt"}, {"task": "old prompt"}),
    ("speculative_draft", {"task": "draft task"}, {"prompt": "old task"}),
    ("speculative_draft", {"candidate": "src/a.py"}, {"workspace": "src/a.py"}),
    ("vision", {"prompt": "inspect", "candidate": "image.png"}, {"task": "old prompt"}),
    ("vision", {"prompt": "inspect", "candidate": "image.png"}, {"context": "old image"}),
    ("eval_drift", {"task": "suite-a"}, {"prompt": "suite-a"}),
    ("complete_code", {"prompt": "prefix", "candidate": "suffix"}, {"context": "old prefix"}),
    ("complete_code", {"prompt": "prefix", "candidate": "suffix"}, {"task": "old suffix"}),
    ("scaffold", {"prompt": "spec", "language": "rust"}, {"task": "old spec"}),
    ("scaffold", {"prompt": "spec", "language": "rust"}, {"candidate": "rust"}),
    ("transcribe", {"candidate": "audio.wav"}, {"context": "old audio"}),
    ("transcribe", {"candidate": "audio.wav"}, {"task": "old audio"}),
    ("transcribe", {"candidate": "audio.wav"}, {"prompt": "old audio"}),
    ("eval_suite", {"task": "suite"}, {"prompt": "old suite"}),
    ("prompt_eval", {"prompt": "template"}, {"task": "old template"}),
    ("prompt_eval", {"prompt": "template"}, {"context": "old variables"}),
])
def test_registered_task_handler_rejects_retired_aliases_before_dispatch(
    action, canonical, retired, monkeypatch,
):
    client = DummyClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_task", {"action": action, **canonical, **retired},
    ))

    assert client.calls == []
    assert "400" in str(result)


@pytest.mark.parametrize(("action", "arguments", "path", "expected"), [
    ("hardware_benchmark", {"prompt": "measure", "model": "m"}, "/api/benchmark/run",
     {"model": "m", "prompt": "measure", "num_tokens": 40}),
    ("speculative_draft", {"task": "draft", "candidate": "src/a.py", "context": "ctx", "root": "repo"},
     "/api/task/speculative_draft", {"task": "draft", "file": "src/a.py", "context": "ctx", "root": "repo"}),
    ("vision", {"prompt": "inspect", "candidate": "image.png", "image_artifact_id": "image-id",
                 "screenshot_artifact_id": "shot-id", "bundle_artifact_id": "bundle-id"},
     "/api/task/vision", {"prompt": "inspect", "image": "image.png", "image_artifact_id": "image-id",
                          "screenshot_artifact_id": "shot-id", "bundle_artifact_id": "bundle-id"}),
    ("eval_drift", {}, "/api/task/eval_drift", {"suite_name": "default"}),
    ("complete_code", {"prompt": "prefix", "candidate": "suffix"}, "/api/complete",
     {"prefix": "prefix", "suffix": "suffix", "max_tokens": 80}),
    ("complete_code", {}, "/api/complete", {"prefix": "", "suffix": "", "max_tokens": 80}),
    ("scaffold", {"prompt": "spec", "language": "auto", "context": "ctx"}, "/api/task/scaffold",
     {"spec": "spec", "context": "ctx", "language": "python", "max_tokens": 4096, "model": ""}),
    ("transcribe", {"candidate": "audio.wav", "model": "m", "language": "fr"}, "/api/task/transcribe",
     {"audio_path": "audio.wav", "model": "m", "language": "fr"}),
    ("eval_suite", {"task": "suite-a", "model": "m", "cases": [
        {"id": "smoke", "input": "x", "expected": "y"},
    ]}, "/api/task/eval_suite", {
        "suite_name": "suite-a", "model": "m",
        "cases": [{"id": "smoke", "input": "x", "expected": "y"}],
    }),
    ("eval_suite", {}, "/api/task/eval_suite", {"suite_name": "default"}),
    ("prompt_eval", {"prompt": "template", "candidate_data": {}}, "/api/task/prompt_eval",
     {"template": "template", "variables": {}}),
])
def test_registered_task_handler_dispatches_canonical_inputs(
    action, arguments, path, expected, monkeypatch,
):
    client = DummyClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)

    asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_task", {"action": action, **arguments},
    ))

    assert len(client.calls) == 1
    assert client.calls[0][0] == path
    assert {key: client.calls[0][1][key] for key in expected} == expected


def test_vision_contract_keeps_distinct_artifact_inputs():
    values = {
        "prompt": "inspect", "candidate": "image.png", "root": "repo",
        "image_artifact_id": "image", "screenshot_artifact_id": "screen",
        "baseline_screenshot_artifact_id": "baseline", "bundle_artifact_id": "bundle",
        "dom_artifact_id": "dom-id", "accessibility_artifact_id": "a11y-id",
        "computed_styles_artifact_id": "styles-id", "runtime_artifact_id": "runtime-id",
        "network_artifact_id": "network-id", "source": "browser",
        "cloud_fallback": True, "dom": {}, "accessibility": {}, "computed_styles": {},
        "runtime": {}, "viewport": {}, "page": {}, "bundle": {}, "html": "<main />",
        "accessibility_snapshot": {}, "computed_style_data": {}, "runtime_context": {},
        "json_schema": {},
    }
    assert validate_operation_arguments("local_ai_task", "vision", values) is None


@pytest.mark.parametrize(("action", "arguments", "alias"), [
    ("hardware_benchmark", {"prompt": "benchmark"}, {"task": "old prompt"}),
    ("speculative_draft", {"task": "draft"}, {"prompt": "old task"}),
    ("vision", {"prompt": "inspect", "candidate": "image.png"}, {"context": "old image"}),
    ("eval_drift", {"task": "suite"}, {"prompt": "old suite"}),
    ("complete_code", {"prompt": "prefix", "candidate": "suffix"}, {"task": "old suffix"}),
    ("scaffold", {"prompt": "spec", "language": "rust"}, {"candidate": "old language"}),
    ("transcribe", {"candidate": "audio.wav"}, {"prompt": "old audio"}),
    ("eval_suite", {"task": "suite"}, {"prompt": "old suite"}),
    ("prompt_eval", {"prompt": "template"}, {"context": "old variables"}),
])
def test_direct_task_impl_rejects_retired_aliases(action, arguments, alias, monkeypatch):
    client = DummyClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    implementation = mcp_server.local_ai_task
    while hasattr(implementation, "__wrapped__"):
        implementation = implementation.__wrapped__

    result = implementation(action=action, **arguments, **alias)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert client.calls == []


def test_task_action_contract_accepts_canonical_task_inputs_and_rejects_aliases():
    cases = [
        ("hardware_benchmark", {"prompt": "benchmark"}, {"task": "alias"}),
        ("speculative_draft", {"task": "draft", "candidate": "src/a.py"}, {"prompt": "alias"}),
        ("vision", {"prompt": "inspect", "candidate": "image.png", "screenshot_artifact_id": "shot"},
         {"task": "alias"}),
        ("eval_drift", {}, {"prompt": "alias"}),
        ("complete_code", {"prompt": "prefix", "candidate": "suffix"}, {"task": "alias"}),
        ("scaffold", {"prompt": "spec", "language": "auto"}, {"candidate": "alias"}),
        ("transcribe", {"candidate": "audio.wav"}, {"context": "alias"}),
        ("eval_suite", {"task": "suite"}, {"prompt": "alias"}),
        ("prompt_eval", {"prompt": "template"}, {"task": "alias"}),
    ]
    for action, canonical, alias in cases:
        assert validate_operation_arguments("local_ai_task", action, canonical) is None
        assert validate_operation_arguments("local_ai_task", action, {**canonical, **alias}) is not None
