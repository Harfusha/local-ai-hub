from __future__ import annotations

import sqlite3
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
    blackboard = BlackboardStore(db_path)
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
    blackboard = BlackboardStore(db_path)
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
