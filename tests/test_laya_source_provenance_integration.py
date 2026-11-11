import hashlib
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from local_ai_hub.app import LocalAIApp
from local_ai_hub.agent_tasks import CompletionGateError
from local_ai_hub.evidence import EvidenceStore
from local_ai_hub.laya_decisions import DecisionCategory
from local_ai_hub.tool_agent import ToolAwareLocalAgent


def test_laya_runtime_adapter_is_cached_once_across_concurrent_requests(monkeypatch):
    from local_ai_hub import laya_runtime

    app = LocalAIApp.__new__(LocalAIApp)
    app._laya_runtime_adapter = None
    app._laya_runtime_adapter_lock = threading.Lock()
    app.scheduler = object()
    constructed = []

    class FakeAdapter:
        def __init__(self, **kwargs):
            time.sleep(0.02)
            constructed.append(self)

    monkeypatch.setattr(laya_runtime, "LayaRuntimeAdapter", FakeAdapter)
    monkeypatch.setattr(laya_runtime, "discover_torch_devices", lambda: ())

    def get_adapter():
        return app._get_laya_runtime_adapter(
            {"allow_cpu": False},
            checkpoint_path="C:/models/revision-1",
            revision="revision-1",
            expected_sha256={"model.safetensors": "a" * 64},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(get_adapter)
        second = executor.submit(get_adapter)
        adapters = (first.result(), second.result())

    assert adapters[0] is adapters[1]
    assert len(constructed) == 1


def test_laya_runtime_api_needs_no_per_example_consent_before_runtime_setup():
    app = LocalAIApp.__new__(LocalAIApp)
    app.laya_candidates = SimpleNamespace()
    operation = {
        "action": "evaluate_context_source",
        "task_id": "task-1",
        "session_id": "session-1",
        "evidence": {},
    }

    app.config = {"laya": {"runtime": {"enabled": False}}}
    with pytest.raises(RuntimeError, match="Laya shadow checkpoint is not configured"):
        app.evaluate_laya_context_source(operation, root="")


def test_laya_runtime_api_accepts_the_session_id_it_validates():
    app = LocalAIApp.__new__(LocalAIApp)
    app.laya_candidates = SimpleNamespace()
    app.config = {"laya": {"runtime": {"enabled": False}}}
    operation = {
        "action": "evaluate_context_source",
        "task_id": "task-1",
        "session_id": "session-1",
        "evidence": {},
    }

    with pytest.raises(RuntimeError, match="Laya shadow checkpoint is not configured"):
        app.evaluate_laya_context_source(operation, root="")


def test_context_capture_is_not_disabled_by_runtime_flag_and_skips_missing_task(tmp_path):
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"laya": {"runtime": {"enabled": False}}}
    observations = []
    app.telemetry = SimpleNamespace(record_stage=lambda **event: observations.append(event))
    request = SimpleNamespace(root=str(tmp_path), task_id="", session_id="session-1")

    result = app.capture_laya_context_source_from_context(
        request,
        {"success": True, "query": "private query", "evidence": [{"text": "private source"}]},
    )

    assert result == {"status": "skipped", "reason": "task_identity_unavailable"}
    assert observations == [{
        "action": "laya_capture",
        "stage": "skipped",
        "bypass_reason": "task_identity_unavailable",
        "success": True,
    }]


def test_ordinary_context_capture_queues_without_per_example_consent(tmp_path):
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"laya": {"runtime": {"enabled": False}}}
    telemetry_events = []
    log_warnings = []
    app.telemetry = SimpleNamespace(record_stage=lambda **event: telemetry_events.append(event))
    app.logger = SimpleNamespace(warning=lambda *args: log_warnings.append(args))
    task = SimpleNamespace(context={"session_id": "session-1"})
    app.agent_tasks = object()
    app.laya_candidates = SimpleNamespace(
        _find_task=lambda *_args: task,
        _session_for_task=lambda value: value.context["session_id"],
    )
    app.evidence = SimpleNamespace(
        put_many=lambda *_args, **_kwargs: [{"evidence_id": "ev-indexed"}],
        get_many=lambda *_args, **_kwargs: [{"success": True, "stale": False}],
        validate_source_provenance=lambda *_args, **_kwargs: True,
    )
    observed = {}
    app.evaluate_laya_context_source = lambda operation, *, root, baseline=None: observed.update(
        operation=operation, root=root, baseline=baseline
    ) or {"status": "captured", "candidate": {"candidate_id": "candidate-1"}}

    class ImmediateExecutor:
        def submit(self, callback, *args, **kwargs):
            observed["callback"] = callback
            observed["args"] = args
            observed["kwargs"] = kwargs
            result = callback(*args, **kwargs)
            future = Future()
            future.set_result(result)
            return future

    app._status_dependency_executor = ImmediateExecutor()
    app._laya_capture_lock = threading.Lock()
    app._laya_capture_queue = []
    app._laya_capture_draining = False
    app._shutdown = threading.Event()
    request = SimpleNamespace(root=str(tmp_path), task_id="task-1", session_id="session-1", query="Find parser behavior")
    result = {
        "success": True,
        "stale": False,
        "retrieval": {
            "backend_states": {"lexical": "used", "rag": "used"},
            "lexical": {
                "freshness": {"status": "current"},
                "coverage": {"complete": False, "candidate_count": 1},
            },
            "semantic": {
                "freshness": {"status": "current"},
                "coverage": {"complete": False, "candidate_count": 1},
            },
        },
        "query": "Find parser behavior",
        "evidence": [
            {"path": "indexed.py", "content_hash": "a" * 64, "text": "parse_request checks the route"},
            {
                "path": "rag.py", "content_hash": "b" * 64,
                "semantic": True, "evidence_id": "ev-rag", "text": "RAG record: parser handles route selection",
            },
        ],
    }

    queued = app.capture_laya_context_source_from_context(request, result)
    assert queued == {"status": "queued"}
    assert [event["stage"] for event in telemetry_events] == ["queued", "captured"]
    assert len(log_warnings) == 0
    assert all(set(event) <= {"action", "stage", "bypass_reason", "success", "error_type"} for event in telemetry_events)
    operation = observed["operation"]
    assert operation["session_id"] == "session-1"
    assert set(operation) == {"action", "task_id", "session_id", "evidence"}
    assert operation["evidence"]["training_content"] == {
        "task_input": "Find parser behavior",
        "context_excerpt": "indexed: parse_request checks the route\nrag: RAG record: parser handles route selection",
    }
    assert observed["baseline"] == {
        "method": "retrieval_rank_order",
        "suggestion": "indexed",
        "evidence_id": "ev-indexed",
    }


def test_ordinary_context_capture_queues_concurrent_requests_serially_and_bounded(tmp_path):
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"laya": {"runtime": {"enabled": True}}}
    telemetry_events = []
    app.telemetry = SimpleNamespace(record_stage=lambda **event: telemetry_events.append(event))
    app.logger = SimpleNamespace(warning=lambda *_args: None)
    task = SimpleNamespace(context={"session_id": "session-1"})
    app.agent_tasks = object()
    app.laya_candidates = SimpleNamespace(
        _find_task=lambda *_args: task,
        _session_for_task=lambda value: value.context["session_id"],
    )
    app.evidence = SimpleNamespace(
        put_many=lambda *_args, **_kwargs: [{"evidence_id": "ev-indexed"}],
        get_many=lambda *_args, **_kwargs: [{"success": True, "stale": False}],
        validate_source_provenance=lambda *_args, **_kwargs: True,
    )
    evaluated = []
    app.evaluate_laya_context_source = lambda operation, *, root, baseline=None: evaluated.append(
        (operation, root, baseline)
    ) or {"status": "captured", "candidate": {"candidate_id": f"candidate-{len(evaluated)}"}}

    class DeferredExecutor:
        def __init__(self):
            self.submissions = []

        def submit(self, callback, *args, **kwargs):
            future = Future()
            self.submissions.append((callback, args, kwargs, future))
            return future

    executor = DeferredExecutor()
    app._status_dependency_executor = executor
    app._laya_capture_inflight = threading.Lock()
    app._laya_capture_lock = threading.Lock()
    app._laya_capture_queue = []
    app._laya_capture_draining = False
    app._shutdown = threading.Event()
    request = SimpleNamespace(root=str(tmp_path), task_id="task-1", session_id="session-1", query="Find parser behavior")
    result = {
        "success": True,
        "stale": False,
        "retrieval": {
            "backend_states": {"lexical": "used", "rag": "used"},
            "lexical": {"freshness": {"status": "current"}, "coverage": {"complete": False, "candidate_count": 1}},
            "semantic": {"freshness": {"status": "current"}, "coverage": {"complete": False, "candidate_count": 1}},
        },
        "evidence": [
            {"path": "indexed.py", "content_hash": "a" * 64, "text": "parse_request checks the route"},
            {"path": "rag.py", "content_hash": "b" * 64, "semantic": True, "evidence_id": "ev-rag", "text": "RAG record: parser handles route selection"},
        ],
    }

    first = app.capture_laya_context_source_from_context(request, result)
    second = app.capture_laya_context_source_from_context(request, result)
    additional = [app.capture_laya_context_source_from_context(request, result) for _ in range(14)]
    overflow = app.capture_laya_context_source_from_context(request, result)
    assert first == second == {"status": "queued"}
    assert additional == [{"status": "queued"}] * 14
    assert overflow == {"status": "skipped", "reason": "capture_queue_unavailable"}
    assert len(app._laya_capture_queue) == 16
    assert len(executor.submissions) == 1
    callback, args, kwargs, future = executor.submissions[0]
    callback(*args, **kwargs)
    future.set_result({"status": "completed"})

    assert len(evaluated) == 16
    stages = [event["stage"] for event in telemetry_events]
    assert stages.count("queued") == 16
    assert stages.count("skipped") == 1
    assert stages.count("captured") == 16


def test_laya_runtime_decision_uses_existing_metadata_telemetry():
    app = LocalAIApp.__new__(LocalAIApp)
    calls = []
    app.telemetry = SimpleNamespace(
        record_laya_decision=lambda metadata, **identity: calls.append((metadata, identity)) or True
    )
    request = SimpleNamespace(
        repository_id="repo-1", task_id="task-1", session_id="session-1"
    )
    metadata = {"decision_id": "laya-1", "suggestion": "indexed"}
    decision = SimpleNamespace(metadata=lambda: metadata)

    app._record_laya_runtime_decision(request, decision)

    assert calls == [(
        metadata,
        {"repository_id": "repo-1", "task_id": "task-1", "session_id": "session-1"},
    )]


def test_laya_runtime_decision_telemetry_failure_is_logged_without_raising():
    app = LocalAIApp.__new__(LocalAIApp)
    warnings = []

    def fail_recording(*_args, **_kwargs):
        raise RuntimeError("telemetry unavailable")

    app.telemetry = SimpleNamespace(record_laya_decision=fail_recording)
    app.logger = SimpleNamespace(warning=lambda *args: warnings.append(args))
    request = SimpleNamespace(
        repository_id="repo-1", task_id="task-1", session_id="session-1"
    )
    decision = SimpleNamespace(metadata=lambda: {"decision_id": "laya-1"})

    assert app._record_laya_runtime_decision(request, decision) is False
    assert warnings == [("Laya decision telemetry failed: %s", "RuntimeError")]


def test_laya_runtime_decision_telemetry_rejection_is_logged_without_raising():
    app = LocalAIApp.__new__(LocalAIApp)
    warnings = []
    app.telemetry = SimpleNamespace(record_laya_decision=lambda *_args, **_kwargs: False)
    app.logger = SimpleNamespace(warning=lambda *args: warnings.append(args))
    request = SimpleNamespace(
        repository_id="repo-1", task_id="task-1", session_id="session-1"
    )
    decision = SimpleNamespace(metadata=lambda: {"decision_id": "laya-1"})

    assert app._record_laya_runtime_decision(request, decision) is False
    assert warnings == [("Laya decision telemetry was not recorded",)]


@pytest.mark.parametrize(
    ("gate_passes", "expected_suggestion"),
    [(True, "ready"), (False, "not_ready")],
)
def test_laya_completion_gap_baseline_comes_from_server_completion_gate(
    gate_passes, expected_suggestion
):
    app = LocalAIApp.__new__(LocalAIApp)
    calls = []

    def validate_completion(task_id):
        calls.append(task_id)
        if not gate_passes:
            raise CompletionGateError("authoritative gate did not pass")

    app.agent_tasks = SimpleNamespace(validate_completion=validate_completion)
    request = SimpleNamespace(
        category=DecisionCategory.COMPLETION_GAP,
        evidence_ids=("E" + "a" * 20,),
    )
    task = SimpleNamespace(
        task_id="task-1",
        checkpoint=SimpleNamespace(evidence_ids=request.evidence_ids),
    )

    baseline = app._derive_laya_decision_baseline(request, task)

    assert calls == ["task-1"]
    assert baseline == {
        "method": "agent_os_completion_gate",
        "suggestion": expected_suggestion,
        "evidence_id": request.evidence_ids[0],
    }


def test_completion_gap_baseline_requires_task_checkpoint_evidence():
    app = LocalAIApp.__new__(LocalAIApp)
    app.agent_tasks = SimpleNamespace(
        validate_completion=lambda *_args: pytest.fail("baseline must not run without task evidence")
    )
    request = SimpleNamespace(
        category=DecisionCategory.COMPLETION_GAP,
        evidence_ids=("E" + "a" * 20,),
    )
    task = SimpleNamespace(
        task_id="task-1",
        checkpoint=SimpleNamespace(evidence_ids=("E" + "b" * 20,)),
    )

    assert app._derive_laya_decision_baseline(request, task) is None


def test_unsupported_laya_decision_category_has_no_server_baseline():
    app = LocalAIApp.__new__(LocalAIApp)
    app.agent_tasks = SimpleNamespace(
        validate_completion=lambda *_args: pytest.fail("unsupported category must not check completion")
    )
    request = SimpleNamespace(
        category=DecisionCategory.MODEL_ROUTE,
        evidence_ids=("E" + "a" * 20,),
    )

    assert app._derive_laya_decision_baseline(request, "task-1") is None


def test_laya_decision_operation_rejects_caller_supplied_baseline():
    app = LocalAIApp.__new__(LocalAIApp)
    operation = {
        "action": "evaluate_decision",
        "task_id": "task-1",
        "decision": {
            "category": "completion_gap",
            "evidence_ids": ["E" + "a" * 20],
            "options": ["ready", "not_ready"],
            "state": {"complete": "false"},
            "training_content": {},
            "baseline": {"method": "agent_os_completion_gate", "suggestion": "ready"},
        },
    }

    with pytest.raises(ValueError, match="decision input fields invalid"):
        app.evaluate_laya_decision(operation, root="unused")


def _evidence_item(root, name, text, sources):
    path = root / name
    path.write_text(text + "\n", encoding="utf-8")
    return {
        "path": name,
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "start_line": 1,
        "end_line": 1,
        "text": text,
        "sources": sources,
    }


def test_repo_search_and_evidence_get_bind_routes_in_real_evidence_store(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    indexed = _evidence_item(root, "indexed.py", "indexed fact", ["lexical"])
    rag = _evidence_item(root, "rag.py", "rag fact", ["rag"])
    evidence = EvidenceStore(tmp_path / "state")
    services = SimpleNamespace(
        repo_search=lambda *_args, **_kwargs: {
            "root": str(root),
            "result_source": "hybrid",
            "results": [indexed, rag],
        }
    )
    agent = ToolAwareLocalAgent.__new__(ToolAwareLocalAgent)
    agent.services = services
    agent.evidence = evidence

    search_result = agent._execute_tool("repo_search", {"query": "fact"}, str(root), str(root))
    evidence_ids = [item["evidence_id"] for item in search_result["results"]]

    assert search_result["progressive_disclosure"] is True
    assert evidence.validate_source_provenance(
        evidence_ids, ["indexed", "rag"], root=str(root)
    ) is True
    assert evidence.validate_source_provenance(
        evidence_ids, ["rag", "indexed"], root=str(root)
    ) is False

    fetched = agent._execute_tool(
        "evidence_get", {"evidence_id": evidence_ids[0]}, str(root), str(root)
    )

    assert fetched["success"] is True
    assert evidence.validate_source_provenance(
        [evidence_ids[0]], ["artifact"], root=str(root)
    ) is True
    assert evidence.validate_source_provenance(
        [evidence_ids[0]], ["artifact"], root=str(tmp_path)
    ) is False
