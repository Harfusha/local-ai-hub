import asyncio
import concurrent.futures
import json
import socket
import threading
import time
import httpx
import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from local_ai_hub.mcp_http import create_app


def test_tiered_stream_forwards_cancellation_and_deadline():
    from types import SimpleNamespace
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime
    stop = lambda: False
    seen = {}
    def stream(*args, **kwargs):
        seen.update(kwargs)
        return {"message": {}}
    runtime = TieredOllamaRuntime.__new__(TieredOllamaRuntime)
    runtime.fast = SimpleNamespace(request_stream=stream)
    runtime.request_stream("/api/chat", {}, None, should_stop=stop, deadline=123.0)
    assert seen["should_stop"] is stop and seen["deadline"] == 123.0


@pytest.mark.parametrize("method", ["stream", "interruptible"])
def test_tiered_waiting_request_cancels_without_disturbing_lock_owner(method):
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime
    runtime = TieredOllamaRuntime.__new__(TieredOllamaRuntime)
    runtime._lock = threading.RLock()
    runtime._target = lambda model: pytest.fail("cancelled request reached model handoff")
    cancel = threading.Event()
    runtime._lock.acquire()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        def call():
            if method == "stream":
                return runtime.request_stream("/api/chat", {"model": "m"}, None, should_stop=cancel.is_set)
            return runtime.request_interruptible("/api/chat", {"model": "m"}, cancel.is_set)
        future = pool.submit(call)
        try:
            cancel.set()
            result = future.result(timeout=1)
            assert result.get("preempted") is True
        finally:
            runtime._lock.release()


def test_tiered_waiting_request_respects_deadline():
    from local_ai_hub.tiered_ollama import TieredOllamaRuntime
    runtime = TieredOllamaRuntime.__new__(TieredOllamaRuntime)
    runtime._lock = threading.RLock()
    runtime._target = lambda model: pytest.fail("expired request reached model handoff")
    runtime._lock.acquire()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(runtime.request_interruptible, "/api/chat", {"model": "m"},
                                 lambda: False, deadline=time.monotonic() + 0.1)
            assert future.result(timeout=1).get("timed_out") is True
    finally:
        runtime._lock.release()


def test_project_profile_forwards_event_to_agent_run():
    from types import SimpleNamespace
    from local_ai_hub.tool_agent import ToolAwareLocalAgent
    event = threading.Event()
    profile = SimpleNamespace(name="p", model="m", role="worker", max_tokens=8,
                              advisory_only=True, declared_model="m", model_fallback=False,
                              model_fallback_reason="", tools=[])
    agent = ToolAwareLocalAgent.__new__(ToolAwareLocalAgent)
    agent.profile_catalog = SimpleNamespace(enabled=True, resolve=lambda *a, **k: profile,
                                            detect_language=lambda task: "en")
    agent.services = SimpleNamespace(runtime=SimpleNamespace(installed_models=lambda: ["m"]))
    def run(*args, **kwargs):
        assert kwargs["cancel_event"] is event
        return {"success": False, "cancelled": True}
    agent.run = run
    assert agent.run_profile("p", "test", "C:/test", cancel_event=event)["cancelled"] is True


@pytest.mark.parametrize("traced", [False, True])
def test_project_tool_agent_cancels_running_generation_without_sharing_cache(tmp_path, monkeypatch, traced):
    from types import SimpleNamespace
    import local_ai_hub.tool_agent as tool_agent
    from local_ai_hub.tool_agent import ToolAwareLocalAgent

    started, cancelled = threading.Event(), threading.Event()
    event = threading.Event()
    class Runtime:
        def request_interruptible(self, endpoint, payload, should_stop, **kwargs):
            started.set()
            while not should_stop():
                time.sleep(0.01)
            cancelled.set()
            return {"error": "cancelled", "preempted": True}
        def request_stream(self, endpoint, payload, on_chunk, *, on_thinking, should_stop):
            return self.request_interruptible(endpoint, payload, should_stop)
    class Scheduler:
        def submit(self, model, *, execute, cancel_event=None, **kwargs):
            assert cancel_event is event
            return execute()
    class Cache:
        def get_or_compute(self, *args):
            raise AssertionError("cancellable generation must not share work")
    policy = SimpleNamespace(profile=lambda *a, **k: SimpleNamespace(cache_scope=lambda: {}),
                             apply_payload=lambda model, payload, **kwargs: (payload, None))
    services = SimpleNamespace(config={}, model_policy=policy, runtime=Runtime(), scheduler=Scheduler(),
        repo_tools=SimpleNamespace(_root=lambda root: root), _repo_cache_state=lambda root: {"fingerprint": "1"},
        generation_cache=Cache())
    preprocessor = SimpleNamespace(touch_if_registered=lambda root: None,
        context_revision=lambda root: "1", compact_context=lambda *args: "")
    agent = ToolAwareLocalAgent({"local_tools": {"bootstrap_deterministic_tools": False}},
                                services, preprocessor, SimpleNamespace(workspace_id=lambda root: "test"))
    trace = SimpleNamespace(model_request=lambda payload: None, output_delta=lambda value: None)
    monkeypatch.setattr(tool_agent, "observer", lambda: trace if traced else None)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(agent.run, "test", "worker", "test", str(tmp_path), 8, 5, cancel_event=event)
        try:
            assert started.wait(3), future.result(timeout=1) if future.done() else "model did not start"
            event.set()
            assert cancelled.wait(3)
            result = future.result(timeout=3)
            assert result.get("cancelled") is True and result.get("success") is False
        finally:
            event.set()


def test_profile_delegate_forwards_cancellation_to_generation():
    from types import SimpleNamespace
    from local_ai_hub.services import LocalAIServices

    event = threading.Event()
    profile = SimpleNamespace(name="test", role="delegate", model="test", max_tokens=8,
                              temperature=0, advisory_only=True, declared_model="test",
                              model_fallback=False, model_fallback_reason="")
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {}
    service.runtime = SimpleNamespace(installed_models=lambda: ["test"])
    service.profile_catalog = SimpleNamespace(
        enabled=True, resolve=lambda *a, **k: profile,
        system_contract=lambda *a, **k: "system", detect_language=lambda task: "en")
    def generate(*args, **kwargs):
        assert kwargs["cancel_event"] is event
        event.set()
        return {"success": True, "text": "late result"}
    service._generate = generate
    result = service.delegate({"profile": "test", "task": "bounded test"}, cancel_event=event)
    assert result.get("cancelled") is True
    assert result.get("success") is False


def test_profile_delegate_forwards_cancellation_to_tool_agent():
    from types import SimpleNamespace
    from local_ai_hub.services import LocalAIServices
    event = threading.Event()
    service = LocalAIServices.__new__(LocalAIServices)
    service.runtime = SimpleNamespace(installed_models=lambda: ["test"])
    service.profile_catalog = SimpleNamespace(enabled=True, resolve=lambda *a, **k: SimpleNamespace(name="test"))
    def run_profile(*args, **kwargs):
        assert kwargs["cancel_event"] is event
        return {"success": False, "cancelled": True}
    service.tool_agent = SimpleNamespace(run_profile=run_profile)
    assert service.delegate({"profile": "test", "task": "test", "root": "C:/test"}, cancel_event=event)["cancelled"]


def test_batch_cancellation_stops_current_and_skips_remaining_items():
    from types import SimpleNamespace
    from local_ai_hub.services import LocalAIServices
    event = threading.Event()
    calls = []
    service = LocalAIServices.__new__(LocalAIServices)
    service.router = SimpleNamespace(classify=lambda *args: {"model": "m"})
    service.scheduler = SimpleNamespace(status=lambda: {"active_model": "m"})
    def delegate(item, *, cancel_event):
        assert cancel_event is event
        calls.append(item["task"])
        event.set()
        return {"success": False, "cancelled": True}
    service.delegate = delegate
    result = service.batch_delegate({"tasks": [{"task": "a"}, {"task": "b"}]}, cancel_event=event)
    assert calls == ["a"]
    assert result["cancelled"] is True
    assert result["results"][1]["request_not_sent"] is True


def test_async_batch_does_not_dispatch_items_after_job_cancel(monkeypatch):
    from types import SimpleNamespace
    import local_ai_hub.services as services_module
    from local_ai_hub.services import LocalAIServices
    cancelled = threading.Event()
    calls = []
    monkeypatch.setattr(services_module, "current_job_should_stop", cancelled.is_set)
    service = LocalAIServices.__new__(LocalAIServices)
    service.router = SimpleNamespace(classify=lambda *args: {"model": "m"})
    service.scheduler = SimpleNamespace(status=lambda: {"active_model": "m"})
    def delegate(item):
        calls.append(item["task"])
        cancelled.set()
        return {"success": False, "cancelled": True}
    service.delegate = delegate
    result = service.batch_delegate({"tasks": [{"task": "a"}, {"task": "b"}]})
    assert calls == ["a"]
    assert result["cancelled"] is True
    assert result["results"][1]["request_not_sent"] is True


def test_async_batch_propagates_cancel_to_running_profile(monkeypatch):
    from types import SimpleNamespace
    import local_ai_hub.services as services_module
    from local_ai_hub.services import LocalAIServices
    cancelled, started, observed = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setattr(services_module, "capture_job_cancellation", lambda: cancelled.is_set)
    monkeypatch.setattr(services_module, "current_job_should_stop", cancelled.is_set)
    service = LocalAIServices.__new__(LocalAIServices)
    service.router = SimpleNamespace(classify=lambda *args: {"model": "m"})
    service.scheduler = SimpleNamespace(status=lambda: {"active_model": "m"})
    def delegate(item, *, cancel_event):
        started.set()
        deadline = time.monotonic() + 3
        while not cancel_event.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        if cancel_event.is_set():
            observed.set()
            return {"success": False, "cancelled": True}
        return {"success": False, "error": "timeout"}
    service.delegate = delegate
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.batch_delegate, {"tasks": [{"task": "a", "profile": "p"}]})
        try:
            assert started.wait(2)
            cancelled.set()
            assert observed.wait(2)
            assert future.result(timeout=2)["cancelled"] is True
        finally:
            cancelled.set()


def test_linked_cancellation_event_wait_observes_async_parent():
    from local_ai_hub.services import _LinkedCancelEvent
    parent, child = threading.Event(), threading.Event()
    linked = _LinkedCancelEvent(child, parent.is_set)
    assert linked.wait(0.01) is False
    parent.set()
    assert linked.wait(1) is True
    assert child.is_set()


def test_review_diff_propagates_cancellation_to_its_generation():
    from types import SimpleNamespace
    from local_ai_hub.services import LocalAIServices
    event = threading.Event()
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {}
    service.deterministic = None
    service.router = SimpleNamespace(classify=lambda *args: {"model": "m", "complexity": "fast"})
    service._resident_optimize = lambda route, *args: route
    service.model_policy = SimpleNamespace(tier_for=lambda model: "fast",
        profile=lambda *args, **kwargs: SimpleNamespace(prompt_budget_tokens=4096))
    def delegate(payload, *, cancel_event):
        assert cancel_event is event
        event.set()
        return {"success": False, "cancelled": True}
    service.delegate = delegate
    result = service.review_diff({"diff": "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new"}, cancel_event=event)
    assert result.get("cancelled") is True


def test_repo_delegate_forwards_cancel_event_after_context():
    from types import SimpleNamespace
    from local_ai_hub.services import LocalAIServices
    event = threading.Event()
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {}
    service.router = SimpleNamespace(classify=lambda *args: {"complexity": "fast"})
    service._hybrid_context = lambda *args, **kwargs: {"success": True, "context": "evidence"}
    def delegate(payload, *, cancel_event):
        assert cancel_event is event
        return {"success": False, "cancelled": True}
    service.delegate = delegate
    assert service.delegate_repo({"root": "C:/test", "task": "test"}, cancel_event=event)["cancelled"]


def test_pipeline_cancellable_stage_does_not_coalesce():
    from local_ai_hub.client import CURRENT_REQUEST_CANCEL_EVENT
    from local_ai_hub.pipeline import LocalAgentPipeline
    event = threading.Event()
    pipeline = LocalAgentPipeline.__new__(LocalAgentPipeline)
    class Cache:
        def get_or_compute(self, *args):
            raise AssertionError("cancellable request must not coalesce")
    pipeline.cache = Cache()
    token = CURRENT_REQUEST_CANCEL_EVENT.set(event)
    try:
        result = pipeline._stage({"test": "key"}, lambda: {"success": True})
    finally:
        CURRENT_REQUEST_CANCEL_EVENT.reset(token)
    assert result["success"] and not result["stage_coalesced"]


def test_cancellable_generations_do_not_share_inflight_result():
    from local_ai_hub.services import _generation_cache_dispatch
    events = [threading.Event(), threading.Event()]
    started = [threading.Event(), threading.Event()]
    class Cache:
        def get_or_compute(self, *args):
            raise AssertionError("cancellable generations must not coalesce")
    def generate(index):
        started[index].set()
        assert events[index].wait(3)
        return {"success": index == 1, "cancelled": index == 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_generation_cache_dispatch, Cache(), "same", lambda i=i: generate(i),
                               lambda i=i: generate(i), use_cache=True, request_cancel_event=events[i])
                   for i in range(2)]
        try:
            assert all(start.wait(2) for start in started)
            events[0].set()
            assert futures[0].result(timeout=2)[0]["cancelled"]
            assert not futures[1].done()
            events[1].set()
            assert futures[1].result(timeout=2)[0]["success"]
        finally:
            for event in events:
                event.set()


@pytest.mark.parametrize("operation", ["scaffold", "generate_tests", "speculative_draft"])
def test_code_generation_routes_forward_cancel_event(operation):
    from local_ai_hub.services import LocalAIServices
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {}
    service.code_index = None
    event = threading.Event()
    def generate(*args, **kwargs):
        assert kwargs["cancel_event"] is event
        event.set()
        return {"success": True, "text": "late result"}
    service._generate = generate
    if operation == "scaffold":
        result = service.task_scaffold({"prompt": "make a function"}, cancel_event=event)
    elif operation == "generate_tests":
        result = service.generate_tests({"symbol": "example"}, cancel_event=event)
    else:
        result = service.speculative_draft({"task": "make a function"}, cancel_event=event)
    assert result.get("cancelled") is True and result.get("success") is False


def test_completion_interrupts_backend_without_sharing_work():
    from types import SimpleNamespace
    from local_ai_hub.services import LocalAIServices
    event = threading.Event()
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {}
    def request(endpoint, payload, should_stop, **kwargs):
        event.set()
        assert should_stop()
        return {"error": "cancelled"}
    service.runtime = SimpleNamespace(request_interruptible=request)
    service.scheduler = SimpleNamespace(submit=lambda model, *, execute, cancel_event, **kwargs: execute())
    service.generation_cache = SimpleNamespace(get_or_compute=lambda *args: pytest.fail("shared cache"))
    result = service.complete_code({"prefix": "def example"}, cancel_event=event)
    assert result.get("cancelled") is True and result.get("success") is False


def test_speculative_verification_forwards_cancel_to_command_broker(tmp_path):
    from types import SimpleNamespace
    from local_ai_hub.services import LocalAIServices
    event = threading.Event()
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {}
    service._generate = lambda *args, **kwargs: {"success": True, "text": "pass"}
    service.affected_tests = lambda *args, **kwargs: {"suggested_command": "test"}
    def run(command, root, *, request_cancel_event):
        assert request_cancel_event is event
        event.set()
        return {"success": False, "cancelled": True}
    service.commands = SimpleNamespace(run=run)
    result = service.speculative_draft({"task": "test", "file": "test.py", "root": str(tmp_path), "verify_tests": True}, cancel_event=event)
    assert result.get("cancelled") is True


def test_route_does_not_publish_result_after_cancelled_selector():
    from types import SimpleNamespace
    from local_ai_hub.services import LocalAIServices
    event = threading.Event()
    service = LocalAIServices.__new__(LocalAIServices)
    def route_text(*args, **kwargs):
        event.set()
        return {"success": True, "context": "late result"}
    service.token_router = SimpleNamespace(route_text=route_text)
    result = service.route_context({"text": "context", "query": "question"}, cancel_event=event)
    assert result.get("cancelled") is True and result.get("success") is False


def test_vision_cancellation_interrupts_running_model_request(monkeypatch):
    from types import SimpleNamespace
    import local_ai_hub.vision_service as vision
    cancel, started, stopped = threading.Event(), threading.Event(), threading.Event()
    prepared = SimpleNamespace(images=["image"], image_artifact_id="", bundle_artifact_id="",
        bundle_context={}, frontend_bundle=None, model_context=None, image_size=None)
    plan = SimpleNamespace(payload={"model": "vision"}, prompt_context="", schema=None)
    monkeypatch.setattr(vision, "select_vision_model", lambda *args: ("vision", None))
    monkeypatch.setattr(vision, "prepare_vision_inputs", lambda **kwargs: prepared)
    monkeypatch.setattr(vision, "build_vision_request", lambda **kwargs: plan)
    monkeypatch.setattr(vision, "vision_capability_error", lambda *args: None)
    class Runtime:
        def request(self, endpoint, payload, timeout=None):
            if endpoint == "/api/show":
                return {}
            raise AssertionError("generation must be interruptible")
        def request_interruptible(self, endpoint, payload, should_stop, **kwargs):
            started.set()
            deadline = time.monotonic() + 3
            while not should_stop() and time.monotonic() < deadline:
                time.sleep(0.01)
            if should_stop():
                stopped.set()
            return {"error": "cancelled"}
    service = vision.VisionService(config={}, runtime=Runtime(), artifacts=None,
                                   model_policy=None, repo_tools=None, max_output_tokens=128)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.run, {"image": "test"}, cancel_event=cancel)
        try:
            assert started.wait(2), future.result(timeout=1) if future.done() else "model not started"
            cancel.set()
            assert stopped.wait(2)
            assert future.result(timeout=2).get("cancelled") is True
        finally:
            cancel.set()


def test_cancelled_local_selector_does_not_cache_fallback(tmp_path):
    from types import SimpleNamespace
    from local_ai_hub.client import CURRENT_REQUEST_CANCEL_EVENT
    from local_ai_hub.token_router import LosslessTokenRouter
    event = threading.Event()
    def generate(*args, **kwargs):
        event.set()
        return {"success": False, "cancelled": True}
    router = LosslessTokenRouter({"server": {"state_dir": str(tmp_path)}}, SimpleNamespace(_generate=generate))
    writes = []
    router.cache = SimpleNamespace(get=lambda key: None, set=lambda *args: writes.append(args))
    token = CURRENT_REQUEST_CANCEL_EVENT.set(event)
    try:
        result = router.route_text("line one\nline two", "question", force_local=True)
    finally:
        CURRENT_REQUEST_CANCEL_EVENT.reset(token)
    assert result.get("cancelled") is True and not writes


def test_shared_http_local_access_exposes_existing_tools():
    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as client:
        request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        }}
        headers = {"Accept": "application/json, text/event-stream"}
        assert client.post("/mcp", json=request, headers={**headers, "Origin": "http://evil.example"}).status_code == 403
        response = client.post("/mcp", json=request, headers=headers)
        assert response.status_code == 200
        assert response.json()["result"]["protocolVersion"] == "2025-03-26"
        headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2,
                               "method": "tools/list", "params": {}}, headers=headers)
        assert response.status_code == 200
        names = {tool["name"] for tool in response.json()["result"]["tools"]}
        from local_ai_hub.mcp_server import mcp
        assert names == {tool.name for tool in asyncio.run(mcp.list_tools())}
        assert "local_ai_repo" in names


@pytest.mark.parametrize("mode", ["async", "adapter"])
def test_deleting_session_cancels_its_calls_without_affecting_another_session(mode):
    from local_ai_hub.mcp_http import HTTPMCPService
    server = FastMCP("session-lifecycle-test")
    started = {key: threading.Event() for key in ("a", "b")}
    cancelled = {key: threading.Event() for key in ("a", "b")}
    release = threading.Event()
    async def async_wait(key: str) -> str:
        started[key].set()
        try:
            while not release.is_set():
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            cancelled[key].set()
            raise
        return key
    def sync_wait(key: str) -> str:
        from local_ai_hub.client import CURRENT_REQUEST_CANCEL_EVENT
        event = CURRENT_REQUEST_CANCEL_EVENT.get()
        started[key].set()
        while not release.wait(0.01):
            if event.is_set():
                cancelled[key].set()
                break
        return key
    if mode == "adapter":
        from local_ai_hub.mcp_server import _async_mcp_adapter
        handler = _async_mcp_adapter(sync_wait)
    else:
        handler = async_wait
    handler.__name__ = "wait"
    server.tool()(handler)
    transport = HTTPMCPService(port=0, server=server)
    transport.start(timeout=5)
    url = f"http://127.0.0.1:{transport.port}/mcp"
    headers = {"Accept": "application/json, text/event-stream"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"}}}
    try:
        with httpx.Client(timeout=5) as client, concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            sessions = [client.post(url, headers=headers, json=init).headers["mcp-session-id"] for _ in range(2)]
            def call(index, key):
                return httpx.post(url, timeout=5, headers={**headers, "Mcp-Session-Id": sessions[index]},
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "wait", "arguments": {"key": key}}})
            calls = [pool.submit(call, index, key) for index, key in enumerate(("a", "b"))]
            try:
                assert started["a"].wait(3) and started["b"].wait(3)
                response = client.delete(url, headers={**headers, "Mcp-Session-Id": sessions[0]})
                assert response.status_code in (200, 204)
                assert cancelled["a"].wait(3)
                assert not cancelled["b"].is_set() and not calls[1].done()
                release.set()
                assert calls[1].result(timeout=3).status_code == 200
            finally:
                release.set()
    finally:
        transport.stop(timeout=5)


def test_real_hub_status_over_http(monkeypatch):
    # This opt-in integration test talks to the configured live Hub.
    import os
    if os.environ.get("LOCAL_AI_TEST_LIVE_MCP_HTTP") != "1":
        pytest.skip("set LOCAL_AI_TEST_LIVE_MCP_HTTP=1 to contact the configured Hub")
    import conftest
    if conftest._ORIGINAL_CONFIG_PRESENT:
        monkeypatch.setenv("LOCAL_AI_CONFIG", conftest._ORIGINAL_CONFIG or "")
    else:
        monkeypatch.delenv("LOCAL_AI_CONFIG", raising=False)
    from local_ai_hub.supervisor import Supervisor
    # Run separately: FastMCP's session manager has a single lifespan.
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.config = {"mcp_http": {"enabled": True, "port": 0}}
    supervisor._mcp_http = None
    supervisor._start_mcp_http()
    try:
        url = f"http://127.0.0.1:{supervisor._mcp_http.port}/mcp"
        client = httpx.Client(timeout=10)
        headers = {"Accept": "application/json, text/event-stream"}
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"}}}
        headers["Mcp-Session-Id"] = client.post(url, headers=headers, json=init).headers["mcp-session-id"]
        response = client.post(url, headers=headers, json={"jsonrpc": "2.0", "id": 2,
            "method": "tools/call", "params": {"name": "local_ai_status", "arguments": {"detail": "brief"}}})
        assert response.status_code == 200
        assert response.json()["result"]["structuredContent"]["hub_online"] is True
        second = client.post(url, headers={k: v for k, v in headers.items() if k != "Mcp-Session-Id"}, json=init)
        second_headers = {**headers, "Mcp-Session-Id": second.headers["mcp-session-id"]}
        payload = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                   "params": {"name": "local_ai_status", "arguments": {"detail": "brief"}}}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(client.post, url, headers=h, json=payload)
                       for h in (headers, second_headers)]
            results = [future.result(timeout=12) for future in futures]
        assert all(item.status_code == 200 and item.json()["result"]["structuredContent"]["hub_online"]
                   for item in results)
    finally:
        if "client" in locals():
            client.close()
        supervisor._stop_mcp_http()


def test_adapter_get_forwards_cancellation_context():
    from local_ai_hub.client import CURRENT_REQUEST_CANCEL_EVENT
    from local_ai_hub.mcp_server import _MCPHubClientAdapter

    class Probe:
        auto_start = False
        def get(self, path, *, cancel_event=None):
            return cancel_event

    event = threading.Event()
    token = CURRENT_REQUEST_CANCEL_EVENT.set(event)
    try:
        assert _MCPHubClientAdapter(Probe()).get("/api/live/status") is event
    finally:
        CURRENT_REQUEST_CANCEL_EVENT.reset(token)


def test_compression_stops_before_next_chunk_after_cancellation():
    from local_ai_hub.services import LocalAIServices

    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"token_saving": {"compression_chunk_tokens": 10}}
    service.deterministic = None
    cancel = threading.Event()
    calls = []

    def generation(*_args, **_kwargs):
        calls.append(1)
        cancel.set()
        return {"success": True, "text": "first chunk"}

    service._generate = generation
    result = service.compress({"text": "a" * 1000}, cancel_event=cancel)
    assert result["cancelled"] is True
    assert len(calls) == 1


def test_delegate_does_not_publish_late_success_after_cancellation():
    from types import SimpleNamespace
    from local_ai_hub.services import LocalAIServices

    service = LocalAIServices.__new__(LocalAIServices)
    route = {"task_type": "general", "complexity": "light", "model": "test-model"}
    service.config = {}
    service.router = SimpleNamespace(classify=lambda *_args: dict(route),
                                     apply_model_override=lambda value, _model: value)
    service._resolve_local_task_project = lambda *_args: (None, "", "", "")
    service._resident_optimize = lambda value, *_args: value
    cancel = threading.Event()

    def generation(*_args, **_kwargs):
        cancel.set()
        return {"success": True, "text": "late result"}

    service._generate = generation
    result = service.delegate({"task": "test cancellation"}, cancel_event=cancel)
    assert result.get("cancelled") is True
    assert result.get("success") is False
    assert "text" not in result


def test_hub_conversation_disconnect_cancels_only_own_operation():
    from local_ai_hub.client import CURRENT_REQUEST_CANCEL_EVENT
    from local_ai_hub.http_server import _ActiveTranscriptionRegistry, _invoke_cancellable_request

    registry = _ActiveTranscriptionRegistry()
    left_a, right_a = socket.socketpair()
    left_b, right_b = socket.socketpair()
    started = {name: threading.Event() for name in ("a", "b")}
    cancelled = {name: threading.Event() for name in ("a", "b")}
    release = threading.Event()

    def operation(payload, *, cancel_event):
        assert CURRENT_REQUEST_CANCEL_EVENT.get() is cancel_event
        name = payload["name"]
        started[name].set()
        while not release.wait(0.01):
            if cancel_event.is_set():
                cancelled[name].set()
                return {"cancelled": True}
        return {"cancelled": False}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        try:
            a = pool.submit(_invoke_cancellable_request, registry, operation, {"name": "a"}, connection=left_a)
            b = pool.submit(_invoke_cancellable_request, registry, operation, {"name": "b"}, connection=left_b)
            assert started["a"].wait(2) and started["b"].wait(2)
            right_a.close()
            assert cancelled["a"].wait(2)
            assert not cancelled["b"].is_set()
            assert a.result(timeout=2)["cancelled"]
            release.set()
            assert not b.result(timeout=2)["cancelled"]
        finally:
            release.set()
            for conn in (left_a, right_a, left_b, right_b):
                conn.close()


@pytest.mark.parametrize("operation", ["conversation", "delegate", "reason", "review", "second_opinion", "compress", "batch", "review_diff", "delegate_repo", "scaffold", "generate_tests", "complete_code", "speculative_draft", "transcribe", "vision"])
def test_real_delegate_operation_stops_on_hub_disconnect(monkeypatch, operation):
    from types import SimpleNamespace
    from local_ai_hub import http_server
    from local_ai_hub.client import HubClient
    from local_ai_hub.mcp_http import HTTPMCPService
    from local_ai_hub.mcp_server import _async_mcp_adapter
    from local_ai_hub.services import LocalAIServices

    started, cancelled, discarded = threading.Event(), threading.Event(), threading.Event()
    service = LocalAIServices.__new__(LocalAIServices)
    route = {"task_type": "general", "complexity": "light", "model": "test-model"}
    service.config = {}
    service.deterministic = None
    service.code_index = None
    service.router = SimpleNamespace(classify=lambda *_args: dict(route),
                                     apply_model_override=lambda value, _model: value)
    service._resolve_local_task_project = lambda *_args: (None, "", "", "")
    service._resident_optimize = lambda value, *_args: value
    service._hybrid_context = lambda *args, **kwargs: {"success": True, "context": "test evidence"}
    service.scheduler = SimpleNamespace(status=lambda: {"active_model": "test-model"},
                                        submit=lambda model, *, execute, **kwargs: execute())
    service.model_policy = SimpleNamespace(tier_for=lambda model: "fast",
        profile=lambda *args, **kwargs: SimpleNamespace(prompt_budget_tokens=4096))
    service._conversation_prompt_limit = lambda: 100000
    service.conversations = SimpleNamespace(
        start_reserved=lambda _settings: SimpleNamespace(conversation_id="test"),
        discard=lambda _conversation_id: discarded.set(),
    )

    def generation(*_args, cancel_event, **_kwargs):
        started.set()
        if cancel_event.wait(3):
            cancelled.set()
            return {"success": False, "cancelled": True}
        return {"success": False, "error": "timeout"}

    service._generate = generation
    def completion_backend(_endpoint, _payload, should_stop, **_kwargs):
        started.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not should_stop():
            time.sleep(0.01)
        if should_stop():
            cancelled.set()
            return {"error": "cancelled"}
        return {"error": "timeout"}
    service.runtime = SimpleNamespace(request_interruptible=completion_backend)
    def transcribe(_payload, *, cancel_event):
        return generation(cancel_event=cancel_event)
    errors = []
    def observed_delegate(*args, **kwargs):
        try:
            return service.delegate(*args, **kwargs)
        except Exception as exc:
            errors.append(repr(exc))
            raise
    def observed_reason(*args, **kwargs):
        try:
            return service.reason(*args, **kwargs)
        except Exception as exc:
            errors.append(repr(exc))
            raise
    def observed_review(*args, **kwargs):
        try:
            return service.review(*args, **kwargs)
        except Exception as exc:
            errors.append(repr(exc))
            raise
    def observed_second_opinion(*args, **kwargs):
        try:
            return service.second_opinion(*args, **kwargs)
        except Exception as exc:
            errors.append(repr(exc))
            raise
    def observed_compress(*args, **kwargs):
        try:
            return service.compress(*args, **kwargs)
        except Exception as exc:
            errors.append(repr(exc))
            raise
    app = SimpleNamespace(config={"server": {}, "security": {}, "debug_traces": {"enabled": False}},
                          services=SimpleNamespace(delegate=observed_delegate, reason=observed_reason, review=observed_review,
                                                   second_opinion=observed_second_opinion, compress=observed_compress,
                                                   batch_delegate=service.batch_delegate, review_diff=service.review_diff,
                                                   delegate_repo=service.delegate_repo, task_scaffold=service.task_scaffold,
                                                   generate_tests=service.generate_tests, complete_code=service.complete_code,
                                                   speculative_draft=service.speculative_draft, transcribe=transcribe, vision=transcribe), recovery=None,
                          telemetry=SimpleNamespace(http_latency_estimate=lambda _path: {"samples": 0}))
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    hub = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=hub.serve_forever, daemon=True)
    thread.start()
    hub_client = HubClient(auto_start=False)
    hub_client.base_url = f"http://127.0.0.1:{hub.server_address[1]}"
    hub_client._http_port = hub.server_address[1]
    mcp = FastMCP("full-chain")

    def delegate(task: str) -> dict:
        if operation == "reason":
            return hub_client.post("/api/reason", {"problem": task}, timeout=5)
        if operation == "review":
            return hub_client.post("/api/review", {"code": task}, timeout=5)
        if operation == "second_opinion":
            return hub_client.post("/api/second-opinion", {"question": task}, timeout=5)
        if operation == "compress":
            return hub_client.post("/api/compress", {"text": task}, timeout=5)
        if operation == "batch":
            return hub_client.post("/api/delegate/batch", {"tasks": [{"task": task}, {"task": "later"}]}, timeout=5)
        if operation == "review_diff":
            return hub_client.post("/api/review/diff", {"diff": "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new"}, timeout=5)
        if operation == "delegate_repo":
            return hub_client.post("/api/delegate/repo", {"task": task, "root": "C:/test"}, timeout=5)
        if operation == "scaffold":
            return hub_client.post("/api/task/scaffold", {"prompt": task}, timeout=5)
        if operation == "generate_tests":
            return hub_client.post("/api/generate_tests", {"symbol": task}, timeout=5)
        if operation == "complete_code":
            return hub_client.post("/api/complete", {"prefix": task}, timeout=5)
        if operation == "speculative_draft":
            return hub_client.post("/api/task/speculative_draft", {"task": task}, timeout=5)
        if operation == "transcribe":
            return hub_client.post("/api/task/transcribe", {"audio": task}, timeout=5)
        if operation == "vision":
            return hub_client.post("/api/task/vision", {"image": task}, timeout=5)
        return hub_client.post("/api/delegate", {"task": task, "conversation": operation == "conversation"}, timeout=5)

    mcp.tool()(_async_mcp_adapter(delegate))
    transport = HTTPMCPService(port=0, server=mcp)
    client = None
    try:
        transport.start(timeout=5)
        headers = {"Accept": "application/json, text/event-stream"}
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"}}}
        with httpx.Client(timeout=3) as probe:
            response = probe.post(f"http://127.0.0.1:{transport.port}/mcp", headers=headers, json=initialize)
            session = response.headers["mcp-session-id"]
        body = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": "delegate", "arguments": {"task": "test cancellation"}}}).encode()
        client = socket.create_connection(("127.0.0.1", transport.port), timeout=3)
        request = (f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{transport.port}\r\n"
                   f"Mcp-Session-Id: {session}\r\nAccept: application/json, text/event-stream\r\n"
                   f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body
        client.sendall(request)
        if not started.wait(3):
            try:
                failure_response = client.recv(4096).decode("utf-8", errors="replace")
            except TimeoutError:
                failure_response = "no response"
            pytest.fail(f"operation did not start; errors={errors}; response={failure_response}")
        client.close()
        assert cancelled.wait(3)
        if operation == "conversation":
            assert discarded.wait(3)
    finally:
        if client is not None:
            client.close()
        transport.stop(timeout=5)
        hub_client.close()
        hub.shutdown()
        hub.server_close()
        thread.join(timeout=3)


def test_hub_http_half_close_does_not_cancel_unmarked_request(monkeypatch):
    from types import SimpleNamespace
    from local_ai_hub import http_server

    started, release, cancelled = threading.Event(), threading.Event(), threading.Event()

    def delegate(_payload, *, cancel_event):
        started.set()
        release.wait(2)
        if cancel_event.is_set():
            cancelled.set()
        return {"success": True}

    app = SimpleNamespace(config={"server": {}, "security": {}, "debug_traces": {"enabled": False}},
                          services=SimpleNamespace(delegate=delegate), recovery=None)
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    hub = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=hub.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({"task": "test", "conversation": True}).encode()
        conn = socket.create_connection(hub.server_address, timeout=3)
        request = (f"POST /api/delegate HTTP/1.1\r\nHost: 127.0.0.1:{hub.server_address[1]}\r\n"
                   f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body
        conn.sendall(request)
        assert started.wait(2)
        conn.shutdown(socket.SHUT_WR)
        time.sleep(0.2)
        release.set()
        assert b"200 OK" in conn.recv(4096)
        assert not cancelled.is_set()
        conn.close()
    finally:
        release.set()
        hub.shutdown()
        hub.server_close()
        thread.join(timeout=3)


def test_adapter_cancellation_closes_real_hub_client_socket():
    from local_ai_hub.client import CURRENT_REQUEST_CANCEL_EVENT, HubClient
    from local_ai_hub.mcp_server import _MCPHubClientAdapter

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(4)
    started, disconnected, cancel = threading.Event(), threading.Event(), threading.Event()

    def backend():
        try:
            conn, _ = listener.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(4)
            data = b""
            while b"\r\n\r\n" not in data:
                data += conn.recv(4096)
            started.set()
            if conn.recv(1) == b"":
                disconnected.set()

    worker = threading.Thread(target=backend, daemon=True)
    worker.start()
    hub = HubClient(auto_start=False)
    hub.base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    hub._http_port = listener.getsockname()[1]
    adapter = _MCPHubClientAdapter(hub)

    def invoke():
        context = CURRENT_REQUEST_CANCEL_EVENT.set(cancel)
        try:
            return adapter.get("/api/live/status", timeout=4)
        finally:
            CURRENT_REQUEST_CANCEL_EVENT.reset(context)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(invoke)
        try:
            assert started.wait(3), future.result(timeout=1) if future.done() else "no backend connection"
            cancel.set()
            assert disconnected.wait(3)
            assert future.result(timeout=3).get("cancelled") is True
        finally:
            cancel.set()
            listener.close()
    worker.join(timeout=4)
    assert not worker.is_alive()


def test_cancellation_is_scoped_to_one_session():
    server = FastMCP("test")
    started = {key: threading.Event() for key in ("a", "b")}
    cancelled = {key: threading.Event() for key in ("a", "b")}
    release = threading.Event()

    @server.tool()
    async def wait(key: str) -> str:
        started[key].set()
        try:
            while not release.is_set():
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            cancelled[key].set()
            raise
        return key

    app = create_app(server=server)
    headers = {"Accept": "application/json, text/event-stream"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"}}}
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as client:
        sessions = [client.post("/mcp", json=init, headers=headers).headers["mcp-session-id"]
                    for _ in range(2)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            try:
                calls = [executor.submit(client.post, "/mcp", headers={**headers, "Mcp-Session-Id": session},
                         json={"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                               "params": {"name": "wait", "arguments": {"key": key}}})
                         for session, key in zip(sessions, ("a", "b"))]
                assert started["a"].wait(3) and started["b"].wait(3)
                result = client.post("/mcp", headers={**headers, "Mcp-Session-Id": sessions[0]},
                    json={"jsonrpc": "2.0", "method": "notifications/cancelled",
                          "params": {"requestId": 7, "reason": "test"}})
                assert result.status_code == 202
                assert cancelled["a"].wait(3)
                assert not cancelled["b"].is_set()
                assert not calls[1].done()
            finally:
                release.set()
            assert calls[1].result(timeout=3).status_code == 200


def test_remote_peer_is_rejected():
    app = create_app(server=FastMCP("test"))
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("192.0.2.1", 50000)) as client:
        response = client.post("/mcp", json={})
        assert response.status_code == 403


def test_transport_lifecycle_listens_only_until_stopped():
    from local_ai_hub.mcp_http import HTTPMCPService
    from tools.setup import _http_mcp_ready

    service = HTTPMCPService(port=0, server=FastMCP("Local AI Hub (compact)"))
    service.start(timeout=5)
    try:
        assert service.port > 0
        assert _http_mcp_ready(f"http://127.0.0.1:{service.port}/mcp")
        with httpx.Client(timeout=3) as client:
            response = client.post(f"http://127.0.0.1:{service.port}/mcp", json={})
            assert response.status_code != 401 and response.status_code < 500
    finally:
        service.stop(timeout=5)
    assert not service.running
    assert not _http_mcp_ready(f"http://127.0.0.1:{service.port}/mcp")
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", service.port), timeout=1)


def test_readiness_refuses_unrelated_mcp_server():
    from local_ai_hub.mcp_http import HTTPMCPService
    from tools.setup import _http_mcp_ready

    service = HTTPMCPService(port=0, server=FastMCP("unrelated"))
    service.start(timeout=5)
    try:
        assert not _http_mcp_ready(f"http://127.0.0.1:{service.port}/mcp")
    finally:
        service.stop(timeout=5)


def test_tcp_disconnect_cancels_running_request():
    from local_ai_hub.client import CURRENT_REQUEST_CANCEL_EVENT
    from local_ai_hub.mcp_server import _async_mcp_adapter

    server = FastMCP("disconnect-test")
    started = {key: threading.Event() for key in ("a", "b")}
    cancelled = {key: threading.Event() for key in ("a", "b")}
    release = threading.Event()

    def wait(key: str) -> str:
        started[key].set()
        event = CURRENT_REQUEST_CANCEL_EVENT.get()
        while not release.wait(0.01):
            if event.is_set():
                cancelled[key].set()
                break
        return "done"

    server.tool()(_async_mcp_adapter(wait))

    app = create_app(server=server)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    runner = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=runner.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not runner.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert runner.started
        url = f"http://127.0.0.1:{port}/mcp"
        headers = {"Accept": "application/json, text/event-stream"}
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"}}}
        with httpx.Client(timeout=3) as client:
            session = client.post(url, headers=headers, json=init).headers["mcp-session-id"]
        connections = []
        for request_id, key in ((9, "a"), (10, "b")):
            body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                               "params": {"name": "wait", "arguments": {"key": key}}}).encode()
            conn = socket.create_connection(("127.0.0.1", port), timeout=3)
            request = (f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                       f"Mcp-Session-Id: {session}\r\n"
                       f"Accept: application/json, text/event-stream\r\nContent-Type: application/json\r\n"
                       f"Content-Length: {len(body)}\r\n\r\n").encode() + body
            conn.sendall(request)
            connections.append(conn)
        assert started["a"].wait(3) and started["b"].wait(3)
        connections[0].close()
        assert cancelled["a"].wait(3)
        assert not cancelled["b"].is_set()
        release.set()
        assert b"200 OK" in connections[1].recv(4096)
        connections[1].close()
    finally:
        release.set()
        runner.should_exit = True
        thread.join(timeout=5)
        listener.close()
    assert not thread.is_alive()
