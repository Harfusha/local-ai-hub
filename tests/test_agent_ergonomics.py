from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_tasks import (
    GoalContract,
    TaskCheckpoint,
    TaskState,
    TaskStatus,
    TaskStore,
)
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore, _receipt_evidence_matches
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.operation_contracts import validate_operation_arguments, operation_contract
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.response_budget import budget_response, json_tokens


def test_repo_tools_apply_patch_exact_crlf_and_whitespace(tmp_path: Path):
    """Point 4: Verify exact, CRLF-tolerant, and whitespace-tolerant patch behavior."""
    repo = tmp_path / "repo"
    repo.mkdir()
    rt = RepositoryTools({})

    # 1. Exact match with LF
    f_lf = repo / "code_lf.py"
    f_lf.write_bytes(b"def hello():\n    print('hello world')\n    return 42\n")
    res1 = rt.apply_patch(str(repo), "code_lf.py", "    print('hello world')\n    return 42", "    return 100")
    assert res1["success"] is True
    assert res1["matched_strategy"] == "exact"
    assert f_lf.read_bytes() == b"def hello():\n    return 100\n"

    # 2. CRLF file patched with LF string (normalization match)
    f_crlf = repo / "code_crlf.py"
    f_crlf.write_bytes(b"def foo():\r\n    x = 1\r\n    y = 2\r\n    return x + y\r\n")
    # Agent sends old_code with standard \n
    target_lf = "    x = 1\n    y = 2"
    repl_lf = "    x = 10\n    y = 20"
    res2 = rt.apply_patch(str(repo), "code_crlf.py", target_lf, repl_lf)
    assert res2["success"] is True
    assert res2["matched_strategy"] == "normalized_line_endings"
    # Preserves \r\n line endings!
    content_after = f_crlf.read_bytes()
    assert b"\r\n" in content_after
    assert b"x = 10\r\n    y = 20" in content_after

    # 3. Trailing whitespace tolerance
    f_ws = repo / "code_ws.py"
    # File has trailing whitespace on line "x = 1  \n"
    f_ws.write_bytes(b"def bar():\n    x = 1  \n    return x\n")
    # Agent sends clean line without trailing whitespace
    res3 = rt.apply_patch(str(repo), "code_ws.py", "    x = 1\n    return x", "    x = 99\n    return x * 2")
    assert res3["success"] is True
    assert res3["matched_strategy"] == "whitespace_tolerant"
    assert b"x = 99\n    return x * 2" in f_ws.read_bytes()

    # 4. Target not found
    res4 = rt.apply_patch(str(repo), "code_lf.py", "non_existent_code()", "something_else()")
    assert res4["success"] is False
    assert "not found" in res4["error"]

    # 5. Ambiguous duplicate target
    f_dup = repo / "code_dup.py"
    f_dup.write_bytes(b"foo = 1\nfoo = 1\n")
    res5 = rt.apply_patch(str(repo), "code_dup.py", "foo = 1", "foo = 2")
    assert res5["success"] is False
    assert "found 2 times" in res5["error"]


def test_task_adoption_and_claim(tmp_path: Path):
    """Point 2: Verify authorized task claiming and cross-agent adoption."""
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    store = TaskStore(state_store)
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    verification_store = VerificationStore(
        state_store, task_store=store, artifact_store=artifact_store
    )
    store.verification_store = verification_store

    contract = GoalContract(
        goal="Feature development",
        acceptance_criteria=("criterion_a",),
        scope=AgentScope.TASK,
    )
    task = store.create(
        contract,
        ScopeContext(repository_id="repo-main", task_id="task-adopt-1"),
        actor="codex",
    )
    assert task.owner == "codex"

    # Mint receipt under original owner codex
    proof = {
        "passed": True,
        "kind": "work_command_verification",
        "task_id": task.task_id,
        "owner": "codex",
        "criterion": "criterion_a",
        "command_id": "a" * 32,
        "repository_revision": "rev-1",
        "mutation_generation": 0,
        "command": "pytest",
        "command_classification": "source_review",
        "output_summary": "ok",
        "exit_code": 0,
        "cached": False,
        "result": {"success": True, "exit_code": 0},
    }
    ev_id = artifact_store.put(json.dumps(proof), kind="command_verification")
    rcpt = VerificationReceipt.create(
        task_id=task.task_id,
        criterion="criterion_a",
        passed=True,
        command_id="a" * 32,
        evidence_id=ev_id,
        evidence_type="source_review",
        repository_revision="rev-1",
        mutation_generation=0,
        owner="codex",
        details={"command": "pytest", "native": True},
    )
    verification_store.record(rcpt)
    store.add_verification_receipt(task.task_id, "criterion_a", rcpt.receipt_id)

    # Agent Gemini adopts the task
    claimed = store.claim(task.task_id, "gemini", actor="gemini")
    assert claimed.owner == "gemini"
    assert claimed.task_id == task.task_id

    # Claiming with same owner is a clean no-op
    reclaimed = store.claim(task.task_id, "gemini", actor="gemini")
    assert reclaimed.owner == "gemini"

    # Verify task state in store reflects new owner
    fetched = store.get(task.task_id)
    assert fetched is not None
    assert fetched.owner == "gemini"

    # Verify that verification receipt and proof artifact were cleanly rebound to new owner gemini
    rebound_rcpt = verification_store.completion(task.task_id, current_revision="rev-1").receipts[0]
    assert rebound_rcpt.owner == "gemini"
    rebound_doc = artifact_store.get(ev_id)
    assert json.loads(rebound_doc["text"])["owner"] == "gemini"


def test_dense_response_profile():
    """Point 3: Verify response_profile='dense' returns pure data without verbose envelopes."""
    raw = {
        "success": True,
        "results": [{"symbol": "run", "path": "main.py", "line": 42}],
        "path_hint_usage": {"used": True, "hints": ["main.py"]},
        "token_efficiency": {"avoided": 100},
    }
    budgeted = budget_response(
        raw,
        max_tokens=800,
        profile="dense",
        token_metadata={"protocol_tokens_est": 10},
    )
    assert isinstance(budgeted, dict)
    assert budgeted["success"] is True
    # In dense profile, internal token_efficiency is omitted to minimize token noise
    assert "token_efficiency" not in budgeted
    # response_budget is present with valid returned_tokens
    assert "response_budget" in budgeted
    assert budgeted["response_budget"]["returned_tokens"] == json_tokens(budgeted)


def test_schema_polymorphism_and_validation():
    """Point 1: Verify schema validation permits confidence, patch, call_graph, task_claim, and record_native_receipt."""
    # confidence in local_ai_coord memory_record
    coord_err = validate_operation_arguments(
        "local_ai_coord",
        "memory_record",
        {"key": "test_k", "value": "test_v", "confidence": 0.9, "root": "."},
    )
    assert coord_err is None

    # task_claim in local_ai_coord
    claim_err = validate_operation_arguments(
        "local_ai_coord",
        "task_claim",
        {"task_id": "t-1", "owner": "gemini", "root": "."},
    )
    assert claim_err is None

    # record_native_receipt in local_ai_coord
    rcpt_err = validate_operation_arguments(
        "local_ai_coord",
        "record_native_receipt",
        {"task_id": "t-1", "criterion": "crit-1", "command": "pytest -q", "passed": True},
    )
    assert rcpt_err is None

    # patch in local_ai_repo
    patch_err = validate_operation_arguments(
        "local_ai_repo",
        "patch",
        {"path": "foo.py", "old_code": "x = 1", "new_code": "x = 2", "root": "."},
    )
    assert patch_err is None

    # call_graph in local_ai_repo
    cg_err = validate_operation_arguments(
        "local_ai_repo",
        "call_graph",
        {"query": "my_function", "root": ".", "limit": 25, "depth": 2},
    )
    assert cg_err is None


def test_native_receipt_verification_integration(tmp_path: Path):
    """Point 5: Verify native receipt artifact generation and verification matching."""
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    task_store = TaskStore(state_store)
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    verification_store = VerificationStore(
        state_store, task_store=task_store, artifact_store=artifact_store
    )

    contract = GoalContract(
        goal="Test native receipt",
        acceptance_criteria=("unit_tests",),
        scope=AgentScope.TASK,
    )
    task = task_store.create(
        contract,
        ScopeContext(repository_id="repo-main", task_id="task-native-1"),
        actor="gemini",
    )

    # Agent ran host-native command 'pytest -q' which passed
    command = "pytest -q tests/test_agent_ergonomics.py"
    revision = "rev-12345"
    command_id = hashlib.sha256(b"cmd_native_1").hexdigest()[:32]
    proof = {
        "passed": True,
        "kind": "work_command_verification",
        "task_id": task.task_id,
        "owner": task.owner,
        "criterion": "unit_tests",
        "command_id": command_id,
        "repository_revision": revision,
        "mutation_generation": 0,
        "command": command,
        "command_classification": "test",
        "output_summary": "5 passed in 0.42s",
        "exit_code": 0,
        "cached": False,
        "result": {"success": True, "exit_code": 0},
    }
    evidence_id = artifact_store.put(json.dumps(proof), kind="command_verification")

    receipt = VerificationReceipt.create(
        task_id=task.task_id,
        criterion="unit_tests",
        passed=True,
        command_id=command_id,
        evidence_id=evidence_id,
        evidence_type="test",
        repository_revision=revision,
        mutation_generation=0,
        owner=task.owner,
        details={"command": command, "native": True},
    )

    # Record receipt in verification store
    saved = verification_store.record(receipt)
    assert saved.receipt_id == receipt.receipt_id

    # Verify matching evidence against artifact store
    matches = _receipt_evidence_matches(
        receipt,
        artifact_store,
        expected_owner=task.owner,
        require_repository_revision=True,
    )
    assert matches is True

    # Link receipt to task
    task_with_receipt = task_store.add_verification_receipt(
        task.task_id, "unit_tests", saved.receipt_id
    )
    assert task_with_receipt.has_receipt("unit_tests") is True


def test_call_graph_structure():
    """Point 6: Verify call_graph returns structured hierarchy with callers and callees."""
    from unittest.mock import MagicMock
    from local_ai_hub.services import LocalAIServices

    services = LocalAIServices.__new__(LocalAIServices)
    services.code_find_declaration = MagicMock(return_value={"success": True, "path": "services.py", "line": 100, "kind": "function"})
    services.callers = MagicMock(return_value={"success": True, "callers": [{"symbol": "caller_a", "path": "app.py"}]})
    services.callees = MagicMock(return_value={"success": True, "callees": [{"symbol": "callee_b", "path": "utils.py"}]})

    res = services.call_graph(".", "my_func", depth=1)
    assert res["success"] is True
    assert res["symbol"] == "my_func"
    assert res["found_in"]["path"] == "services.py"
    assert len(res["callers"]) == 1
    assert len(res["callees"]) == 1
    assert res["caller_count"] == 1
    assert res["callee_count"] == 1
    assert res["depth"] == 1


def test_repo_query_task_aliasing():
    """Point 1: Verify query and task are gracefully aliased in local_ai_repo."""
    from unittest.mock import patch
    from local_ai_hub.mcp_server import local_ai_repo

    with patch("local_ai_hub.mcp_server._local_ai_repo_impl") as mock_impl:
        mock_impl.return_value = {"success": True}
        # Calling context with task instead of query
        res = local_ai_repo(action="context", root=".", task="investigate issue")
        assert mock_impl.called
        args, kwargs = mock_impl.call_args
        assert args[2] == "investigate issue"  # query is mapped from task!



import subprocess


def test_repo_git_status_and_revert(tmp_path: Path):
    """Points 6 & 8: Verify git_status and revert operations in repo_tools."""
    repo = tmp_path / "repo"
    repo.mkdir()
    # Init git repo
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), check=True, capture_output=True)

    f1 = repo / "hello.py"
    f1.write_text("print('hello initial')\n", encoding="utf-8")
    subprocess.run(["git", "add", "hello.py"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), check=True, capture_output=True)

    rt = RepositoryTools({})

    # Clean state
    st_clean = rt.git_status(str(repo))
    assert st_clean["success"] is True
    assert st_clean["dirty"] is False
    assert len(st_clean["changed_paths"]) == 0
    assert len(st_clean["untracked_paths"]) == 0

    # Modify file and add untracked file
    f1.write_text("print('hello modified')\n", encoding="utf-8")
    f2 = repo / "untracked.py"
    f2.write_text("print('untracked')\n", encoding="utf-8")

    st_dirty = rt.git_status(str(repo))
    assert st_dirty["success"] is True
    assert st_dirty["dirty"] is True
    assert "hello.py" in st_dirty["changed_paths"]
    assert "untracked.py" in st_dirty["untracked_paths"]

    # Revert modified file
    rev_res = rt.git_revert_file(str(repo), "hello.py")
    assert rev_res["success"] is True
    assert rev_res["reverted"] is True
    assert f1.read_text(encoding="utf-8") == "print('hello initial')\n"

    # Status after revert
    st_after = rt.git_status(str(repo))
    assert "hello.py" not in st_after["changed_paths"]
    assert "untracked.py" in st_after["untracked_paths"]


def test_artifact_batch_source_and_slice_alias(tmp_path: Path):
    """Points 2 & 9: Verify batch source slicing and slice->source alias."""
    from unittest.mock import patch
    from local_ai_hub.mcp_server import local_ai_artifact

    f1 = tmp_path / "a.py"
    f1.write_text("line1\nline2\nline3\n", encoding="utf-8")

    with patch("local_ai_hub.mcp_server._workspace", str(tmp_path)):
        # Calling slice with path (without artifact_id)
        res_slice = local_ai_artifact(action="slice", path="a.py", line_start=1, line_end=2)
        assert res_slice["success"] is True
        assert "line1" in res_slice.get("text", "")

        # Calling batch_source with slices list
        slices = [
            {"path": "a.py", "line_start": 1, "line_end": 1},
            {"path": "a.py", "line_start": 3, "line_end": 3},
        ]
        res_batch = local_ai_artifact(action="source", slices=slices)
        assert res_batch["success"] is True
        assert len(res_batch.get("slices", [])) == 2


def test_checkpoint_packaging_and_incident_aliases():
    """Points 1 & 4: Verify task_checkpoint packaging and negative_knowledge_record mapping."""
    from unittest.mock import patch
    from local_ai_hub.mcp_server import local_ai_coord

    with patch("local_ai_hub.mcp_server.CLIENT") as mock_client:
        mock_client.coord.return_value = {"success": True}
        mock_client.post.return_value = {"success": True}

        # Checkpoint called with top-level phase and paths
        local_ai_coord(action="task_checkpoint", task_id="t1", phase="testing", reason="pytest passed", paths=["src/a.py"])
        assert mock_client.coord.called
        kwargs = mock_client.coord.call_args[1]
        assert "checkpoint" in kwargs
        chk = kwargs["checkpoint"]
        assert chk["phase"] == "testing"
        assert chk["next_action"] == "pytest passed"
        assert chk["affected_paths"] == ["src/a.py"]

        # Negative knowledge record with aliases (description, error_class, paths)
        local_ai_coord(action="negative_knowledge_record", record={"description": "bug in regex", "error_class": "ValueError", "paths": ["src/re.py"]})
        assert mock_client.post.called
        post_kwargs = mock_client.post.call_args[0]
        payload = post_kwargs[1]
        assert payload["message"] == "bug in regex"
        assert payload["operation_class"] == "ValueError"
        assert payload["affected_paths"] == ["src/re.py"]


def test_task_compress_and_review_flexibility():
    """Point 3: Verify local_ai_task compress and review accept prompt/candidate/context."""
    from unittest.mock import patch
    from local_ai_hub.mcp_server import local_ai_task, FEATURES

    with patch.object(FEATURES, "tasks", True), patch.object(FEATURES, "has_any_model", return_value=True), patch("local_ai_hub.mcp_server.CLIENT") as mock_client:
        mock_client.post.return_value = {"success": True, "text": "compressed"}

        # Compress with prompt instead of context
        local_ai_task(action="compress", prompt="test failure log output")
        payload = mock_client.post.call_args[0][1]
        assert payload["text"] == "test failure log output"

        # Review with candidate instead of context
        local_ai_task(action="review", candidate="def buggy(): return 1/0")
        payload_rev = mock_client.post.call_args[0][1]
        assert payload_rev["code"] == "def buggy(): return 1/0"
