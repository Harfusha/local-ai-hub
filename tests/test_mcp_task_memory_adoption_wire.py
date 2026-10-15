from __future__ import annotations

import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

# Run the focused regression batch without importing an operator configuration
# during collection. This changes only this test runner's inherited environment.
if __name__ == "__main__":
    import os
    import tempfile

    with tempfile.TemporaryDirectory(prefix="mcp-memory-wire-regressions-") as directory:
        config = Path(directory) / "config.toml"
        config.write_text(
            '[server]\nport=9\nauto_start_ollama=true\nstate_dir='
            + json.dumps((Path(directory) / "state").as_posix())
            + '\n[hardware]\nprofile="cpu"\nauto_tune=false\n'
              '[ollama]\nenabled=false\n[llama_cpp]\nmode="off"\n', encoding="utf-8")
        os.environ["LOCAL_AI_CONFIG"] = str(config)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from local_ai_hub import mcp_server as isolated_mcp

        isolated_mcp.CLIENT.auto_start = False
        isolated_mcp._ACCOUNTING_REPORTER.record = lambda event: None
        import pytest

        raise SystemExit(pytest.main(sys.argv[1:]))

import anyio
from jsonschema import Draft202012Validator
from mcp import ClientSession
import mcp.client.stdio as stdio
import pytest

from local_ai_hub.operation_contracts import validate_operation_output
from local_ai_hub.token_accounting import json_tokens


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "00000000-0000-0000-0000-000000000001"
INSTRUCTION = (
    "Memory is advisory. Cite used memory IDs in the next checkpoint; otherwise record "
    "not_used_reason. Verify volatile facts against current source before relying on them."
)


def _memory(root: Path):
    return {
        "schema_version": 1, "tenant_key": "7" * 64, "instruction": INSTRUCTION,
        "items": [
            {"id": "M00000000000000000000000000000001", "origin": "memory_store",
             "content": "Use the lease owner and preserve dirty source changes.",
             "source": "human_instruction", "scope": "repository", "scope_id": str(root),
             "status": "confirmed", "version": "17",
             "validity": {"created_at": 1791763200.0, "updated_at": 1791849600.0,
                          "expires_at": 4102444800.0},
             "confidence": 1.0, "volatile": False,
             "provenance": {"repository_revision": "abc123", "evidence_ids": ["E" + "a" * 20]},
             "estimated_tokens": 15},
            {"id": "M00000000000000000000000000000002", "origin": "memory_store",
             "content": "Check the current package bytes before adopting older release evidence.",
             "source": "source_receipt", "scope": "task", "scope_id": TASK_ID,
             "status": "confirmed", "version": "3",
             "validity": {"created_at": 1791763200.0, "updated_at": 1791849600.0,
                          "expires_at": None},
             "confidence": 0.9, "volatile": True, "provenance": {}, "estimated_tokens": 18},
        ], "warnings": [], "estimated_tokens": 75,
    }


def _round_trip(tmp_path, requests, monkeypatch, *, real_store=False, return_store=False):
    repo = tmp_path / "repository"
    repo.mkdir()
    expected = _memory(repo)
    calls = []
    current_audit = None
    tasks = None
    if real_store:
        from dataclasses import replace
        from local_ai_hub.agent_context import ContextCompiler
        from local_ai_hub.agent_events import AgentStateStore
        from local_ai_hub.agent_identity import AgentScope, ScopeContext
        from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore
        from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, TaskCheckpoint, TaskStore
        from local_ai_hub import trace_context

        state_store = AgentStateStore(tmp_path / "real-agent-state.sqlite3")
        tasks = TaskStore(state_store)
        memory_store = MemoryStore(state_store)
        memory_store.record(replace(MemoryRecord.create(
            kind=MemoryKind.FACT, scope=AgentScope.REPOSITORY, scope_id=str(repo),
            key="renderer cache", value="Renderer cache uses the current theme revision",
            source="user", status=MemoryStatus.CONFIRMED,
            provenance={"root": str(repo), "tenant": "memory-wire-test", "version": "v1"},
        ), record_id="mem_store_wire"), actor="user")
        tasks.set_memory_adoption(memory_store=memory_store,
            context_compiler=ContextCompiler(state_store, task_store=tasks, memory_store=memory_store))

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            nonlocal current_audit
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            request_id = self.headers.get("X-LocalAI-Request-ID", "")
            calls.append({"path": self.path, "body": body, "request_id": request_id})
            if tasks is not None:
                token = trace_context.set_context(
                    request_id=request_id, trace_id=request_id, tenant="memory-wire-test")
                try:
                    action = body["action"]
                    if action == "create":
                        task = tasks.create(GoalContract(goal="Verify renderer cache theme revision"),
                            ScopeContext(repository_id=str(repo), task_id=TASK_ID), task_id=TASK_ID,
                            repo_root=str(repo), actor="wire-owner")
                    elif action == "checkpoint":
                        try:
                            task = tasks.checkpoint(
                                TASK_ID, TaskCheckpoint.from_dict(body["checkpoint"]),
                                response_budget_tokens=body.get("response_budget_tokens"),
                                actor="wire-owner")
                        except (ValueError, CompletionGateError) as exc:
                            from local_ai_hub.agent_tasks import CheckpointResponseBudgetError
                            if isinstance(exc, CheckpointResponseBudgetError):
                                status = 413
                                payload = {
                                    "success": False, "error": str(exc), "status_code": status,
                                    "terminal": True, "retryable": False,
                                    "mutation_applied": False, "operation_not_started": True,
                                    "request_id": request_id,
                                    "response_budget": {"requested_tokens": exc.requested_tokens,
                                                        "required_tokens": exc.required_tokens,
                                                        "unit": "estimated_tokens"},
                                }
                            else:
                                status = 400
                                payload = {"success": False, "error": str(exc), "status_code": status,
                                           "request_id": request_id,
                                           "terminal": True, "retryable": False}
                            encoded = json.dumps(payload).encode()
                            self.send_response(status)
                            self.send_header("Content-Type", "application/json")
                            self.send_header("Content-Length", str(len(encoded)))
                            self.end_headers()
                            self.wfile.write(encoded)
                            return
                    elif action == "resume":
                        task = tasks.resume(TASK_ID, actor="wire-owner", idempotency_key="wire-resume")
                    else:
                        task = tasks.get(TASK_ID)
                    encoded = json.dumps({"success": True, "task": task.to_dict(),
                                          "request_id": request_id}).encode()
                finally:
                    trace_context.reset_context(token)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            if body["action"] == "checkpoint":
                current_audit = copy.deepcopy(body["checkpoint"]["state_data"]["memory_audit"])
            elif body["action"] == "resume":
                current_audit = None
            payload = {
                "success": True, "context_id": "memory-context-17", "request_id": request_id,
                "task": {"task_id": TASK_ID, "status": "running", "owner": "wire-owner",
                         "context": {"task_id": TASK_ID, "clone_id": "clone-wire",
                                     "session_id": "session-wire", "repository_id": "repo-wire",
                                     "worktree_id": "worktree-wire", "branch": "test",
                                     "user_blob": "private context blob " * 4000},
                         "created_at": 1791763200.0, "updated_at": 1791849600.0 + len(calls),
                         "contract": {"goal": "private goal " * 4000},
                         "checkpoint": {"phase": "implement", "state_data": {
                             "memory_context": copy.deepcopy(expected),
                             "memory_audit": copy.deepcopy(current_audit),
                             "memory_audit_history": ["private history " * 4000],
                             "raw_debug": "private checkpoint debug " * 4000}}},
                "raw_model_output": "private model trace " * 4000,
            }
            if body.get("reason") == "failure":
                payload.update(success=False, error="Task is cancelled", status_code=409,
                               terminal=True, retryable=False)
            if body.get("reason") == "unchanged":
                payload["task"]["updated_at"] = 1791849600.0
            encoded = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    http.daemon_threads = True
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    config = tmp_path / "config.toml"
    config.write_text(
        f"[server]\nport={http.server_port}\nauto_start_ollama=false\nstate_dir="
        + json.dumps((tmp_path / "state").as_posix())
        + '\n[hardware]\nprofile="cpu"\nauto_tune=false\n'
          '[ollama]\nenabled=false\n[llama_cpp]\nmode="off"\n'
          '[mcp.response_budget.tool_tokens]\nlocal_ai_coord=3200\n', encoding="utf-8")
    bootstrap = (
        "import sys; sys.path.insert(0,sys.argv[1]); "
        "import local_ai_hub.mcp_server as server; server.CLIENT.auto_start=False; "
        "server._ACCOUNTING_REPORTER.record=lambda event:None; server.main()"
    )
    params = stdio.StdioServerParameters(command=sys.executable,
        args=["-B", "-c", bootstrap, str(ROOT / "src")], cwd=tmp_path,
        env={"LOCAL_AI_CONFIG": str(config), "LOCAL_AI_TENANT": "memory-wire-test"})
    children = []
    spawn = stdio._create_platform_compatible_process

    async def capture(*args, **kwargs):
        with anyio.CancelScope(shield=True):
            child = await spawn(*args, **kwargs)
            children.append(child)
        return child

    monkeypatch.setattr(stdio, "_create_platform_compatible_process", capture)

    async def run():
        results = []
        try:
            with (tmp_path / "stderr.log").open("w", encoding="utf-8") as errlog:
                async with stdio.stdio_client(params, errlog=errlog) as (read, write):
                    async with ClientSession(read, write) as session:
                        with anyio.fail_after(20):
                            await session.initialize()
                            listed = await session.list_tools()
                            for arguments in requests:
                                results.append(await session.call_tool("local_ai_coord", {
                                    "root": str(repo), "task_id": TASK_ID, **arguments}))
            return listed, results
        finally:
            with anyio.CancelScope(shield=True):
                for child in children:
                    if child.returncode is None:
                        await stdio._terminate_process_tree(child, timeout_seconds=2)

    try:
        listed, results = anyio.run(run)
    finally:
        http.shutdown()
        thread.join(timeout=2)
        http.server_close()
    assert not thread.is_alive()
    assert len(children) == 1 and children[0].returncode == 0
    tool = next(tool for tool in listed.tools if tool.name == "local_ai_coord")
    Draft202012Validator.check_schema(tool.inputSchema)
    Draft202012Validator.check_schema(tool.outputSchema)
    for request, result in zip(requests, results):
        payload = result.structuredContent
        assert isinstance(payload, dict), result
        Draft202012Validator(tool.outputSchema).validate(payload)
        assert validate_operation_output("local_ai_coord", request["action"], payload) is None
        wire_tokens = json_tokens(result.model_dump(mode="json", by_alias=True, exclude_none=True))
        requested = request.get("max_response_tokens", 3200)
        assert wire_tokens <= requested
        assert payload["response_budget"]["returned_tokens"] == wire_tokens
    if return_store:
        return expected, calls, results, tasks
    return expected, calls, results


def test_real_store_create_checkpoint_get_and_resume_deliver_memories_over_stdio(tmp_path, monkeypatch):
    audit = {"used_ids": ["mem_store_wire"]}
    requests = [
        {"action": "task_create", "contract": {"goal": "Verify renderer cache theme revision"}},
        {"action": "task_checkpoint", "checkpoint": {"phase": "edit", "state_data": {"memory_audit": audit}}},
        {"action": "task_get"},
        {"action": "task_resume"},
    ]
    _, calls, results = _round_trip(tmp_path, requests, monkeypatch, real_store=True)
    for result in results:
        payload = result.structuredContent
        assert payload["success"] is True, json.dumps(payload)
        context = payload["task"]["checkpoint"]["state_data"]["memory_context"]
        assert [item["id"] for item in context["items"]] == ["mem_store_wire"]
        assert "Cite used memory IDs" in context["instruction"]
        assert context["items"][0]["origin"] == "memory_store"
        assert context["items"][0]["scope"] == "repository"
        assert context["items"][0]["version"] == "v1"
        assert "expires_at" in context["items"][0]["validity"]
        assert json_tokens(context) == context["estimated_tokens"] <= 512
    assert results[1].structuredContent["task"]["checkpoint"]["state_data"]["memory_audit"] == audit
    assert results[2].structuredContent["task"]["checkpoint"]["state_data"]["memory_audit"] == audit
    assert results[3].structuredContent["task"]["checkpoint"]["state_data"]["memory_audit"] is None
    assert [call["body"]["action"] for call in calls] == ["create", "checkpoint", "get", "resume"]


def test_registered_mcp_checkpoint_budget_preflight_is_atomic_at_128_tokens(tmp_path, monkeypatch):
    audit = {"used_ids": ["mem_store_wire"]}
    _, calls, results, tasks = _round_trip(tmp_path, [
        {"action": "task_create", "contract": {"goal": "Verify renderer cache theme revision"}},
        {"action": "task_checkpoint", "checkpoint": {"phase": "edit", "state_data": {"memory_audit": audit}},
         "response_profile": "compact", "max_response_tokens": 128},
    ], monkeypatch, real_store=True, return_store=True)
    result = results[1]
    payload = result.structuredContent
    assert payload["success"] is False
    assert payload["mutation_applied"] is False
    assert payload["operation_not_started"] is True
    assert "request_not_sent" not in payload
    assert payload["request_id"] == calls[-1]["request_id"]
    assert payload["response_budget"]["returned_tokens"] == json_tokens(
        result.model_dump(mode="json", by_alias=True, exclude_none=True))
    task = tasks.get(TASK_ID)
    assert "memory_audit" not in task.checkpoint.state_data
    assert tasks.state_store.event_page(f"task:{TASK_ID}")["last_seq"] == 1
    assert calls[-1]["body"]["response_budget_tokens"] == 128


def test_registered_mcp_checkpoint_preflight_allows_full_memory_wire(tmp_path, monkeypatch):
    audit = {"used_ids": ["mem_store_wire"]}
    _, calls, results, tasks = _round_trip(tmp_path, [
        {"action": "task_create", "contract": {"goal": "Verify renderer cache theme revision"}},
        {"action": "task_checkpoint", "checkpoint": {"phase": "edit", "state_data": {"memory_audit": audit}},
         "response_profile": "compact", "max_response_tokens": 3200},
    ], monkeypatch, real_store=True, return_store=True)
    payload = results[1].structuredContent
    assert payload["success"] is True
    assert payload["request_id"] == calls[-1]["request_id"]
    assert payload["task"]["checkpoint"]["state_data"]["memory_audit"] == audit
    assert tasks.get(TASK_ID).checkpoint.state_data["memory_audit"] == audit
    assert tasks.state_store.event_page(f"task:{TASK_ID}")["last_seq"] == 2
    assert calls[-1]["body"]["response_budget_tokens"] == 3200


def test_registered_mcp_checkpoint_rejects_malformed_audit_before_preflight(tmp_path, monkeypatch):
    _, _, results, tasks = _round_trip(tmp_path, [
        {"action": "task_create", "contract": {"goal": "Verify renderer cache theme revision"}},
        {"action": "task_checkpoint", "checkpoint": {"phase": "edit", "state_data": {"memory_audit": {}}},
         "response_profile": "compact", "max_response_tokens": 3200},
    ], monkeypatch, real_store=True, return_store=True)
    payload = results[1].structuredContent
    assert payload["success"] is False
    assert "memory_audit" in payload["error"]
    assert tasks.state_store.event_page(f"task:{TASK_ID}")["last_seq"] == 1
    assert "memory_audit" not in tasks.get(TASK_ID).checkpoint.state_data


@pytest.mark.parametrize("action", ["task_create", "task_resume"])
@pytest.mark.parametrize("profile,budget", [("compact", 3200), ("minimal", 2000), ("compact", 2000)])
def test_stdio_task_memory_is_automatically_delivered(tmp_path, monkeypatch, action, profile, budget):
    expected, calls, results = _round_trip(tmp_path, [
        {"action": action, "contract": {"goal": "wire task"},
         "response_profile": profile, "max_response_tokens": budget}], monkeypatch)
    payload = results[0].structuredContent
    assert payload["success"] is True, payload
    assert payload["task"]["checkpoint"]["state_data"]["memory_context"] == expected
    assert "private" not in json.dumps(payload)
    assert [(c["path"], c["body"]["action"]) for c in calls] == [
        ("/api/agent-state/tasks", action.removeprefix("task_"))]


def test_stdio_delta_keeps_unchanged_memory_and_usage_instructions(tmp_path, monkeypatch):
    arguments = {"action": "task_resume", "response_profile": "delta",
                 "max_response_tokens": 2000, "reuse_key": "memory-wire-resume"}
    expected, calls, results = _round_trip(tmp_path, [arguments, arguments], monkeypatch)
    for result in results:
        payload = result.structuredContent
        assert payload["success"] is True
        assert payload["task"]["checkpoint"]["state_data"]["memory_context"] == expected
    assert len(calls) == 2
    assert "delta" in results[1].structuredContent


def test_stdio_reused_memory_pointer_still_delivers_complete_advice(tmp_path, monkeypatch):
    arguments = {"action": "task_resume", "reason": "unchanged", "response_profile": "minimal",
                 "max_response_tokens": 2000, "reuse_key": "memory-wire-unchanged"}
    expected, _, results = _round_trip(tmp_path, [arguments, arguments], monkeypatch)
    assert results[1].structuredContent["reused"] is True
    for result in results:
        assert result.structuredContent["task"]["checkpoint"]["state_data"]["memory_context"] == expected


def test_stdio_default_budget_delivers_memory_without_extra_fields(tmp_path, monkeypatch):
    expected, _, results = _round_trip(tmp_path, [
        {"action": "task_create", "contract": {"goal": "wire task"}}], monkeypatch)
    payload = results[0].structuredContent
    assert payload["response_budget"]["requested_tokens"] == 3200
    assert payload["task"]["checkpoint"]["state_data"]["memory_context"] == expected


def test_stdio_subminimum_quota_rejected_before_task_side_effect(tmp_path, monkeypatch):
    _, calls, results = _round_trip(tmp_path, [
        {"action": "task_create", "contract": {"goal": "wire task"},
         "max_response_tokens": 127}], monkeypatch)
    assert results[0].structuredContent["success"] is False
    assert "128" in results[0].structuredContent["error"]
    assert calls == []


@pytest.mark.parametrize("action", ["task_create", "task_resume"])
def test_stdio_tiny_budget_explicitly_rejects_memory_delivery(tmp_path, monkeypatch, action):
    _, calls, results = _round_trip(tmp_path, [
        {"action": action, "contract": {"goal": "wire task"},
         "response_profile": "minimal", "max_response_tokens": 128}], monkeypatch)
    payload = results[0].structuredContent
    assert payload["success"] is False
    assert payload["error"] == "budget_too_small"
    assert payload["terminal"] is True and payload["retryable"] is False
    assert payload["task_id"] == TASK_ID
    assert len(calls) == 1


def test_stdio_memory_task_preserves_upstream_error_state(tmp_path, monkeypatch):
    expected, _, results = _round_trip(tmp_path, [
        {"action": "task_resume", "reason": "failure", "max_response_tokens": 3200}], monkeypatch)
    payload = results[0].structuredContent
    assert payload["success"] is False and payload["status_code"] == 409
    assert payload["error"] == "Task is cancelled"
    assert payload["terminal"] is True and payload["retryable"] is False
    assert payload["task"]["checkpoint"]["state_data"]["memory_context"] == expected


def test_stdio_tiny_memory_budget_keeps_upstream_failure_identity(tmp_path, monkeypatch):
    _, _, results = _round_trip(tmp_path, [
        {"action": "task_resume", "reason": "failure", "max_response_tokens": 128}], monkeypatch)
    payload = results[0].structuredContent
    assert payload["success"] is False and payload["error"] == "budget_too_small"
    assert payload["status_code"] == 409 and payload["source_error"] == "Task is cancelled"
    assert payload["task_id"] == TASK_ID
    assert payload["terminal"] is True and payload["retryable"] is False


def test_stdio_checkpoint_get_show_current_audit_and_resume_resets_it(tmp_path, monkeypatch):
    memory_id = "M00000000000000000000000000000002"
    evidence_id = "E" + "b" * 20
    audit = {"used_ids": [memory_id], "not_used_reason": "", "source_checked": True,
             "source_checks": {memory_id: {"checked": True, "evidence_ids": [evidence_id],
                                           "raw_source": "private source body " * 4000}},
             "raw_debug": "private audit debug " * 4000}
    _, calls, results = _round_trip(tmp_path, [
        {"action": "task_checkpoint", "max_response_tokens": 2000, "checkpoint": {
            "phase": "implement", "state_data": {"memory_audit": audit}}},
        {"action": "task_get", "max_response_tokens": 2000},
        {"action": "task_resume", "max_response_tokens": 2000},
    ], monkeypatch)
    projected_audit = {"used_ids": [memory_id], "not_used_reason": "", "source_checked": True,
                       "source_checks": {memory_id: {"checked": True, "evidence_ids": [evidence_id]}}}
    for result in results[:2]:
        payload = result.structuredContent
        assert payload["task"]["checkpoint"]["state_data"]["memory_audit"] == projected_audit
        assert "private" not in json.dumps(payload)
        assert set(payload["task"]["context"]) == {
            "task_id", "clone_id", "session_id", "repository_id", "worktree_id", "branch"}
    resumed = results[2].structuredContent
    assert resumed["task"]["checkpoint"]["state_data"]["memory_audit"] is None
    assert [call["body"]["action"] for call in calls] == ["checkpoint", "get", "resume"]


def test_task_memory_wire_cannot_succeed_with_overlong_identity_at_tiny_budget():
    from local_ai_hub import mcp_server

    contents, structured = mcp_server._mcp_budget_payload("local_ai_coord", {
        "action": "task_resume", "max_response_tokens": 128,
    }, {"success": True, "task_id": "t" * 2000, "task": {
        "task_id": "t" * 2000, "status": "running", "checkpoint": {
            "state_data": {"memory_context": _memory(Path("repository"))}}}})
    assert structured["success"] is False
    assert structured["error"] == "budget_too_small"
    assert structured["terminal"] is True and structured["retryable"] is False
    assert structured["result_id"]
    wire = {"content": [{"type": "text", "text": contents[0].text}],
            "structuredContent": structured, "isError": False}
    assert json_tokens(wire) <= 128
    assert structured["response_budget"]["returned_tokens"] == json_tokens(wire)
