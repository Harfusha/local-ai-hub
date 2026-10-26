"""End-to-end acceptance test: isolated Git repository with two worktrees,
in-flight requirement clarification, contract revision reconciliation, session resumption,
authentic receipts, commits, integration, and recoverable archival.
"""

import subprocess
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_tasks import (
    GoalContract,
    ScopeContext,
    TaskCheckpoint,
    TaskStore,
)
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.repo_plan import RepoPlanWorkspace
from local_ai_hub.repo_plan.agent_bridge import (
    TaskBindingManager,
    reconcile_contract_revision,
    record_authentic_native_receipt,
    sync_checkpoint_to_plan,
)
from local_ai_hub.repo_plan.models import TaskWorkStatus


def run_git(cwd: Path, *args: str) -> str:
    """Helper to run bounded git commands in an isolated directory."""
    cmd = ["git"] + list(args)
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=10.0,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def isolated_git_repo(tmp_path: Path):
    """Create a fully isolated real Git repository with initial commit on master."""
    repo_dir = tmp_path / "main_repo"
    repo_dir.mkdir()

    run_git(repo_dir, "init", "-b", "master")
    run_git(repo_dir, "config", "user.name", "Test Committer")
    run_git(repo_dir, "config", "user.email", "committer@example.com")
    run_git(repo_dir, "config", "commit.gpgsign", "false")

    # Initial file
    (repo_dir / "README.md").write_text("# Project Root\n", encoding="utf-8")
    run_git(repo_dir, "add", "README.md")
    run_git(repo_dir, "commit", "-m", "Initial commit")

    # Setup state dir
    state_dir = tmp_path / "hub_state"
    state_dir.mkdir()

    return repo_dir, state_dir


def test_repo_plan_e2e_multi_worktree_workflow(isolated_git_repo):
    """Complete multi-worktree workflow matching Superpowers specification."""
    repo_dir, state_dir = isolated_git_repo

    # 1. Initialize project workspace on master
    ws_master = RepoPlanWorkspace(repo_dir)
    ws_master.init_workspace()

    # Create plan with two independent tasks
    spec_dir = repo_dir / "docs" / "superpowers" / "specs"
    spec_dir.mkdir(parents=True)
    spec_file = spec_dir / "parser.md"
    spec_file.write_text("# Parser Spec v1\nMust parse basic tokens.\n", encoding="utf-8")

    create_res = ws_master.create_plan(
        plan_id="plan_parser_suite",
        title="Parser Suite Project",
        description="Deliver robust token and syntax parser",
        tasks={
            "task_parser": {
                "title": "Implement core parser",
                "description": "Parse basic tokens",
                "acceptance_criteria": ["Parser passes unit tests"],
                "work_status": "planned",
                "deliveries": {
                    "delivery_master": {
                        "target_ref": "refs/heads/master",
                        "accountable_role": "integrator",
                        "disposition": "pending",
                        "reason": "Awaiting branch merge",
                        "results": [],
                    }
                },
            },
            "task_validator": {
                "title": "Implement AST validator",
                "description": "Validate parser output AST",
                "acceptance_criteria": ["Validator passes unit tests"],
                "work_status": "planned",
            },
        },
    )
    assert create_res["success"] is True

    # Commit workspace, spec, and plan into master
    run_git(repo_dir, "add", ".local-ai-hub", "docs")
    run_git(repo_dir, "commit", "-m", "Add project plan and spec")
    master_head = run_git(repo_dir, "rev-parse", "HEAD")
    assert master_head

    # 2. Spawn two linked worktrees: worktree-a and worktree-b
    wt_a_dir = repo_dir.parent / "worktree_a"
    wt_b_dir = repo_dir.parent / "worktree_b"

    run_git(repo_dir, "worktree", "add", "-b", "feat/parser", str(wt_a_dir), "master")
    run_git(repo_dir, "worktree", "add", "-b", "feat/validator", str(wt_b_dir), "master")

    # 3. Worktree A: Bind task_parser to an Agent OS task
    db_path = state_dir / "agent_tasks.db"
    state_store = AgentStateStore(db_path)
    task_store = TaskStore(state_store)
    artifact_store = ArtifactStore(state_dir / "artifacts")
    verif_store = VerificationStore(
        state_store,
        task_store=task_store,
        artifact_store=artifact_store,
    )

    contract_a = GoalContract(
        goal="Implement core parser",
        acceptance_criteria=["Parser passes unit tests"],
    )
    context_a = ScopeContext(
        repository_id=str(wt_a_dir),
        task_id="agent_task_a1",
    )
    created_task_a = task_store.create(
        contract=contract_a,
        context=context_a,
        actor="agent_a",
        repo_root=str(wt_a_dir),
        task_id="agent_task_a1",
    )
    assert created_task_a.task_id == "agent_task_a1"

    bm_a = TaskBindingManager(wt_a_dir)
    binding_a = bm_a.bind_task(
        task_id="agent_task_a1",
        plan_id="plan_parser_suite",
        plan_task_id="task_parser",
        plan_rel_path=".local-ai-hub/plans/plan_parser_suite.plan.json",
        contract_revision=1,
    )

    # Checkpoint progress on task A -> in_progress
    cp_a = TaskCheckpoint(
        phase="implementing",
        next_action="Write token scanner",
        affected_paths=["src/scanner.py"],
        evidence_ids=[],
        blockers=[],
        state_data={"memory_audit": {"not_used_reason": "none", "used_ids": []}},
    )
    task_store.checkpoint("agent_task_a1", cp_a, actor="agent_a")

    # Verify task in worktree A plan file is in_progress
    ws_a = RepoPlanWorkspace(wt_a_dir)
    plan_a_data = ws_a.get_plan("plan_parser_suite")["plan"]
    assert plan_a_data["tasks"]["task_parser"]["work_status"] == "in_progress"

    # 4. In-flight requirement clarification occurs on Worktree A!
    # Operator changes requirement: Parser must support hex literals as well
    updated_spec_text = "# Parser Spec v2\nMust parse basic tokens and hex numbers (0x...).\n"
    spec_a_file = wt_a_dir / "docs" / "superpowers" / "specs" / "parser.md"
    spec_a_file.write_text(updated_spec_text, encoding="utf-8")

    new_criteria = [
        "Parser passes unit tests",
        "Parser supports hex literal syntax (0x...)",
    ]
    rec_res, new_rev = reconcile_contract_revision(
        storage=ws_a.storage,
        binding=binding_a,
        new_acceptance_criteria=new_criteria,
        reason="Operator clarification: Support hex numbers",
        task_store=task_store,
        spec_rel_path="docs/superpowers/specs/parser.md",
        spec_content=updated_spec_text,
        owner="agent_a",
    )
    assert rec_res["success"] is True
    assert new_rev == 2

    # Verify plan task updated criteria & clarification
    plan_a_revised = ws_a.get_plan("plan_parser_suite")["plan"]["tasks"]["task_parser"]
    assert len(plan_a_revised["acceptance_criteria"]) == 2
    assert len(plan_a_revised["clarifications"]) == 1
    assert "hex numbers" in plan_a_revised["clarifications"][0]["summary"]

    # 5. Simulate session restart/resumption in Worktree A
    # Re-initialize managers from disk; assert state is fully preserved
    bm_a_resumed = TaskBindingManager(wt_a_dir)
    binding_resumed = bm_a_resumed.get_binding("agent_task_a1")
    assert binding_resumed is not None
    assert binding_resumed.contract_revision == 2

    # 6. Implement code in Worktree A and run authentic validation
    src_dir_a = wt_a_dir / "src"
    src_dir_a.mkdir(parents=True)
    parser_code = (
        "def parse_token(t):\n"
        "    if t.startswith('0x'):\n"
        "        return int(t, 16)\n"
        "    return int(t)\n"
    )
    (src_dir_a / "parser.py").write_text(parser_code, encoding="utf-8")

    test_dir_a = wt_a_dir / "tests"
    test_dir_a.mkdir(parents=True)
    test_code = (
        "from src.parser import parse_token\n"
        "def test_parse():\n"
        "    assert parse_token('42') == 42\n"
        "    assert parse_token('0x2A') == 42\n"
    )
    (test_dir_a / "test_parser.py").write_text(test_code, encoding="utf-8")

    # Run native pytest in worktree A
    cmd = ["python", "-m", "pytest", "tests/test_parser.py"]
    proc = subprocess.run(
        cmd,
        cwd=str(wt_a_dir),
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    assert proc.returncode == 0

    # Process output cannot be promoted into broker-authenticated evidence.
    with pytest.raises(ValueError, match="trusted command_id"):
        record_authentic_native_receipt(
            task_store=task_store,
            verification_store=verif_store,
            artifact_store=artifact_store,
            task_id="agent_task_a1",
            criterion="Parser passes unit tests",
            command="python -m pytest tests/test_parser.py",
            root=wt_a_dir,
            owner="agent_a",
        )

    # 7. Keep the task in progress until CommandBroker provides a receipt.
    cp_a_done = TaskCheckpoint(
        phase="verification",
        next_action="Import a receipt from CommandBroker",
        affected_paths=["src/parser.py", "tests/test_parser.py"],
        evidence_ids=[],
        blockers=[],
        state_data={"memory_audit": {"not_used_reason": "none", "used_ids": []}},
    )
    task_store.checkpoint("agent_task_a1", cp_a_done, actor="agent_a")
    sync_checkpoint_to_plan(
        ws_a.storage,
        binding_a,
        agent_status="in_progress",
        phase="verification",
            next_action="Import authentic CommandBroker receipt",
    )

    plan_a_final = ws_a.get_plan("plan_parser_suite")["plan"]["tasks"]["task_parser"]
    assert plan_a_final["work_status"] == TaskWorkStatus.IN_PROGRESS.value

    # Commit changes on branch feat/parser
    run_git(wt_a_dir, "add", "src", "tests", "docs", ".local-ai-hub")
    run_git(wt_a_dir, "commit", "-m", "Implement parser with hex support and update plan")
    feat_a_head = run_git(wt_a_dir, "rev-parse", "HEAD")

    # 8. Integrator merges feat/parser into master
    run_git(repo_dir, "merge", "--no-ff", feat_a_head, "-m", "Merge feat/parser into master")

    # A merge alone does not prove verified delivery.
    plan_master_after = ws_master.get_plan("plan_parser_suite")["plan"]

    # Board retains the parser task in progress and the validator task planned.
    board_master = ws_master.get_board_view()
    assert board_master["columns"]["done"] == []
    assert board_master["columns"]["in_progress"][0]["task_id"] == "task_parser"
    assert len(board_master["columns"]["planned"]) == 1
    assert board_master["columns"]["planned"][0]["task_id"] == "task_validator"

    # 9. Clean up worktree A safely and confirm master state is intact
    run_git(repo_dir, "worktree", "remove", str(wt_a_dir))
    run_git(repo_dir, "worktree", "remove", str(wt_b_dir))

    # Master plan still exists and is fully intact
    verified_plan = ws_master.get_plan("plan_parser_suite")["plan"]
    assert verified_plan["tasks"]["task_parser"]["work_status"] == "in_progress"
    assert board_master["columns"]["in_progress"][0]["verified"] is False
