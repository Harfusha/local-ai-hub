from __future__ import annotations

import json
import threading
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
import sys
import threading
from types import ModuleType, SimpleNamespace
import pytest

from local_ai_hub import agent_tasks as agent_tasks_module
from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_tasks import (
    CompletionGateError,
    GoalContract,
    InvalidTransitionError,
    MAX_TASK_QUERY_SCAN_ROWS,
    TaskCheckpoint,
    TaskState,
    TaskStatus,
    TaskStore,
)
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
from local_ai_hub.sqlite_support import connect_sqlite
import local_ai_hub.agent_tasks as agent_tasks_module
from local_ai_hub import trace_context


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    return TaskStore(state_store)


def task_context() -> ScopeContext:
    return ScopeContext(repository_id="repo-1", branch="main", task_id="task-1")


def contract_with_criteria(*criteria: str) -> GoalContract:
    return GoalContract(
        goal="Implement feature",
        acceptance_criteria=tuple(criteria),
        scope=AgentScope.TASK,
    )


def make_trusted_repository(parent: Path) -> tuple[Path, str]:
    root = parent / "repo"
    root.mkdir()
    (root / ".local-ai.toml").write_text(
        '[commands.test]\nargv = ["python", "-B", "-c", "print(1)"]\n'
        '[verification_rules]\ntests = ["test"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T08 test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t08-test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "add", ".local-ai.toml"], cwd=root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "test project config"], cwd=root, check=True)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    return root, revision


def prepare_project_rule_completion(
    store: TaskStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_revision: bool = True,
) -> TaskState:
    repo_root, revision = make_trusted_repository(tmp_path)
    task = store.create(contract_with_criteria("tests"), task_context())
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    store.transition(task.task_id, TaskStatus.VERIFYING, reason="ready", actor="agent", idempotency_key="v")
    state_data = {
        "worktree": {"repo_root": str(repo_root)},
        "repo_root": str(repo_root),
    }
    if with_revision:
        state_data["repository_revision"] = revision
    store.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data=state_data),
        actor="agent",
        idempotency_key="project-root",
    )
    VerificationStore(store.state_store, task_store=store).record(
        VerificationReceipt.create(task.task_id, "tests", evidence_id="ev-tests")
    )
    project_config = ModuleType("local_ai_hub.project_config")
    project_config.resolve_project_context = lambda root, state_dir: SimpleNamespace(
        settings=SimpleNamespace(
            verification_rules={"tests": ("test",)}, commands={"test": "pytest"}
        )
    )
    monkeypatch.setitem(sys.modules, "local_ai_hub.project_config", project_config)
    return task

from local_ai_hub import trace_context

def test_goal_contract_requires_nonempty_goal():
    with pytest.raises(ValueError, match="requires goal"):
        GoalContract(goal=" ")


def test_legacy_empty_goal_is_loadable_with_explicit_fallback(store: TaskStore):
    task = store.create(contract_with_criteria("tests"), task_context(), task_id="legacy-goal")
    con = connect_sqlite(store.state_store.db_path, isolation_level=None)
    try:
        row = con.execute(
            "SELECT contract FROM agent_tasks_projection WHERE task_id=?",
            (task.task_id,),
        ).fetchone()
        data = json.loads(row[0])
        data["goal"] = ""
        con.execute(
            "UPDATE agent_tasks_projection SET contract=? WHERE task_id=?",
            (json.dumps(data), task.task_id),
        )
    finally:
        con.close()

    loaded = store.get(task.task_id)
    assert loaded is not None
    assert loaded.contract.goal == "Legacy task contract: legacy-goal"


def test_task_creation_and_retrieval(store: TaskStore):
    contract = contract_with_criteria("unit_tests")
    task = store.create(contract, task_context(), task_id="t-1")
    assert task.task_id == "t-1"
    assert task.status == TaskStatus.PLANNED
    fetched = store.get("t-1")
    assert fetched is not None
    assert fetched.task_id == "t-1"
    assert fetched.contract.goal == "Implement feature"




def test_transition_idempotency_reuse_by_different_actor_is_rejected(store: TaskStore):
    task = store.create(contract_with_criteria(), task_context())
    store.transition(
        task.task_id,
        TaskStatus.ACTIVE,
        reason="R",
        actor="agent-one",
        idempotency_key="shared-transition-key",
    )

    with pytest.raises(ValueError, match="^idempotency key was already used$"):
        store.transition(
            task.task_id,
            TaskStatus.VERIFYING,
            reason="start",
            actor="agent-two",
            idempotency_key="shared-transition-key",
        )

    persisted = store.get(task.task_id)
    assert persisted is not None and persisted.status is TaskStatus.ACTIVE
    assert len(store.state_store.events(f"task:{task.task_id}")) == 2


def test_same_status_transition_rejects_idempotency_key_owned_by_another_actor(store: TaskStore):
    task = store.create(contract_with_criteria(), task_context())
    active = store.transition(
        task.task_id,
        TaskStatus.ACTIVE,
        reason="R",
        actor="agent-one",
        idempotency_key="shared-transition-key",
    )
    with pytest.raises(ValueError, match="^idempotency key was already used$"):
        store.transition(
            task.task_id,
            TaskStatus.ACTIVE,
            reason="R",
            actor="agent-two",
            idempotency_key="shared-transition-key",
        )

    same_actor_retry = store.transition(
        task.task_id,
        TaskStatus.ACTIVE,
        reason="R",
        actor="agent-one",
        idempotency_key="shared-transition-key",
    )
    assert same_actor_retry == active

    with pytest.raises(ValueError, match="idempotency key was already used"):
        store.transition(
            task.task_id,
            TaskStatus.ACTIVE,
            reason="changed reason",
            actor="agent-one",
            idempotency_key="shared-transition-key",
        )


def test_task_query_bounds_rows_scanned(store: TaskStore):
    task = store.create(contract_with_criteria("tests"), task_context(), task_id="scan-seed")
    con = connect_sqlite(store.state_store.db_path)
    try:
        rows = [
            (
                f"scan-{index:05d}",
                TaskStatus.PLANNED.value,
                "",
                "",
                "{" if index == 10_000 else "{}",
                "{}",
                "{}",
                "{}",
                0.0,
                0.0,
                0.0 if index == 10_000 else float(index + 1),
            )
            for index in range(10_001)
        ]
        con.executemany(
            """
            INSERT INTO agent_tasks_projection (
                task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                heartbeat_expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        con.commit()
    finally:
        con.close()

    assert store.list_tasks(query="absent-query", limit=1) == []


def test_task_query_scan_window_is_bounded_before_stale_filter(store: TaskStore):
    store.create(contract_with_criteria("tests"), task_context(), task_id="stale-scan-seed")
    con = connect_sqlite(store.state_store.db_path)
    try:
        rows = [
            (
                f"stale-scan-{index:05d}",
                TaskStatus.PLANNED.value,
                "",
                "",
                "{}",
                "{}",
                "{}",
                "{}",
                1.0,
                0.0,
                float(MAX_TASK_QUERY_SCAN_ROWS - index),
            )
            for index in range(MAX_TASK_QUERY_SCAN_ROWS)
        ]
        rows.append((
            "fresh-scan-match",
            TaskStatus.PLANNED.value,
            "",
            "",
            '{"goal":"needle after bounded stale window"}',
            "{}",
            "{}",
            "{}",
            0.0,
            0.0,
            0.0,
        ))
        con.executemany(
            """
            INSERT INTO agent_tasks_projection (
                task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                heartbeat_expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        con.commit()
    finally:
        con.close()

    tasks = store.list_tasks(query="needle", limit=1)

    assert tasks == []
    assert tasks.query_truncated is True


def test_task_query_skips_stale_candidate_before_page_limit(store: TaskStore):
    stale = store.create(GoalContract(goal="page-needle stale"), task_context(), task_id="stale-page-match")
    fresh = store.create(GoalContract(goal="page-needle fresh"), task_context(), task_id="fresh-page-match")
    con = connect_sqlite(store.state_store.db_path)
    try:
        con.execute(
            "UPDATE agent_tasks_projection SET heartbeat_expires_at=?, updated_at=? WHERE task_id=?",
            (1.0, 2.0, stale.task_id),
        )
        con.execute(
            "UPDATE agent_tasks_projection SET heartbeat_expires_at=?, updated_at=? WHERE task_id=?",
            (0.0, 1.0, fresh.task_id),
        )
        con.commit()
    finally:
        con.close()

    tasks = store.list_tasks(query="page-needle", limit=1)

    assert [task.task_id for task in tasks] == ["fresh-page-match"]
    assert tasks.query_truncated is False


def test_completed_requires_all_criteria_to_have_fresh_receipts(store: TaskStore):
    task = store.create(contract_with_criteria("tests", "review"), task_context())
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    store.transition(task.task_id, TaskStatus.VERIFYING, reason="ready", actor="agent", idempotency_key="v")
    with pytest.raises(CompletionGateError):
        store.transition(task.task_id, TaskStatus.COMPLETED, reason="claimed", actor="agent", idempotency_key="c")


def test_completed_succeeds_when_verified(
    store: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo_root, revision = make_trusted_repository(tmp_path)
    task = store.create(contract_with_criteria("tests"), task_context())
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    store.transition(task.task_id, TaskStatus.VERIFYING, reason="ready", actor="agent", idempotency_key="v")
    store.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={
            "worktree": {"repo_root": str(repo_root)},
            "repo_root": str(repo_root),
            "repository_revision": revision,
        }),
        actor="agent",
        idempotency_key="project-root",
    )
    # Completion requires durable verification evidence, not projection-only receipt IDs.
    store.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={"repository_revision": "rev-1", "mutation_generation": 0}),
        actor="agent",
        idempotency_key="verify-revision",
    )
    artifact_store = ArtifactStore(store.state_store.db_path.parent / "artifacts")
    command_id = "cmd-tests"
    proof = {
        "kind": "work_command_verification",
        "passed": True,
        "task_id": task.task_id,
        "owner": task.owner,
        "criterion": "tests",
        "command_id": command_id,
        "exit_code": 0,
        "repository_revision": "rev-1",
        "mutation_generation": 0,
        "result": {"success": True, "exit_code": 0},
    }
    evidence_id = artifact_store.put_json(proof, task.owner, "command_verification")
    VerificationStore(
        store.state_store, task_store=store, artifact_store=artifact_store
    ).record(
        VerificationReceipt.create(
            task.task_id, "tests", evidence_id=evidence_id, command_id=command_id,
            owner=task.owner, repository_revision="rev-1", mutation_generation=0,
            evidence_type="test",
        )
    )

    project_config = ModuleType("local_ai_hub.project_config")
    project_config.resolve_project_context = lambda root, state_dir: SimpleNamespace(
        settings=SimpleNamespace(verification_rules={}, commands={})
    )
    monkeypatch.setitem(sys.modules, "local_ai_hub.project_config", project_config)

    class CurrentVerifierAdapter:
        def completion(
            self,
            task_id,
            *,
            current_revision,
            current_mutation_generation,
            verification_rules,
            configured_criteria,
        ):
            assert verification_rules == {}
            assert configured_criteria == ()
            return VerificationStore(store.state_store, task_store=store).completion(
                task_id, current_revision=current_revision
            )

    store.set_verification_store(CurrentVerifierAdapter())
    completed = store.transition(task.task_id, TaskStatus.COMPLETED, reason="all passed", actor="agent", idempotency_key="c")
    assert completed.status == TaskStatus.COMPLETED


def test_completed_forwards_project_rules_to_verification_completion(
    store: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo_root, revision = make_trusted_repository(tmp_path)
    task = store.create(
        contract_with_criteria("tests"),
        ScopeContext(repository_id=str(repo_root), branch="main", task_id="task-1"),
    )
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    store.transition(task.task_id, TaskStatus.VERIFYING, reason="ready", actor="agent", idempotency_key="v")
    store.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={
            "repository_revision": revision,
            "mutation_generation": 4,
        }),
        actor="agent",
        idempotency_key="project-root",
    )
    VerificationStore(store.state_store, task_store=store).record(
        VerificationReceipt.create(task.task_id, "tests", evidence_id="ev-tests")
    )

    resolved = {}

    def resolve_project_context(root, state_dir):
        resolved.update(root=root, state_dir=state_dir)
        return SimpleNamespace(
            settings=SimpleNamespace(
                verification_rules={"tests": ("test",)},
                commands={"test": "pytest"},
            )
        )

    project_config = ModuleType("local_ai_hub.project_config")
    project_config.resolve_project_context = resolve_project_context
    monkeypatch.setitem(sys.modules, "local_ai_hub.project_config", project_config)

    class RecordingVerifier:
        def __init__(self):
            self.calls = []

        def completion(
            self,
            task_id,
            *,
            current_revision,
            current_mutation_generation,
            verification_rules,
            configured_criteria,
        ):
            self.calls.append((
                task_id,
                current_revision,
                current_mutation_generation,
                verification_rules,
                configured_criteria,
            ))
            return SimpleNamespace(complete=True, unsatisfied_criteria=(), stale_criteria=())

    verifier = RecordingVerifier()
    store.set_verification_store(verifier)

    completed = store.transition(
        task.task_id, TaskStatus.COMPLETED, reason="verified", actor="agent", idempotency_key="c"
    )

    assert completed.status is TaskStatus.COMPLETED
    assert Path(resolved["root"]) == repo_root
    assert Path(resolved["state_dir"]) == store.state_store.db_path.parent
    assert verifier.calls == [(task.task_id, revision, 4, {"tests": ("test",)}, ("test",))]


def test_completed_skips_nonapplicable_project_rules_without_repository_revision(
    store: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo_root, _revision = make_trusted_repository(tmp_path)
    context = ScopeContext(repository_id=str(repo_root), branch="main", task_id="task-1")
    task = store.create(contract_with_criteria("tests"), context)
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    store.transition(task.task_id, TaskStatus.VERIFYING, reason="ready", actor="agent", idempotency_key="v")
    store.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={"mutation_generation": 4}),
        actor="agent",
        idempotency_key="project-rules-without-revision",
    )
    verifications = VerificationStore(store.state_store, task_store=store)
    verifications.record(VerificationReceipt.create(task.task_id, "tests", evidence_id="ev-tests"))

    project_config = ModuleType("local_ai_hub.project_config")
    project_config.resolve_project_context = lambda root, state_dir: SimpleNamespace(
        settings=SimpleNamespace(
            verification_rules={"lint": ("lint",)}, commands={"lint": "ruff"}
        )
    )
    monkeypatch.setitem(sys.modules, "local_ai_hub.project_config", project_config)

    calls = []

    class NonapplicableRuleVerifier:
        def completion(
            self,
            task_id,
            *,
            current_revision,
            current_mutation_generation,
            verification_rules,
            configured_criteria,
        ):
            calls.append((
                current_revision,
                current_mutation_generation,
                verification_rules,
                configured_criteria,
            ))
            return verifications.completion(task_id, current_revision=current_revision)

    store.set_verification_store(NonapplicableRuleVerifier())
    completed = store.transition(
        task.task_id, TaskStatus.COMPLETED, reason="verified", actor="agent", idempotency_key="c"
    )

    assert completed.status is TaskStatus.COMPLETED
    assert calls == [("", 4, {"lint": ("lint",)}, ("lint",))]


def test_completed_requires_repository_revision_for_active_project_rule(
    store: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    task = prepare_project_rule_completion(
        store, tmp_path, monkeypatch, with_revision=False
    )
    calls = []

    class ProjectRuleVerifier:
        def completion(
            self,
            task_id,
            *,
            current_revision,
            current_mutation_generation,
            verification_rules,
            configured_criteria,
        ):
            calls.append(task_id)
            return SimpleNamespace(complete=True, unsatisfied_criteria=(), stale_criteria=())

    store.set_verification_store(ProjectRuleVerifier())

    with pytest.raises(CompletionGateError, match="trusted repository_revision is unavailable"):
        store.transition(
            task.task_id,
            TaskStatus.COMPLETED,
            reason="verified",
            actor="agent",
            idempotency_key="c",
        )

    persisted = store.get(task.task_id)
    assert persisted is not None
    assert persisted.status is TaskStatus.VERIFYING
    assert calls == []


def test_completed_rejects_generic_kwargs_evaluator_for_project_rules(
    store: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    task = prepare_project_rule_completion(store, tmp_path, monkeypatch)

    class GenericKwargsVerifier:
        def completion(self, task_id, **kwargs):
            return SimpleNamespace(complete=True, unsatisfied_criteria=(), stale_criteria=())

    store.set_verification_store(GenericKwargsVerifier())

    with pytest.raises(CompletionGateError, match="does not support project rules"):
        store.transition(
            task.task_id, TaskStatus.COMPLETED, reason="verified", actor="agent", idempotency_key="c"
        )


@pytest.mark.parametrize("complete", ["false", 1])
def test_completed_rejects_non_boolean_verifier_result(
    store: TaskStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    complete: object,
):
    task = prepare_project_rule_completion(store, tmp_path, monkeypatch)

    class MalformedResultVerifier:
        def completion(
            self,
            task_id,
            *,
            current_revision,
            current_mutation_generation,
            verification_rules,
            configured_criteria,
        ):
            return {"complete": complete}

    store.set_verification_store(MalformedResultVerifier())

    with pytest.raises(CompletionGateError, match="rejected completion"):
        store.transition(
            task.task_id, TaskStatus.COMPLETED, reason="verified", actor="agent", idempotency_key="c"
        )


@pytest.mark.parametrize("failure_mode", ["rejected", "raises"])
def test_completion_verifier_failure_does_not_complete_task_or_add_receipt(
    store: TaskStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
):
    task = prepare_project_rule_completion(store, tmp_path, monkeypatch)
    before = store.get(task.task_id)

    class FailingVerifier:
        def completion(
            self,
            task_id,
            *,
            current_revision,
            current_mutation_generation,
            verification_rules,
            configured_criteria,
        ):
            if failure_mode == "raises":
                raise RuntimeError("verification command failed")
            return {"complete": False, "unsatisfied_criteria": ("tests",)}

    store.set_verification_store(FailingVerifier())
    expected_message = "evaluator failed" if failure_mode == "raises" else "rejected completion"

    with pytest.raises(CompletionGateError, match=expected_message):
        store.transition(
            task.task_id, TaskStatus.COMPLETED, reason="verified", actor="agent", idempotency_key="c"
        )

    after = store.get(task.task_id)
    assert after.status == TaskStatus.VERIFYING
    assert after.verification_receipts == before.verification_receipts
    assert all(
        event.payload.get("to_status") != TaskStatus.COMPLETED.value
        for event in store.state_store.events(f"task:{task.task_id}")
    )


def test_completed_fails_closed_when_project_config_cannot_resolve(
    store: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo_root, revision = make_trusted_repository(tmp_path)
    task = store.create(contract_with_criteria("tests"), task_context())
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    store.transition(task.task_id, TaskStatus.VERIFYING, reason="ready", actor="agent", idempotency_key="v")
    store.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={
            "worktree": {"repo_root": str(repo_root)},
            "repo_root": str(repo_root),
            "repository_revision": revision,
        }),
        actor="agent",
        idempotency_key="project-root",
    )
    VerificationStore(store.state_store, task_store=store).record(
        VerificationReceipt.create(task.task_id, "tests", evidence_id="ev-tests")
    )

    project_config = ModuleType("local_ai_hub.project_config")

    def fail_resolution(root, state_dir):
        raise RuntimeError("project config missing")

    project_config.resolve_project_context = fail_resolution
    monkeypatch.setitem(sys.modules, "local_ai_hub.project_config", project_config)

    with pytest.raises(CompletionGateError, match="project verification config"):
        store.transition(
            task.task_id, TaskStatus.COMPLETED, reason="verified", actor="agent", idempotency_key="c"
        )


def test_completed_uses_receipts_when_no_project_root_is_available(store: TaskStore):
    task = store.create(contract_with_criteria("tests"), task_context())
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    store.transition(task.task_id, TaskStatus.VERIFYING, reason="ready", actor="agent", idempotency_key="v")
    VerificationStore(store.state_store, task_store=store).record(
        VerificationReceipt.create(task.task_id, "tests", evidence_id="ev-tests")
    )

    completed = store.transition(
        task.task_id, TaskStatus.COMPLETED, reason="verified", actor="agent", idempotency_key="c"
    )

    assert completed.status is TaskStatus.COMPLETED


def test_completed_uses_task_context_repo_root_without_worktree_checkpoint(
    store: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo_root = tmp_path / "repository"
    repo_root.mkdir()
    context = ScopeContext(repository_id=str(repo_root), branch="main", task_id="task-context-root")
    task = store.create(contract_with_criteria("tests"), context)
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    store.transition(task.task_id, TaskStatus.VERIFYING, reason="ready", actor="agent", idempotency_key="v")
    store.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={"mutation_generation": 1}),
        actor="agent",
        idempotency_key="context-root-checkpoint",
    )
    artifact_store = ArtifactStore(store.state_store.db_path.parent / "artifacts")
    command_id = "cmd-context-tests"
    proof = {
        "kind": "work_command_verification", "passed": True,
        "task_id": task.task_id, "owner": task.owner, "criterion": "tests",
        "command_id": command_id, "exit_code": 0, "repository_revision": "rev-ctx",
        "mutation_generation": 1, "result": {"success": True, "exit_code": 0},
    }
    evidence_id = artifact_store.put_json(proof, task.owner, "command_verification")
    store.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={"repository_revision": "rev-ctx", "mutation_generation": 1}),
        actor="agent", idempotency_key="context-root-revision",
    )
    VerificationStore(store.state_store, task_store=store, artifact_store=artifact_store).record(
        VerificationReceipt.create(
            task.task_id, "tests", evidence_id=evidence_id, command_id=command_id,
            owner=task.owner, repository_revision="rev-ctx", mutation_generation=1,
            evidence_type="test",
        )
    )

    resolved = {}
    project_config = ModuleType("local_ai_hub.project_config")
    project_config.ProjectSettings = SimpleNamespace

    def resolve_project_context(root, state_dir):
        resolved["root"] = Path(root)
        return SimpleNamespace(
            config_digest="test-config-digest",
            settings=SimpleNamespace(verification_rules={}, commands={}),
        )

    project_config.resolve_project_context = resolve_project_context
    monkeypatch.setitem(sys.modules, "local_ai_hub.project_config", project_config)

    completed = store.transition(
        task.task_id, TaskStatus.COMPLETED, reason="verified", actor="agent", idempotency_key="c"
    )

    assert completed.status is TaskStatus.COMPLETED
    assert resolved["root"] == repo_root


def test_completed_forwards_project_rules_to_compatible_verifier(
    store: TaskStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo_root = tmp_path / "repository"
    repo_root.mkdir()
    task = store.create(
        contract_with_criteria("tests"),
        ScopeContext(repository_id=str(repo_root), branch="main", task_id="project-rules"),
    )
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    store.transition(task.task_id, TaskStatus.VERIFYING, reason="ready", actor="agent", idempotency_key="v")
    store.checkpoint(
        task.task_id,
        TaskCheckpoint(state_data={"repository_revision": "rev-1", "mutation_generation": 4}),
        actor="agent",
        idempotency_key="project-rules",
    )
    VerificationStore(store.state_store, task_store=store).record(
        VerificationReceipt.create(
            task.task_id, "tests", evidence_id="ev-tests", evidence_type="source_review"
        )
    )
    project_config = ModuleType("local_ai_hub.project_config")
    project_config.ProjectSettings = SimpleNamespace
    project_config.resolve_project_context = lambda root, state_dir: SimpleNamespace(
        config_digest="test-config-digest",
        settings=SimpleNamespace(
            verification_rules={"tests": ("test",)}, commands={"test": "pytest"}
        )
    )
    monkeypatch.setitem(sys.modules, "local_ai_hub.project_config", project_config)

    class RecordingVerifier:
        def __init__(self):
            self.calls = []

        def completion(
            self,
            task_id,
            *,
            current_revision,
            current_mutation_generation,
            verification_rules,
            configured_criteria,
            configured_commands,
            project_config_digest,
            configured_environment_sha256,
            project_root,
        ):
            self.calls.append(
                (task_id, current_revision, current_mutation_generation, verification_rules, configured_criteria)
            )
            return SimpleNamespace(complete=True, unsatisfied_criteria=(), stale_criteria=())

    verifier = RecordingVerifier()
    store.verification_store = verifier
    completed = store.transition(
        task.task_id, TaskStatus.COMPLETED, reason="verified", actor="agent", idempotency_key="c"
    )

    assert completed.status is TaskStatus.COMPLETED
    assert verifier.calls == [(task.task_id, "rev-1", 4, {"tests": ("test",)}, ("test",))]


def test_expired_active_task_becomes_abandoned_with_checkpoint(store: TaskStore, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    tenant_token = trace_context.set_context(tenant="tenant-a")
    try:
        task = store.create(contract_with_criteria("tests"), task_context(), task_id="t-heartbeat", repo_root=str(repo_root))
    finally:
        trace_context.reset_context(tenant_token)
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    store.checkpoint(task.task_id, TaskCheckpoint(phase="coding", next_action="run tests"), actor="agent", idempotency_key="chk-1")
    active_task = store.get(task.task_id)
    assert active_task is not None
    assert active_task.status == TaskStatus.ACTIVE
    assert active_task.heartbeat_expires_at > 0

    reaped = store.reap_expired_heartbeats(now=active_task.heartbeat_expires_at + 10, repo_root=repo_root, tenant="tenant-a")
    assert reaped == [task.task_id]
    abandoned = store.get(task.task_id)
    assert abandoned is not None
    assert abandoned.status == TaskStatus.ABANDONED
    assert abandoned.checkpoint.phase == "coding"
    assert abandoned.checkpoint.next_action == "run tests"


def test_resume_abandoned_task(store: TaskStore, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    tenant_token = trace_context.set_context(tenant="tenant-a")
    try:
        task = store.create(contract_with_criteria("tests"), task_context(), task_id="t-resume", repo_root=str(repo_root))
    finally:
        trace_context.reset_context(tenant_token)
    store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="a")
    memory_context = {
        "records": [{
            "record_id": "memory-api-shape",
            "scope": "repository",
            "content": "Keep the public API shape stable during this work.",
            "evidence_ids": ["artifact:api-contract"],
        }],
        "revision": "memory-revision-7",
    }
    store.checkpoint(
        task.task_id,
        TaskCheckpoint(
            phase="planning",
            next_action="replan with repository memory",
            state_data={"agent_os_memory_context": memory_context},
        ),
        actor="agent",
        idempotency_key="memory-checkpoint",
    )
    store.reap_expired_heartbeats(now=store.get(task.task_id).heartbeat_expires_at + 10, repo_root=repo_root, tenant="tenant-a")

    resumed = store.resume(task.task_id, actor="agent", idempotency_key="res-1")
    assert resumed.status == TaskStatus.ACTIVE
    assert resumed.checkpoint.state_data["agent_os_memory_context"] == memory_context

    stream_id = f"task:{task.task_id}"
    events_after_resume = len(store.state_store.events(stream_id))
    replayed = store.resume(task.task_id, actor="agent", idempotency_key="res-1")
    assert replayed == resumed
    assert len(store.state_store.events(stream_id)) == events_after_resume
    with pytest.raises(ValueError, match="idempotency key was already used"):
        store.resume(task.task_id, actor="different-actor", idempotency_key="res-1")
    with pytest.raises(ValueError, match="idempotency key was already used"):
        store.transition(task.task_id, TaskStatus.ACTIVE, reason="different", actor="agent", idempotency_key="res-1")
    assert len(store.state_store.events(stream_id)) == events_after_resume

    stream_id = f"task:{task.task_id}"
    events_after_resume = len(store.state_store.events(stream_id))
    replayed = store.resume(task.task_id, actor="agent", idempotency_key="res-1")
    assert replayed == resumed
    assert len(store.state_store.events(stream_id)) == events_after_resume
    with pytest.raises(ValueError, match="idempotency key was already used"):
        store.resume(task.task_id, actor="different-actor", idempotency_key="res-1")
    with pytest.raises(ValueError, match="idempotency key was already used"):
        store.transition(
            task.task_id,
            TaskStatus.ACTIVE,
            reason="different",
            actor="agent",
            idempotency_key="res-1",
        )
    assert len(store.state_store.events(stream_id)) == events_after_resume


def test_illegal_transition_raises_error(store: TaskStore):
    task = store.create(contract_with_criteria("tests"), task_context())
    with pytest.raises(InvalidTransitionError):
        store.transition(task.task_id, TaskStatus.COMPLETED, reason="skip to end", actor="agent", idempotency_key="bad")


def test_add_verification_receipt_emits_event(tmp_path: Path):
    from local_ai_hub.agent_events import AgentStateStore

    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    task_store = TaskStore(state_store)
    task = task_store.create(contract_with_criteria("tests"), task_context(), task_id="t-evt")

    events_before = state_store.events(stream_id=f"task:{task.task_id}")
    assert len(events_before) == 1  # task.created

    task_store.add_verification_receipt(task.task_id, "tests", "rcpt-123")

    events_after = state_store.events(stream_id=f"task:{task.task_id}")
    assert len(events_after) == 2
    assert events_after[-1].kind == "task.verified"
    assert events_after[-1].payload == {"criterion": "tests", "receipt_id": "rcpt-123"}


def test_stores_schema_initialized_flag(tmp_path: Path):
    from local_ai_hub.agent_events import AgentStateStore
    from local_ai_hub.agent_verification import VerificationStore
    from local_ai_hub.agent_memory import MemoryStore
    from local_ai_hub.agent_incidents import IncidentStore
    from local_ai_hub.agent_learning import LearningStore

    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    ts = TaskStore(state_store)
    vs = VerificationStore(state_store)
    ms = MemoryStore(state_store)
    inc = IncidentStore(state_store)
    ls = LearningStore(state_store)

    assert ts._initialized is True
    assert vs._initialized is True
    assert ms._initialized is True
    assert inc._initialized is True
    assert ls._initialized is True


def test_goal_contract_normalizes_scope_string_and_serializes_without_error():
    # Constructing with string scope directly
    c1 = GoalContract(goal="test 1", scope="task")
    assert isinstance(c1.scope, AgentScope)
    assert c1.scope == AgentScope.TASK
    assert c1.to_dict()["scope"] == "task"

    # Constructing with alias string
    c2 = GoalContract(goal="test 2", scope="code")
    assert isinstance(c2.scope, AgentScope)
    assert c2.scope == AgentScope.TASK
    assert c2.to_dict()["scope"] == "task"

    # Constructing via from_dict with empty/None scope
    c3 = GoalContract.from_dict({"goal": "test 3", "scope": None})
    assert isinstance(c3.scope, AgentScope)
    assert c3.scope == AgentScope.TASK
    assert c3.to_dict()["scope"] == "task"

    c4 = GoalContract.from_dict({"goal": "test 4", "scope": ""})
    assert isinstance(c4.scope, AgentScope)
    assert c4.scope == AgentScope.TASK
    assert c4.to_dict()["scope"] == "task"


def test_structured_description_survives_contract_and_task_round_trip(store: TaskStore):
    contract = GoalContract.from_dict(
        {
            "goal": "Harden receipt freshness",
            "title": "Receipt freshness",
            "description": "Reject a pass when a newer receipt failed.",
            "acceptance_criteria": ["tests"],
        }
    )

    assert contract.goal == "Harden receipt freshness"
    assert contract.description == "Reject a pass when a newer receipt failed."
    assert contract.to_dict()["description"] == "Reject a pass when a newer receipt failed."

    stored = store.create(contract, task_context(), task_id="t-description")
    fetched = store.get(stored.task_id)

    assert fetched is not None
    assert fetched.contract.goal == "Harden receipt freshness"
    assert fetched.contract.description == "Reject a pass when a newer receipt failed."


def test_legacy_goal_contract_without_description_loads_empty_description():
    contract = GoalContract.from_dict(
        {"goal": "Legacy task", "acceptance_criteria": ["tests"]}
    )

    assert contract.goal == "Legacy task"
    assert contract.description == ""


def test_description_only_terms_are_searchable_without_replacing_goal(store: TaskStore):
    task = store.create(
        GoalContract(
            goal="Receipt review",
            description="quasar evidence provenance",
            acceptance_criteria=("tests",),
        ),
        task_context(),
        task_id="description-search",
    )

    matches = store.list_tasks(query="quasar provenance")

    assert [match.task_id for match in matches] == [task.task_id]
    assert matches[0].contract.goal == "Receipt review"
    assert matches[0].contract.description == "quasar evidence provenance"


def test_task_keyword_query_matches_each_term_across_indexed_fields(store: TaskStore):
    target = store.create(
        GoalContract(
            goal="Receipt freshness gate",
            description="Evidence from closed runs",
            acceptance_criteria=("reject stale generation",),
        ),
        task_context(),
        task_id="task-search-target",
    )
    other = store.create(
        GoalContract(goal="Unrelated task", description="No matching evidence"),
        task_context(),
        task_id="task-search-other",
    )
    for task in (target, other):
        store.transition(
            task.task_id,
            TaskStatus.ACTIVE,
            reason="start search fixture",
            actor="agent",
            idempotency_key=f"search-active-{task.task_id}",
        )
    store.checkpoint(
        target.task_id,
        TaskCheckpoint(next_action="Review oldmarker"),
        actor="agent",
        idempotency_key="search-checkpoint-old",
    )
    store.checkpoint(
        target.task_id,
        TaskCheckpoint(next_action="Review signed handoff"),
        actor="agent",
        idempotency_key="search-checkpoint",
    )

    assert [task.task_id for task in store.list_tasks(TaskStatus.ACTIVE, limit=1, query="CEIPT generation signed")] == [target.task_id]
    assert [task.task_id for task in store.list_tasks(query="closed runs")] == [target.task_id]
    assert [task.task_id for task in store.list_tasks(query="search-target")] == [target.task_id]
    assert store.list_tasks(query="oldmarker") == []
    assert store.list_tasks(query="fresh missing") == []
    assert len(store.list_tasks(query="   ")) == 2

    con = connect_sqlite(store.state_store.db_path, isolation_level=None)
    try:
        con.execute("UPDATE agent_tasks_projection SET heartbeat_expires_at=1 WHERE task_id=?", (target.task_id,))
    finally:
        con.close()
    assert store.list_tasks(query="CEIPT") == []
    assert [task.task_id for task in store.list_tasks(query="CEIPT", include_stale=True)] == [target.task_id]


def test_task_keyword_query_does_not_join_grams_across_fields(store: TaskStore):
    task = store.create(
        GoalContract(goal="abcd prefix", description="cde suffix"),
        task_context(),
        task_id="task-search-cross-field-grams",
    )

    assert "abcde" not in {
        field
        for field in TaskStore._searchable_task_fields(
            task.task_id,
            {
                "goal": task.contract.goal,
                "description": task.contract.description,
                "acceptance_criteria": task.contract.acceptance_criteria,
            },
            {"next_action": task.checkpoint.next_action},
        )
    }
    con = connect_sqlite(store.state_store.db_path)
    try:
        indexed_grams = {
            str(row[0])
            for row in con.execute(
                "SELECT gram FROM agent_task_search_grams WHERE task_id=?",
                (task.task_id,),
            ).fetchall()
        }
    finally:
        con.close()
    assert {"abc", "bcd", "cde"} <= indexed_grams
    assert store.list_tasks(query="abcde") == []


def test_task_keyword_index_backfills_existing_projection_on_startup(store: TaskStore):
    task = store.create(
        GoalContract(goal="Legacy task", description="Backfill searchable marker"),
        task_context(),
        task_id="task-search-backfill",
    )
    con = connect_sqlite(store.state_store.db_path, isolation_level=None)
    try:
        con.execute("DELETE FROM agent_task_search_grams WHERE task_id=?", (task.task_id,))
        con.execute("DELETE FROM agent_task_search_documents WHERE task_id=?", (task.task_id,))
    finally:
        con.close()

    reloaded_store = TaskStore(store.state_store)

    assert [item.task_id for item in reloaded_store.list_tasks(query="searchable marker")] == [task.task_id]


def test_task_keyword_index_backfills_legacy_title_field(store: TaskStore):
    task = store.create(
        GoalContract(goal="Legacy task"),
        task_context(),
        task_id="task-search-legacy-title",
    )
    con = connect_sqlite(store.state_store.db_path, isolation_level=None)
    try:
        con.execute(
            "UPDATE agent_tasks_projection SET contract=? WHERE task_id=?",
            (json.dumps({"title": "Legacy title quasar marker"}), task.task_id),
        )
        con.execute("DELETE FROM agent_task_search_grams WHERE task_id=?", (task.task_id,))
        con.execute("DELETE FROM agent_task_search_documents WHERE task_id=?", (task.task_id,))
        TaskStore._backfill_task_search_index(con)
    finally:
        con.close()

    matches = store.list_tasks(query="quasar")
    assert [item.task_id for item in matches] == [task.task_id]
    assert matches[0].contract.goal == "Legacy title quasar marker"


def test_task_keyword_index_repairs_partial_grams_on_startup(store: TaskStore):
    task = store.create(
        GoalContract(goal="Index integrity", description="Rare zxq marker"),
        task_context(),
        task_id="task-search-partial-index",
    )
    con = connect_sqlite(store.state_store.db_path, isolation_level=None)
    try:
        con.execute(
            "DELETE FROM agent_task_search_grams WHERE task_id=? AND gram=?",
            (task.task_id, "zxq"),
        )
        assert con.execute(
            "SELECT 1 FROM agent_task_search_documents WHERE task_id=?",
            (task.task_id,),
        ).fetchone() is not None
        assert con.execute(
            "SELECT COUNT(*) FROM agent_task_search_grams WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] > 0
    finally:
        con.close()

    reloaded_store = TaskStore(store.state_store)

    assert [item.task_id for item in reloaded_store.list_tasks(query="zxq")] == [task.task_id]


def test_task_keyword_query_uses_nfkc_normalization(store: TaskStore):
    task = store.create(
        GoalContract(goal="Unicode search", description="Ｒｅｌｅａｓｅ　Ｃａｎｄｉｄａｔｅ"),
        task_context(),
        task_id="task-search-unicode",
    )

    assert [item.task_id for item in store.list_tasks(query="RELEASE CANDIDATE")] == [task.task_id]


def test_task_keyword_query_filters_before_recency_limit(store: TaskStore):
    older = store.create(GoalContract(goal="Shared marker older"), task_context(), task_id="task-search-older")
    newer = store.create(GoalContract(goal="Shared marker newer"), task_context(), task_id="task-search-newer")
    store.create(GoalContract(goal="Unrelated newest task"), task_context(), task_id="task-search-unrelated")
    con = connect_sqlite(store.state_store.db_path, isolation_level=None)
    try:
        con.execute("UPDATE agent_tasks_projection SET updated_at=10 WHERE task_id=?", (older.task_id,))
        con.execute("UPDATE agent_tasks_projection SET updated_at=20 WHERE task_id=?", (newer.task_id,))
        con.execute(
            "UPDATE agent_tasks_projection SET updated_at=30 WHERE task_id=?",
            ("task-search-unrelated",),
        )
    finally:
        con.close()

    assert [item.task_id for item in store.list_tasks(query="shared", limit=2)] == [newer.task_id, older.task_id]
    assert [item.task_id for item in store.list_tasks(query="shared", limit=1)] == [newer.task_id]

def test_checkpoint_idempotency_replay_requires_same_actor(store: TaskStore):
    task = store.create(contract_with_criteria(), task_context())
    checkpoint = TaskCheckpoint(phase="coding", next_action="review changes")
    store.checkpoint(
        task.task_id,
        checkpoint,
        actor="agent-one",
        idempotency_key="checkpoint-same-payload",
    )
    original = store.get(task.task_id)
    events_before_replay = store.state_store.events(f"task:{task.task_id}")
    replayed = store.checkpoint(
        task.task_id,
        checkpoint,
        actor="agent-one",
        idempotency_key="checkpoint-same-payload",
    )
    assert replayed == original
    assert store.state_store.events(f"task:{task.task_id}") == events_before_replay

    with pytest.raises(ValueError, match="idempotency key was already used"):
        store.checkpoint(
            task.task_id,
            checkpoint,
            actor="agent-two",
            idempotency_key="checkpoint-same-payload",
        )

    persisted = store.get(task.task_id)
    assert persisted == original
    assert persisted is not None
    assert persisted.checkpoint == checkpoint
    assert store.state_store.events(f"task:{task.task_id}") == events_before_replay
    matching_events = [
        event
        for event in store.state_store.events(f"task:{task.task_id}")
        if event.idempotency_key == "checkpoint-same-payload"
    ]
    assert len(matching_events) == 1
    assert matching_events[0].actor == "agent-one"

def test_same_status_retry_serializes_with_concurrent_transition_event(
    store: TaskStore, monkeypatch: pytest.MonkeyPatch
):
    task = store.create(contract_with_criteria(), task_context())
    active = store.transition(
        task.task_id,
        TaskStatus.ACTIVE,
        reason="start",
        actor="agent-one",
        idempotency_key="start-key",
    )
    key = "concurrent-transition-key"
    concurrent_event = AgentEvent.create(
        stream_id=f"task:{task.task_id}",
        kind="task.transitioned",
        payload={"from_status": TaskStatus.PLANNED.value, "to_status": TaskStatus.ACTIVE.value, "reason": "R"},
        idempotency_key=key,
        actor="agent-one",
    )
    writer = connect_sqlite(store.state_store.db_path, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    appended = store.state_store.append_in_transaction(writer, concurrent_event, strict_idempotency=True)
    assert appended.error is None and appended.event is not None

    lock_attempted = threading.Event()
    outcome: list[object] = []
    worker_name = "t08-same-status-replay"
    original_connect = agent_tasks_module.connect_sqlite

    class ConnectionProbe:
        def __init__(self, inner):
            self.inner = inner

        def execute(self, sql, *args):
            if threading.current_thread().name == worker_name and sql.strip().upper() == "BEGIN IMMEDIATE":
                lock_attempted.set()
            return self.inner.execute(sql, *args)

        def close(self):
            self.inner.close()

        @property
        def in_transaction(self):
            return self.inner.in_transaction

    def connect_with_probe(path, *args, **kwargs):
        connection = original_connect(path, *args, **kwargs)
        if threading.current_thread().name == worker_name:
            return ConnectionProbe(connection)
        return connection

    monkeypatch.setattr(agent_tasks_module, "connect_sqlite", connect_with_probe)

    def replay_from_other_actor():
        try:
            outcome.append(store.transition(
                task.task_id,
                TaskStatus.ACTIVE,
                reason="R",
                actor="agent-two",
                idempotency_key=key,
            ))
        except Exception as exc:
            outcome.append(exc)

    worker = threading.Thread(target=replay_from_other_actor, name=worker_name)
    try:
        worker.start()
        assert lock_attempted.wait(timeout=2), "replay did not enter its write-serialized check"
    finally:
        writer.execute("COMMIT")
        writer.close()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert len(outcome) == 1 and isinstance(outcome[0], ValueError)
    assert str(outcome[0]) == "idempotency key was already used"
    assert active.status is TaskStatus.ACTIVE
