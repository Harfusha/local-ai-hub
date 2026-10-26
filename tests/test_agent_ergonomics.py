from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from local_ai_hub.mcp_server import (
    FEATURES,
    _local_ai_repo_impl,
    local_ai_coord,
    local_ai_task,
    local_ai_artifact,
    local_ai_rag,
    local_ai_repo,
    local_ai_status,
    local_ai_work,
)

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

    with patch.object(FEATURES, "tasks", True), \
         patch.object(FEATURES, "has_any_model", return_value=True), \
         patch("local_ai_hub.mcp_server.operational_mode_gate_error", return_value=None), \
         patch("local_ai_hub.mcp_server.CLIENT") as mock_client:
        mock_client.post.return_value = {"success": True, "text": "compressed"}

        # Compress with prompt instead of context
        local_ai_task(action="compress", prompt="test failure log output")
        payload = mock_client.post.call_args[0][1]
        assert payload["text"] == "test failure log output"

        # Review with candidate instead of context
        mock_client.reset_mock()
        local_ai_task(action="review", candidate="def buggy(): return 1/0")
        payload_rev = mock_client.post.call_args[0][1]
        assert payload_rev["code"] == "def buggy(): return 1/0"


def test_repo_find_files_and_glob(tmp_path):
    """Phase 3 Point 6: Verify find_files and glob pattern matching."""
    from local_ai_hub.repo_tools import RepositoryTools
    from unittest.mock import patch
    from local_ai_hub.mcp_server import _local_ai_repo_impl

    # Test RepositoryTools directly
    rt = RepositoryTools({})
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "alpha.py").write_text("print(1)")
    (tmp_path / "src" / "beta.json").write_text("{}")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_alpha.py").write_text("assert True")

    res = rt.find_files(str(tmp_path), pattern="*.py")
    assert res["success"] is True
    assert "src/alpha.py" in res["files"]
    assert "tests/test_alpha.py" in res["files"]
    assert "src/beta.json" not in res["files"]
    assert res["count"] == 2

    # Test MCP routing for find_files and glob alias
    with patch("local_ai_hub.mcp_server.CLIENT") as mock_client:
        mock_client.post.return_value = {"success": True, "files": ["src/alpha.py"]}
        res_mcp = _local_ai_repo_impl(action="glob", pattern="*.py", root=str(tmp_path))
        assert mock_client.post.called
        assert mock_client.post.call_args[0][0] == "/api/repo/find_files"
        assert mock_client.post.call_args[0][1]["pattern"] == "*.py"


def test_repo_patch_deletion_and_aliases(tmp_path):
    """Phase 3 Point 7: Verify patch supports deletion (new_code="") and target/replacement aliases."""
    from unittest.mock import patch
    from local_ai_hub.mcp_server import _local_ai_repo_impl

    with patch("local_ai_hub.mcp_server.CLIENT") as mock_client:
        mock_client.post.return_value = {"success": True, "patched": True}

        # 1. Code deletion (replacement="")
        _local_ai_repo_impl(action="patch", root=str(tmp_path), path="a.py", old_code="obsolete()", new_code="")
        assert mock_client.post.called
        assert mock_client.post.call_args[0][1]["new_code"] == ""

        # 2. Target and replacement aliases
        mock_client.post.reset_mock()
        _local_ai_repo_impl(action="patch", root=str(tmp_path), path="a.py", target="old()", replacement="new()")
        assert mock_client.post.called
        payload = mock_client.post.call_args[0][1]
        assert payload["old_code"] == "old()"
        assert payload["new_code"] == "new()"


def test_git_log_and_empty_query_history(tmp_path):
    """Phase 3 Point 8: Verify git_log action and empty query git_history_search."""
    from unittest.mock import patch
    from local_ai_hub.mcp_server import _local_ai_repo_impl

    with patch("local_ai_hub.mcp_server.CLIENT") as mock_client:
        mock_client.post.return_value = {"success": True, "commits": [{"hash": "abc", "message": "feat: test"}]}

        # git_log
        _local_ai_repo_impl(action="git_log", root=str(tmp_path), limit=5)
        assert mock_client.post.called
        assert mock_client.post.call_args[0][0] == "/api/git/history_search"
        payload = mock_client.post.call_args[0][1]
        assert payload["query"] == ""
        assert payload["max_commits"] == 5

        # git_history_search with empty query
        mock_client.post.reset_mock()
        _local_ai_repo_impl(action="git_history_search", root=str(tmp_path), query="")
        assert mock_client.post.called
        assert mock_client.post.call_args[0][1]["query"] == ""


def test_coord_task_create_and_fail_aliases():
    """Phase 3 Points 1, 4, 5, 10: Verify task_create criteria, task_fail error, board_item, and task_list filter."""
    from unittest.mock import patch
    from local_ai_hub.mcp_server import local_ai_coord

    with patch("local_ai_hub.mcp_server.CLIENT") as mock_client:
        mock_client.coord.return_value = {"success": True}

        # 1. task_create with top-level acceptance_criteria and goal
        local_ai_coord(action="task_create", task_id="t10", goal="Build X", acceptance_criteria=["Tests pass"])
        assert mock_client.coord.called
        kwargs = mock_client.coord.call_args[1]
        assert "contract" in kwargs
        contract = kwargs["contract"]
        assert contract["goal"] == "Build X"
        assert contract["acceptance_criteria"] == ["Tests pass"]

        # 2. task_fail with error and message
        mock_client.coord.reset_mock()
        local_ai_coord(action="task_fail", task_id="t10", error="Build failed code 1")
        assert mock_client.coord.called
        assert mock_client.coord.call_args[1]["reason"] == "Build failed code 1"

        # 3. task_list with status and owner filter
        mock_client.coord.reset_mock()
        local_ai_coord(action="task_list", status="in_progress", owner="gemini")
        assert mock_client.coord.called
        list_kwargs = mock_client.coord.call_args[1]
        assert list_kwargs["status"] == "in_progress"
        assert list_kwargs["owner"] == "gemini"

        # 4. board_item_create with name and description
        mock_client.coord.reset_mock()
        local_ai_coord(action="board_item_create", name="Task 1", description="Details 1")
        assert mock_client.coord.called
        board_kwargs = mock_client.coord.call_args[1]
        assert board_kwargs["title"] == "Task 1"
        assert board_kwargs["details"] == {"description": "Details 1"}


def test_argument_suggestion_hints():
    """Phase 3 Point 9: Verify argument suggestions when close typos occur."""
    import asyncio
    from local_ai_hub import mcp_server

    # Call with a typo in argument name: e.g. 'pattrn' instead of 'pattern' in find_files
    response = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {"action": "find_files", "pattrn": "*.py"}))
    assert response[1]["status_code"] == 400
    assert "argument_help" in response[1]
    # Check that suggestion is present and identifies 'pattern'
    assert "suggestion" in response[1]["argument_help"]
    assert "pattern" in response[1]["argument_help"]["suggestion"]



def test_memory_root_find_and_kind(tmp_path: Path):
    """Phase 4 Points 1, 2, 3: Verify root-based memory find, kind parameter, and memory_list alias."""
    from unittest.mock import patch
    from local_ai_hub.agent_memory import MemoryStore, MemoryRecord, MemoryKind
    from local_ai_hub.mcp_server import local_ai_coord

    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    store = MemoryStore(state_store)

    rec1 = MemoryRecord(
        record_id="rec-1",
        key="naming_convention",
        value="use snake_case for functions",
        scope=AgentScope.REPOSITORY,
        scope_id="repo-1",
        kind=MemoryKind.CONVENTION,
    )
    rec2 = MemoryRecord(
        record_id="rec-2",
        key="architecture_fact",
        value="single owner PC architecture",
        scope=AgentScope.REPOSITORY,
        scope_id="repo-1",
        kind=MemoryKind.FACT,
    )
    store.record(rec1)
    store.record(rec2)

    # 1. Query with kind filter
    res_conv = store.find(scope=AgentScope.REPOSITORY, query="snake", scope_id="repo-1", kind="convention", semantic=False)
    assert len(res_conv) == 1
    assert res_conv[0].key == "naming_convention"
    assert res_conv[0].kind == MemoryKind.CONVENTION

    res_fact = store.find(scope=AgentScope.REPOSITORY, query="architecture", scope_id="repo-1", kind="fact", semantic=False)
    assert len(res_fact) == 1
    assert res_fact[0].key == "architecture_fact"

    # Query with mismatching kind
    res_none = store.find(scope=AgentScope.REPOSITORY, query="snake", scope_id="repo-1", kind="fact", semantic=False)
    assert len(res_none) == 0

    # 2. MCP memory_list alias and kind parameter
    with patch("local_ai_hub.mcp_server.CLIENT") as mock_client:
        mock_client.coord.return_value = {"success": True, "results": []}

        # memory_list alias
        local_ai_coord(action="memory_list", root=str(tmp_path), kind="convention")
        assert mock_client.coord.called
        kwargs = mock_client.coord.call_args[1]
        assert kwargs["action"] == "memory_find"
        assert kwargs["kind"] == "convention"
        assert kwargs["query"] == ""

        # task_update alias
        mock_client.coord.reset_mock()
        local_ai_coord(action="task_update", task_id="t1", phase="implementation")
        assert mock_client.coord.called
        kwargs2 = mock_client.coord.call_args[1]
        assert kwargs2["action"] == "task_checkpoint"
        assert (kwargs2.get("phase") or kwargs2.get("checkpoint", {}).get("phase")) == "implementation"


def test_repo_file_info_and_stat(tmp_path: Path):
    """Phase 4 Points 5, 6, 7: Verify file_info/stat, read_file/source, and line aliases."""
    repo = tmp_path / "repo"
    repo.mkdir()
    test_file = repo / "hello.py"
    test_file.write_text("line 1\nline 2\nline 3\nline 4\nline 5\n", encoding="utf-8")

    rt = RepositoryTools({})

    # 1. file_info on existing file
    info = rt.file_info(str(repo), "hello.py")
    assert info["success"] is True
    assert info["exists"] is True
    assert info["is_file"] is True
    assert info["is_dir"] is False
    assert info["line_count"] == 5
    assert info["size_bytes"] > 0
    assert "mtime" in info

    # 2. file_info on directory
    sub_dir = repo / "subdir"
    sub_dir.mkdir()
    info_dir = rt.file_info(str(repo), "subdir")
    assert info_dir["success"] is True
    assert info_dir["exists"] is True
    assert info_dir["is_dir"] is True
    assert info_dir["line_count"] == 0

    # 3. file_info on non-existent path
    info_none = rt.file_info(str(repo), "non_existent.py")
    assert info_none["success"] is True
    assert info_none["exists"] is False

    # 4. MCP read_file and line aliases
    from local_ai_hub.mcp_server import _local_ai_repo_impl
    res_slice = _local_ai_repo_impl(
        action="read_file",
        root=str(repo),
        path="hello.py",
        start_line=2,
        end_line=4,
    )
    assert res_slice["success"] is True
    assert "line 2" in res_slice["content"]
    assert "line 4" in res_slice["content"]
    assert "line 5" not in res_slice["content"]

    # 5. MCP source action
    res_source = _local_ai_repo_impl(
        action="source",
        root=str(repo),
        path="hello.py",
        start_line=1,
        end_line=2,
    )
    assert res_source["success"] is True
    assert "line 1" in res_source["content"]


def test_git_diff_base_head_and_status_path(tmp_path: Path):
    """Phase 4 Points 8, 9: Verify git_diff base/head and git_status path filtering."""
    from unittest.mock import patch
    from local_ai_hub.mcp_server import _local_ai_repo_impl

    with patch("local_ai_hub.mcp_server.CLIENT") as mock_client:
        mock_client.post.return_value = {"success": True, "diff": "test diff"}

        # git_diff with base and head
        _local_ai_repo_impl(action="git_diff", root=str(tmp_path), base="HEAD~2", head="HEAD")
        assert mock_client.post.called
        assert mock_client.post.call_args[0][0] == "/api/git/diff"
        payload = mock_client.post.call_args[0][1]
        assert payload["base"] == "HEAD~2"
        assert payload["head"] == "HEAD"

        # git_status with path filter
        mock_client.get.reset_mock()
        mock_client.get.return_value = {
            "success": True,
            "changed_paths": ["src/local_ai_hub/foo.py", "docs/bar.md"],
            "modified": ["src/local_ai_hub/foo.py", "docs/bar.md"],
        }
        res_status = _local_ai_repo_impl(action="git_status", root=str(tmp_path), path="src/local_ai_hub")
        assert mock_client.get.called
        assert "/api/git/status" in mock_client.get.call_args[0][0]
        assert res_status["changed_paths"] == ["src/local_ai_hub/foo.py"]


def test_rag_query_limit_and_task_summarize_models(tmp_path: Path):
    """Phase 4 Points 10, 11, 12: Verify RAG query/limit, task summarize, and status models."""
    from unittest.mock import patch
    from local_ai_hub.mcp_server import local_ai_rag, local_ai_task, local_ai_status, FEATURES

    with patch.object(FEATURES, "tasks", True), patch.object(FEATURES, "has_any_model", return_value=True), patch("local_ai_hub.mcp_server.CLIENT") as mock_client:
        mock_client.post.return_value = {"success": True, "text": "summary", "results": []}

        # 1. RAG query and limit alias
        local_ai_rag(action="query", task="architecture query", limit=5, root=str(tmp_path))
        assert mock_client.post.called
        rag_calls = [c for c in mock_client.post.call_args_list if c[0][0] == "/api/rag/search"]
        assert len(rag_calls) >= 1
        rag_payload = rag_calls[0][0][1]
        assert rag_payload["query"] == "architecture query"
        assert rag_payload["top_k"] == 5

        # 2. Task summarize alias
        mock_client.post.reset_mock()
        mock_client.post.return_value = {"success": True, "text": "summary"}
        local_ai_task(action="summarize", context="long verbose output")
        assert mock_client.post.called
        compress_calls = [c for c in mock_client.post.call_args_list if c[0][0] == "/api/compress"]
        assert len(compress_calls) >= 1

        # 3. Status detail="models"
        mock_client.get.return_value = {
            "success": True,
            "data": [{"id": "qwen2.5-coder:7b"}],
        }
        res_models = local_ai_status(detail="models")
        assert res_models["success"] is True
        assert "installed_models" in res_models
        assert "qwen2.5-coder:7b" in res_models["installed_models"]


# ===========================================================================
# Phase 5 agent ergonomics regression tests
# ===========================================================================

# 1. callers/callees accept symbol= alias for query=
# ---------------------------------------------------------------------------

def test_callers_accepts_symbol_alias():
    """Agents often pass symbol= instead of query= for callers/callees."""
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.post.return_value = {"success": True, "callers": []}
        res = _local_ai_repo_impl(action="callers", root="/repo", symbol="MyClass.method")
        assert res.get("success") is True, f"callers should accept symbol= alias: {res}"
        payload = mc.post.call_args[0][1]
        assert payload["symbol"] == "MyClass.method"


def test_callees_accepts_symbol_alias():
    """Agents often pass symbol= instead of query= for callees."""
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.post.return_value = {"success": True, "callees": []}
        res = _local_ai_repo_impl(action="callees", root="/repo", symbol="utils.parse")
        assert res.get("success") is True, f"callees should accept symbol= alias: {res}"
        payload = mc.post.call_args[0][1]
        assert payload["symbol"] == "utils.parse"


def test_implementations_accepts_symbol_alias():
    """implementations also uses query= as symbol; symbol= should alias it."""
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.post.return_value = {"success": True, "implementations": []}
        res = _local_ai_repo_impl(action="implementations", root="/repo", symbol="IParser")
        assert res.get("success") is True, f"implementations should accept symbol= alias: {res}"
        payload = mc.post.call_args[0][1]
        assert payload["symbol"] == "IParser"


# ---------------------------------------------------------------------------
# 2. vision accepts path= / image_path= alias for image_artifact_id=
# ---------------------------------------------------------------------------

def test_vision_accepts_image_path_alias():
    """Agents may pass path= or image_path= for a local screenshot file."""
    with (
        patch.object(FEATURES, "tasks", True),
        patch.object(FEATURES, "vision", True),
        patch.object(FEATURES, "has_any_model", return_value=True),
        patch("local_ai_hub.mcp_server.CLIENT") as mc,
    ):
        mc.post.return_value = {"success": True, "text": "looks good"}
        # path= should map to image_artifact_id
        res = local_ai_task(
            action="vision",
            prompt="What is in this image?",
            path="/tmp/screen.png",
        )
        assert res.get("success") is True, f"vision should accept path= alias: {res}"
        vision_calls = [c for c in mc.post.call_args_list if "/api/task/vision" in str(c)]
        assert len(vision_calls) >= 1
        payload = vision_calls[0][0][1]
        assert payload.get("image_artifact_id") == "/tmp/screen.png"


def test_vision_accepts_image_path_named_alias():
    """Agents may pass image_path= for a screenshot file."""
    with (
        patch.object(FEATURES, "tasks", True),
        patch.object(FEATURES, "vision", True),
        patch.object(FEATURES, "has_any_model", return_value=True),
        patch("local_ai_hub.mcp_server.CLIENT") as mc,
    ):
        mc.post.return_value = {"success": True, "text": "chart detected"}
        res = local_ai_task(
            action="vision",
            prompt="Describe this chart",
            image_path="/screenshots/chart.png",
        )
        assert res.get("success") is True, f"vision should accept image_path= alias: {res}"
        vision_calls = [c for c in mc.post.call_args_list if "/api/task/vision" in str(c)]
        assert len(vision_calls) >= 1
        payload = vision_calls[0][0][1]
        assert payload.get("image_artifact_id") == "/screenshots/chart.png"


# ---------------------------------------------------------------------------
# 3. transcribe accepts audio_path= / path= / file= as alias for candidate=
# ---------------------------------------------------------------------------

def test_transcribe_accepts_audio_path_alias():
    """Agents use audio_path= for the audio file path in transcribe."""
    with (
        patch.object(FEATURES, "tasks", True),
        patch.object(FEATURES, "has_any_model", return_value=True),
        patch("local_ai_hub.mcp_server.CLIENT") as mc,
    ):
        mc.post.return_value = {"success": True, "text": "hello world"}
        res = local_ai_task(action="transcribe", audio_path="/recordings/meeting.mp3")
        assert res.get("success") is True, f"transcribe should accept audio_path= alias: {res}"
        transcribe_calls = [c for c in mc.post.call_args_list if "/api/task/transcribe" in str(c)]
        assert len(transcribe_calls) >= 1
        payload = transcribe_calls[0][0][1]
        assert payload.get("audio_path") == "/recordings/meeting.mp3"


def test_transcribe_accepts_path_alias():
    """Agents use path= for audio file path in transcribe."""
    with (
        patch.object(FEATURES, "tasks", True),
        patch.object(FEATURES, "has_any_model", return_value=True),
        patch("local_ai_hub.mcp_server.CLIENT") as mc,
    ):
        mc.post.return_value = {"success": True, "text": "meeting notes"}
        res = local_ai_task(action="transcribe", path="/audio/standup.ogg")
        assert res.get("success") is True, f"transcribe should accept path= alias: {res}"
        transcribe_calls = [c for c in mc.post.call_args_list if "/api/task/transcribe" in str(c)]
        assert len(transcribe_calls) >= 1
        payload = transcribe_calls[0][0][1]
        assert payload.get("audio_path") == "/audio/standup.ogg"


def test_transcribe_accepts_file_alias():
    """Agents use file= for audio file path in transcribe."""
    with (
        patch.object(FEATURES, "tasks", True),
        patch.object(FEATURES, "has_any_model", return_value=True),
        patch("local_ai_hub.mcp_server.CLIENT") as mc,
    ):
        mc.post.return_value = {"success": True, "text": "interview content"}
        res = local_ai_task(action="transcribe", file="/audio/interview.wav")
        assert res.get("success") is True, f"transcribe should accept file= alias: {res}"
        transcribe_calls = [c for c in mc.post.call_args_list if "/api/task/transcribe" in str(c)]
        assert len(transcribe_calls) >= 1
        payload = transcribe_calls[0][0][1]
        assert payload.get("audio_path") == "/audio/interview.wav"


# ---------------------------------------------------------------------------
# 4. complete_code: task= maps to prefix/context (not retired)
# ---------------------------------------------------------------------------

def test_complete_code_prompt_is_prefix():
    """complete_code sends prompt as prefix and candidate as suffix."""
    with (
        patch.object(FEATURES, "tasks", True),
        patch.object(FEATURES, "has_any_model", return_value=True),
        patch("local_ai_hub.mcp_server.CLIENT") as mc,
    ):
        mc.post.return_value = {"success": True, "completion": "    return x + y"}
        res = local_ai_task(action="complete_code", prompt="def add(x, y):\n", candidate="")
        assert res.get("success") is True, f"complete_code failed: {res}"
        comp_calls = [c for c in mc.post.call_args_list if "/api/complete" in str(c)]
        assert len(comp_calls) >= 1
        payload = comp_calls[0][0][1]
        assert payload.get("prefix") == "def add(x, y):\n"


# ---------------------------------------------------------------------------
# 5. callers arg error includes helpful suggestion
# ---------------------------------------------------------------------------

def test_callers_missing_query_gives_hint():
    """When agent calls callers without query, error should hint at query param."""
    with patch("local_ai_hub.mcp_server.CLIENT"):
        # Pass no query/symbol - should fail with hint
        res = _local_ai_repo_impl(action="callers", root="/repo")
        assert res.get("success") is False
        error_text = str(res.get("error", "")) + str(res.get("argument_help", ""))
        assert "query" in error_text or "symbol" in error_text, (
            f"Error should hint at query/symbol param: {res}"
        )


# ---------------------------------------------------------------------------
# 6. context_compile accepts changed_paths= alias for paths=
# ---------------------------------------------------------------------------

def test_context_compile_accepts_changed_paths_alias():
    """Agents use changed_paths= everywhere; context_compile should accept it as alias for paths=."""
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.post.return_value = {
            "success": True,
            "complete": True,
            "task_context": {"text": "compiled context", "complete": True, "success": True},
        }
        res = local_ai_coord(
            action="context_compile",
            task_id="task-123",
            root="/repo",
            changed_paths=["src/foo.py", "src/bar.py"],
        )
        assert res.get("success") is True, f"context_compile with changed_paths= failed: {res}"
        coord_calls = [c for c in mc.post.call_args_list if "/api/agent-state/context" in str(c)]
        assert len(coord_calls) >= 1
        payload = coord_calls[0][0][1]
        assert "src/foo.py" in payload.get("changed_paths", [])


# ---------------------------------------------------------------------------
# 7. review_diff accepts diff= string shortcut
# ---------------------------------------------------------------------------

def test_review_diff_accepts_diff_string():
    """Agents often want to review a diff string directly; diff= should be accepted."""
    diff_text = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.post.return_value = {"success": True, "findings": []}
        res = _local_ai_repo_impl(
            action="review_diff",
            root="/repo",
            diff=diff_text,
        )
        assert res.get("success") is True, f"review_diff should accept diff= string: {res}"
        rd_calls = [c for c in mc.post.call_args_list if "/api/review/diff" in str(c)]
        assert len(rd_calls) >= 1
        payload = rd_calls[0][0][1]
        # diff string should be forwarded as diff field
        assert payload.get("diff") == diff_text



# ===========================================================================
# PHASE 6 ERGONOMICS TESTS
# ===========================================================================

# ---------------------------------------------------------------------------
# 1. local_ai_task accepts code= and diff= for review
# ---------------------------------------------------------------------------

def test_task_review_accepts_code_and_diff():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc, \
         patch.object(FEATURES, "tasks", True), \
         patch.object(FEATURES, "has_any_model", return_value=True):
        mc.post.return_value = {"success": True, "text": "findings"}
        res = local_ai_task(action="review", code="def foo(): pass")
        assert res.get("success") is True, f"review with code= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/review" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("code") == "def foo(): pass"

        # Also test diff=
        mc.reset_mock()
        res = local_ai_task(action="review", diff="--- a/foo.py\n+++ b/foo.py\n")
        assert res.get("success") is True, f"review with diff= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/review" in str(c)]
        assert len(calls) >= 1
        assert "--- a/foo.py" in calls[0][0][1].get("code", "")


# ---------------------------------------------------------------------------
# 2. local_ai_task accepts problem= and query= for reason
# ---------------------------------------------------------------------------

def test_task_reason_accepts_problem_and_query():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc, \
         patch.object(FEATURES, "tasks", True), \
         patch.object(FEATURES, "has_any_model", return_value=True):
        mc.post.return_value = {"success": True, "text": "analysis ok"}
        res = local_ai_task(action="reason", problem="Why does test X fail?")
        assert res.get("success") is True, f"reason with problem= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/reason" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("problem") == "Why does test X fail?"

        mc.reset_mock()
        res = local_ai_task(action="reason", query="Why does test Y fail?")
        assert res.get("success") is True, f"reason with query= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/reason" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("problem") == "Why does test Y fail?"


# ---------------------------------------------------------------------------
# 3. local_ai_task accepts question= for second_opinion
# ---------------------------------------------------------------------------

def test_task_second_opinion_accepts_question():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc, \
         patch.object(FEATURES, "tasks", True), \
         patch.object(FEATURES, "has_any_model", return_value=True):
        mc.post.return_value = {"success": True, "text": "verdict ok"}
        res = local_ai_task(action="second_opinion", question="Is this secure?", candidate="def login(): ...")
        assert res.get("success") is True, f"second_opinion with question= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/second-opinion" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("question") == "Is this secure?"
        assert calls[0][0][1].get("candidate") == "def login(): ..."


# ---------------------------------------------------------------------------
# 4. local_ai_task accepts text= for compress
# ---------------------------------------------------------------------------

def test_task_compress_accepts_text():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc, \
         patch.object(FEATURES, "tasks", True), \
         patch.object(FEATURES, "has_any_model", return_value=True):
        mc.post.return_value = {"success": True, "text": "compressed"}
        res = local_ai_task(action="compress", text="Line 1\nLine 2\nLine 3")
        assert res.get("success") is True, f"compress with text= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/compress" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("text") == "Line 1\nLine 2\nLine 3"


# ---------------------------------------------------------------------------
# 5. local_ai_task accepts query= for explore and delegate
# ---------------------------------------------------------------------------

def test_task_explore_accepts_query():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc, \
         patch.object(FEATURES, "tasks", True), \
         patch.object(FEATURES, "has_any_model", return_value=True):
        mc.post.return_value = {"success": True, "text": "exploration"}
        res = local_ai_task(action="explore", query="How does caching work?")
        assert res.get("success") is True, f"explore with query= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/delegate" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("task") == "How does caching work?"


# ---------------------------------------------------------------------------
# 6. local_ai_artifact path= / file= redirects to source even with action='get'
# ---------------------------------------------------------------------------

def test_artifact_get_with_path_redirects_to_source(tmp_path):
    test_file = tmp_path / "app.py"
    test_file.write_text("def main(): pass\n", encoding="utf-8")
    with patch("local_ai_hub.mcp_server._workspace", str(tmp_path)):
        # Calling without action (defaults to get) + path
        res = local_ai_artifact(path="app.py")
        assert res.get("success") is True, f"artifact with path= failed: {res}"
        assert "def main" in res.get("text", "")

        # Calling with action='get' + file=
        res2 = local_ai_artifact(action="get", file="app.py")
        assert res2.get("success") is True, f"artifact with file= failed: {res2}"
        assert "def main" in res2.get("text", "")


# ---------------------------------------------------------------------------
# 7. local_ai_artifact accepts id= alias for artifact_id=
# ---------------------------------------------------------------------------

def test_artifact_accepts_id_alias():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.post.return_value = {
            "success": True,
            "artifact_id": "art-12345",
            "kind": "text",
            "text": "data",
            "offset": 0,
            "next_offset": None,
            "total_chars": 4,
            "sections": [],
        }
        res = local_ai_artifact(action="get", id="art-12345")
        assert res.get("success") is True, f"artifact with id= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/artifact/get" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("artifact_id") == "art-12345"


# ---------------------------------------------------------------------------
# 8. local_ai_coord accepts path= and file= for single-path operations
# ---------------------------------------------------------------------------

def test_coord_accepts_path_and_file_for_single_path():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.post.return_value = {"success": True, "lease_id": "L1"}
        res = local_ai_coord(action="claim", root="/repo", path="src/main.py", owner="agent")
        assert res.get("success") is True, f"claim with path= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/leases/claim_batch" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("paths") == ["src/main.py"]

        mc.reset_mock()
        res = local_ai_coord(action="claim", root="/repo", file="src/main.py", owner="agent")
        assert res.get("success") is True, f"claim with file= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/leases/claim_batch" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("paths") == ["src/main.py"]


# ---------------------------------------------------------------------------
# 9. local_ai_coord task_create accepts title= and description=
# ---------------------------------------------------------------------------

def test_coord_task_create_accepts_title_and_description():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.coord.return_value = {"success": True, "task_id": "T1"}
        res = local_ai_coord(action="task_create", root="/repo", title="Fix memory leak")
        assert res.get("success") is True, f"task_create with title= failed: {res}"
        assert mc.coord.call_count >= 1
        contract = mc.coord.call_args[1].get("contract", {})
        assert contract.get("goal") == "Fix memory leak"

        mc.reset_mock()
        res = local_ai_coord(action="task_create", root="/repo", description="Refactor router")
        assert res.get("success") is True, f"task_create with description= failed: {res}"
        assert mc.coord.call_count >= 1
        contract = mc.coord.call_args[1].get("contract", {})
        assert contract.get("goal") == "Refactor router"


# ---------------------------------------------------------------------------
# 10. local_ai_coord memory_record accepts content= and name=
# ---------------------------------------------------------------------------

def test_coord_memory_record_accepts_content_and_name():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.coord.return_value = {"success": True, "memory_id": "M1"}
        res = local_ai_coord(action="memory_record", root="/repo", name="api_key_format", content="Starts with sk-")
        assert res.get("success") is True, f"memory_record with name/content failed: {res}"
        assert mc.coord.call_count >= 1
        kwargs = mc.coord.call_args[1]
        assert kwargs.get("key") == "api_key_format"
        assert kwargs.get("value") == "Starts with sk-"


# ---------------------------------------------------------------------------
# 11. local_ai_rag accepts name= for docsets and retrieve/find action aliases
# ---------------------------------------------------------------------------

def test_rag_accepts_name_and_action_aliases():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc, \
         patch.object(FEATURES, "rag", True):
        mc.post.return_value = {"success": True, "results": []}
        res = local_ai_rag(action="docset_search", name="developer_docs", query="architecture")
        assert res.get("success") is True, f"docset_search with name= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/rag/docset/search" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("name") == "developer_docs"

        mc.reset_mock()
        res = local_ai_rag(action="retrieve", root="C:\\fake_repo", query="how to run")
        assert res.get("success") is True, f"rag with retrieve failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/rag/search" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("query") == "how to run"


# ---------------------------------------------------------------------------
# 12. local_ai_repo accepts file= and paths=, and generate_tests_for_diff with changed_paths
# ---------------------------------------------------------------------------

def test_repo_accepts_file_paths_and_changed_paths():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.post.return_value = {"success": True, "tests": "def test_new(): pass"}
        res = _local_ai_repo_impl(action="generate_tests_for_diff", root="/repo", changed_paths=["src/logic.py"])
        assert res.get("success") is True, f"generate_tests_for_diff with changed_paths failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/repo/generate_tests_for_diff" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("path") == "src/logic.py"

        # local_ai_repo git_diff with file=
        mc.reset_mock()
        mc.get.return_value = {"success": True, "diff": "diff content"}
        res = local_ai_repo(action="git_diff", root="/repo", file="src/model.py")
        assert res.get("success") is True, f"git_diff with file= failed: {res}"


# ===========================================================================
# PHASE 7 ERGONOMICS TESTS
# ===========================================================================

# ---------------------------------------------------------------------------
# 1. local_ai_coord task_checkpoint accepts next_action, blockers, evidence_ids
# ---------------------------------------------------------------------------

def test_coord_checkpoint_accepts_next_action_blockers_evidence():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.coord.return_value = {"success": True, "task": {"task_id": "T1"}}
        res = local_ai_coord(
            action="task_checkpoint",
            task_id="T1",
            root="/repo",
            phase="build",
            next_action="run tests",
            blockers=["PR pending"],
            evidence_ids=["E100"],
        )
        assert res.get("success") is True, f"task_checkpoint with next_action failed: {res}"
        assert mc.coord.call_count >= 1
        cp = mc.coord.call_args[1].get("checkpoint", {})
        assert cp.get("next_action") == "run tests"
        assert cp.get("blockers") == ["PR pending"]
        assert cp.get("evidence_ids") == ["E100"]


# ---------------------------------------------------------------------------
# 2. local_ai_coord accepts id= alias for task_get and task actions
# ---------------------------------------------------------------------------

def test_coord_accepts_id_alias_for_task_get():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.coord.return_value = {"success": True, "task": {"task_id": "T-456"}}
        res = local_ai_coord(action="task_get", root="/repo", id="T-456")
        assert res.get("success") is True, f"task_get with id= failed: {res}"
        assert mc.coord.call_count >= 1
        assert mc.coord.call_args[1].get("task_id") == "T-456"


# ---------------------------------------------------------------------------
# 3. local_ai_coord accepts summary= and result= for task_complete
# ---------------------------------------------------------------------------

def test_coord_accepts_summary_for_task_complete():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.coord.return_value = {"success": True, "task": {"task_id": "T1", "status": "completed"}}
        res = local_ai_coord(action="task_complete", root="/repo", task_id="T1", summary="All tests passed")
        assert res.get("success") is True, f"task_complete with summary= failed: {res}"
        assert mc.coord.call_count >= 1
        assert mc.coord.call_args[1].get("reason") == "All tests passed"


# ---------------------------------------------------------------------------
# 4. local_ai_coord accepts timeout_seconds= for wait_for_event & semaphores
# ---------------------------------------------------------------------------

def test_coord_accepts_timeout_seconds():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.coord.return_value = {"success": True, "event": None}
        res = local_ai_coord(action="wait_for_event", root="/repo", topic="deploy", timeout_seconds=45.0)
        assert res.get("success") is True, f"wait_for_event with timeout_seconds= failed: {res}"
        assert mc.coord.call_count >= 1
        assert mc.coord.call_args[1].get("timeout") == 45.0


# ---------------------------------------------------------------------------
# 5. local_ai_coord board_item_create accepts task_id and string labels
# ---------------------------------------------------------------------------

def test_coord_board_item_accepts_task_id_and_string_labels():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.coord.return_value = {"success": True, "item_id": "BI-1"}
        res = local_ai_coord(
            action="board_item_create",
            root="/repo",
            title="Implement feature",
            task_id="T-123",
            labels="frontend",
        )
        assert res.get("success") is True, f"board_item_create failed: {res}"
        assert mc.coord.call_count >= 1
        kwargs = mc.coord.call_args[1]
        assert kwargs.get("linked_task_id") == "T-123"
        assert kwargs.get("labels") == ["frontend"]


# ---------------------------------------------------------------------------
# 6. local_ai_artifact accepts root= and workspace= parameters
# ---------------------------------------------------------------------------

def test_artifact_accepts_root_and_workspace(tmp_path):
    sub = tmp_path / "subrepo"
    sub.mkdir()
    f = sub / "test.py"
    f.write_text("print('hello')\n", encoding="utf-8")
    res = local_ai_artifact(root=str(sub), path="test.py")
    assert res.get("success") is True, f"artifact with root= failed: {res}"
    assert "hello" in res.get("text", "")


# ---------------------------------------------------------------------------
# 7. local_ai_repo structural_search accepts pattern= alias
# ---------------------------------------------------------------------------

def test_repo_structural_search_accepts_pattern():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.post.return_value = {"success": True, "matches": []}
        res = local_ai_repo(action="structural_search", root="/repo", pattern="console.log($A)")
        assert res.get("success") is True, f"structural_search with pattern= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/repo/structural_search" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("pattern") == "console.log($A)"


# ---------------------------------------------------------------------------
# 8. local_ai_repo batch_replace accepts single target/replacement without edits= list
# ---------------------------------------------------------------------------

def test_repo_batch_replace_accepts_single_target_replacement():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc, \
         patch.object(FEATURES, "batch_replacement", True):
        mc.post.return_value = {"success": True, "applied": 1}
        res = local_ai_repo(action="batch_replace", root="/repo", path="app.py", target="old_val", replacement="new_val")
        assert res.get("success") is True, f"batch_replace with target/replacement failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/code/batch_replace" in str(c)]
        assert len(calls) >= 1
        edits = calls[0][0][1].get("edits", [])
        assert len(edits) == 1
        assert edits[0]["target"] == "old_val"
        assert edits[0]["replacement"] == "new_val"


# ---------------------------------------------------------------------------
# 9. local_ai_repo git_status path filtering
# ---------------------------------------------------------------------------

def test_repo_git_status_path_filtering():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.get.return_value = {
            "success": True,
            "branch": "master",
            "clean": False,
            "files": ["src/app.py", "src/util.py", "docs/guide.md"],
        }
        # Path filter for src/
        res = _local_ai_repo_impl(action="git_status", root="/repo", path="src/")
        assert res.get("success") is True
        assert len(res.get("files", [])) == 2
        assert "docs/guide.md" not in res.get("files", [])
        assert res.get("clean") is False

        # Path filter for tests/ (should be clean)
        res_empty = _local_ai_repo_impl(action="git_status", root="/repo", path="tests/")
        assert res_empty.get("success") is True
        assert len(res_empty.get("files", [])) == 0
        assert res_empty.get("clean") is True


# ---------------------------------------------------------------------------
# 10. local_ai_rag accepts text= for search and ingest_document
# ---------------------------------------------------------------------------

def test_rag_accepts_text_for_search_and_ingest():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc, \
         patch.object(FEATURES, "rag", True):
        mc.post.return_value = {"success": True, "results": []}
        res = local_ai_rag(action="search", root="C:\\fake_repo", text="authentication flow")
        assert res.get("success") is True, f"rag search with text= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/rag/search" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("query") == "authentication flow"

        mc.reset_mock()
        mc.post.return_value = {"success": True, "doc_id": "D1"}
        res2 = local_ai_rag(action="ingest_document", root="C:\\fake_repo", text="full doc content")
        assert res2.get("success") is True, f"rag ingest with text= failed: {res2}"
        calls2 = [c for c in mc.post.call_args_list if "/api/rag/ingest_document" in str(c)]
        assert len(calls2) >= 1
        assert calls2[0][0][1].get("content") == "full doc content"


# ---------------------------------------------------------------------------
# 11. local_ai_task accepts chat and ask action aliases
# ---------------------------------------------------------------------------

def test_task_accepts_chat_and_ask_aliases():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc, \
         patch.object(FEATURES, "tasks", True), \
         patch.object(FEATURES, "has_any_model", return_value=True):
        mc.post.return_value = {"success": True, "text": "I can help with that"}
        res = local_ai_task(action="ask", query="how to configure routing?")
        assert res.get("success") is True, f"local_ai_task with action='ask' failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/delegate" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("task") == "how to configure routing?"


# ---------------------------------------------------------------------------
# 12. local_ai_coord record_native_receipt accepts summary=
# ---------------------------------------------------------------------------

def test_coord_record_native_receipt_accepts_summary():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.post.return_value = {"success": True, "verified": True}
        res = local_ai_coord(
            action="record_native_receipt",
            root="/repo",
            task_id="T1",
            criterion="C1",
            command="pytest",
            summary="All 10 passed",
        )
        assert res.get("success") is True, f"record_native_receipt with summary failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/agent-state/verification" in str(c)]
        assert len(calls) >= 1
        assert calls[0][0][1].get("output_summary") == "All 10 passed"


# ===========================================================================
# Phase 8: Agent Ergonomics & Resilience Tests
# ===========================================================================

# ---------------------------------------------------------------------------
# 1. local_ai_status accepts root= and workspace=
# ---------------------------------------------------------------------------

def test_status_accepts_root_and_workspace():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.get.return_value = {"success": True, "hub_online": True, "version": "5.1.0"}
        res = local_ai_status(root="C:\fake_repo", workspace="C:\fake_repo")
        assert res.get("success") is True, f"status with root/workspace failed: {res}"


# ---------------------------------------------------------------------------
# 2. local_ai_status accepts action= aliases (health, check, ping)
# ---------------------------------------------------------------------------

def test_status_accepts_health_ping_check():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.get.return_value = {"success": True, "hub_online": True}
        res_health = local_ai_status(action="health")
        assert res_health.get("success") is True
        res_ping = local_ai_status(action="ping")
        assert res_ping.get("success") is True


# ---------------------------------------------------------------------------
# 3. local_ai_work accepts id= alias for work_id
# ---------------------------------------------------------------------------

def test_work_accepts_id_alias_and_goal():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc,          patch.object(FEATURES, "work_orchestrator", True):
        mc.post.return_value = {"success": True, "work_id": "W-123", "status": "running"}
        res_get = local_ai_work(action="get", id="W-123")
        assert res_get.get("success") is True, f"work get with id= failed: {res_get}"
        calls = [c for c in mc.post.call_args_list if "/api/work-orders" in str(c)]
        assert len(calls) >= 1
        assert calls[-1][0][1].get("work_id") == "W-123"

        # submit with goal= and single string acceptance_criteria
        mc.post.return_value = {"success": True, "work_id": "W-124"}
        res_sub = local_ai_work(action="submit", goal="Build parser", acceptance_criteria="All tests pass")
        assert res_sub.get("success") is True
        payload = mc.post.call_args_list[-1][0][1]
        assert payload.get("task") == "Build parser"
        assert payload.get("acceptance_criteria") == ["All tests pass"]


# ---------------------------------------------------------------------------
# 4. local_ai_coord task_create string tolerance and criterion alias
# ---------------------------------------------------------------------------

def test_coord_task_create_string_criteria_and_criterion():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.coord.return_value = {"success": True, "task_id": "T-99"}
        # Single string acceptance_criteria
        res = local_ai_coord(action="task_create", root="/repo", goal="Fix bug", acceptance_criteria="pytest passes")
        assert res.get("success") is True, f"task_create with string acceptance_criteria failed: {res}"
        contract = mc.coord.call_args[1].get("contract", {})
        assert contract.get("acceptance_criteria") == ["pytest passes"]

        # criterion= alias
        mc.reset_mock()
        res2 = local_ai_coord(action="task_create", root="/repo", goal="Fix bug 2", criterion="mypy passes")
        assert res2.get("success") is True, f"task_create with criterion failed: {res2}"
        contract2 = mc.coord.call_args[1].get("contract", {})
        assert contract2.get("acceptance_criteria") == ["mypy passes"]


# ---------------------------------------------------------------------------
# 5. local_ai_coord task_checkpoint accepts notes and state_data
# ---------------------------------------------------------------------------

def test_coord_checkpoint_accepts_notes_and_state_data():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.coord.return_value = {"success": True, "task": {"task_id": "T-1"}}
        res = local_ai_coord(
            action="task_checkpoint",
            task_id="T-1",
            root="/repo",
            notes="Refactored internal state",
            state_data={"step": 2},
        )
        assert res.get("success") is True, f"checkpoint with notes/state_data failed: {res}"
        cp = mc.coord.call_args[1].get("checkpoint", {})
        assert cp.get("next_action") == "Refactored internal state"
        assert cp.get("state_data") == {"step": 2}


# ---------------------------------------------------------------------------
# 6. local_ai_coord semaphore_acquire accepts resource= alias
# ---------------------------------------------------------------------------

def test_coord_semaphore_accepts_resource_alias():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.coord.return_value = {"success": True, "acquired": True}
        res = local_ai_coord(action="semaphore_acquire", root="/repo", resource="gpu_lock")
        assert res.get("success") is True, f"semaphore_acquire with resource= failed: {res}"
        kwargs = mc.coord.call_args[1]
        assert kwargs.get("name") == "gpu_lock"


# ---------------------------------------------------------------------------
# 7. local_ai_coord task_list accepts state= alias for status
# ---------------------------------------------------------------------------

def test_coord_task_list_accepts_state_alias():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        mc.coord.return_value = {"success": True, "tasks": []}
        res = local_ai_coord(action="task_list", root="/repo", state="active")
        assert res.get("success") is True, f"task_list with state= failed: {res}"
        kwargs = mc.coord.call_args[1]
        assert kwargs.get("status") == "active"


# ---------------------------------------------------------------------------
# 8. local_ai_task batch accepts items= alias for tasks
# ---------------------------------------------------------------------------

def test_task_batch_accepts_items_alias():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc,          patch.object(FEATURES, "tasks", True),          patch.object(FEATURES, "has_any_model", return_value=True):
        mc.post.return_value = {"success": True, "results": []}
        res = local_ai_task(action="batch", items=[{"task": "subtask 1"}])
        assert res.get("success") is True, f"batch with items= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/delegate/batch" in str(c)]
        assert len(calls) >= 1
        assert calls[-1][0][1].get("tasks") == [{"task": "subtask 1"}]


# ---------------------------------------------------------------------------
# 9. local_ai_task action="code_review" aliases to "review"
# ---------------------------------------------------------------------------

def test_task_code_review_alias():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc,          patch.object(FEATURES, "tasks", True),          patch.object(FEATURES, "has_any_model", return_value=True):
        mc.post.return_value = {"success": True, "text": "Looks good", "analysis": "Looks good"}
        res = local_ai_task(action="code_review", code="def test(): pass")
        assert res.get("success") is True, f"code_review failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/review" in str(c)]
        assert len(calls) >= 1


# ---------------------------------------------------------------------------
# 10. local_ai_repo symbol navigation aliases (definition, references, find_symbol)
# ---------------------------------------------------------------------------

def test_repo_symbol_navigation_aliases():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc:
        # definition -> declaration
        mc.post.return_value = {"success": True, "path": "src/app.py", "line": 10}
        res_def = _local_ai_repo_impl(action="definition", root="/repo", query="User")
        assert res_def.get("success") is True
        calls = [c for c in mc.post.call_args_list if "/api/code/declaration" in str(c)]
        assert len(calls) >= 1

        # references -> callers
        mc.post.return_value = {"success": True, "callers": []}
        res_ref = _local_ai_repo_impl(action="references", root="/repo", query="User")
        assert res_ref.get("success") is True
        calls = [c for c in mc.post.call_args_list if "/api/repo/callers" in str(c)]
        assert len(calls) >= 1

        # find_symbol -> code_index
        mc.post.return_value = {"success": True, "symbols": []}
        res_sym = _local_ai_repo_impl(action="find_symbol", root="/repo", query="User")
        assert res_sym.get("success") is True
        calls = [c for c in mc.post.call_args_list if "/api/repo/code-index" in str(c)]
        assert len(calls) >= 1


# ---------------------------------------------------------------------------
# 11. local_ai_rag ingest_diagram accepts path/file as image_path
# ---------------------------------------------------------------------------

def test_rag_ingest_diagram_accepts_path():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc,          patch.object(FEATURES, "rag", True):
        mc.post.return_value = {"success": True, "diagram_id": "D1"}
        res = local_ai_rag(action="ingest_diagram", root="C:\fake_repo", path="architecture.png")
        assert res.get("success") is True, f"ingest_diagram with path= failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/rag/ingest_diagram" in str(c)]
        assert len(calls) >= 1
        assert calls[-1][0][1].get("image_path") == "architecture.png"


# ---------------------------------------------------------------------------
# 12. local_ai_rag ingest aliases (ingest -> ingest_document, search_docset -> docset_search)
# ---------------------------------------------------------------------------

def test_rag_action_aliases():
    with patch("local_ai_hub.mcp_server.CLIENT") as mc,          patch.object(FEATURES, "rag", True):
        # ingest -> ingest_document
        mc.post.return_value = {"success": True, "document_id": "DOC1"}
        res = local_ai_rag(action="ingest", root="C:\fake_repo", content="# My Doc")
        assert res.get("success") is True, f"rag action=ingest failed: {res}"
        calls = [c for c in mc.post.call_args_list if "/api/rag/ingest_document" in str(c)]
        assert len(calls) >= 1

        # search_docset -> docset_search
        mc.post.return_value = {"success": True, "results": []}
        res2 = local_ai_rag(action="search_docset", root="C:\fake_repo", query="setup guide")
        assert res2.get("success") is True, f"rag action=search_docset failed: {res2}"
        calls = [c for c in mc.post.call_args_list if "/api/rag/docset/search" in str(c)]
        assert len(calls) >= 1
