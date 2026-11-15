from __future__ import annotations

from types import SimpleNamespace
from local_ai_hub.agent_tasks import TaskStatus
from local_ai_hub.app import LocalAIApp


def test_observe_laya_watchdog_lifecycle(tmp_path):
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {
        "laya": {
            "enabled": True,
            "runtime": {
                "checkpoint_path": "fake/path",
                "revision": "rev1",
                "expected_sha256": {"file": "sha"},
            },
        }
    }
    app.logger = SimpleNamespace(debug=lambda *args: None)

    task_mock = SimpleNamespace(
        task_id="task-watch-1",
        status=TaskStatus.ACTIVE,
        checkpoint=SimpleNamespace(
            evidence_ids=["ev-watch-1"],
            state_data={"_agent_task_scope": {"version": 2, "repo_root": str(tmp_path)}},
        ),
        scope={"version": 2, "repo_root": str(tmp_path)},
        context=SimpleNamespace(session_id="sess-watch-1"),
    )

    app.agent_tasks = SimpleNamespace(
        list_tasks=lambda status, limit: SimpleNamespace(tasks=[task_mock])
    )

    queued = []
    app.queue_laya_decision_observation = lambda op, root, baseline: (
        queued.append((op, root, baseline)) or {"status": "queued"}
    )

    app._observe_laya_watchdog_lifecycle()

    assert len(queued) == 1
    op, root, baseline = queued[0]
    assert op["decision"]["category"] == "watchdog"
    assert op["task_id"] == "task-watch-1"
    assert baseline["method"] == "agent_os_task_lifecycle"
    assert baseline["suggestion"] == "recommend_continue"
    assert baseline["evidence_id"] == "ev-watch-1"

    # Second call within cooldown should not queue again
    app._observe_laya_watchdog_lifecycle()
    assert len(queued) == 1
