from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.agent_context import (
    CompiledContext,
    ContextCompiler,
    ContextElement,
    ContextRequest,
)
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore


def test_context_knapsack_pins_goal_and_packs_by_value_density(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    task_store = TaskStore(state_store)
    verif_store = VerificationStore(state_store, task_store=task_store)
    mem_store = MemoryStore(state_store)

    # 1. Create task with goal
    task_store.create(
        GoalContract(goal="Build Mars Rover navigation module", acceptance_criteria=("lidar_ok", "imu_ok")),
        ScopeContext(task_id="rover-1"),
        task_id="rover-1",
    )

    # 2. Add large low-density memory record
    # ~ 100 chars -> ~25 tokens. prio=70, conf=0.5 -> score = 35/25 = 1.4
    mem_store.record(
        MemoryRecord.create(
            key="long_history",
            value="X" * 100,
            kind=MemoryKind.FACT,
            scope="task",
            confidence=0.5,
        )
    )

    # 3. Add small high-density memory record
    # ~ 12 chars -> ~3 tokens. prio=70, conf=1.0 -> score = 70/3 = 23.33
    mem_store.record(
        MemoryRecord.create(
            key="rover_ip",
            value="192.168.1.10",
            kind=MemoryKind.FACT,
            scope="task",
            confidence=1.0,
        )
    )

    # 4. Add verification receipt
    verif_store.record(
        VerificationReceipt.create(
            task_id="rover-1",
            criterion="lidar_ok",
            passed=True,
            details={"samples": 100},
        )
    )

    comp = ContextCompiler(
        state_store=state_store,
        task_store=task_store,
        verification_store=verif_store,
        memory_store=mem_store,
    )

    # Compile with tight budget that can fit goal and small high-density items, but NOT the large memory
    # Goal takes ~18 tokens. Small memory takes ~7 tokens. Receipt takes ~16 tokens.
    # Total for those ~ 41 tokens. Large memory takes ~27 tokens.
    # Budget = 45.
    ctx = comp.compile(ContextRequest(task_id="rover-1", token_budget=45))

    element_ids = [el.element_id for el in ctx.elements]
    assert "goal_rover-1" in element_ids, "Mandatory task goal must be pinned"
    assert any(el.source_kind == "verification_receipt" for el in ctx.elements)
    assert any("rover_ip" in el.content for el in ctx.elements), "Small high-density memory should be packed"
    assert not any("long_history" in el.content for el in ctx.elements), "Large low-density memory should be skipped"
    assert ctx.truncated is True
    assert ctx.estimated_tokens <= 45
    assert ctx.value_density > 0.0
    assert 0.0 < ctx.packed_ratio <= 1.0

    d = ctx.to_dict()
    assert "value_density" in d
    assert "packed_ratio" in d
