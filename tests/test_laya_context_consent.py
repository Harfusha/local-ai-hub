from __future__ import annotations

import threading
from concurrent.futures import Future
from types import SimpleNamespace

from local_ai_hub.app import LocalAIApp


def test_ordinary_context_shadow_operation_omits_per_example_consent(tmp_path):
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"laya": {"runtime": {"enabled": True}}}
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
        root=str(tmp_path), task_id="task-1", session_id="session-1"
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
            {"path": "indexed.py", "content_hash": "a" * 64, "text": "indexed"},
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
    assert len(operation["evidence"]["evidence_ids"]) == 2
    assert set(operation) == {"action", "task_id", "session_id", "evidence"}
    assert "per_example_consented" not in operation["evidence"]
    assert "consent_receipt_id" not in operation["evidence"]
