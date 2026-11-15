from __future__ import annotations

import pytest
from types import SimpleNamespace

from local_ai_hub.laya_candidates import LayaCandidateStore
from local_ai_hub.services import LocalAIServices


def test_adhoc_task_find_and_session_resolution(tmp_path):
    store = LayaCandidateStore(tmp_path)
    fake_task_store = SimpleNamespace(list_tasks=lambda limit=5000: [])

    # Non-adhoc missing task still raises ValueError
    with pytest.raises(ValueError, match="outside the authorized repository scope"):
        store._find_task(fake_task_store, str(tmp_path), "task-missing")

    # Ad-hoc task resolves successfully
    adhoc_task = store._find_task(fake_task_store, str(tmp_path), "adhoc_sess-123")
    assert adhoc_task.task_id == "adhoc_sess-123"
    assert store._session_for_task(adhoc_task) == "sess-123"


def test_queue_shadow_observation_supports_adhoc_session_fallback():
    service = LocalAIServices.__new__(LocalAIServices)
    observed = []
    service.laya_decision_observer = lambda operation, root, baseline: (
        observed.append((operation, root, baseline)) or {"status": "queued"}
    )

    # Missing task_id, but session_id present -> adhoc_session-1
    queued = service._queue_laya_shadow_observation(
        {
            "session_id": "session-1",
            "evidence_ids": ["ev-1"],
        },
        root="C:/repo",
        category="model_route",
        options=["fast", "smart"],
        state={"task_type": "code", "complexity": "fast"},
        training_content={"task_input": "Fix parser."},
        baseline={
            "method": "model_router_classify",
            "suggestion": "fast",
            "evidence_id": "ev-1",
        },
    )

    assert queued is True
    assert len(observed) == 1
    operation, root, baseline = observed[0]
    assert operation["task_id"] == "adhoc_session-1"


def test_capture_context_source_adhoc_fallback(tmp_path):
    from local_ai_hub.app import LocalAIApp

    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {
        "laya": {
            "runtime": {
                "checkpoint_path": "fake/path",
                "revision": "rev1",
                "expected_sha256": {"file": "sha"},
            }
        }
    }
    app.agent_tasks = SimpleNamespace(list_tasks=lambda limit=5000: [])
    app.laya_candidates = LayaCandidateStore(tmp_path)

    request = SimpleNamespace(task_id="adhoc_sess-xyz", session_id="sess-xyz", root=str(tmp_path))
    # Passing incomplete result (not dict with success=True) will return context_unavailable
    res1 = app._capture_laya_context_source_from_context(request, {"success": False})
    assert res1 == {"status": "skipped", "reason": "context_unavailable"}

    # Passing valid dict with success=True without retrieval will reach retrieval_provenance_unavailable
    # which proves it passed task_id and task_scope check!
    res2 = app._capture_laya_context_source_from_context(request, {"success": True})
    assert res2 == {"status": "skipped", "reason": "retrieval_provenance_unavailable"}
