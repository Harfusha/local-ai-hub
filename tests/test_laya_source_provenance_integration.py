import hashlib
import threading
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from local_ai_hub.app import LocalAIApp
from local_ai_hub.evidence import EvidenceStore
from local_ai_hub.tool_agent import ToolAwareLocalAgent


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
    with pytest.raises(RuntimeError, match="Laya shadow runtime is disabled"):
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

    with pytest.raises(RuntimeError, match="Laya shadow runtime is disabled"):
        app.evaluate_laya_context_source(operation, root="")


def test_context_capture_persists_typed_skip_status_without_request_content(tmp_path):
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"laya": {"runtime": {"enabled": False}}}
    observations = []
    app.telemetry = SimpleNamespace(record_stage=lambda **event: observations.append(event))
    request = SimpleNamespace(root=str(tmp_path), task_id="task-1", session_id="session-1")

    result = app.capture_laya_context_source_from_context(
        request,
        {"success": True, "query": "private query", "evidence": [{"text": "private source"}]},
    )

    assert result == {"status": "disabled"}
    assert observations == [{
        "action": "laya_capture",
        "stage": "disabled",
        "bypass_reason": "runtime_disabled",
        "success": True,
    }]


def test_ordinary_context_capture_queues_without_per_example_consent(tmp_path):
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"laya": {"runtime": {"enabled": True}}}
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
    app.evaluate_laya_context_source = lambda operation, *, root: observed.update(
        operation=operation, root=root
    ) or {"status": "captured"}

    class ImmediateExecutor:
        def submit(self, callback, *args, **kwargs):
            observed["callback"] = callback
            observed["args"] = args
            observed["kwargs"] = kwargs
            future = Future()
            future.set_result({"status": "captured"})
            return future

    app._status_dependency_executor = ImmediateExecutor()
    app._laya_capture_inflight = threading.Lock()
    request = SimpleNamespace(root=str(tmp_path), task_id="task-1", session_id="session-1")
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
        "evidence": [
            {"path": "indexed.py", "content_hash": "a" * 64, "text": "indexed"},
            {
                "path": "rag.py", "content_hash": "b" * 64,
                "semantic": True, "evidence_id": "ev-rag",
            },
        ],
    }

    queued = app.capture_laya_context_source_from_context(request, result)
    assert queued == {"status": "queued"}
    assert [event["stage"] for event in telemetry_events] == ["queued", "failed"]
    assert telemetry_events[-1]["bypass_reason"] == "outcome_not_captured"
    assert len(log_warnings) == 1
    assert all(set(event) <= {"action", "stage", "bypass_reason", "success", "error_type"} for event in telemetry_events)
    operation = observed["args"][0]
    assert operation["session_id"] == "session-1"
    assert set(operation) == {"action", "task_id", "session_id", "evidence"}


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
