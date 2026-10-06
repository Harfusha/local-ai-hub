from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest

from local_ai_hub.agent_blackboard import BlackboardStore
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.swarm import SwarmCoordinator, SwarmState


def test_swarm_lifecycle_success(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_state.sqlite3"
    agent_state = AgentStateStore(db_path)
    blackboard = BlackboardStore(db_path, state_store=agent_state)
    leases = ScopeLeaseStore(tmp_path)
    verifications = VerificationStore(agent_state)
    coordinator = SwarmCoordinator(db_path, leases=leases, blackboard=blackboard, verifications=verifications)

    # 1. Dispatch
    res = coordinator.dispatch(
        goal="Refactor auth token verification",
        target_paths=["src/auth.py"],
        test_command="pytest tests/test_auth.py",
        author="lead_agent",
        root=str(tmp_path),
    )
    assert res["success"] is True
    swarm_id = res["swarm_id"]
    assert res["state"] == SwarmState.CODING.value
    # Leases should be claimed for coder
    active_leases = leases.list(str(tmp_path))
    assert any("src/auth.py" in str(l.get("path")) for l in active_leases)

    # 2. Coder steps
    step1 = coordinator.step(
        swarm_id=swarm_id,
        role="Coder",
        action="submit_patch",
        payload={"patch": "diff --git a/src/auth.py..."},
    )
    assert step1["success"] is True
    assert step1["state"] == SwarmState.TESTING.value

    # Check blackboard updated
    sec_res = blackboard.get(f"swarm:{swarm_id}", "code")
    assert sec_res["success"] is True
    assert "patch" in sec_res["section"]["content"]

    # 3. Tester steps
    step2 = coordinator.step(
        swarm_id=swarm_id,
        role="Tester",
        action="report_test_results",
        payload={"passed": True, "output": "1 passed in 0.05s"},
    )
    assert step2["success"] is True
    assert step2["state"] == SwarmState.REVIEWING.value

    # 4. Reviewer steps
    step3 = coordinator.step(
        swarm_id=swarm_id,
        role="Reviewer",
        action="approve",
        payload={"review": "Code looks solid and safe.", "score": 0.95},
    )
    assert step3["success"] is True
    assert step3["state"] == SwarmState.COMPLETED.value
    assert "receipt_id" in step3

    # Leases should be released on completion
    active_leases_post = leases.list(str(tmp_path))
    assert not any("src/auth.py" in str(l.get("path")) for l in active_leases_post)

    # Final status
    status = coordinator.get_status(swarm_id)
    assert status["success"] is True
    assert status["state"] == SwarmState.COMPLETED.value
    assert len(status["history"]) == 4


def test_swarm_lifecycle_test_failure_triggers_rejection(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_state.sqlite3"
    agent_state = AgentStateStore(db_path)
    blackboard = BlackboardStore(db_path, state_store=agent_state)
    leases = ScopeLeaseStore(tmp_path)
    verifications = VerificationStore(agent_state)
    coordinator = SwarmCoordinator(db_path, leases=leases, blackboard=blackboard, verifications=verifications)

    res = coordinator.dispatch(
        goal="Fix payment webhook",
        target_paths=["src/payments.py"],
        test_command="pytest tests/test_payments.py",
        author="lead_agent",
        root=str(tmp_path),
    )
    swarm_id = res["swarm_id"]

    coordinator.step(
        swarm_id=swarm_id,
        role="Coder",
        action="submit_patch",
        payload={"patch": "broken patch"},
    )

    # Tester reports failure
    fail_step = coordinator.step(
        swarm_id=swarm_id,
        role="Tester",
        action="report_test_results",
        payload={"passed": False, "error": "AssertionError on line 42"},
    )
    assert fail_step["success"] is True
    assert fail_step["state"] == SwarmState.FAILED.value

    # Leases released on failure
    active = leases.list(str(tmp_path))
    assert not any("src/payments.py" in str(l.get("path")) for l in active)


@pytest.mark.parametrize(
    ("stage", "role", "action", "payload", "board_section"),
    [
        ("code", "Coder", "submit_patch", {"patch": "candidate"}, "code"),
        (
            "test",
            "Tester",
            "report_test_results",
            {"passed": True, "output": "candidate"},
            "test",
        ),
        ("review", "Reviewer", "approve", {"review": "candidate"}, "review"),
    ],
)
def test_swarm_step_uses_blackboard_cas_with_one_concurrent_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    role: str,
    action: str,
    payload: dict[str, object],
    board_section: str,
) -> None:
    db_path = tmp_path / "agent_state.sqlite3"
    agent_state = AgentStateStore(db_path)
    blackboard = BlackboardStore(db_path, state_store=agent_state)
    coordinator = SwarmCoordinator(
        db_path,
        blackboard=blackboard,
        verifications=VerificationStore(agent_state),
        state_store=agent_state,
    )
    dispatched = coordinator.dispatch("concurrent board CAS", root=str(tmp_path))
    swarm_id = dispatched["swarm_id"]

    if stage in {"test", "review"}:
        code_step = coordinator.step(
            swarm_id, "Coder", "submit_patch", {"patch": "seed code section"}
        )
        assert code_step["success"] is True
    if stage == "review":
        test_step = coordinator.step(
            swarm_id,
            "Tester",
            "report_test_results",
            {"passed": True, "output": "seed test section"},
        )
        assert test_step["success"] is True

    board_versions: list[int | None] = []
    board_versions_lock = threading.Lock()
    original_update = blackboard.update

    def record_board_cas(*args, **kwargs):
        with board_versions_lock:
            board_versions.append(kwargs.get("expected_version"))
        return original_update(*args, **kwargs)

    monkeypatch.setattr(blackboard, "update", record_board_cas)
    expected_version = coordinator.get_status(swarm_id)["version"]
    barrier = threading.Barrier(3)

    def step(value: str) -> dict[str, object]:
        barrier.wait(timeout=2)
        candidate = {**payload, "candidate": value}
        return coordinator.step(
            swarm_id,
            role,
            action,
            candidate,
            expected_version=expected_version,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(step, "first")
        second = pool.submit(step, "second")
        barrier.wait(timeout=2)
        results = [first.result(timeout=5), second.result(timeout=5)]

    assert sum(result["success"] is True for result in results) == 1
    assert sum(result.get("version_conflict") is True for result in results) == 1
    assert board_versions == [0]
    section = blackboard.get(f"swarm:{swarm_id}", board_section)["section"]
    assert section["version"] == 1
    board_events = agent_state.events(f"blackboard:swarm:{swarm_id}:{board_section}")
    assert sum(event.kind == "blackboard.updated" for event in board_events) == 1


@pytest.mark.parametrize("operation", ["step", "cancel"])
def test_swarm_idempotent_replay_rejects_changed_expected_version(
    tmp_path: Path,
    operation: str,
) -> None:
    db_path = tmp_path / "agent_state.sqlite3"
    agent_state = AgentStateStore(db_path)
    coordinator = SwarmCoordinator(db_path, state_store=agent_state)
    dispatched = coordinator.dispatch(
        "expected version is part of operation",
        root=str(tmp_path),
    )
    swarm_id = dispatched["swarm_id"]
    initial_version = int(dispatched["version"])

    if operation == "step":
        def invoke(expected_version: int) -> dict[str, object]:
            return coordinator.step(
                swarm_id,
                "Coder",
                "submit_patch",
                {"patch": "candidate"},
                expected_version=expected_version,
                idempotency_key="same-operation",
            )
    else:
        def invoke(expected_version: int) -> dict[str, object]:
            return coordinator.cancel(
                swarm_id,
                "cancel candidate",
                expected_version=expected_version,
                idempotency_key="same-operation",
            )

    initial = invoke(initial_version)
    exact_replay = invoke(initial_version)
    changed_version_replay = invoke(initial_version + 1)

    assert initial["success"] is True
    assert exact_replay["success"] is True
    assert exact_replay["duplicate"] is True
    assert changed_version_replay["success"] is False
    assert changed_version_replay["idempotency_conflict"] is True


@pytest.mark.parametrize("operation", ["step", "cancel"])
def test_legacy_swarm_replay_allows_unversioned_retry_only(
    tmp_path: Path,
    operation: str,
) -> None:
    db_path = tmp_path / "agent_state.sqlite3"
    agent_state = AgentStateStore(db_path)
    coordinator = SwarmCoordinator(db_path, state_store=agent_state)
    dispatched = coordinator.dispatch("legacy replay contract", root=str(tmp_path))
    swarm_id = dispatched["swarm_id"]

    if operation == "step":
        def invoke(expected_version: int | None) -> dict[str, object]:
            return coordinator.step(
                swarm_id,
                "Coder",
                "submit_patch",
                {"patch": "legacy candidate"},
                expected_version=expected_version,
                idempotency_key="legacy-operation",
            )
    else:
        def invoke(expected_version: int | None) -> dict[str, object]:
            return coordinator.cancel(
                swarm_id,
                "legacy cancel",
                expected_version=expected_version,
                idempotency_key="legacy-operation",
            )

    initial = invoke(None)
    assert initial["success"] is True
    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT payload FROM agent_events WHERE stream_id = ? AND idempotency_key = ?",
            (f"swarm:{swarm_id}", "legacy-operation"),
        ).fetchone()
        assert row is not None
        legacy_payload = json.loads(str(row[0]))
        legacy_payload.pop("expected_version")
        con.execute(
            "UPDATE agent_events SET payload = ? WHERE stream_id = ? AND idempotency_key = ?",
            (
                json.dumps(legacy_payload, separators=(",", ":")),
                f"swarm:{swarm_id}",
                "legacy-operation",
            ),
        )
        con.commit()
    finally:
        con.close()

    exact_retry = invoke(None)
    versioned_retry = invoke(0)

    assert exact_retry["success"] is True
    assert exact_retry["duplicate"] is True
    assert versioned_retry["success"] is False
    assert versioned_retry["idempotency_conflict"] is True
