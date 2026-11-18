from __future__ import annotations

import pytest
from types import SimpleNamespace

from local_ai_hub.laya_candidates import LayaCandidateStore
from local_ai_hub.services import LocalAIServices


def test_adhoc_task_find_and_session_resolution(tmp_path):
    store = LayaCandidateStore(tmp_path)
    fake_task_store = SimpleNamespace(get=lambda task_id: None)

    # Non-adhoc missing task still raises ValueError
    with pytest.raises(ValueError, match="outside the authorized repository scope"):
        store._find_task(fake_task_store, str(tmp_path), "task-missing")

    # Ad-hoc task resolves successfully
    adhoc_task = store._find_task(fake_task_store, str(tmp_path), "adhoc_sess-123")
    assert adhoc_task.task_id == "adhoc_sess-123"
    assert store._session_for_task(adhoc_task) == "sess-123"


def test_task_find_uses_indexed_lookup_and_verifies_repository_scope(tmp_path):
    store = LayaCandidateStore(tmp_path)
    task = SimpleNamespace(
        task_id="task-1",
        is_stale=False,
        checkpoint=SimpleNamespace(state_data={
            "_agent_task_scope": {"version": 2, "repo_root": str(tmp_path)},
        }),
    )
    lookups = []

    def get(task_id):
        lookups.append(task_id)
        return task

    task_store = SimpleNamespace(get=get, list_tasks=lambda **_: pytest.fail("must not scan task list"))

    assert store._find_task(task_store, str(tmp_path), "task-1") is task
    assert lookups == ["task-1"]

    other_root = tmp_path / "other"
    other_root.mkdir()
    with pytest.raises(ValueError, match="outside the authorized repository scope"):
        store._find_task(task_store, str(other_root), "task-1")

    task.is_stale = True
    with pytest.raises(ValueError, match="outside the authorized repository scope"):
        store._find_task(task_store, str(tmp_path), "task-1")


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
    app.agent_tasks = SimpleNamespace(get=lambda task_id: None)
    app.laya_candidates = LayaCandidateStore(tmp_path)

    request = SimpleNamespace(task_id="adhoc_sess-xyz", session_id="sess-xyz", root=str(tmp_path))
    # Passing incomplete result (not dict with success=True) will return context_unavailable
    res1 = app._capture_laya_context_source_from_context(request, {"success": False})
    assert res1 == {"status": "skipped", "reason": "context_unavailable"}

    # Passing valid dict with success=True without retrieval will reach retrieval_provenance_unavailable
    # which proves it passed task_id and task_scope check!
    res2 = app._capture_laya_context_source_from_context(request, {"success": True})
    assert res2 == {"status": "skipped", "reason": "retrieval_provenance_unavailable"}


def test_laya_disabled_skips_automatic_capture_queues(tmp_path):
    from local_ai_hub.app import LocalAIApp

    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {
        "laya": {
            "enabled": False,
            "runtime": {
                "checkpoint_path": "fake/path",
                "revision": "rev1",
                "expected_sha256": {"file": "sha"},
            },
        }
    }
    app._record_laya_capture_observation = lambda *_args, **_kwargs: None

    assert app.queue_laya_completion_observation(
        {"task_id": "task-1", "session_id": "session-1", "outcome": "complete"},
        str(tmp_path),
    ) == {"status": "skipped", "reason": "laya_disabled"}
    assert app.queue_laya_decision_observation(
        {"action": "evaluate_decision", "task_id": "task-1", "decision": {}},
        str(tmp_path),
        {},
    ) == {"status": "skipped", "reason": "laya_disabled"}


def test_laya_disabled_skips_context_source_capture(tmp_path):
    from local_ai_hub.app import LocalAIApp

    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"laya": {"enabled": False}}
    request = SimpleNamespace(task_id="task-1", session_id="session-1", root=str(tmp_path))

    assert app._capture_laya_context_source_from_context(
        request, {"success": True}
    ) == {"status": "skipped", "reason": "laya_disabled"}


def test_laya_disabled_rejects_direct_shadow_inference(tmp_path):
    from local_ai_hub.app import LocalAIApp

    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"laya": {"enabled": False}}

    with pytest.raises(RuntimeError, match="Laya inference is disabled"):
        app.evaluate_laya_context_source({}, root=str(tmp_path))
    with pytest.raises(RuntimeError, match="Laya inference is disabled"):
        app.evaluate_laya_decision({}, root=str(tmp_path))
