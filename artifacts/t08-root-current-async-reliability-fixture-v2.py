from __future__ import annotations

import json
from typing import Any

import pytest

from local_ai_hub.async_jobs import AsyncJobManager


class _ArtifactStore:
    def __init__(
        self,
        *,
        fail_put: bool = False,
        artifact_id: str = "async-result-artifact",
        fail_get: bool = False,
    ) -> None:
        self.fail_put = fail_put
        self.artifact_id = artifact_id
        self.fail_get = fail_get
        self.items: dict[tuple[str, str], str] = {}

    def put(self, _body: str, _tenant: str, _kind: str) -> str:
        if self.fail_put:
            raise OSError("artifact store unavailable")
        if self.artifact_id:
            self.items[(_tenant, self.artifact_id)] = _body
        return self.artifact_id

    def get(self, artifact_id: str, *, offset: int = 0, max_chars: int = 6000, tenant: str | None = None) -> dict[str, Any]:
        if self.fail_get or (tenant, artifact_id) not in self.items:
            return {"success": False, "error": "artifact not found or expired"}
        return {"success": True, "artifact_id": artifact_id, "offset": offset, "max_chars": max_chars}


@pytest.fixture
def manager_factory(tmp_path: Any, monkeypatch):
    managers: list[AsyncJobManager] = []
    default_artifacts = _ArtifactStore()

    def create(executor, *, artifacts: _ArtifactStore | None = None):
        manager = AsyncJobManager(
            {
                "server": {"state_dir": str(tmp_path)},
                "async_jobs": {"max_attempts": 3, "result_ttl_seconds": 600},
            },
            scheduler=object(),
            artifacts=artifacts if artifacts is not None else default_artifacts,
            executor=executor,
        )
        monkeypatch.setattr(
            manager,
            "_operational_mode_snapshot",
            lambda: {
                "mode": "active",
                "revision": 0,
                "degraded": False,
                "snapshot": None,
                "gate_error": None,
            },
        )
        managers.append(manager)
        return manager

    yield create
    for manager in managers:
        manager.close()


def _cancel_delayed_dispatch(manager: AsyncJobManager, job_id: str) -> None:
    timer = manager._delayed_dispatch.pop(job_id, None)
    if timer is not None:
        timer.cancel()


def test_same_request_id_after_restart_reuses_completed_job(manager_factory) -> None:
    executions: list[tuple[str, str]] = []

    def execute(action: str, payload: dict[str, Any], tenant: str) -> dict[str, Any]:
        executions.append((action, tenant))
        return {"success": True, "value": "committed-result"}

    first_manager = manager_factory(execute)
    payload = {"request_id": "t13-stable-request-001", "input": "mutating operation"}
    first = first_manager.submit("tenant-a", "delegate", payload, dispatch_delay_seconds=30)
    _cancel_delayed_dispatch(first_manager, first["job_id"])
    first_manager._execute(first["job_id"])
    first_manager.close()

    restarted_manager = manager_factory(execute)
    replay = restarted_manager.submit("tenant-a", "delegate", payload, dispatch_delay_seconds=30)
    _cancel_delayed_dispatch(restarted_manager, replay["job_id"])

    assert replay["job_id"] == first["job_id"]
    assert replay["state"] == "done"
    assert restarted_manager.result("tenant-a", first["job_id"])["result"]["value"] == "committed-result"
    assert executions == [("delegate", "tenant-a")]


def test_same_request_id_with_different_payload_is_a_conflict(manager_factory) -> None:
    executions: list[str] = []
    manager = manager_factory(
        lambda action, _payload, _tenant: executions.append(action) or {"success": True}
    )
    first = manager.submit(
        "tenant-a",
        "batch",
        {"request_id": "t13-stable-request-002", "task": "first payload"},
        dispatch_delay_seconds=30,
    )
    _cancel_delayed_dispatch(manager, first["job_id"])

    conflict = manager.submit(
        "tenant-a",
        "batch",
        {"request_id": "t13-stable-request-002", "task": "different payload"},
        dispatch_delay_seconds=30,
    )

    assert conflict["success"] is False
    assert conflict["state"] == "conflict"
    assert conflict["job_id"] == first["job_id"]
    assert manager.stats()["submitted"] == 1
    assert executions == []


def test_restart_retries_running_job_with_same_request_id(manager_factory, monkeypatch) -> None:
    observed_request_ids: list[str] = []

    def execute(_action: str, payload: dict[str, Any], _tenant: str) -> dict[str, Any]:
        observed_request_ids.append(str(payload["request_id"]))
        return {"success": True, "value": "committed-result"}

    first_manager = manager_factory(execute)
    request_id = "t13-stable-request-003"
    submitted = first_manager.submit(
        "tenant-a", "batch", {"request_id": request_id, "input": "mutating operation"}, dispatch_delay_seconds=30
    )
    _cancel_delayed_dispatch(first_manager, submitted["job_id"])
    con = first_manager._connect()
    try:
        con.execute(
            "UPDATE async_jobs SET state='running',attempts=1,cancel_requested=0 WHERE job_id=?",
            (submitted["job_id"],),
        )
        con.commit()
    finally:
        con.close()
    first_manager._shutdown.set()

    restarted_manager = manager_factory(execute)
    dispatched: list[str] = []
    monkeypatch.setattr(restarted_manager, "_dispatch", lambda job_id: dispatched.append(job_id))
    assert restarted_manager.recover() == 1
    assert restarted_manager.status("tenant-a", submitted["job_id"])["state"] == "queued"
    assert dispatched == [submitted["job_id"]]

    restarted_manager._execute(submitted["job_id"])

    assert observed_request_ids == [request_id]
    assert restarted_manager.result("tenant-a", submitted["job_id"])["result"]["value"] == "committed-result"


@pytest.mark.parametrize(
    ("request_id", "expected_state"),
    [(None, "outcome_unknown"), ("t13-stable-request-004", "queued")],
)
def test_retryable_executor_failure_requeues_only_with_request_id(manager_factory, request_id, expected_state) -> None:
    executed_payloads: list[dict[str, Any]] = []

    def execute(_action: str, payload: dict[str, Any], _tenant: str) -> dict[str, Any]:
        executed_payloads.append(payload)
        return {
            "success": False,
            "error": "connection lost after possible commit",
            "retryable": True,
        }

    manager = manager_factory(execute)
    payload = {"task": "mutating operation"}
    payload["_async_request_id_supplied"] = True
    if request_id is not None:
        payload["request_id"] = request_id
    submitted = manager.submit("tenant-a", "batch", payload, dispatch_delay_seconds=30)
    _cancel_delayed_dispatch(manager, submitted["job_id"])
    stored = manager._row("tenant-a", submitted["job_id"])
    assert stored is not None
    stored_payload = json.loads(str(stored["payload_json"]))
    assert stored_payload["request_id"]
    assert stored_payload["_async_request_id_supplied"] is (request_id is not None)

    manager._execute(submitted["job_id"])

    status = manager.status("tenant-a", submitted["job_id"])
    assert status["state"] == expected_state
    assert status["retryable"] is (expected_state == "queued")
    assert status["terminal"] is (expected_state == "outcome_unknown")
    assert len(executed_payloads) == 1
    assert "_async_request_id_supplied" not in executed_payloads[0]


def test_reason_retry_without_caller_request_id_is_safe(manager_factory) -> None:
    manager = manager_factory(
        lambda _action, _payload, _tenant: {"success": False, "retryable": True, "error": "transient"}
    )
    submitted = manager.submit("tenant-a", "reason", {"task": "read-only"}, dispatch_delay_seconds=30)
    _cancel_delayed_dispatch(manager, submitted["job_id"])

    result = manager._execute(submitted["job_id"])

    assert result["retryable"] is True
    assert manager.status("tenant-a", submitted["job_id"])["state"] == "queued"
    assert manager.status("tenant-a", submitted["job_id"])["attempts"] == 1

def test_worker_exception_retry_limit_counts_started_attempts_once(manager_factory) -> None:
    manager = manager_factory(lambda _action, _payload, _tenant: {"success": True})
    submitted = manager.submit(
        "tenant-a",
        "batch",
        {"request_id": "t13-attempt-count-001", "tasks": [{"task": "bounded work"}]},
        dispatch_delay_seconds=30,
    )
    _cancel_delayed_dispatch(manager, submitted["job_id"])

    for attempt in (1, 2, 3):
        con = manager._connect()
        try:
            con.execute(
                "UPDATE async_jobs SET state='running',attempts=?,cancel_requested=0 WHERE job_id=?",
                (attempt, submitted["job_id"]),
            )
            con.commit()
        finally:
            con.close()

        manager._release_for_retry(submitted["job_id"], f"worker interrupted at attempt {attempt}")
        status = manager.status("tenant-a", submitted["job_id"])
        assert status["state"] == ("queued" if attempt < 3 else "outcome_unknown")
        assert int(manager._row("tenant-a", submitted["job_id"])["attempts"]) == attempt


def test_worker_retry_after_shutdown_does_not_reopen_state_db(manager_factory, monkeypatch) -> None:
    manager = manager_factory(lambda _action, _payload, _tenant: {"success": True})
    submitted = manager.submit(
        "tenant-a", "batch", {"request_id": "t13-shutdown-retry-001"}, dispatch_delay_seconds=30
    )
    _cancel_delayed_dispatch(manager, submitted["job_id"])
    con = manager._connect()
    try:
        con.execute(
            "UPDATE async_jobs SET state='running',attempts=1,cancel_requested=0 WHERE job_id=?",
            (submitted["job_id"],),
        )
        con.commit()
    finally:
        con.close()
    manager.close()
    monkeypatch.setattr(manager, "_connect", lambda: pytest.fail("closed manager reopened its state database"))
    manager._release_for_retry(submitted["job_id"], "late worker exception")


@pytest.mark.parametrize("recovery_path", ["restart", "expired_lease"])
def test_restart_does_not_replay_running_job_without_request_id(manager_factory, monkeypatch, recovery_path) -> None:
    executions: list[str] = []

    def execute(action: str, _payload: dict[str, Any], _tenant: str) -> dict[str, Any]:
        executions.append(action)
        return {"success": True}

    first_manager = manager_factory(execute)
    submitted = first_manager.submit(
        "tenant-a", "batch", {"operations": [{"kind": "mutating"}]}, dispatch_delay_seconds=30
    )
    _cancel_delayed_dispatch(first_manager, submitted["job_id"])
    con = first_manager._connect()
    try:
        con.execute(
            "UPDATE async_jobs SET state='running',attempts=1,cancel_requested=0 WHERE job_id=?",
            (submitted["job_id"],),
        )
        con.commit()
    finally:
        con.close()

    restarted_manager = manager_factory(execute)
    dispatched: list[str] = []
    monkeypatch.setattr(restarted_manager, "_dispatch", lambda job_id: dispatched.append(job_id))
    if recovery_path == "restart":
        restarted_manager.recover()
    else:
        restarted_manager.tick()

    status = restarted_manager.status("tenant-a", submitted["job_id"])
    assert status["state"] == "outcome_unknown"
    assert status["terminal"] is True
    assert status["retryable"] is False
    assert dispatched == []
    assert executions == []


@pytest.mark.parametrize("artifact_failure", ["raises", "empty_id", "unreadable"])
def test_done_result_without_artifact_is_not_reported_as_success(manager_factory, artifact_failure) -> None:
    manager = manager_factory(
        lambda _action, _payload, _tenant: {"success": True, "value": "computed"},
        artifacts=_ArtifactStore(
            fail_put=artifact_failure == "raises",
            artifact_id="" if artifact_failure == "empty_id" else "async-result-artifact",
            fail_get=artifact_failure == "unreadable",
        ),
    )
    submitted = manager.submit("tenant-a", "review", {"input": "small"}, dispatch_delay_seconds=30)
    _cancel_delayed_dispatch(manager, submitted["job_id"])
    manager._execute(submitted["job_id"])

    status = manager.status("tenant-a", submitted["job_id"])
    result = manager.result("tenant-a", submitted["job_id"])
    assert status["state"] == "outcome_unknown"
    assert status["terminal"] is True
    assert status["retryable"] is False
    assert result["success"] is False
    assert result["state"] == "outcome_unknown"
    assert result["outcome_unknown"] is True

@pytest.mark.parametrize(
    ("attempts", "expected_state", "expected_recovered"),
    [(0, "queued", 1), (1, "outcome_unknown", 0)],
)
def test_recovery_distinguishes_unstarted_from_interrupted_reason_without_request_id(
    manager_factory, monkeypatch, attempts, expected_state, expected_recovered
) -> None:
    execute = lambda _action, _payload, _tenant: {"success": True}
    first_manager = manager_factory(execute)
    submitted = first_manager.submit(
        "tenant-a", "reason", {"task": "restart boundary"}, dispatch_delay_seconds=30
    )
    _cancel_delayed_dispatch(first_manager, submitted["job_id"])
    con = first_manager._connect()
    try:
        con.execute(
            "UPDATE async_jobs SET state='running',attempts=?,cancel_requested=0 WHERE job_id=?",
            (attempts, submitted["job_id"]),
        )
        con.commit()
    finally:
        con.close()
    first_manager._shutdown.set()

    restarted = manager_factory(execute)
    dispatched = []
    monkeypatch.setattr(restarted, "_dispatch", dispatched.append)
    assert restarted.recover() == expected_recovered
    assert restarted.status("tenant-a", submitted["job_id"])["state"] == expected_state
    assert dispatched == ([submitted["job_id"]] if expected_recovered else [])
