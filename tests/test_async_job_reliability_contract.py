from __future__ import annotations

import json
import threading
import time
from contextlib import closing
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
        self.items: dict[str, str] = {}

    def put(self, _body: str, *, kind: str) -> str:
        if self.fail_put:
            raise OSError("artifact store unavailable")
        if self.artifact_id:
            self.items[self.artifact_id] = _body
        return self.artifact_id

    def get(self, artifact_id: str, *, offset: int = 0, max_chars: int = 6000) -> dict[str, Any]:
        if self.fail_get or artifact_id not in self.items:
            return {"success": False, "error": "artifact not found or expired"}
        return {"success": True, "artifact_id": artifact_id, "text": self.items[artifact_id][offset:offset + max_chars], "offset": offset, "max_chars": max_chars}


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

    def execute(action: str, payload: dict[str, Any]) -> dict[str, Any]:
        executions.append((action, str(payload.get("task_id", ""))))
        return {"success": True, "value": "committed-result"}

    first_manager = manager_factory(execute)
    payload = {"request_id": "t13-stable-request-001", "input": "mutating operation"}
    first = first_manager.submit("delegate", payload, dispatch_delay_seconds=30)
    _cancel_delayed_dispatch(first_manager, first["job_id"])
    first_manager._execute(first["job_id"])
    first_manager.close()

    restarted_manager = manager_factory(execute)
    replay = restarted_manager.submit("delegate", payload, dispatch_delay_seconds=30)
    _cancel_delayed_dispatch(restarted_manager, replay["job_id"])

    assert replay["job_id"] == first["job_id"]
    assert replay["state"] == "done"
    assert restarted_manager.result(first["job_id"])["result"]["value"] == "committed-result"
    assert executions == [("delegate", "")]


def test_same_request_id_with_different_payload_is_a_conflict(manager_factory) -> None:
    executions: list[str] = []
    manager = manager_factory(
        lambda action, _payload: executions.append(action) or {"success": True}
    )
    first = manager.submit(
        "batch",
        {"request_id": "t13-stable-request-002", "task": "first payload"},
        dispatch_delay_seconds=30,
    )
    _cancel_delayed_dispatch(manager, first["job_id"])

    conflict = manager.submit(
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

    def execute(_action: str, payload: dict[str, Any]) -> dict[str, Any]:
        observed_request_ids.append(str(payload["request_id"]))
        return {"success": True, "value": "committed-result"}

    first_manager = manager_factory(execute)
    request_id = "t13-stable-request-003"
    submitted = first_manager.submit(
        "batch", {"request_id": request_id, "input": "mutating operation"}, dispatch_delay_seconds=30
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
    assert restarted_manager.status(submitted["job_id"])["state"] == "queued"
    assert dispatched == [submitted["job_id"]]

    restarted_manager._execute(submitted["job_id"])

    assert observed_request_ids == [request_id]
    assert restarted_manager.result(submitted["job_id"])["result"]["value"] == "committed-result"


@pytest.mark.parametrize(
    ("request_id", "expected_state"),
    [(None, "outcome_unknown"), ("t13-stable-request-004", "queued")],
)
def test_retryable_executor_failure_requeues_only_with_request_id(manager_factory, request_id, expected_state) -> None:
    executed_payloads: list[dict[str, Any]] = []

    def execute(_action: str, payload: dict[str, Any]) -> dict[str, Any]:
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
    submitted = manager.submit("batch", payload, dispatch_delay_seconds=30)
    _cancel_delayed_dispatch(manager, submitted["job_id"])
    stored = manager._row(submitted["job_id"])
    assert stored is not None
    stored_payload = json.loads(str(stored["payload_json"]))
    assert stored_payload["request_id"]
    assert stored_payload["_async_request_id_supplied"] is (request_id is not None)

    manager._execute(submitted["job_id"])

    status = manager.status(submitted["job_id"])
    assert status["state"] == expected_state
    assert status["retryable"] is (expected_state == "queued")
    assert status["terminal"] is (expected_state == "outcome_unknown")
    assert len(executed_payloads) == 1
    assert "_async_request_id_supplied" not in executed_payloads[0]
    if request_id is None:
        assert "request_id" not in executed_payloads[0]
    else:
        assert executed_payloads[0]["request_id"] == request_id


def test_reason_retry_without_caller_request_id_is_safe(manager_factory) -> None:
    manager = manager_factory(
        lambda _action, _payload: {"success": False, "retryable": True, "error": "transient"}
    )
    submitted = manager.submit("reason", {"task": "read-only"}, dispatch_delay_seconds=30)
    _cancel_delayed_dispatch(manager, submitted["job_id"])

    result = manager._execute(submitted["job_id"])

    assert result["retryable"] is True
    assert manager.status(submitted["job_id"])["state"] == "queued"
    assert manager.status(submitted["job_id"])["attempts"] == 1

def test_worker_exception_retry_limit_counts_started_attempts_once(manager_factory) -> None:
    manager = manager_factory(lambda _action, _payload: {"success": True})
    submitted = manager.submit(
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
        status = manager.status(submitted["job_id"])
        assert status["state"] == ("queued" if attempt < 3 else "outcome_unknown")
        assert int(manager._row(submitted["job_id"])["attempts"]) == attempt


def test_worker_retry_after_shutdown_does_not_reopen_state_db(manager_factory, monkeypatch) -> None:
    manager = manager_factory(lambda _action, _payload: {"success": True})
    submitted = manager.submit(
        "batch", {"request_id": "t13-shutdown-retry-001"}, dispatch_delay_seconds=30
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

    def execute(action: str, _payload: dict[str, Any]) -> dict[str, Any]:
        executions.append(action)
        return {"success": True}

    first_manager = manager_factory(execute)
    submitted = first_manager.submit(
        "batch", {"operations": [{"kind": "mutating"}]}, dispatch_delay_seconds=30
    )
    _cancel_delayed_dispatch(first_manager, submitted["job_id"])
    con = first_manager._connect()
    try:
        con.execute(
            "UPDATE async_jobs SET state='running',attempts=1,cancel_requested=0,lease_until=0 WHERE job_id=?",
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

    status = restarted_manager.status(submitted["job_id"])
    assert status["state"] == "outcome_unknown"
    assert status["terminal"] is True
    assert status["retryable"] is False
    assert dispatched == []
    assert executions == []


def test_recovery_does_not_replay_legacy_running_job_without_caller_provenance(manager_factory, monkeypatch) -> None:
    request_id = "legacy-caller-request-async-001"
    received_payloads: list[dict[str, Any]] = []
    manager = manager_factory(
        lambda _action, payload: received_payloads.append(payload) or {"success": True}
    )
    job_id = "legacy-running-async-job"
    now = time.time()
    with closing(manager._connect()) as con, con:
        con.execute(
            "INSERT INTO async_jobs(job_id,action,request_hash,payload_json,state,lease_until,attempts,cancel_requested,created_at,updated_at,expires_at) "
            "VALUES(?,?,?,?,'running',?,?,?,?,?,?)",
            (
                job_id,
                "batch",
                "legacy-request-hash",
                json.dumps({"request_id": request_id, "input": "legacy"}),
                now - 1,
                1,
                0,
                now - 1,
                now - 1,
                now + 600,
            ),
        )
        con.commit()

    dispatches: list[str] = []
    monkeypatch.setattr(manager, "_dispatch", dispatches.append)

    recovered = manager.recover()

    assert recovered == 0
    assert dispatches == []
    assert received_payloads == []
    assert manager.status(job_id)["state"] == "outcome_unknown"


@pytest.mark.parametrize("artifact_failure", ["raises", "empty_id", "unreadable"])
def test_done_result_without_artifact_is_not_reported_as_success(manager_factory, artifact_failure) -> None:
    manager = manager_factory(
        lambda _action, _payload: {"success": True, "value": "computed"},
        artifacts=_ArtifactStore(
            fail_put=artifact_failure == "raises",
            artifact_id="" if artifact_failure == "empty_id" else "async-result-artifact",
            fail_get=artifact_failure == "unreadable",
        ),
    )
    submitted = manager.submit("review", {"input": "small"}, dispatch_delay_seconds=30)
    _cancel_delayed_dispatch(manager, submitted["job_id"])
    manager._execute(submitted["job_id"])

    status = manager.status(submitted["job_id"])
    result = manager.result(submitted["job_id"])
    assert status["state"] == "outcome_unknown"
    assert status["terminal"] is True
    assert status["retryable"] is False
    assert result["success"] is False
    assert result["state"] == "outcome_unknown"
    assert result["outcome_unknown"] is True


def test_tick_respects_persisted_dispatch_not_before_before_timer_registration(
    manager_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = manager_factory(lambda _action, _payload: {"success": True})
    event_created = threading.Event()
    release_submit = threading.Event()
    paused_job_ids: list[str] = []
    submitted: list[dict[str, Any]] = []
    errors: list[Exception] = []
    dispatches: list[str] = []
    dispatch_ready = threading.Event()
    original_event = manager._event
    first_event = True

    def hold_after_commit(job_id: str):
        nonlocal first_event
        event = original_event(job_id)
        if first_event:
            first_event = False
            paused_job_ids.append(job_id)
            event_created.set()
            if not release_submit.wait(timeout=5):
                raise TimeoutError("submit did not resume after deterministic race window")
        return event

    monkeypatch.setattr(manager, "_event", hold_after_commit)

    def record_dispatch(job_id: str) -> None:
        dispatches.append(job_id)
        dispatch_ready.set()

    monkeypatch.setattr(manager, "_dispatch", record_dispatch)

    def submit_delayed_job() -> None:
        try:
            submitted.append(
                manager.submit("review", {"input": "race"}, dispatch_delay_seconds=1)
            )
        except Exception as exc:
            errors.append(exc)

    submitter = threading.Thread(target=submit_delayed_job, daemon=True)
    submitter.start()
    try:
        assert event_created.wait(timeout=2)
        job_id = paused_job_ids[0]

        manager.tick()

        assert dispatches == []
        with closing(manager._connect()) as con:
            dispatch_not_before = float(
                con.execute("SELECT dispatch_not_before FROM async_jobs WHERE job_id=?", (job_id,)).fetchone()[0]
            )
        assert dispatch_not_before > time.time()
    finally:
        release_submit.set()
        submitter.join(timeout=2)

    assert not submitter.is_alive()
    assert errors == []
    assert submitted[0]["job_id"] == paused_job_ids[0]
    assert dispatch_ready.wait(timeout=2)
    assert dispatches == [paused_job_ids[0]]
    _cancel_delayed_dispatch(manager, paused_job_ids[0])


def test_restart_recovery_defers_queued_job_until_persisted_dispatch_not_before(
    manager_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_manager = manager_factory(lambda _action, _payload: {"success": True})
    submitted = first_manager.submit(
        "review", {"input": "restart-delay"}, dispatch_delay_seconds=30
    )
    job_id = submitted["job_id"]
    _cancel_delayed_dispatch(first_manager, job_id)

    restarted_manager = manager_factory(lambda _action, _payload: {"success": True})
    dispatches: list[str] = []
    monkeypatch.setattr(restarted_manager, "_dispatch", dispatches.append)

    with closing(restarted_manager._connect()) as con:
        dispatch_not_before = float(
            con.execute("SELECT dispatch_not_before FROM async_jobs WHERE job_id=?", (job_id,)).fetchone()[0]
        )
    assert dispatch_not_before > time.time()

    recovered = restarted_manager.recover()

    with closing(restarted_manager._connect()) as con:
        row = con.execute(
            "SELECT state, dispatch_not_before FROM async_jobs WHERE job_id=?", (job_id,)
        ).fetchone()
    assert recovered == 0
    assert dispatches == []
    assert str(row[0]) == "queued"
    assert float(row[1]) > time.time()

    with closing(restarted_manager._connect()) as con:
        con.execute(
            "UPDATE async_jobs SET dispatch_not_before=? WHERE job_id=?", (time.time() - 1, job_id)
        )
        con.commit()
    restarted_manager.tick()
    assert dispatches == [job_id]
@pytest.mark.parametrize(
    ("attempts", "expected_state", "expected_recovered"),
    [(0, "queued", 1), (1, "outcome_unknown", 0)],
)
def test_recovery_distinguishes_unstarted_from_interrupted_reason_without_request_id(
    manager_factory, monkeypatch, attempts, expected_state, expected_recovered
) -> None:
    execute = lambda _action, _payload: {"success": True}
    first_manager = manager_factory(execute)
    submitted = first_manager.submit(
        "reason", {"task": "restart boundary"}, dispatch_delay_seconds=30
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
    assert restarted.status(submitted["job_id"])["state"] == expected_state
    assert dispatched == ([submitted["job_id"]] if expected_recovered else [])


def test_submit_reports_sqlite_commit_for_new_and_replayed_acceptance(manager_factory) -> None:
    manager = manager_factory(lambda *_: {"success": True})
    payload = {"request_id": "durable-acceptance-001", "task": "persist before acknowledging"}

    first = manager.submit("reason", payload, dispatch_delay_seconds=30)
    _cancel_delayed_dispatch(manager, first["job_id"])
    replay = manager.submit("reason", payload, dispatch_delay_seconds=30)
    _cancel_delayed_dispatch(manager, replay["job_id"])

    assert first["success"] is True
    assert first["state"] == "queued"
    assert first["durability"] == "sqlite_committed"
    assert replay["job_id"] == first["job_id"]
    assert replay["durability"] == "sqlite_committed"
    assert manager.status(first["job_id"])["state"] == "queued"


def test_coalesced_submit_reports_sqlite_commit(manager_factory) -> None:
    manager = manager_factory(lambda *_: {"success": True})
    payload = {"task": "coalesce after durable insert"}

    first = manager.submit("reason", payload, dispatch_delay_seconds=30)
    _cancel_delayed_dispatch(manager, first["job_id"])
    coalesced = manager.submit("reason", payload, dispatch_delay_seconds=30)

    assert coalesced["success"] is True
    assert coalesced["coalesced"] is True
    assert coalesced["job_id"] == first["job_id"]
    assert coalesced["durability"] == "sqlite_committed"
