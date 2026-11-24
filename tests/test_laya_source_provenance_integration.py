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
from local_ai_hub.services import LocalAIServices




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
    with pytest.raises(RuntimeError, match="pinned Laya checkpoint is unavailable locally or could not be verified"):
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

    with pytest.raises(RuntimeError, match="pinned Laya checkpoint is unavailable locally or could not be verified"):
        app.evaluate_laya_context_source(operation, root="")








def test_laya_runtime_decision_uses_existing_metadata_telemetry():
    app = LocalAIApp.__new__(LocalAIApp)
    calls = []
    app.telemetry = SimpleNamespace(
        record_laya_decision=lambda metadata, **identity: calls.append((metadata, identity)) or True
    )
    request = SimpleNamespace(
        repository_id="repo-1", task_id="task-1", session_id="session-1",
        provider_label="generic_mcp",
    )
    metadata = {"decision_id": "laya-1", "suggestion": "indexed"}
    decision = SimpleNamespace(metadata=lambda: metadata)

    app._record_laya_runtime_decision(request, decision)

    assert calls == [(
        metadata,
        {"repository_id": "repo-1", "task_id": "task-1", "session_id": "session-1"},
    )]
    assert calls[0][0]["provider_label"] == "generic_mcp"


def test_laya_runtime_decision_telemetry_failure_is_logged_without_raising():
    app = LocalAIApp.__new__(LocalAIApp)
    warnings = []

    def fail_recording(*_args, **_kwargs):
        raise RuntimeError("telemetry unavailable")

    app.telemetry = SimpleNamespace(record_laya_decision=fail_recording)
    app.logger = SimpleNamespace(warning=lambda *args: warnings.append(args))
    request = SimpleNamespace(
        repository_id="repo-1", task_id="task-1", session_id="session-1",
        provider_label="generic_mcp",
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
        repository_id="repo-1", task_id="task-1", session_id="session-1",
        provider_label="generic_mcp",
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


def test_typed_laya_decision_rejects_missing_server_baseline_before_inference(tmp_path, monkeypatch):
    app = LocalAIApp.__new__(LocalAIApp)
    task = SimpleNamespace(task_id="task-1")
    app._laya_inference_enabled = lambda: True
    app.config = {
        "laya": {
            "runtime": {
                "checkpoint_path": str(tmp_path / "checkpoint"),
                "revision": "revision-1",
                "expected_sha256": {"model.safetensors": "a" * 64},
            }
        },
        "server": {"state_dir": str(tmp_path / "state")},
    }
    app.agent_tasks = SimpleNamespace()
    app.evidence = object()
    app.laya_candidates = SimpleNamespace(
        _find_task=lambda *_args: task,
        _session_for_task=lambda _task: "session-1",
        _candidate_input=lambda value: value,
        _validate_context_source_evidence=lambda *_args, **_kwargs: None,
    )
    app._derive_laya_decision_baseline = lambda *_args: None
    app._get_laya_runtime_adapter = lambda *_args, **_kwargs: pytest.fail(
        "Laya must not run when no deterministic baseline exists"
    )
    monkeypatch.setattr(
        "local_ai_hub.project_config.resolve_project_context",
        lambda *_args: SimpleNamespace(coordination_id="repo-1"),
    )
    operation = {
        "action": "evaluate_decision",
        "task_id": "task-1",
        "decision": {
            "category": "model_route",
            "evidence_ids": ["E" + "a" * 20],
            "options": ["fast", "smart"],
            "state": {"request_kind": "code"},
            "training_content": {},
        },
    }

    with pytest.raises(ValueError, match="deterministic server baseline"):
        app.evaluate_laya_decision(operation, root=str(tmp_path))


def test_typed_retrieval_advisory_accepts_pipeline_hybrid_baseline(tmp_path, monkeypatch):
    from local_ai_hub.laya_decisions import DecisionCategory

    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    evidence_id = "E" + "a" * 20
    app = LocalAIApp.__new__(LocalAIApp)
    task = SimpleNamespace(task_id="task-retrieval")
    app._laya_inference_enabled = lambda: True
    app.config = {
        "laya": {
            "enabled": True,
            "runtime": {
                "checkpoint_path": str(checkpoint),
                "revision": "revision-1",
                "expected_sha256": {"model.safetensors": "a" * 64},
            },
        },
        "models": {},
        "server": {"state_dir": str(tmp_path / "state")},
    }
    app.agent_tasks = object()
    app.evidence = object()
    app.laya_lifecycle = object()
    app.laya_candidates = SimpleNamespace(
        _find_task=lambda *_args: task,
        _session_for_task=lambda _task: "session-retrieval",
        _candidate_input=lambda value: value,
        _validate_context_source_evidence=lambda *_args, **_kwargs: None,
        capture_runtime_outcome=lambda *_args, **_kwargs: {"candidate_id": "candidate-1"},
    )
    app._record_laya_decision_eligibility = lambda _request: True
    app._record_laya_runtime_decision = lambda *_args: None
    app._record_laya_capture_observation = lambda *_args, **_kwargs: True

    class Adapter:
        def evaluate_decision(self, request, _decision_input, **kwargs):
            assert request.category is DecisionCategory.RETRIEVAL_STRATEGY
            assert kwargs["outcome_recorder"] is not None
            decision = SimpleNamespace(
                success=True,
                status=SimpleNamespace(value="success"),
                suggestion="hybrid",
                reason_codes=("EVIDENCE_SUFFICIENT",),
                metadata=lambda: {"success": True},
            )
            outcome = SimpleNamespace(
                decision=decision,
                runtime=SimpleNamespace(provider="stub", revision="revision-1", latency_ms=1),
            )
            kwargs["outcome_recorder"](request, _decision_input, outcome)
            return outcome

    app._get_laya_runtime_adapter = lambda *_args, **_kwargs: Adapter()
    monkeypatch.setattr(
        "local_ai_hub.project_config.resolve_project_context",
        lambda *_args: SimpleNamespace(coordination_id="repo-retrieval"),
    )
    operation = {
        "action": "evaluate_decision",
        "task_id": "task-retrieval",
        "decision": {
            "category": "retrieval_strategy",
            "evidence_ids": [evidence_id],
            "options": ["lexical_bm25", "hybrid"],
            "state": {"context_source": "hybrid"},
            "training_content": {"task_input": "find the relevant code"},
        },
    }

    result = app.evaluate_laya_decision(
        operation,
        root=str(tmp_path),
        _server_baseline={
            "method": "hybrid_context_default",
            "suggestion": "hybrid",
            "evidence_id": evidence_id,
        },
    )

    assert result["success"] is True
    assert result["baseline"]["method"] == "hybrid_context_default"
    assert result["decision"]["suggestion"] == "hybrid"


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


@pytest.mark.parametrize("capture_fails", [True, False])
def test_typed_laya_decision_reports_and_records_capture_status(monkeypatch, tmp_path, capture_fails):
    app = LocalAIApp.__new__(LocalAIApp)
    observations = []
    eligibility = []
    decisions = []
    app.config = {
        "server": {"state_dir": str(tmp_path)},
        "laya": {
            "runtime": {
                "checkpoint_path": str(tmp_path),
                "revision": "revision-1",
                "expected_sha256": {"model.safetensors": "a" * 64},
            }
        },
    }
    app.telemetry = SimpleNamespace(
        record_laya_eligibility=lambda **event: eligibility.append(event) or True,
        record_laya_decision=lambda metadata, **identity: decisions.append((metadata, identity)) or True,
        record_stage=lambda **event: observations.append(event),
    )
    app.logger = SimpleNamespace(warning=lambda *_args, **_kwargs: None)

    evidence_id = "E" + "a" * 20
    task = SimpleNamespace(
        task_id="task-1",
        context=SimpleNamespace(session_id="session-1"),
        checkpoint=SimpleNamespace(evidence_ids=(evidence_id,)),
    )

    class CandidateStore:
        @staticmethod
        def _find_task(*_args):
            return task

        @staticmethod
        def _session_for_task(_task):
            return "session-1"

        @staticmethod
        def _candidate_input(candidate):
            return candidate

        @staticmethod
        def _validate_context_source_evidence(*_args, **_kwargs):
            return None

        @staticmethod
        def capture_runtime_outcome(*_args, **_kwargs):
            if capture_fails:
                raise OSError("candidate store unavailable")
            return {
                "candidate_id": "laya-1",
                "duplicate": False,
                "status": "pending",
                "runtime_output_recorded": True,
            }

    app.laya_candidates = CandidateStore()
    app.agent_tasks = SimpleNamespace(validate_completion=lambda _task_id: None)
    app.evidence = object()
    app.laya_lifecycle = object()
    monkeypatch.setattr(
        "local_ai_hub.project_config.resolve_project_context",
        lambda *_args, **_kwargs: SimpleNamespace(coordination_id="repo-1"),
    )

    class Adapter:
        @staticmethod
        def evaluate_decision(request, decision_input, **kwargs):
            decision = SimpleNamespace(
                success=True,
                status=SimpleNamespace(value="success"),
                suggestion="missing_verification",
                reason_codes=("EVIDENCE_SUFFICIENT",),
                metadata=lambda: {"success": True},
            )
            runtime = SimpleNamespace(
                provider="torch", revision="revision-1", latency_ms=18.0,
                inference_latency_ms=15.0, adapter_queue_wait_ms=3.0,
                fallback_reason=None,
            )
            outcome = SimpleNamespace(decision=decision, runtime=runtime)
            try:
                kwargs["outcome_recorder"](request, decision_input, outcome)
            except Exception:
                return SimpleNamespace(decision=decision, runtime=runtime, capture_status="failed")
            return SimpleNamespace(decision=decision, runtime=runtime, capture_status="captured")

    app._get_laya_runtime_adapter = lambda *_args, **_kwargs: Adapter()
    result = app.evaluate_laya_decision(
        {
            "action": "evaluate_decision",
            "task_id": "task-1",
            "decision": {
                "category": "completion_gap",
                "evidence_ids": [evidence_id],
                "options": ["missing_verification", "resolve_blocker"],
                "state": {"complete": "false"},
                "training_content": {},
            },
        },
        root=str(tmp_path),
    )

    assert result["decision"]["suggestion"] == "missing_verification"
    assert result["baseline"] == {
        "method": "agent_os_completion_gate",
        "suggestion": "ready",
        "evidence_id": evidence_id,
    }
    assert result["capture_status"] == ("failed" if capture_fails else "captured")
    assert result["capture_error_type"] == ("OSError" if capture_fails else None)
    assert len(eligibility) == 1
    assert eligibility[0]["mode"] == "advisory"
    assert eligibility[0]["category"] == "completion_gap"
    assert len(decisions) == 1
    assert decisions[0][0]["runtime_latency_ms"] == 18.0
    assert decisions[0][0]["inference_latency_ms"] == 15.0
    assert decisions[0][0]["queue_wait_ms"] == 3.0
    assert decisions[0][0]["backend"] == "torch"
    assert decisions[0][0]["fallback_used"] is False
    if not capture_fails:
        assert result["candidate"]["candidate_id"] == "laya-1"
    expected_event = {
        "action": "laya_capture",
        "stage": "failed" if capture_fails else "captured",
        "bypass_reason": "capture_exception" if capture_fails else "runtime_outcome",
        "success": not capture_fails,
    }
    if capture_fails:
        expected_event["error_type"] = "OSError"
    assert observations == [expected_event]
