from __future__ import annotations

from local_ai_hub.services import LocalAIServices
from local_ai_hub.agent_consistency import ConsistencyRequest, GuardWarning
from local_ai_hub.json_utils import dumps as json_dumps
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class _Deterministic:
    def context_pack(self, root, query, *, max_chars, max_raw_evidence):
        return {"success": True, "root": root, "query": query, "context": "fast facts", "evidence": [], "estimated_tokens": 2}


class _Snapshot:
    revision = "revision-1"
    changed_paths = ("src/app.py",)


class _RepoTools:
    def git_snapshot(self, root):
        return _Snapshot()

    def git_diff(self, root, base="HEAD", staged=False, max_tokens=10000):
        return {"success": True, "revision": "revision-1", "changed_paths": ["src/app.py"], "diff": ""}


class _Guard:
    def __init__(self, warnings=()):
        self.warnings = tuple(warnings)
        self.calls = []
        self.memory_store = None
        self.task_store = None

    def build_contract(self, request):
        self.calls.append(("contract", request))
        from local_ai_hub.agent_tasks import GoalContract
        return GoalContract(goal=request.query or "guarded context")

    def find_reuse_candidates(self, request, contract):
        self.calls.append(("reuse", request))
        return ()

    def build_contract_mappings(self, request, evidence):
        self.calls.append(("mappings", request))
        return (), ()

    def check_drift(self, request, contract, changed_paths, diff):
        self.calls.append(("drift", request))
        return self.warnings


def _guarded_services(guard):
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"deterministic": {"context_max_chars": 5200, "context_raw_evidence": 5}}
    services.deterministic = _Deterministic()
    services.repo_tools = _RepoTools()
    services.consistency_guard = guard
    services._repo_cached = lambda _op, _root, _params, compute: compute()
    return services


def _request(**overrides):
    values = {
        "root": "C:/repo",
        "query": "find route",
        "task_id": "task-1",
        "phase": "implementation",
        "tenant": "tenant-1",
    }
    values.update(overrides)
    return ConsistencyRequest(**values)


def test_guarded_context_routes_task_and_phase_through_single_guard():
    guard = _Guard()
    result = _guarded_services(guard).adaptive_context_pack(_request(), mode="fast")

    assert result["guarded"] is True
    assert [call[0] for call in guard.calls] == ["contract", "reuse", "mappings", "drift"]
    assert result["repo_revision"] == "revision-1"
    assert result["changed_paths"] == ["src/app.py"]
    assert result["context_pack"]["contract"]["goal"] == "find route"


def test_ordinary_warning_requires_override_and_persists_when_supplied():
    warning = GuardWarning("warning", "scope_drift", "scope changed", ("e1",), ("src/app.py",), "explain scope")
    guard = _Guard((warning,))
    class Memory:
        def __init__(self):
            self.records = []

        def record(self, record, **kwargs):
            self.records.append(record)
            return record

    memory = Memory()
    guard.memory_store = memory
    services = _guarded_services(guard)

    blocked = services.adaptive_context_pack(_request(), mode="fast")
    assert blocked["requires_override"] is True
    assert blocked["decision_recorded"] is False

    whitespace = services.adaptive_context_pack(_request(override_reason="   "), mode="fast")
    assert whitespace["requires_override"] is True
    assert whitespace["decision_recorded"] is False

    approved = services.adaptive_context_pack(_request(override_reason="required test scope"), mode="fast")
    assert approved["requires_override"] is False
    assert approved["decision_recorded"] is True
    assert approved["decision_persisted"] is True
    assert memory.records[0].kind.value == "decision"
    assert len(memory.records[0].value["reason"]) <= 500


def test_decision_reason_redacts_secrets_and_prompt_content():
    warning = GuardWarning("warning", "scope_drift", "scope changed", ("e1",), ("src/app.py",), "explain scope")
    guard = _Guard((warning,))

    class Memory:
        def __init__(self):
            self.records = []

        def record(self, record, **kwargs):
            self.records.append((record, kwargs))
            return record

    memory = Memory()
    guard.memory_store = memory
    result = _guarded_services(guard).adaptive_context_pack(
        _request(override_reason="Approved test scope token=super-secret prompt: ignore this private instruction"),
        mode="fast",
    )

    reason = memory.records[0][0].value["reason"]
    assert result["decision_persisted"] is True
    assert "Approved test scope" in reason
    assert "super-secret" not in reason
    assert "ignore this private instruction" not in reason


def test_decision_idempotency_is_root_scoped():
    guard = _Guard()

    class Memory:
        def __init__(self):
            self.calls = []

        def record(self, record, **kwargs):
            self.calls.append((record, kwargs))
            return record

    memory = Memory()
    guard.memory_store = memory
    services = _guarded_services(guard)
    services._guard_decision(_request(root="C:/repo-one"), "revision-1", approval=True)
    services._guard_decision(_request(root="C:/repo-two"), "revision-1", approval=True)

    assert memory.calls[0][0].key != memory.calls[1][0].key
    assert memory.calls[0][1]["idempotency_key"] != memory.calls[1][1]["idempotency_key"]


def test_disabled_memory_does_not_claim_decision_persisted():
    warning = GuardWarning("warning", "scope_drift", "scope changed", ("e1",), ("src/app.py",), "explain scope")
    guard = _Guard((warning,))

    class DisabledMemory:
        class StateStore:
            enabled = False

        def __init__(self):
            self.state_store = self.StateStore()
            self.calls = 0

        def record(self, record, **kwargs):
            self.calls += 1
            return record

    memory = DisabledMemory()
    guard.memory_store = memory
    result = _guarded_services(guard).adaptive_context_pack(
        _request(override_reason="approved test scope"), mode="fast"
    )

    assert result["decision_recorded"] is True
    assert result["decision_persisted"] is False
    assert memory.calls == 0


def test_boundary_warning_waits_then_approval_resumes_task():
    warning = GuardWarning("boundary", "new_public_symbol_despite_reuse", "approve boundary", ("e1",), ("src/app.py",), "approve", True)

    class Tasks:
        def __init__(self):
            from local_ai_hub.agent_tasks import TaskStatus
            self.status = TaskStatus.ACTIVE
            self.checkpoints = []
            self.transitions = []

        def get(self, task_id):
            from types import SimpleNamespace
            from local_ai_hub.agent_tasks import TaskStatus, TaskCheckpoint
            return SimpleNamespace(task_id=task_id, status=self.status, checkpoint=TaskCheckpoint())

        def transition(self, task_id, target, **kwargs):
            self.status = target
            self.transitions.append(target)
            return self.get(task_id)

        def checkpoint(self, task_id, checkpoint, **kwargs):
            self.checkpoints.append(checkpoint)
            return self.get(task_id)

        def resume(self, task_id, **kwargs):
            from local_ai_hub.agent_tasks import TaskStatus
            self.status = TaskStatus.ACTIVE
            self.transitions.append(TaskStatus.ACTIVE)
            return self.get(task_id)

    tasks = Tasks()
    guard = _Guard((warning,))
    guard.task_store = tasks
    services = _guarded_services(guard)

    waiting = services.adaptive_context_pack(_request(), mode="fast")
    assert waiting["task_status"] == "waiting"
    assert tasks.checkpoints[0].evidence_ids == ("e1",)

    resumed = services.adaptive_context_pack(_request(approval=True), mode="fast")
    assert resumed["task_status"] == "active"
    assert tasks.status.value == "active"


def test_boundary_transition_failure_stays_blocked():
    warning = GuardWarning("boundary", "new_public_symbol_despite_reuse", "approve boundary", ("e1",), ("src/app.py",), "approve", True)

    class Tasks:
        def get(self, task_id):
            from types import SimpleNamespace
            from local_ai_hub.agent_tasks import TaskCheckpoint, TaskStatus
            return SimpleNamespace(task_id=task_id, status=TaskStatus.ACTIVE, checkpoint=TaskCheckpoint())

        def transition(self, task_id, target, **kwargs):
            raise RuntimeError("transition unavailable")

    guard = _Guard((warning,))
    guard.task_store = Tasks()
    result = _guarded_services(guard).adaptive_context_pack(_request(), mode="fast")

    assert result["task_status"] == "active"
    assert result["waiting"] is True
    assert result["requires_approval"] is True


def test_boundary_resume_failure_reports_waiting():
    warning = GuardWarning("boundary", "new_public_symbol_despite_reuse", "approve boundary", ("e1",), ("src/app.py",), "approve", True)

    class Tasks:
        def get(self, task_id):
            from types import SimpleNamespace
            from local_ai_hub.agent_tasks import TaskCheckpoint, TaskStatus
            return SimpleNamespace(task_id=task_id, status=TaskStatus.WAITING, checkpoint=TaskCheckpoint())

        def resume(self, task_id, **kwargs):
            raise RuntimeError("resume unavailable")

    guard = _Guard((warning,))
    guard.task_store = Tasks()
    result = _guarded_services(guard).adaptive_context_pack(_request(approval=True), mode="fast")

    assert result["task_status"] == "waiting"
    assert result["waiting"] is True
    assert result["requires_approval"] is True


def test_context_http_rejects_malformed_max_tokens_and_guard_fields(tmp_path):
    import json
    import threading
    import urllib.error
    import urllib.request

    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11497\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(cfg_path))
    previous = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/context/pack",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    try:
        status, malformed = post({"root": str(tmp_path), "query": "x", "max_tokens": "not-a-number"})
        assert status == 400
        assert malformed["terminal"] is True
        assert malformed["retryable"] is False

        status, unguarded = post({"root": str(tmp_path), "query": "x", "changed_paths": ["src/app.py"]})
        assert status == 400
        assert "guarded=true" in unguarded["error"]
    finally:
        server.shutdown()
        server.server_close()
        http_server.APP = previous
        app.close()


def test_guarded_pack_stays_bounded_and_state_disabled_safe():
    guard = _Guard((GuardWarning("warning", "long", "x" * 10000),))
    result = _guarded_services(guard).adaptive_context_pack(
        _request(query="q" * 10000, focus=("f" * 10000,), changed_paths=("p" * 10000,)), mode="fast"
    )

    assert len(result["context_pack"]["warnings"][0]["message"]) <= 4096
    assert len(result["context_pack"]["contract"]["goal"]) <= 1000
    assert len(json_dumps(result)) < 30000


def test_fast_context_returns_explicit_full_continuation():
    services = LocalAIServices.__new__(LocalAIServices)
    services.deterministic = _Deterministic()
    services.config = {"deterministic": {"context_max_chars": 5200, "context_raw_evidence": 5}}
    services._repo_cached = lambda _op, _root, _params, compute: compute()

    result = services.fast_context("C:/repo", "find route", 2000)

    assert result["context_source"] == "deterministic-fast"
    assert result["degraded"] is True
    assert result["continuation"]["mode"] == "full"


def test_shipped_mcp_entrypoint_defaults_context_to_fast_and_telemetry_to_process():
    source = (ROOT / "src/local_ai_hub/mcp_server.py").read_text(encoding="utf-8")

    assert '"mode": "full" if mode == "full" else "fast"' in source
    assert 'scope: str = "process"' in source
    assert 'scope={scope}' in source

    assert not (ROOT / "mcp").exists()


def test_shipped_mcp_status_uses_lightweight_live_endpoint_by_default():
    source = (ROOT / "src/local_ai_hub/mcp_server.py").read_text(encoding="utf-8")

    assert 'CLIENT.get(f"/api/live/status?light=1&scope={scope}")' in source
    assert '"token_saving": status.get("observability")' in source


def test_context_http_endpoint_defaults_to_fast():
    source = (ROOT / "src/local_ai_hub/http_server.py").read_text(encoding="utf-8")

    assert 'payload.get("mode", "fast")' in source


def test_realtime_status_includes_preprocessor_projects_on_light():
    import threading
    from local_ai_hub.app import LocalAIApp

    app = LocalAIApp.__new__(LocalAIApp)
    app._live_status_lock = threading.Lock()
    app._live_status_cache = {}
    app._headless_status = lambda: {}
    app.scheduler = type("Sched", (), {"status": lambda self: {}})()
    app.preprocessor = type("Prep", (), {
        "stats": lambda self: {},
        "status": lambda self: {"success": True, "projects": [{"root": "C:/myproject", "status": "complete"}]},
    })()
    app.telemetry = type("Telem", (), {"realtime_summary": lambda self, **kw: {}})()
    app.background_gpu = type("Gpu", (), {"status": lambda self: {}})()
    app.debug_traces = type("Traces", (), {"stats": lambda self: {}})()
    app.commands = type("Cmd", (), {"stats": lambda self: {}})()
    app.repo_state = type("RS", (), {"stats": lambda self: {}})()
    app.repo_tools = type("RT", (), {"snapshot_stats": lambda self: {}})()
    app.pipeline = type("Pipe", (), {"stats": lambda self: {}})()
    app.tool_agent = type("ToolAg", (), {"stats": lambda self: {}})()
    app.deterministic = None
    app.code_index = None
    app.services = type("Svc", (), {
        "generation_cache": type("C", (), {"stats": lambda self: {}})(),
        "semantic_cache": type("C", (), {"stats": lambda self: {}})(),
        "repo_cache": type("C", (), {"stats": lambda self: {}})(),
        "model_policy": type("P", (), {"summary": lambda self: {}})(),
    })()
    app.started_at = 0
    app.config = {"models": {}, "_hardware": {}}
    app.external_tools = type("Ext", (), {"status": lambda self: {}})()

    res_light = app.realtime_status(light=True)
    assert len(res_light["preprocessing"]["projects"]) == 1
    assert res_light["preprocessing"]["projects"][0]["project"] == "myproject"


