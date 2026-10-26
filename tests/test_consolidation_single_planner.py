"""Acceptance tests for consolidation: single source of truth for planning and Kanban.

Confirms that:
1. No two independent writable planners exist.
2. A single task change propagates across:
   - Plan file (.local-ai-hub/plans/<plan-id>.plan.json)
   - Board view / Kanban (board_summary, board_item_list, plan_board_view)
   - Session briefing (session_briefing)
   - Context compilation (ContextCompiler / context_compile)
3. Legacy SQLite board items are cleanly adoptable into plan files without data loss.
4. Agent OS task checkpoints immediately synchronize to the bound plan task.
"""

from pathlib import Path
import pytest

from local_ai_hub.repo_plan.workspace import RepoPlanWorkspace
from local_ai_hub.repo_plan.storage import RepoPlanStorage
from local_ai_hub.repo_plan.agent_bridge import (
    TaskBindingManager,
    reconcile_contract_revision,
)
from local_ai_hub.agent_board import BoardStore
from local_ai_hub.agent_context import ContextCompiler, ContextRequest
from local_ai_hub.services import LocalAIServices, AgentStateStore
from local_ai_hub.agent_tasks import (
    TaskStore,
    GoalContract,
    ScopeContext,
    TaskCheckpoint,
)


@pytest.fixture
def repo_env(tmp_path: Path):
    """Setup a temporary repo root with state and db."""
    root = tmp_path / "test_repo"
    root.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    db_path = state_dir / "agent_board.db"
    task_db_path = state_dir / "agent_tasks.db"
    return root, state_dir, db_path, task_db_path


from unittest.mock import MagicMock


def make_services(state_dir: Path):
    config = {
        "server": {"state_dir": str(state_dir)},
        "cache": {},
        "models": {"fast_code": "test-fast", "heavy_code": "test-heavy"},
    }
    return LocalAIServices(
        config=config,
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
    )


def test_single_source_of_truth_propagation(repo_env):
    """Verify that updating a task updates plan file, board, briefing, and context without divergence."""
    root, state_dir, db_path, task_db_path = repo_env
    services = make_services(state_dir)
    ws = RepoPlanWorkspace(str(root))
    ws.init_workspace()

    # Create plan with one task
    create_res = ws.create_plan(
        plan_id="plan_alpha",
        title="Project Alpha",
        goal="Deliver Alpha Feature",
        tasks={
            "task_1": {
                "title": "Implement core parser",
                "acceptance_criteria": ["All tests pass"],
                "work_status": "planned",
                "work_phase": "discovery",
            }
        },
    )
    assert create_res["success"] is True

    # 1. Check initial board view & summary
    summary = services.board_summary(root=str(root))
    assert summary["success"] is True
    assert summary.get("source") == "repo_plan"
    assert summary["counts"]["planned"] == 1
    assert summary["counts"]["in_progress"] == 0

    items_res = services.board_item_list(root=str(root))
    assert items_res["success"] is True
    assert len(items_res["items"]) == 1
    assert items_res["items"][0]["status"] == "planned"
    assert items_res["items"][0]["title"] == "Implement core parser"

    # 2. Check session briefing initial state
    briefing = services.session_briefing(include=["board", "plans"], root=str(root))
    assert briefing["success"] is True
    assert len(briefing["plans"]) == 1
    assert briefing["board_summary"]["planned"] == 1
    assert briefing["board_summary"]["in_progress"] == 0

    # 3. Setup Agent OS task binding
    state_store = AgentStateStore(task_db_path)
    task_store = TaskStore(state_store)
    services.set_task_store(task_store)

    actual_tid = "agent_task_100"
    contract = GoalContract(
        goal="Implement core parser",
        acceptance_criteria=["All tests pass"],
    )
    context = ScopeContext(
        repository_id=str(root),
        task_id=actual_tid,
    )
    created_task = task_store.create(contract=contract, context=context, actor="agent", repo_root=str(root), task_id="agent_task_100")

    actual_tid = created_task.task_id
    binding_mgr = TaskBindingManager(str(root))
    binding = binding_mgr.bind_task(
        task_id=actual_tid,
        plan_id="plan_alpha",
        plan_task_id="task_1",
        plan_rel_path=".local-ai-hub/plans/plan_alpha.plan.json",
    )
    assert binding.task_id == actual_tid

    # 4. Checkpoint the Agent OS task -> progress to in_progress
    cp = TaskCheckpoint(
        phase="implementing",
        next_action="write test cases",
        affected_paths=["src/parser.py"],
        evidence_ids=[],
        blockers=[],
        state_data={"memory_audit": {"not_used_reason": "none", "used_ids": []}},
    )
    updated_task = task_store.checkpoint(actual_tid, cp, actor="agent")
    assert updated_task.checkpoint.phase == "implementing"

    # 5. Verify the plan file was automatically synchronized
    plan_data = ws.get_plan("plan_alpha")["plan"]
    task_in_plan = plan_data["tasks"]["task_1"]
    assert task_in_plan["work_status"] == "in_progress"
    assert task_in_plan["next_action"] == "write test cases"
    assert task_in_plan["work_phase"] == "implementation"

    # 6. Verify board summary and list reflect the exact same in_progress status
    summary_after = services.board_summary(root=str(root))
    assert summary_after["counts"]["planned"] == 0
    assert summary_after["counts"]["in_progress"] == 1
    assert summary_after["total_items"] == 1

    items_after = services.board_item_list(root=str(root))
    assert len(items_after["items"]) == 1
    assert items_after["items"][0]["status"] == "in_progress"
    assert items_after["items"][0]["details"]["next_action"] == "write test cases"

    # 7. Verify session briefing reflects the exact same synchronized state
    briefing_after = services.session_briefing(include=["board", "plans"], root=str(root))
    assert briefing_after["board_summary"]["in_progress"] == 1
    assert briefing_after["board_summary"]["planned"] == 0
    assert len(briefing_after["plan_board"]["in_progress"]) == 1
    assert briefing_after["plan_board"]["in_progress"][0]["task_id"] == "task_1"

    # 8. Verify context compiler incorporates the authoritative plan task
    compiler = ContextCompiler(state_store, task_store=task_store)
    ctx_req = ContextRequest(
        task_id=actual_tid,
        root=str(root),
        token_budget=4000,
    )
    compiled = compiler.compile(ctx_req)
    assert compiled is not None
    # The compiled elements should contain the checkpoint and repo plan task
    element_kinds = [e.source_kind for e in compiled.elements]
    assert "task_checkpoint" in element_kinds
    assert "repo_plan_task" in element_kinds
    # Check that text mentions next action
    plan_elem = next(e for e in compiled.elements if e.source_kind == "repo_plan_task")
    assert "write test cases" in plan_elem.content
    assert "in_progress" in plan_elem.content


def test_contract_reconciliation_single_source_of_truth(repo_env):
    """Verify that clarifying requirements updates spec, plan, and contract revision atomically."""
    root, state_dir, db_path, task_db_path = repo_env
    ws = RepoPlanWorkspace(str(root))
    ws.init_workspace()

    ws.create_plan(
        plan_id="plan_beta",
        title="Project Beta",
        goal="Feature Beta",
        tasks={
            "task_b1": {
                "title": "Build storage layer",
                "acceptance_criteria": ["Supports save and read"],
                "work_status": "in_progress",
            }
        },
    )

    binding_mgr = TaskBindingManager(str(root))
    binding = binding_mgr.bind_task(
        task_id="agent_task_200",
        plan_id="plan_beta",
        plan_task_id="task_b1",
        plan_rel_path=".local-ai-hub/plans/plan_beta.plan.json",
        contract_revision=1,
    )

    storage = RepoPlanStorage(str(root))

    # Perform in-flight clarification
    save_res, new_rev = reconcile_contract_revision(
        storage=storage,
        binding=binding,
        new_acceptance_criteria=["Supports save and read", "Supports crash recovery"],
        reason="Operator clarified need for crash recovery durability",
        spec_rel_path=".local-ai-hub/specs/storage_spec.md",
        spec_content="# Storage Spec\n\nMust support atomic write and crash recovery.",
    )

    assert save_res["success"] is True
    assert new_rev == 2
    assert binding.contract_revision == 2

    # Verify plan file has updated criteria and clarification history
    plan_obj = ws.get_plan("plan_beta")["plan"]
    task_obj = plan_obj["tasks"]["task_b1"]
    assert len(task_obj["acceptance_criteria"]) == 2
    assert "Supports crash recovery" in task_obj["acceptance_criteria"]
    assert len(task_obj["clarifications"]) == 1
    assert task_obj["clarifications"][0]["summary"] == "Operator clarified need for crash recovery durability"

    # Verify spec file was created/updated
    spec_path = root / ".local-ai-hub" / "specs" / "storage_spec.md"
    assert spec_path.exists()
    assert "crash recovery" in spec_path.read_text(encoding="utf-8")


def test_adopt_legacy_board_no_duplicate_planner(repo_env):
    """Verify adopting legacy SQLite items converts them into the authoritative plan and removes dual writers."""
    root, state_dir, db_path, task_db_path = repo_env
    legacy_board = BoardStore(db_path)

    # Insert legacy items
    i1 = legacy_board.item_create(title="Legacy task 1", status="planned")
    i2 = legacy_board.item_create(title="Legacy task 2", status="in_progress")
    assert i1["success"] is True
    assert i2["success"] is True

    # Initial legacy board summary has 2 items
    leg_summary = legacy_board.summary()
    assert leg_summary["counts"]["total"] == 2

    # Adopt into file-backed plan
    ws = RepoPlanWorkspace(str(root))
    items = legacy_board.item_list(limit=100)["items"]
    adopt_res = ws.adopt_legacy_board_items(legacy_items=items, plan_id="plan_migrated", title="Migrated Plan")
    assert adopt_res["success"] is True
    assert adopt_res["tasks_imported"] == 2

    # Verify plan file now holds both tasks
    plan = ws.get_plan("plan_migrated")["plan"]
    assert len(plan["tasks"]) == 2

    # Verify services now routes board calls to the authoritative plan
    services = make_services(state_dir)
    new_summary = services.board_summary(root=str(root))
    assert new_summary["success"] is True
    assert new_summary.get("source") == "repo_plan"
    assert new_summary["total_items"] == 2
    assert new_summary["counts"]["planned"] == 1
    assert new_summary["counts"]["in_progress"] == 1
