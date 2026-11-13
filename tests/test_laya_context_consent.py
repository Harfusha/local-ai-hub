from __future__ import annotations

import threading
from concurrent.futures import Future
from types import SimpleNamespace

from local_ai_hub.app import LocalAIApp, _redact_laya_training_text
from local_ai_hub.laya_decisions import DecisionResult, DecisionStatus


def test_laya_training_text_redacts_common_credentials():
    value = (
        "Authorization: Bearer bearer-secret "
        "https://user:url-secret@example.test/path "
        "sk-proj-abcdefghijklmnopqrstuvwxyz123456 "
        "-----BEGIN PRIVATE KEY-----\nprivate-secret\n-----END PRIVATE KEY-----"
    )

    redacted = _redact_laya_training_text(value)

    for secret in ("bearer-secret", "url-secret", "sk-proj-", "private-secret"):
        assert secret not in redacted
    assert redacted.count("[REDACTED]") == 4


def test_ordinary_context_shadow_capture_runs_without_legacy_flag_or_consent(tmp_path):
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"laya": {"runtime": {
        "enabled": False,
        "checkpoint_path": "pinned-local-checkpoint",
        "revision": "pinned-revision",
        "expected_sha256": {"model.safetensors": "a" * 64},
    }}}
    task = SimpleNamespace(context={"session_id": "session-1"})
    app.agent_tasks = object()
    app.laya_candidates = SimpleNamespace(
        _find_task=lambda *_args: task,
        _session_for_task=lambda value: value.context["session_id"],
    )
    app.evidence = SimpleNamespace(
        put_many=lambda *_args, **_kwargs: [{"evidence_id": "ev-indexed"}],
        get_many=lambda ids, *, root, **_kwargs: [
            {"success": True, "stale": False, "evidence_id": evidence_id, "root": root}
            for evidence_id in ids
        ],
        validate_source_provenance=lambda *_args, **_kwargs: True,
    )
    memory_record = SimpleNamespace(
        record_id="mem-task",
        scope=SimpleNamespace(value="task"),
        status=SimpleNamespace(value="active"),
        sensitivity="normal",
        evidence_ids=("ev-memory",),
        value="Verified task memory excerpt; password=memory-secret",
    )
    app.agent_memory = SimpleNamespace(
        find=lambda *, scope, **_kwargs: [memory_record] if scope.value == "task" else []
    )
    observed = {}

    class ImmediateExecutor:
        def submit(self, callback, *args, **kwargs):
            future = Future()
            try:
                future.set_result(callback(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)
            return future

    app._status_dependency_executor = ImmediateExecutor()
    app._laya_capture_lock = threading.Lock()
    app._laya_capture_queue = []
    app._laya_capture_draining = False
    app.logger = SimpleNamespace(warning=lambda *args: observed.setdefault("warnings", []).append(args))

    def evaluate(operation, *, root, baseline=None):
        observed["operation"] = operation
        return {"candidate": {"candidate_id": "candidate-1"}}

    app.evaluate_laya_context_source = evaluate
    request = SimpleNamespace(
        root=str(tmp_path), task_id="task-1", session_id="session-1",
        query="Find missing evidence. api_key=query-secret",
    )
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
            {
                "path": "indexed.py",
                "content_hash": "a" * 64,
                "text": "indexed source; token=source-secret",
            },
            {
                "path": "rag.py",
                "content_hash": "b" * 64,
                "semantic": True,
                "evidence_id": "ev-rag",
            },
        ],
    }

    queued = app.capture_laya_context_source_from_context(request, result)

    assert queued == {"status": "queued"}
    operation = observed["operation"]
    assert app._laya_capture_queue == []
    assert app._laya_capture_draining is False
    assert operation["action"] == "evaluate_context_source"
    assert operation["task_id"] == "task-1"
    assert operation["session_id"] == "session-1"
    assert operation["evidence"]["source_codes"] == ["indexed", "rag", "memory"]
    assert operation["evidence"]["source_record_ids"] == [None, None, "mem-task"]
    assert operation["evidence"]["evidence_ids"] == ["ev-indexed", "ev-rag", "ev-memory"]
    training_text = " ".join(operation["evidence"]["training_content"].values())
    assert "Verified task memory excerpt" in training_text
    assert "[REDACTED]" in training_text
    assert "query-secret" not in training_text
    assert "source-secret" not in training_text
    assert "memory-secret" not in training_text
    assert set(operation) == {"action", "task_id", "session_id", "evidence"}
    assert "per_example_consented" not in operation["evidence"]
    assert "consent_receipt_id" not in operation["evidence"]


def test_evaluate_context_source_keeps_memory_ids_out_of_model_input(tmp_path, monkeypatch):
    from local_ai_hub import project_config

    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {
        "laya": {"runtime": {"checkpoint_path": "pinned.gguf", "revision": "rev-1", "expected_sha256": {"pinned.gguf": "a" * 64}, "allow_cpu": False}},
        "server": {"state_dir": str(tmp_path / "state")},
    }
    task = SimpleNamespace(context={"session_id": "session-1"})
    app.agent_tasks = object()
    app.agent_memory = object()
    app.evidence = object()
    observed = {}
    app.laya_candidates = SimpleNamespace(
        _find_task=lambda *_args: task,
        _session_for_task=lambda value: value.context["session_id"],
        _candidate_input=lambda candidate: candidate,
        _validate_context_source_evidence=lambda candidate, **kwargs: observed.update(
            candidate=candidate, validation=kwargs,
        ),
        capture_runtime_outcome=lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        project_config,
        "resolve_project_context",
        lambda *_args: SimpleNamespace(coordination_id="repo-coordination-id"),
    )

    class Adapter:
        def evaluate_context_source(self, request, evidence, **_kwargs):
            observed["model_input"] = evidence.model_input()
            return SimpleNamespace(
                decision=DecisionResult(
                    request=request,
                    success=True,
                    status=DecisionStatus.SUCCESS,
                    suggestion=request.options[0],
                    reason_codes=(),
                ),
                runtime=None,
                capture_status="skipped",
            )

    app._get_laya_runtime_adapter = lambda *_args, **_kwargs: Adapter()
    app._record_laya_runtime_decision = lambda *_args: None
    app.laya_lifecycle = object()

    result = app.evaluate_laya_context_source(
        {
            "action": "evaluate_context_source",
            "task_id": "task-1",
            "session_id": "session-1",
            "evidence": {
                "gap_code": "unresolved_evidence_gap",
                "source_codes": ["indexed", "rag", "memory"],
                "freshness_codes": ["current", "current", "current"],
                "coverage_codes": ["partial", "partial", "partial"],
                "evidence_ids": ["ev-indexed", "ev-rag", "ev-memory"],
                "source_record_ids": [None, None, "mem-task"],
                "training_content": {"task_input": "Find missing evidence."},
            },
        },
        root=str(tmp_path),
    )

    assert result["success"] is True
    assert observed["candidate"]["source_record_ids"] == [None, None, "mem-task"]
    assert "source_record_ids" not in observed["candidate"]["state"]
    assert "source_record_ids" not in observed["model_input"]
    assert observed["validation"]["memory_store"] is app.agent_memory
    assert observed["validation"]["task_id"] == "task-1"
    assert observed["validation"]["session_id"] == "session-1"
    assert observed["validation"]["coordination_id"] == "repo-coordination-id"
