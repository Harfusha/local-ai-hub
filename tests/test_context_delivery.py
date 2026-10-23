from __future__ import annotations

from local_ai_hub.services import LocalAIServices, generation_cache_key
from local_ai_hub.agent_consistency import ConsistencyRequest, GuardWarning
from local_ai_hub.json_utils import dumps as json_dumps
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
_TEST_ROOT = None
_TEST_STATE_DIR = None


@pytest.fixture(autouse=True)
def _isolated_guarded_context_paths(tmp_path):
    global _TEST_ROOT, _TEST_STATE_DIR
    _TEST_ROOT = tmp_path / "repository"
    _TEST_ROOT.mkdir()
    _TEST_STATE_DIR = tmp_path / "state"


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

    def context_pack(self, root, query, *, max_tokens, top_k):
        return {
            "success": True,
            "root": root,
            "query": query,
            "context": "fast facts",
            "evidence": [],
            "estimated_tokens": 2,
        }


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


def _guarded_services(guard, *, stub_retrieval=True):
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {
        "deterministic": {"context_max_chars": 5200, "context_raw_evidence": 5},
        "server": {"state_dir": str(_TEST_STATE_DIR)},
    }
    services.deterministic = _Deterministic()
    services.repo_tools = _RepoTools()
    services.code_index = None
    services.rag = None
    services.preprocessor = None
    services.external_tools = None
    services.evidence_store = None
    services.consistency_guard = guard
    services.learner = None
    services._repo_cached = lambda _op, _root, _params, compute: compute()
    if stub_retrieval:
        # Guard-decision and persistence tests don't need optional retrieval
        # backends; keep their dependency surface deterministic.
        services._hybrid_context = lambda root, query, **_kwargs: {
            "success": True,
            "root": root,
            "query": query,
            "context": "fast facts",
            "evidence": [],
            "estimated_tokens": 2,
        }
    else:
        # Exercise real preload integration without unrelated deterministic or
        # optional backend behavior.
        services.deterministic = None
    return services


def _request(**overrides):
    values = {
        "root": str(_TEST_ROOT),
        "query": "find route",
        "task_id": "task-1",
        "phase": "implementation",
        "session_id": "session-1",
    }
    values.update(overrides)
    return ConsistencyRequest(**values)


def test_guarded_context_routes_task_and_phase_through_single_guard():
    guard = _Guard()
    result = _guarded_services(guard).adaptive_context_pack(_request(), mode="adaptive")

    assert result["guarded"] is True
    assert [call[0] for call in guard.calls] == ["contract", "reuse", "mappings", "drift"]
    assert result["repo_revision"] == "revision-1"
    assert result["changed_paths"] == ["src/app.py"]
    assert result["context_pack"]["contract"]["goal"] == "find route"


def test_guarded_context_uses_configured_preload_profile(tmp_path):
    preload = tmp_path / "review-notes.md"
    preload.write_text("configured review preload", encoding="utf-8")
    guard = _Guard()
    services = _guarded_services(guard, stub_retrieval=False)
    services.config["context"] = {
        "preloads": {"profiles": {"review": {"files": ["review-notes.md"]}}}
    }

    result = services.adaptive_context_pack(
        _request(root=str(tmp_path), preload_profile="review"), mode="adaptive"
    )

    assert "configured review preload" in result["context"]
    assert any(item.get("source_kind") == "preload" for item in result["evidence"])


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

    blocked = services.adaptive_context_pack(_request(), mode="adaptive")
    assert blocked["requires_override"] is True
    assert blocked["decision_recorded"] is False

    whitespace = services.adaptive_context_pack(_request(override_reason="   "), mode="adaptive")
    assert whitespace["requires_override"] is True
    assert whitespace["decision_recorded"] is False

    approved = services.adaptive_context_pack(_request(override_reason="required test scope"), mode="adaptive")
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
        mode="adaptive",
    )

    reason = memory.records[0][0].value["reason"]
    assert result["decision_persisted"] is True
    assert "Approved test scope" in reason
    assert "super-secret" not in reason
    assert "ignore this private instruction" not in reason


def test_decision_reason_redacts_authorization_bearer_credential_as_one_token():
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
    _guarded_services(guard).adaptive_context_pack(
        _request(override_reason="Authorization: Bearer super-secret-token"), mode="adaptive",
    )

    reason = memory.records[0].value["reason"]
    assert "super-secret-token" not in reason
    assert "Bearer [REDACTED]" in reason


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


def test_disabled_memory_fails_closed_for_operator_decision():
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
        _request(override_reason="approved test scope"), mode="adaptive"
    )

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["stop_code"] == "context_decision_persistence_failed"
    assert memory.calls == 0


def test_memory_revision_database_error_fails_closed():
    guard = _Guard()

    class BrokenMemory:
        @staticmethod
        def revision(_root):
            raise RuntimeError("database unavailable")

    guard.memory_store = BrokenMemory()
    result = _guarded_services(guard).adaptive_context_pack(_request(), mode="adaptive")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["stop_code"] == "context_memory_revision_unavailable"


def test_task_state_database_error_fails_closed():
    guard = _Guard()

    class BrokenTasks:
        @staticmethod
        def get(_task_id):
            raise RuntimeError("database unavailable")

    guard.task_store = BrokenTasks()
    result = _guarded_services(guard).adaptive_context_pack(_request(), mode="adaptive")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["stop_code"] == "context_task_state_unavailable"


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

    class Memory:
        def record(self, record, **kwargs):
            return record

    guard.memory_store = Memory()
    services = _guarded_services(guard)

    waiting = services.adaptive_context_pack(_request(), mode="adaptive")
    assert waiting["task_status"] == "waiting"
    assert tasks.checkpoints[0].evidence_ids == ("e1",)

    resumed = services.adaptive_context_pack(_request(approval=True), mode="adaptive")
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
    result = _guarded_services(guard).adaptive_context_pack(_request(), mode="adaptive")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["stop_code"] == "context_task_state_unavailable"


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
    guard.memory_store = type("Memory", (), {"record": lambda self, record, **kwargs: record})()
    result = _guarded_services(guard).adaptive_context_pack(_request(approval=True), mode="adaptive")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["stop_code"] == "context_task_state_unavailable"


def test_boundary_guard_stops_when_task_state_is_missing():
    from types import SimpleNamespace

    warning = GuardWarning("boundary", "high_risk", "stop", ("e1",), ("src/app.py",), "obtain task state", True)
    guard = _Guard((warning,))
    guard.task_store = SimpleNamespace(get=lambda _task_id: None)

    result = _guarded_services(guard).adaptive_context_pack(_request(), mode="adaptive")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["stop_code"] == "guard_task_state_unavailable"


def test_boundary_guard_stops_when_task_id_is_missing():
    warning = GuardWarning("boundary", "high_risk", "stop", ("e1",), ("src/app.py",), "provide task id", True)

    result = _guarded_services(_Guard((warning,))).adaptive_context_pack(_request(task_id=""), mode="adaptive")

    assert result["terminal"] is True
    assert result["stop_code"] == "guard_task_id_required"


def test_boundary_guard_stops_when_agent_os_is_disabled():
    from types import SimpleNamespace

    warning = GuardWarning("high-risk", "high_risk", "stop", ("e1",), ("src/app.py",), "enable agent state", True)
    guard = _Guard((warning,))
    guard.task_store = SimpleNamespace(state_store=SimpleNamespace(enabled=False))

    result = _guarded_services(guard).adaptive_context_pack(_request(), mode="adaptive")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["stop_code"] == "agent_os_disabled"


def test_completion_revision_resolution_stops_without_snapshot():
    from local_ai_hub import http_server

    revision, stop = http_server._completion_revision_or_stop("", object())

    assert revision == ""
    assert stop["terminal"] is True
    assert stop["retryable"] is False
    assert stop["stop_code"] == "completion_repository_revision_unavailable"


def test_completion_revision_resolution_stops_on_degraded_snapshot():
    from local_ai_hub import http_server
    from types import SimpleNamespace

    revision, stop = http_server._completion_revision_or_stop(
        "C:/repo", SimpleNamespace(git_snapshot=lambda _root: SimpleNamespace(revision="", degraded=True)),
    )

    assert revision == ""
    assert stop["terminal"] is True
    assert stop["stop_code"] == "completion_repository_revision_unavailable"


def test_taskless_context_pack_cache_identity_includes_repository_root(monkeypatch, tmp_path):
    import json
    import threading
    import urllib.request

    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11497\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        f'[security]\napi_token = "context-pack-owner-token"\n'
        f'allowed_roots = ["{tmp_path.as_posix()}"]\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(cfg_path))
    root_a = tmp_path / "repo-a"
    root_b = tmp_path / "repo-b"
    root_a.mkdir()
    root_b.mkdir()
    hybrid_calls = []

    def record_hybrid(*args, **kwargs):
        hybrid_calls.append((args, kwargs))
        return {"success": True, "context": "bounded", "evidence": []}

    app.services._hybrid_context = record_hybrid
    previous = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for root in (root_a, root_b):
            token = "context-pack-owner-token"
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_address[1]}/api/context/pack",
                data=json.dumps({"root": str(root), "query": "same query", "mode": "adaptive"}).encode(),
                headers={"Content-Type": "application/json", "X-LocalAI-Token": token},
                method="POST",
            )
            with urllib.request.urlopen(request) as response:
                assert response.status == 200

        context_roots = [call[0][0] for call in hybrid_calls]
        assert context_roots == [str(root_a.resolve()), str(root_b.resolve())]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous


def test_context_http_rejects_malformed_max_tokens_and_guard_fields(tmp_path, monkeypatch):
    import json
    import sqlite3
    import threading
    from types import SimpleNamespace
    import urllib.error
    import urllib.request

    from local_ai_hub import http_server, project_config
    from local_ai_hub.app import LocalAIApp

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11497\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n"
        "\n[debug_traces]\nenabled = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(cfg_path))
    # This test exercises HTTP validation and request shaping, not external
    # repository backends.
    app.services._hybrid_context = lambda *_args, **_kwargs: {
        "success": True,
        "context": "bounded test context",
        "evidence": [],
    }
    resolved_project = {"digest": "a" * 64}
    original_project_resolver = project_config.resolve_project_context

    def resolve_project_context(_root, _state_dir):
        settings = SimpleNamespace(retrieval_weights={}, pinned_context=(), entry_points=())
        return SimpleNamespace(
            config_digest=resolved_project["digest"],
            coordination_id=original_project_resolver(_root, _state_dir).coordination_id,
            settings=settings,
            path_hints=lambda **_kwargs: (),
        )
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

        for invalid_budget in (512.0, "512", True):
            status, invalid = post({"root": str(tmp_path), "query": "x", "max_tokens": invalid_budget})
            assert status == 400
            assert invalid["terminal"] is True
            assert invalid["retryable"] is False
            assert "max_tokens must be an integer" in invalid["error"]

        status, negative = post({"root": str(tmp_path), "query": "x", "max_tokens": -1})
        assert status == 400
        assert negative["terminal"] is True
        assert negative["retryable"] is False
        assert "max_tokens must be non-negative" in negative["error"]

        status, invalid_mode = post({"root": str(tmp_path), "query": "x", "mode": "unsafe"})
        assert status == 400
        assert "context mode" in invalid_mode["error"]

        status, below_minimum = post({"root": str(tmp_path), "query": "x", "task_id": "task-1", "phase": "review", "max_tokens": 127})
        assert status == 400
        assert "128" in below_minimum["error"]

        status, mismatched_budget = post({
            "root": str(tmp_path), "query": "x", "task_id": "task-1", "phase": "review",
            "max_tokens": 256, "token_budget": 512,
        })
        assert status == 400
        assert "must match" in mismatched_budget["error"]

        status, malformed_identity = post({
            "root": str(tmp_path), "query": "x", "task_id": "task-1", "phase": "review",
            "worktree_id": 42,
        })
        assert status == 400
        assert "worktree_id must be string" in malformed_identity["error"]

        status, oversized_focus = post({
            "root": str(tmp_path), "query": "x", "task_id": "task-1", "phase": "review",
            "focus": ["x"] * 17,
        })
        assert status == 400
        assert "focus exceeds maximum of 16" in oversized_focus["error"]

        status, unguarded = post({"root": str(tmp_path), "query": "x", "changed_paths": ["src/app.py"]})
        assert status == 400
        assert "guarded=true" in unguarded["error"]

        status, invalid_phase = post({"root": str(tmp_path), "phase": "invented-phase", "max_tokens": 512})
        assert status == 400
        assert "phase" in invalid_phase["error"]

        status, phase_only = post(
            {"root": str(tmp_path), "phase": "discover", "focus": ["logs", "timeouts"], "max_tokens": 512}
        )
        assert status == 200
        assert phase_only["success"] is True
        assert phase_only["context_pack"]["contract"]["goal"] == "logs timeouts"
        assert phase_only["query"] == "logs timeouts"

        hybrid_calls = []
        hybrid_budgets = []
        route_warnings = [{"code": "route-context-warning"}]
        def record_hybrid(*args, **kwargs):
            hybrid_calls.append(kwargs)
            hybrid_budgets.append(kwargs["max_tokens"])
            return {
                "success": True, "context": "adaptive evidence", "context_source": "adaptive-hybrid",
                "warnings": route_warnings,
                "retrieval": {"backend_states": {"deterministic": "used"}},
            }
        app.services._hybrid_context = record_hybrid
        status, adaptive = post({"root": str(tmp_path), "query": "route repair", "mode": "adaptive", "max_tokens": 512})
        assert status == 200
        assert hybrid_calls[-1]["quality_first"] is True
        assert adaptive["retrieval"]["backend_states"]["deterministic"] == "used"
        assert adaptive["warnings"] == route_warnings
        assert hybrid_budgets[-1] == 512

        monkeypatch.setattr(project_config, "resolve_project_context", resolve_project_context)
        original_memory_revision = app.services._adaptive_memory_revision
        for failure in (
            RuntimeError("private memory backend detail"),
            sqlite3.OperationalError("private sqlite detail"),
        ):
            def fail_memory_revision(_request, failure=failure):
                raise failure

            monkeypatch.setattr(app.services, "_adaptive_memory_revision", fail_memory_revision)
            hybrid_count = len(hybrid_calls)
            status, unavailable_revision = post({
                "root": str(tmp_path), "query": "memory revision failure", "mode": "adaptive",
                "path_hints": [{"path": "src/api.py", "purpose": "implementation"}],
                "max_tokens": 512,
            })
            assert status == 200
            assert unavailable_revision["success"] is False
            assert unavailable_revision["terminal"] is True
            assert unavailable_revision["retryable"] is False
            assert unavailable_revision["stop_code"] == "context_memory_revision_unavailable"
            assert "context memory revision unavailable:" in unavailable_revision["error"]
            assert "private" not in json.dumps(unavailable_revision)
            assert len(hybrid_calls) == hybrid_count
        monkeypatch.setattr(app.services, "_adaptive_memory_revision", original_memory_revision)
        status, hinted_adaptive = post({
            "root": str(tmp_path), "query": "find the CakePHP button", "mode": "adaptive",
            "path_hints": [{"path": "/templates/element/button.php", "purpose": "button templates"}],
            "directory_hints": ["/templates/element"],
            "exclude_paths": ["build", "fixtures/private"],
            "force_include_paths": ["build/required-schema.json"],
            "max_tokens": 512,
        })
        assert status == 200
        assert hybrid_calls[-1]["path_hints"] == ({"path": "templates/element/button.php", "purpose": "button templates"},)
        assert hybrid_calls[-1]["directory_hints"] == ("templates/element",)
        assert hybrid_calls[-1]["exclude_paths"] == ("build", "fixtures/private")
        assert hybrid_calls[-1]["force_include_paths"] == ("build/required-schema.json",)
        assert hybrid_calls[-1]["context_identity"]["path_hints"] == hybrid_calls[-1]["path_hints"]
        assert hybrid_calls[-1]["context_identity"]["directory_hints"] == hybrid_calls[-1]["directory_hints"]
        assert hybrid_calls[-1]["context_identity"]["project_config_digest"] == "a" * 64
        first_identity = dict(hybrid_calls[-1]["context_identity"])
        resolved_project["digest"] = "b" * 64
        status, _changed_digest = post({
            "root": str(tmp_path), "query": "find the CakePHP button", "mode": "adaptive",
            "path_hints": [{"path": "/templates/element/button.php", "purpose": "button templates"}],
            "directory_hints": ["/templates/element"],
            "exclude_paths": ["build", "fixtures/private"],
            "force_include_paths": ["build/required-schema.json"], "max_tokens": 512,
        })
        assert status == 200
        assert hybrid_calls[-1]["context_identity"]["project_config_digest"] == "b" * 64
        assert first_identity != hybrid_calls[-1]["context_identity"]
        status, client_digest = post({
            "root": str(tmp_path), "query": "find the CakePHP button", "mode": "adaptive",
            "path_hints": [{"path": "/templates/element/button.php", "purpose": "button templates"}],
            "project_config_digest": "client-controlled-value", "max_tokens": 512,
        })
        assert status == 400
        assert "server-resolved" in client_digest["error"]
        monkeypatch.setattr(project_config, "resolve_project_context", original_project_resolver)
        assert hinted_adaptive["success"] is True

        status, unsafe_hint = post({
            "root": str(tmp_path), "query": "button", "mode": "adaptive",
            "path_hints": [{"path": "../outside.py"}], "max_tokens": 512,
        })
        assert status == 400
        assert "repository-relative" in unsafe_hint["error"]

        status, non_adaptive_hints = post({
            "root": str(tmp_path), "query": "button", "mode": "fast",
            "directory_hints": ["templates/element"], "max_tokens": 512,
        })
        assert status == 400
        assert "adaptive" in non_adaptive_hints["error"]

        status, full = post({"root": str(tmp_path), "query": "route repair", "mode": "full", "max_tokens": 512})
        assert status == 200
        assert hybrid_calls[-1]["quality_first"] is False

        fast_calls = []
        app.services.fast_context = lambda root, query, max_tokens: (
            fast_calls.append((root, query, max_tokens)) or
            {"success": True, "context": "deterministic fast evidence", "context_source": "deterministic-fast"}
        )
        hybrid_count = len(hybrid_calls)
        status, fast = post({"root": str(tmp_path), "query": "route repair", "mode": "fast", "max_tokens": 512})
        assert status == 200
        assert fast["context_source"] == "deterministic-fast"
        assert fast["delivery_mode"] == "fast"
        assert fast_calls == [(str(tmp_path.resolve()), "route repair", 512)]
        assert len(hybrid_calls) == hybrid_count

        from local_ai_hub.agent_context import CompiledContext

        app.services.adaptive_context_pack = lambda *_args, **_kwargs: {
            "success": True, "context": "repo evidence", "repo_revision": "revision-1",
            "evidence": [], "context_pack": {"context_id": "ctx-1", "evidence": []},
        }
        app.agent_context.compile = lambda _request: CompiledContext(
            elements=[], estimated_tokens=0, token_budget=512,
            repo_revision="revision-1", stale=True,
        )
        status, incomplete = post({
            "root": str(tmp_path), "task_id": "task-context", "phase": "review", "max_tokens": 512,
        })
        assert status == 503
        assert incomplete["success"] is False
        assert incomplete["stop_code"] == "context_task_context_incomplete"

        app.agent_context = None
        status, missing_compiler = post({
            "root": str(tmp_path), "task_id": "task-context", "phase": "review", "max_tokens": 512,
        })
        assert status == 503
        assert missing_compiler["success"] is False
        assert missing_compiler["stop_code"] == "context_task_context_unavailable"
    finally:
        server.shutdown()
        server.server_close()
        http_server.APP = previous
        app.close()


def test_guarded_pack_stays_bounded_and_state_disabled_safe():
    guard = _Guard((GuardWarning("warning", "long", "x" * 10000),))
    result = _guarded_services(guard).adaptive_context_pack(
        _request(query="q" * 10000, focus=("f" * 10000,), changed_paths=("p" * 10000,)), mode="adaptive"
    )

    assert len(result["context_pack"]["warnings"][0]["message"]) <= 4096
    assert len(result["context_pack"]["contract"]["goal"]) <= 1000
    assert len(json_dumps(result)) < 30000


def test_deterministic_context_continuation_uses_adaptive_mode():
    services = LocalAIServices.__new__(LocalAIServices)
    services.deterministic = _Deterministic()
    services.config = {
        "deterministic": {"context_max_chars": 5200, "context_raw_evidence": 5},
        "server": {"state_dir": str(_TEST_STATE_DIR)},
    }
    services._repo_cached = lambda _op, _root, _params, compute: compute()

    result = services.fast_context("C:/repo", "find route", 2000)

    assert result["context_source"] == "deterministic-fast"
    assert result["degraded"] is True
    assert result["continuation"]["mode"] == "adaptive"


def test_shipped_mcp_entrypoint_defaults_context_to_adaptive_and_telemetry_to_process():
    source = (ROOT / "src/local_ai_hub/mcp_server.py").read_text(encoding="utf-8")

    assert '"mode": mode,' in source
    assert 'scope: str = "process"' in source
    assert 'scope={scope}' in source

    assert not (ROOT / "mcp").exists()


def test_shipped_mcp_status_uses_lightweight_live_endpoint_by_default():
    source = (ROOT / "src/local_ai_hub/mcp_server.py").read_text(encoding="utf-8")

    assert 'CLIENT.get("/api/live/status?light=1")' in source
    assert 'CLIENT.get(f"/api/live/status?light=1&scope={scope}")' not in source
    assert '"token_saving": status.get("observability")' not in source


def test_context_http_endpoint_defaults_to_adaptive():
    source = (ROOT / "src/local_ai_hub/http_server.py").read_text(encoding="utf-8")

    assert 'payload.get("mode", "adaptive")' in source


def _path_inventory_services(tmp_path, *, indexed_paths=None, index_error=None, inventory_size=0):
    class Preprocessor:
        def __init__(self):
            self.roots = []

        def candidate_paths(self, _root, _query, limit=32):
            return ["src/generic.py"][:limit]

        def indexed_paths(self, root):
            self.roots.append(str(root))
            if index_error:
                raise index_error
            if callable(indexed_paths):
                return list(indexed_paths(str(root)))
            return list(indexed_paths or ())

    class RepoTools:
        def __init__(self):
            self.iterated = 0
            self.candidates = []

        def iter_files(self, _root):
            for index in range(inventory_size):
                self.iterated += 1
                yield tmp_path / f"inventory/{index:04}.py"

        def context_pack_paths(self, root, query, paths, max_tokens=2600, top_k=10, **path_controls):
            self.candidates = list(paths)
            evidence = [
                {"path": path, "evidence_id": f"e-{index}", "text": path}
                for index, path in enumerate(self.candidates[:20])
            ]
            return {
                "success": True, "root": str(root), "query": query,
                "context": "\n".join(item["text"] for item in evidence),
                "evidence": evidence, "scanned_files": len(evidence),
            }

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"features": {"rag": False}, "search": {"context_top_k": 14}}
    services.learner = None
    services.rag = None
    services.deterministic = None
    services.code_index = None
    services.preprocessor = Preprocessor() if indexed_paths is not None or index_error else None
    services.repo_tools = RepoTools()
    services.evidence_store = None
    services._external_context_candidates = lambda *_args, **_kwargs: (
        {}, [], {"serena": "skipped", "rag": "skipped"}
    )
    return services


def test_adaptive_path_controls_use_root_scoped_index_without_full_file_walk(tmp_path):
    services = _path_inventory_services(
        tmp_path,
        indexed_paths=(
            "src/generic.py", "templates/element/button.php", "build/private.py",
            "build/required.py", "src/forced.py", "../outside.py",
        ),
    )

    result = services._hybrid_context_uncached(
        str(tmp_path), "find button", workspace=None, max_tokens=512,
        quality_first=True,
        path_hints=({"path": "templates/element/button.php", "purpose": "button"},),
        directory_hints=("templates/element",),
        exclude_paths=("build/**",),
        force_include_paths=("build/required.py", "src/forced.py"),
    )

    assert result["success"] is True
    assert services.repo_tools.iterated == 0
    assert "templates/element/button.php" in services.repo_tools.candidates
    assert "build/required.py" not in services.repo_tools.candidates
    assert "build/required.py" not in [item["path"] for item in result["evidence"]]
    assert "src/forced.py" in services.repo_tools.candidates
    assert "build/private.py" not in services.repo_tools.candidates
    assert "build/private.py" not in [item["path"] for item in result["evidence"]]
    assert "../outside.py" not in services.repo_tools.candidates
    assert result["retrieval"]["backend_states"]["path_inventory"] == "used"


def test_directory_hint_resolves_indexed_descendants_and_structured_hint(tmp_path):
    services = _path_inventory_services(
        tmp_path,
        indexed_paths=(
            "templates/element/button.php", "templates/element/input.php",
            "templates/other/hidden.php", "../outside.php",
        ),
        inventory_size=1000,
    )

    result = services._hybrid_context_uncached(
        str(tmp_path), "find button", workspace=None, max_tokens=512,
        quality_first=True,
        path_hints=({"path": "templates/element/button.php", "purpose": "button template"},),
        directory_hints=("templates/element",),
    )

    assert result["success"] is True
    assert services.repo_tools.iterated == 0
    assert "templates/element/button.php" in services.repo_tools.candidates
    assert "templates/element/input.php" in services.repo_tools.candidates
    assert "templates/other/hidden.php" in services.repo_tools.candidates
    assert services.repo_tools.candidates.index("templates/element/button.php") < services.repo_tools.candidates.index("templates/element/input.php")
    assert services.repo_tools.candidates.index("templates/element/button.php") < services.repo_tools.candidates.index("templates/other/hidden.php")
    assert services.repo_tools.candidates.index("templates/element/input.php") < services.repo_tools.candidates.index("templates/other/hidden.php")
    assert "../outside.php" not in services.repo_tools.candidates


def test_directory_hint_finds_late_index_entries_without_filesystem_walk(tmp_path):
    indexed_paths = tuple(f"unrelated/{index:04}.py" for index in range(600)) + (
        "templates/element/button.php", "templates/element/input.php",
    )
    services = _path_inventory_services(tmp_path, indexed_paths=indexed_paths, inventory_size=1000)

    result = services._hybrid_context_uncached(
        str(tmp_path), "find button", workspace=None, max_tokens=512,
        quality_first=True, directory_hints=("templates/element",),
    )

    assert result["success"] is True
    assert services.repo_tools.iterated == 0
    assert "templates/element/button.php" in services.repo_tools.candidates
    assert "templates/element/input.php" in services.repo_tools.candidates
    assert len(services.repo_tools.candidates) <= 512


def test_focus_and_changed_paths_change_candidate_order(tmp_path):
    services = _path_inventory_services(
        tmp_path,
        indexed_paths=("src/app.py", "docs/database.md", "tests/test_app.py"),
    )

    services._hybrid_context_uncached(
        str(tmp_path), "find app", workspace=None, max_tokens=512,
        quality_first=True, focus=("database",),
    )
    focus_order = list(services.repo_tools.candidates)
    services._hybrid_context_uncached(
        str(tmp_path), "find app", workspace=None, max_tokens=512,
        quality_first=True, changed_paths=("tests/test_app.py",),
    )
    changed_order = list(services.repo_tools.candidates)

    assert focus_order[0] == "docs/database.md"
    assert changed_order[0] == "tests/test_app.py"
    assert focus_order != changed_order
    assert "src/app.py" in focus_order
    assert "docs/database.md" in changed_order


def test_adaptive_path_scan_fallback_is_bounded_and_explicitly_degraded(tmp_path):
    services = _path_inventory_services(tmp_path, inventory_size=1000)

    result = services._hybrid_context_uncached(
        str(tmp_path), "find route", workspace=None, max_tokens=512,
        quality_first=True, exclude_paths=("inventory/private/**",),
    )

    assert result["success"] is True
    assert services.repo_tools.iterated == 512
    assert len(services.repo_tools.candidates) <= 512
    assert result["retrieval"]["backend_states"]["path_inventory"] == "degraded"
    assert any("bounded filesystem fallback" in warning for warning in result["retrieval"]["warnings"])


def test_fallback_hints_boost_without_narrowing_inventory_candidates(tmp_path):
    services = _path_inventory_services(tmp_path, inventory_size=1000)

    result = services._hybrid_context_uncached(
        str(tmp_path), "find route", workspace=None, max_tokens=512,
        quality_first=True,
        path_hints=({"path": "src/desired.py", "purpose": "task"},),
        directory_hints=("src",),
    )

    assert result["success"] is True
    assert services.repo_tools.iterated == 512
    assert "inventory/0000.py" in services.repo_tools.candidates
    assert result["retrieval"]["backend_states"]["path_inventory"] == "degraded"


def test_empty_available_path_index_does_not_trigger_filesystem_fallback(tmp_path):
    services = _path_inventory_services(tmp_path, indexed_paths=(), inventory_size=1000)

    result = services._hybrid_context_uncached(
        str(tmp_path), "find route", workspace=None, max_tokens=512,
        quality_first=True, exclude_paths=("private/**",),
    )

    assert result["success"] is True
    assert services.repo_tools.iterated == 0
    assert result["retrieval"]["backend_states"]["path_inventory"] == "used"


def test_path_inventory_candidates_stay_repository_scoped(tmp_path):
    root_a = tmp_path / "repo-a"
    root_b = tmp_path / "repo-b"
    root_a.mkdir()
    root_b.mkdir()
    root_paths = {
        str(root_a): ("src/a.py",),
        str(root_b): ("src/b.py",),
    }
    services = _path_inventory_services(
        tmp_path, indexed_paths=lambda root: root_paths[root],
    )

    first = services._hybrid_context_uncached(
        str(root_a), "find item", workspace=None, max_tokens=512,
        quality_first=True, directory_hints=("src",),
    )
    candidates_a = list(services.repo_tools.candidates)
    second = services._hybrid_context_uncached(
        str(root_b), "find item", workspace=None, max_tokens=512,
        quality_first=True, directory_hints=("src",),
    )
    candidates_b = list(services.repo_tools.candidates)

    assert first["success"] is second["success"] is True
    assert "src/a.py" in candidates_a and "src/b.py" not in candidates_a
    assert "src/b.py" in candidates_b and "src/a.py" not in candidates_b
    assert services.preprocessor.roots == [str(root_a), str(root_b)]


def test_path_inventory_rejects_symlink_alias_before_candidate_normalization(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "linked").mkdir(parents=True)
    (root / "linked" / "private.py").write_text("private needle", encoding="utf-8")
    services = _path_inventory_services(root, indexed_paths=("linked/private.py", "src/safe.py"))
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == root / "linked" or original_is_symlink(path))

    result = services._hybrid_context_uncached(
        str(root), "needle", workspace=None, max_tokens=512,
        quality_first=True, directory_hints=("linked",),
        force_include_paths=("linked/private.py",),
    )

    assert result["success"] is True
    assert "linked/private.py" not in services.repo_tools.candidates
    assert "src/safe.py" in services.repo_tools.candidates


def test_context_pack_forwards_focus_and_changed_paths_to_candidate_ranking():
    services = _guarded_services(_Guard())
    services.consistency_guard = None
    captured = []
    services._hybrid_context = lambda *args, **kwargs: (
        captured.append(kwargs) or {"success": True, "context": "", "evidence": []}
    )

    services.adaptive_context_pack(
        _request(focus=("authentication flow",), changed_paths=("src/auth/session.py",)),
        mode="adaptive",
    )

    assert captured[0]["focus"] == ("authentication flow",)
    assert captured[0]["changed_paths"] == ("src/auth/session.py",)


def test_realtime_status_includes_preprocessor_projects_on_light():
    import threading
    from local_ai_hub.app import LocalAIApp, _STATUS_MAX_INFLIGHT_DEPENDENCIES, _new_status_dependency_executor

    app = LocalAIApp.__new__(LocalAIApp)
    app._live_status_lock = threading.Lock()
    app._live_status_cache = {}
    app._status_dependency_lock = threading.Lock()
    app._status_dependency_inflight = {}
    app._status_dependency_slots = threading.BoundedSemaphore(_STATUS_MAX_INFLIGHT_DEPENDENCIES)
    app._status_dependency_executor = _new_status_dependency_executor()
    app._headless_status = lambda: {"supervisor": True, "ollama_online": False}
    app.runtime = type("Runtime", (), {
        "is_online": lambda self: True,
        "managed_profile_status": lambda self: {},
    })()
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
    assert res_light["ollama_online"] is True
    assert res_light["headless"]["ollama_online"] is True
    app._status_dependency_executor.shutdown(wait=False, cancel_futures=True)


class _EvidenceDeterministic(_Deterministic):
    def __init__(self, events):
        self.events = events

    def context_pack(self, root, query, *, max_chars, max_raw_evidence):
        return {
            "success": True,
            "root": root,
            "query": query,
            "context": "deterministic context",
            "evidence": [{"evidence_id": "det-1", "path": "src/app.py", "raw": "secret-value"}],
            "estimated_tokens": 3,
        }

    def query(self, root, query, limit):
        self.events.append("deterministic")
        return {
            "success": True, "confidence": 1.0,
            "facts": [{"path": "src/app.py", "text": "route fact"}],
            "evidence": [{"path": "src/app.py", "evidence_id": "det-1"}],
        }

    def related_paths(self, root, query, *, limit, result=None):
        return ["src/app.py"]


class _EvidenceRepoTools(_RepoTools):
    def __init__(self, backend):
        self.backend = backend

    def iter_files(self, root):
        return iter(("src/app.py",))

    def context_pack(self, root, query, *, max_tokens, top_k):
        return self.backend.context_pack(
            root, query, max_chars=max_tokens * 4, max_raw_evidence=top_k,
        )

    def context_pack_paths(self, root, query, paths, *, max_tokens, top_k, **kwargs):
        return self.context_pack(root, query, max_tokens=max_tokens, top_k=top_k)


def _bind_evidence_backends(services):
    services.repo_tools = _EvidenceRepoTools(services.deterministic)
    services._refresh_changed_intelligence = lambda _root: None


class _RelevanceGuard(_Guard):
    def structured_evidence(self, evidence, *, limit=24):
        return ({"evidence_id": "det-1", "authority": "deterministic", "path": "src/app.py", "start_line": 1, "end_line": 2},)

    def postprocess_model_claims(self, evidence, claims, request):
        return {"claims": tuple(claims[:1]), "unknowns": (), "warnings": (), "authoritative_evidence_ids": ("det-1",)}


def test_adaptive_context_is_deterministic_first():
    events = []
    guard = _RelevanceGuard()
    services = _guarded_services(guard, stub_retrieval=False)
    services.deterministic = _EvidenceDeterministic(events)
    _bind_evidence_backends(services)
    services._generate = lambda *args, **kwargs: events.append("model") or {"success": True, "text": '{"selected_evidence_ids":["det-1"],"claims":[]}' }

    result = services.adaptive_context_pack(_request(memory_revision="memory-1"), mode="adaptive")

    assert events == ["deterministic", "model"]
    assert result["context_source"] == "adaptive-hybrid"
    assert result["repo_revision"] == "revision-1"


def test_model_relevance_pass_receives_structured_evidence_only():
    captured = {}
    guard = _RelevanceGuard()
    services = _guarded_services(guard, stub_retrieval=False)

    def generate(*args, **kwargs):
        captured["prompt"] = args[1]
        captured["system"] = args[2]
        captured["format"] = kwargs["format"]
        return {"success": True, "text": '{"selected_evidence_ids":["det-1"],"claims":[]}' }

    services.deterministic = _EvidenceDeterministic([])
    _bind_evidence_backends(services)
    services._generate = generate

    services.adaptive_context_pack(_request(query="find route private prompt secret-value"), mode="adaptive")

    assert "secret-value" not in captured["prompt"]
    assert "find route private prompt" not in captured["prompt"]
    assert '"evidence_id":"det-1"' in captured["prompt"]
    assert '"raw"' not in captured["prompt"]
    assert captured["format"] == {"type": "object"}


def test_model_failure_returns_deterministic_degraded_pack():
    guard = _RelevanceGuard()
    services = _guarded_services(guard, stub_retrieval=False)
    services.deterministic = _EvidenceDeterministic([])
    _bind_evidence_backends(services)
    services._generate = lambda *args, **kwargs: {"success": False, "error": "timeout"}

    result = services.adaptive_context_pack(_request(), mode="adaptive")

    assert result["context"] == "deterministic context"
    assert result["model_degraded"] is True
    assert result["model_degraded_reason"] == "model_unavailable"
    assert result["context_source"] == "adaptive-hybrid"


def test_adaptive_context_cache_key_includes_revision_phase_and_memory_revision():
    calls = []
    guard = _RelevanceGuard()
    services = _guarded_services(guard, stub_retrieval=False)
    services.deterministic = _EvidenceDeterministic([])
    _bind_evidence_backends(services)
    services._generate = lambda *args, **kwargs: {"success": True, "text": '{"claims":[]}' }
    original = services._repo_cached

    def capture(operation, root, params, compute):
        calls.append((operation, params))
        return original(operation, root, params, compute)

    services._repo_cached = capture
    services.adaptive_context_pack(
        _request(phase="review", focus=("contracts",), preload_profile="review", memory_revision="memory-7"),
        mode="adaptive",
    )

    params = next(item[1] for item in calls if item[0] == "adaptive-relevance")
    assert params["repository_revision"] == "revision-1"
    assert params["phase"] == "review"
    assert params["memory_revision"] == "memory-7"
    assert params["focus"] == ("contracts",)
    assert params["preload_profile"] == "review"


def test_adaptive_context_uses_project_weights_and_invalidates_config_identity(monkeypatch):
    from types import SimpleNamespace
    from local_ai_hub import project_config

    services = _guarded_services(_Guard(), stub_retrieval=False)
    services.consistency_guard = None
    captured = []
    cache_calls = []
    revisions = iter(("repo-1", "repo-2"))
    services.rag = None
    services.deterministic = None
    services._repo_cached = lambda _operation, _root, params, compute: (
        cache_calls.append(dict(params)) or compute()
    )
    services._hybrid_context_uncached = lambda *args, **kwargs: (
        captured.append(kwargs)
        or {"success": True, "context": "context", "evidence": [], "repo_revision": next(revisions)}
    )
    request = _request(
        root=str(ROOT),
        path_hints=({"path": "docs/pinned.md", "purpose": "repository_search", "scope": "task"},
                    {"path": "src/entry.py", "purpose": "repository_search", "scope": "task"}),
        exclude_paths=("vendor/**",),
        force_include_paths=("src/entry.py",),
        memory_revision="m" * 500,
    )

    coordination_id = project_config.resolve_project_context(ROOT, services.config["server"]["state_dir"]).coordination_id
    results = []
    for digest, weight in (("config-a", 0.25), ("config-b", 0.75)):
        project = SimpleNamespace(
            root=ROOT,
            coordination_id=coordination_id,
            settings=project_config.ProjectSettings(retrieval_weights={"lexical": weight}),
            config_digest=digest,
            path_hints=lambda **_kwargs: (),
        )
        monkeypatch.setattr(
            project_config, "resolve_project_context",
            lambda _root, _state, project=project: project,
        )
        results.append(services.adaptive_context_pack(request, mode="adaptive"))

    first, second = captured
    assert first["retrieval_weights"] == {"lexical": 0.25}
    assert second["retrieval_weights"] == {"lexical": 0.75}
    assert cache_calls[0]["context_identity"] != cache_calls[1]["context_identity"]
    assert cache_calls[0]["context_identity"]["memory_revision"] == "m" * 200
    assert results[0]["context_id"] != results[1]["context_id"]
    assert first["path_hints"] == second["path_hints"] == request.path_hints
    assert first["exclude_paths"] == second["exclude_paths"] == ("vendor/**",)
    assert first["force_include_paths"] == second["force_include_paths"] == ("src/entry.py",)
    assert cache_calls[0]["context_identity"]["project_config_digest"] == "config-a"
    assert cache_calls[1]["context_identity"]["project_config_digest"] == "config-b"
    assert cache_calls[0]["retrieval_weights"] == {"lexical": 0.25}
    assert cache_calls[1]["retrieval_weights"] == {"lexical": 0.75}


def test_generation_cache_key_changes_for_adaptive_context_inputs():
    common = {
        "model": "m", "prompt": "p", "system": "s", "options": {},
        "think": None, "execution": {}, "format": {"type": "object"},
    }
    first = generation_cache_key(
        **common, repository_revision="r1", phase="edit", memory_revision="m1",
        focus=("contracts",), preload_profile="default",
    )
    second = generation_cache_key(
        **common, repository_revision="r2", phase="review", memory_revision="m2",
        focus=("errors",), preload_profile="review",
    )

    assert first != second


class _PathRankingIndex:
    def __init__(self, paths):
        self.paths = paths

    def related_paths(self, root, query, limit):
        return self.paths[:limit]


class _PathScanRepoTools:
    def __init__(self):
        self.path_calls = []
        self.full_scan_calls = 0
        self.iterated = []

    def context_pack_paths(self, root, query, paths, max_tokens, top_k, **path_controls):
        self.path_calls.append(list(paths))
        return {
            "success": True, "root": root, "query": query, "context": "",
            "evidence": [], "estimated_tokens": 0, "scanned_files": len(paths),
        }

    def context_pack(self, *args, **kwargs):
        self.full_scan_calls += 1
        raise AssertionError("path-scoped retrieval must not launch a full recall scan")

    def iter_files(self, root):
        for path in self.iterated:
            yield path


def _path_scan_services(tmp_path, paths, *, indexed=True):
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"search": {"context_top_k": 8}, "preprocessing": {}}
    services.repo_tools = _PathScanRepoTools()
    services.repo_tools.iterated = [tmp_path / path for path in paths]
    services.code_index = _PathRankingIndex(paths) if indexed else None
    services.deterministic = None
    services.preprocessor = None
    services.rag = None
    services.learner = None
    services.evidence_store = None
    return services


def test_path_scoped_context_uses_bounded_candidates_with_exclude_force_precedence(tmp_path):
    paths = ("src/app.py", "src/private.py", "vendor/lib.py")
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("needle", encoding="utf-8")
    services = _path_scan_services(tmp_path, paths)

    result = services._hybrid_context_uncached(
        str(tmp_path), "needle", workspace=None, max_tokens=1000,
        path_hints=("src/app.py", "../outside.py"),
        exclude_paths=("src/**",),
        force_include_paths=("src/private.py",),
    )

    assert result["success"] is True
    assert services.repo_tools.path_calls == [["vendor/lib.py"]]
    assert services.repo_tools.full_scan_calls == 0


def test_context_focus_and_changed_paths_change_candidate_ranking(tmp_path):
    paths = ("src/app.py", "docs/guide.md", "tests/test_app.py")
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("needle", encoding="utf-8")
    services = _path_scan_services(tmp_path, paths)

    services._hybrid_context_uncached(
        str(tmp_path), "needle", workspace=None, max_tokens=1000, focus=("docs",),
    )
    focus_order = services.repo_tools.path_calls[-1]
    services._hybrid_context_uncached(
        str(tmp_path), "needle", workspace=None, max_tokens=1000,
        changed_paths=("tests/test_app.py",),
    )
    changed_order = services.repo_tools.path_calls[-1]

    assert focus_order[0] == "docs/guide.md"
    assert changed_order[0] == "tests/test_app.py"
    assert focus_order != changed_order


def test_path_scoped_context_uses_bounded_degraded_fallback_without_index(tmp_path):
    paths = ("src/a.py", "src/b.py", "src/c.py")
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("needle", encoding="utf-8")
    services = _path_scan_services(tmp_path, paths, indexed=False)
    services.config["search"]["context_fallback_scan_limit"] = 2

    result = services._hybrid_context_uncached(
        str(tmp_path), "needle", workspace=None, max_tokens=1000, path_hints=("src",),
    )

    assert services.repo_tools.path_calls == [["src/a.py", "src/b.py"]]
    assert services.repo_tools.full_scan_calls == 0
    assert result["degraded"] is True
    assert result["degraded_reason"] == "bounded_path_candidate_fallback"

def test_adaptive_context_identity_covers_guard_inputs_and_session():
    services = _guarded_services(_Guard())
    services.config["retrieval"] = {"profile": "quality-v1"}
    base = {
        "task_id": "task-1",
        "session_id": "session-1",
        "phase": "review",
        "focus": ("contracts",),
        "changed_paths": ("src/api.py",),
        "preload_profile": "review",
        "memory_revision": "memory-1",
    }
    original = services.adaptive_context_pack(_request(**base), mode="adaptive")["context_pack"]["context_id"]
    variants = (
        {"session_id": "session-2"},
        {"phase": "test"},
        {"focus": ("timeouts",)},
        {"changed_paths": ("src/repo.py",)},
        {"preload_profile": "plan"},
        {"memory_revision": "memory-2"},
        {"task_id": "task-2"},
    )

    for changed in variants:
        assert services.adaptive_context_pack(_request(**(base | changed)), mode="adaptive")["context_pack"]["context_id"] != original

    services.config["retrieval"]["profile"] = "quality-v2"
    assert services.adaptive_context_pack(_request(**base), mode="adaptive")["context_pack"]["context_id"] != original


def test_context_identity_changes_when_repository_revision_changes():
    services = _guarded_services(_Guard())

    class RevisionedRepoTools:
        revision = "repo-r1"

        def git_snapshot(self, root):
            return type("Snapshot", (), {"revision": self.revision, "changed_paths": ()})()

        def git_diff(self, root, base="HEAD", staged=False, max_tokens=10000):
            return {"success": True, "revision": self.revision, "changed_paths": [], "diff": ""}

    class RevisionedDeterministic:

        def context_pack(self, root, query, *, max_chars, max_raw_evidence):
            return {
                "success": True, "root": root, "query": query, "context": "facts",
                "evidence": [],
            }

    repo_tools = RevisionedRepoTools()
    services.repo_tools = repo_tools
    services.deterministic = RevisionedDeterministic()
    first = services.adaptive_context_pack(_request(), mode="adaptive")["context_pack"]["context_id"]

    repo_tools.revision = "repo-r2"
    second = services.adaptive_context_pack(_request(), mode="adaptive")["context_pack"]["context_id"]

    assert first != second


def test_unchanged_repository_revision_returns_context_reuse_pointer():
    result = _guarded_services(_Guard()).adaptive_context_pack(
        _request(), mode="adaptive", since_hash="revision-1"
    )

    assert result["unchanged"] is True
    assert result["reuse_pointer"] == result["context_pack"]["context_id"]
    assert result["context"] == "fast facts"


def test_context_http_preserves_terminal_pack_failure_with_and_without_task_context(tmp_path):
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
    terminal_failure = {
        "success": False,
        "terminal": True,
        "retryable": False,
        "stop_code": "context_memory_revision_unavailable",
        "error": "context memory revision unavailable: RuntimeError",
        "context": "",
        "evidence": [],
    }
    app.services.adaptive_context_pack = lambda *_args, **_kwargs: dict(terminal_failure)

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
        payload = {"root": str(tmp_path), "query": "bounded context", "guarded": True, "max_tokens": 512}
        status, body = post(payload)
        assert status == 500
        assert body["stop_code"] == terminal_failure["stop_code"]

        payload["task_id"] = "context-pack-terminal-failure"
        status, body = post(payload)
        assert status == 503
        assert body["stop_code"] == "context_task_context_incomplete"
        assert body["terminal"] is True
        assert body["retryable"] is False
        assert body["task_context"]["repository"]["stop_code"] == terminal_failure["stop_code"]

        retryable_failure = {
            **terminal_failure,
            "terminal": False,
            "retryable": True,
            "stop_code": "context_backend_busy",
        }
        app.services.adaptive_context_pack = lambda *_args, **_kwargs: dict(retryable_failure)
        status, body = post({"root": str(tmp_path), "query": "bounded context", "guarded": True, "max_tokens": 512})
        assert body["stop_code"] == retryable_failure["stop_code"]
        assert body["retryable"] is True
        assert status == 503
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous


def test_authoritative_deterministic_evidence_gets_stable_evidence_id():
    services = _guarded_services(_Guard(), stub_retrieval=False)

    class DeterministicWithEvidence:
        @staticmethod
        def context_pack(root, query, *, max_chars, max_raw_evidence):
            return {
                "success": True, "root": root, "query": query, "context": "exact route fact",
                "evidence": [{"path": "src/routes.py", "start_line": 3, "end_line": 3, "text": "route fact"}],
            }

    services.deterministic = DeterministicWithEvidence()
    _bind_evidence_backends(services)
    result = services.adaptive_context_pack(_request(), mode="adaptive")

    assert result["evidence"][0]["evidence_id"]


