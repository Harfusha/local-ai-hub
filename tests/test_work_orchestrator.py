from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from local_ai_hub.response_protocol import project_response
from local_ai_hub.app import LocalAIApp
from local_ai_hub import http_server
from local_ai_hub.services import LocalAIServices
from local_ai_hub.work_orchestrator import WorkOrchestrator, _patch_changes, _patch_paths, _stable_toposort_steps
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.project_config import resolve_project_context


class FakeArtifacts:
    def __init__(self): self.data = {}
    def put(self, text, *, kind):
        key = f"a{len(self.data)+1}"
        self.data[key] = {"text": text, "kind": kind}
        return key
    def get(self, artifact_id, *, max_chars=50_000):
        artifact = self.data.get(artifact_id)
        if artifact is None:
            return {"success": False, "artifact_id": artifact_id}
        return {
            "success": True,
            "artifact_id": artifact_id,
            "kind": artifact["kind"],
            "text": artifact["text"][:max_chars],
            "next_offset": None,
        }


class FakeLeases:
    def claim_batch(self, owner, root, paths, ttl_seconds=900, purpose="", *, coordination_id=None):
        self.coordination_id = coordination_id
        return {"success": True, "lease_id": "lease1", "paths": paths}
    def release(self, *, owner, lease_id=""):
        return {"success": True}


class FakeServices:
    def __init__(self, patch: str, validation_ok: bool = True):
        self.patch = patch
        self.validation_ok = validation_ok
        self.delegate_calls = 0
        self.verify_calls = 0

    def repo_profile(self, root): return {"success": True, "validation_commands": ["git diff --check"]}
    def repo_map(self, root, max_symbols=80): return {"success": True, "files": ["a.txt"]}
    def test_matrix(self, root): return {"success": True, "commands": ["git diff --check"]}
    def deterministic_query(self, root, query, limit=24): return {"success": True, "facts": []}
    def code_query(self, root, query, limit=20): return {"success": True, "symbols": []}
    def fast_context(self, root, query, max_tokens): return {"success": True, "evidence": []}
    def repo_diff(self, root, base="HEAD", staged=False, max_tokens=5000):
        cp = subprocess.run(["git", "-C", root, "diff"], capture_output=True, text=True, check=False)
        return {"success": True, "diff": cp.stdout}
    def delegate_repo(self, args):
        self.delegate_calls += 1
        if self.delegate_calls == 1:
            plan = {
                "summary": "change a.txt safely", "needs_agent": False,
                "steps": [
                    {"id":"s1","kind":"inspect","task":"inspect a.txt","depends_on":[],"acceptance":[]},
                    {"id":"s2","kind":"edit","task":"change old to new","depends_on":["s1"],"acceptance":["a.txt contains new"]},
                    {"id":"s3","kind":"validate","task":"validate diff","depends_on":["s2"],"acceptance":["a.txt contains new"]},
                    {"id":"s4","kind":"review","task":"review integrated change","depends_on":["s3"],"acceptance":["a.txt contains new"]},
                ],
                "validation_commands": ["git diff --check"],
            }
            return {"success": True, "text": json.dumps(plan)}
        return {"success": True, "text": self.patch}
    def second_opinion(self, args):
        self.verify_calls += 1
        return {"success": True, "text": json.dumps({
            "passed": True, "summary": "verified", "criteria": [{"criterion":"a.txt contains new","passed":True}], "risks": []
        })}
    def command(self, args):
        if args.get("action") == "discover":
            return {"success": True, "validation_commands": ["git diff --check"]}
        return {"success": self.validation_ok, "exit_code": 0 if self.validation_ok else 1, "error": "" if self.validation_ok else "failed"}




def config(state: Path):
    return {"work_orchestrator": {"enabled": True, "max_steps": 16, "max_llm_steps": 10, "max_seconds": 60, "step_retry_limit": 0}}


def init_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"; root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "a.txt").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-qm", "init"], check=True)
    return root


def owned_verification_context(tmp_path: Path, root: Path, artifacts: FakeArtifacts, task_id: str):
    state_store = AgentStateStore(tmp_path / "agent-state.sqlite3")
    tasks = TaskStore(state_store)
    coordination_id = resolve_project_context(str(root), tmp_path / "project-state").coordination_id
    tasks.create(
        GoalContract(goal="verified work order", acceptance_criteria=["work order verified"]),
        ScopeContext(repository_id=coordination_id),
        task_id=task_id,
        actor="work-order-owner",
        repo_root=str(root),
    )
    return VerificationStore(state_store, task_store=tasks, artifact_store=artifacts)


def wait_terminal(wo: WorkOrchestrator, wid: str, timeout=8):
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = wo.get(wid, profile="debug")
        if res.get("status") in {"complete", "failed", "cancelled", "needs_agent", "partial"}:
            return res
        time.sleep(0.05)
    raise AssertionError(wo.get(wid, profile="debug"))




def test_planner_dag_is_stably_toposorted_and_cycles_fail_closed():
    steps = [
        {"id": "review", "depends_on": ["validate"]},
        {"id": "edit", "depends_on": ["inspect"]},
        {"id": "inspect", "depends_on": []},
        {"id": "validate", "depends_on": ["edit"]},
    ]
    ordered = _stable_toposort_steps(steps)
    assert [step["id"] for step in ordered] == ["inspect", "edit", "validate", "review"]

    with pytest.raises(ValueError, match="cyclic step dependencies"):
        _stable_toposort_steps([
            {"id": "a", "depends_on": ["b"]},
            {"id": "b", "depends_on": ["a"]},
        ])

    with pytest.raises(ValueError, match="unknown step dependencies"):
        _stable_toposort_steps([{"id": "edit", "depends_on": ["missing"]}])

    with pytest.raises(ValueError, match="self dependency"):
        _stable_toposort_steps([{"id": "edit", "depends_on": ["edit"]}])

    with pytest.raises(ValueError, match="duplicate planner step ids"):
        _stable_toposort_steps([{"id": "edit", "depends_on": []}, {"id": "edit", "depends_on": []}])


def test_planner_rejects_unknown_step_kind_and_missing_acceptance(tmp_path):
    class UnknownKindServices(FakeServices):
        def delegate_repo(self, args):
            return {"success": True, "text": json.dumps({
                "summary": "unknown planner kind",
                "steps": [{"id": "s1", "kind": "unknown", "task": "inspect", "depends_on": [], "acceptance": []}],
            })}

    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", UnknownKindServices(""), None, FakeLeases(), FakeArtifacts())
    try:
        with pytest.raises(ValueError, match="explicit acceptance criteria"):
            wo._plan(str(tmp_path), "inspect", {"budget": {"max_steps": 16}, "acceptance_criteria": []}, {})
        with pytest.raises(ValueError, match="unknown planner step kind"):
            wo._plan(str(tmp_path), "inspect", {"budget": {"max_steps": 16}, "acceptance_criteria": ["inspect result"]}, {})
    finally:
        wo.close()


def test_planner_enforces_edit_and_command_budgets_and_retains_acceptance(tmp_path):
    class BudgetPlanServices(FakeServices):
        def delegate_repo(self, args):
            return {"success": True, "text": json.dumps({
                "summary": "bounded plan",
                "steps": [
                    {"id": "inspect", "kind": "inspect", "task": "inspect", "depends_on": [], "acceptance": []},
                    {"id": "edit", "kind": "edit", "task": "edit", "depends_on": ["inspect"], "acceptance": []},
                ],
                "validation_commands": ["python -m pytest -q"],
            })}

    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", BudgetPlanServices(""), None, FakeLeases(), FakeArtifacts())
    try:
        base = {"budget": {"max_steps": 2, "max_edits": 0, "max_commands": 1}, "acceptance_criteria": ["result remains correct"]}
        for name, value in (
            ("max_steps", True), ("max_steps", 1.5),
            ("max_tokens", True), ("max_tokens", 1.5),
            ("max_edits", True), ("max_edits", 1.5),
            ("max_commands", True), ("max_commands", 1.5),
        ):
            invalid_budget = {"budget": {"max_steps": 2, "max_edits": 1, "max_commands": 1, "max_tokens": 1400}, "acceptance_criteria": ["result remains correct"]}
            invalid_budget["budget"][name] = value
            with pytest.raises(ValueError, match=f"{name} budget must be an integer"):
                wo._plan(str(tmp_path), "bounded change", invalid_budget, {})

        with pytest.raises(ValueError, match="edit-step budget"):
            wo._plan(str(tmp_path), "bounded change", base, {})

        command_limited = {"budget": {"max_steps": 2, "max_edits": 1, "max_commands": 0}, "acceptance_criteria": ["result remains correct"]}
        with pytest.raises(ValueError, match="command budget"):
            wo._plan(str(tmp_path), "bounded change", command_limited, {})

        step_limited = {"budget": {"max_steps": 1}, "acceptance_criteria": ["result remains correct"]}
        with pytest.raises(ValueError, match="more than the 1 step budget"):
            wo._plan(str(tmp_path), "bounded change", step_limited, {})

        accepted = {"budget": {"max_steps": 2, "max_edits": 1, "max_commands": 1}, "acceptance_criteria": ["result remains correct"]}
        plan = wo._plan(str(tmp_path), "bounded change", accepted, {})
        assert plan["acceptance_criteria"] == ["result remains correct"]
        assert all(step["acceptance"] == ["result remains correct"] for step in plan["steps"])
        assert plan["validation_commands"] == ["python -m pytest -q"]
    finally:
        wo.close()


def test_planner_rejects_duplicate_ids_instead_of_sanitizing(tmp_path):
    class OddPlanServices(FakeServices):
        def delegate_repo(self, args):
            return {"success": True, "text": json.dumps({
                "summary": "odd planner output",
                "steps": [
                    {"id": "dup", "kind": "inspect", "task": "first", "depends_on": [], "acceptance": "not-a-list"},
                    {"id": "dup", "kind": "review", "task": "second", "depends_on": [], "acceptance": []},
                    {"id": "   ", "kind": "unknown", "task": "", "depends_on": [], "acceptance": []},
                ],
            })}
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", OddPlanServices(""), None, FakeLeases(), FakeArtifacts())
    try:
        payload = {"budget": {"max_steps": 16}, "acceptance_criteria": ["keep explicit acceptance"], "constraints": []}
        with pytest.raises(ValueError, match="duplicate planner step ids"):
            wo._plan(str(tmp_path), "inspect", payload, {})
    finally:
        wo.close()


def test_work_id_is_bounded_before_persistence(tmp_path):
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    root = init_repo(tmp_path)
    try:
        result = wo.submit({"root": str(root.resolve()), "task": "inspect", "work_id": "x" * 129})
        assert result["success"] is False
        assert "128" in result["error"]
        assert wo.stats()["states"] == {}
    finally:
        wo.close()


@pytest.mark.parametrize("extra", [
    {},
    {"acceptance_criteria": ["done"], "budget": {"max_steps": 17}},
    {"acceptance_criteria": ["done"], "budget": {"max_steps": True}},
    {"acceptance_criteria": ["done"], "budget": []},
    {"acceptance_criteria": ["done"], "budget": None},
    {"acceptance_criteria": ["done"], "budget": {"max_tokens": True}},
    {"acceptance_criteria": ["done"], "budget": {"max_steps": 2, "max_edits": 3}},
    {"acceptance_criteria": ["done"], "budget": {"max_commands": -1}},
    {"acceptance_criteria": ["done"], "budget": {"max_llm_calls": False}},
    {"acceptance_criteria": ["done"], "budget": {"max_llm_calls": 0}},
    {"acceptance_criteria": ["done"], "budget": {"max_llm_calls": None}},
    {"acceptance_criteria": ["done"], "budget": {"max_seconds": 29}},
    {"acceptance_criteria": ["done"], "budget": {"max_seconds": 7201}},
    {"acceptance_criteria": ["done"], "budget": {"max_seconds": 1.5}},
    {"acceptance_criteria": ["done"], "budget": {"max_time": 50}},
    {"acceptance_criteria": [42]},
    {"acceptance_criteria": ["done"], "permissions": {"edit": "false"}},
    {"acceptance_criteria": ["done"], "permissions": {"network": 0}},
    {"acceptance_criteria": ["done"], "permissions": {"unknown": False}},
    {"acceptance_criteria": ["done"], "permissions": None},
    {"acceptance_criteria": ["done"], "mode": False},
    {"acceptance_criteria": ["done"], "mode": None},
    {"acceptance_criteria": ["done"], "mode": ""},
    {"acceptance_criteria": ["done"], "permissions": {"read": False}},
    {"acceptance_criteria": ["done"], "permissions": {"tests": False}},
    {"acceptance_criteria": ["done"], "permissions": {"build": False}},
    {"acceptance_criteria": ["done"], "keep_failed_workspace": "false"},
    {"acceptance_criteria": ["done"], "keep_failed_workspace": None},
    {"acceptance_criteria": ["done"], "keep_failed_workspace": 0},
])
def test_submit_rejects_invalid_contract_before_enqueue(tmp_path, monkeypatch, extra):
    wo = WorkOrchestrator({"work_orchestrator": {"enabled": True}}, tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(wo, "_ensure_workers", lambda: None)
    try:
        result = wo.submit({"root": str(tmp_path.resolve()), "task": "inspect", **extra})
        assert result["success"] is False
        assert result.get("terminal") is True
        assert wo.stats()["states"] == {}
    finally:
        wo.close()


def test_submit_default_step_budget_is_accepted_by_planner(tmp_path, monkeypatch):
    wo = WorkOrchestrator({"work_orchestrator": {"enabled": True}}, tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(wo, "_ensure_workers", lambda: None)
    try:
        result = wo.submit({"root": str(tmp_path.resolve()), "task": "inspect", "acceptance_criteria": ["done"]})
        assert result["success"] is True
        payload = json.loads(wo._row(result["work_id"])["payload_json"])
        assert 1 <= payload["budget"]["max_steps"] <= 16
        assert wo._plan(str(tmp_path), "inspect", payload, {})["steps"]
    finally:
        wo.close()


@pytest.mark.parametrize('task', [None, False, 123, [], 'bad\x00task', 'x' * 24001], ids=['null', 'bool', 'number', 'list', 'nul', 'oversized'])
def test_submit_rejects_invalid_task_before_enqueue(tmp_path, monkeypatch, task):
    wo = WorkOrchestrator({"work_orchestrator": {"enabled": True}}, tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(wo, "_ensure_workers", lambda: None)
    try:
        result = wo.submit({"root": str(tmp_path.resolve()), "task": task, "acceptance_criteria": ["done"]})
        assert result["success"] is False
        assert wo.stats()["states"] == {}
    finally:
        wo.close()


def test_submit_preserves_explicit_planner_budgets(tmp_path, monkeypatch):
    wo = WorkOrchestrator({"work_orchestrator": {"enabled": True}}, tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(wo, "_ensure_workers", lambda: None)
    budget = {"max_steps": 8, "max_edits": 0, "max_commands": 1, "max_tokens": 512, "max_llm_calls": 2, "max_seconds": 60}
    try:
        result = wo.submit({"root": str(tmp_path.resolve()), "task": "inspect", "acceptance_criteria": ["done"], "budget": budget})
        assert result["success"] is True
        stored = json.loads(wo._row(result["work_id"])["payload_json"])["budget"]
        assert all(stored[key] == value for key, value in budget.items())
    finally:
        wo.close()


def test_submit_preserves_explicit_permission_denial(tmp_path, monkeypatch):
    wo = WorkOrchestrator({"work_orchestrator": {"enabled": True}}, tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(wo, '_ensure_workers', lambda: None)
    try:
        result = wo.submit({'root':str(tmp_path.resolve()), 'task':'inspect', 'acceptance_criteria':['done'], 'permissions':{'edit':False}})
        assert result['success'] is True
        payload = json.loads(wo._row(result['work_id'])['payload_json'])
        assert payload['permissions']['edit'] is False
    finally:
        wo.close()


def test_plan_only_accepts_disabled_validation_permissions(tmp_path, monkeypatch):
    wo = WorkOrchestrator({"work_orchestrator": {"enabled": True}}, tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(wo, '_ensure_workers', lambda: None)
    try:
        result = wo.submit({'root':str(tmp_path.resolve()), 'task':'inspect', 'acceptance_criteria':['done'], 'mode':'plan', 'permissions':{'tests':False, 'build':False}})
        assert result['success'] is True
    finally:
        wo.close()


@pytest.mark.parametrize('permissions, error', [
    ({'read':False, 'edit':True, 'tests':True, 'build':True, 'network':False, 'git_commit':False, 'create':True, 'delete':True}, 'read permission'),
    ({'read':True, 'edit':True, 'tests':False, 'build':True, 'network':False, 'git_commit':False, 'create':True, 'delete':True}, 'test and build'),
    ({'read':True}, 'contract is invalid'),
])
def test_resumed_work_rechecks_permissions_before_repository_access(tmp_path, permissions, error):
    wo = object.__new__(WorkOrchestrator)
    row = {'work_id':'work', 'root':str(tmp_path), 'task':'inspect', 'payload_json':json.dumps({'budget':{}, 'mode':'execute', 'permissions':permissions, 'keep_failed_workspace':False})}
    with pytest.raises(PermissionError, match=error):
        wo._execute_fenced(row, None, 10)


def test_resumed_work_rejects_nonstring_mode_before_repository_access(tmp_path):
    wo = object.__new__(WorkOrchestrator)
    permissions = {'read':True, 'edit':True, 'tests':True, 'build':True, 'network':False, 'git_commit':False, 'create':True, 'delete':True}
    row = {'work_id':'work', 'root':str(tmp_path), 'task':'inspect', 'payload_json':json.dumps({'budget':{}, 'mode':[], 'permissions':permissions, 'keep_failed_workspace':False})}
    with pytest.raises(PermissionError, match='contract is invalid'):
        wo._execute_fenced(row, None, 10)


def test_resumed_work_rejects_nonboolean_retention_before_repository_access(tmp_path):
    wo = object.__new__(WorkOrchestrator)
    permissions = {'read':True, 'edit':True, 'tests':True, 'build':True, 'network':False, 'git_commit':False, 'create':True, 'delete':True}
    row = {'work_id':'work', 'root':str(tmp_path), 'task':'inspect', 'payload_json':json.dumps({'budget':{}, 'mode':'execute', 'permissions':permissions, 'keep_failed_workspace':'false'})}
    with pytest.raises(PermissionError):
        wo._execute_fenced(row, None, 10)


def test_mcp_work_preserves_explicit_null_budget_for_server_validation(monkeypatch):
    from local_ai_hub import mcp_server
    calls = []
    client = mcp_server.HubClient(auto_start=False)
    monkeypatch.setattr(mcp_server.FEATURES, 'work_orchestrator', True)
    monkeypatch.setattr(mcp_server, 'CLIENT', client)
    monkeypatch.setattr(client, 'post', lambda endpoint, payload, **kwargs: calls.append(payload) or {'success':False, 'error':'invalid budget'})
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda event: None)
    token = mcp_server._CURRENT_MCP_CALL_ARGUMENTS.set(('local_ai_work', {'action':'submit', 'budget':None}))
    try:
        mcp_server.local_ai_work(action='submit', budget=None)
    finally:
        mcp_server._CURRENT_MCP_CALL_ARGUMENTS.reset(token)
    assert calls[0]['budget'] is None


@pytest.mark.parametrize('field', ['budget', 'permissions'])
def test_explicit_null_object_is_rejected_at_registered_mcp_boundary(tmp_path, monkeypatch, field):
    import asyncio
    import mcp.types as mcp_types
    from local_ai_hub import mcp_server
    wo = WorkOrchestrator({"work_orchestrator": {"enabled": True}}, tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(wo, '_ensure_workers', lambda: None)
    client = mcp_server.HubClient(auto_start=False)
    monkeypatch.setattr(mcp_server.FEATURES, 'work_orchestrator', True)
    monkeypatch.setattr(mcp_server, 'CLIENT', client)
    monkeypatch.setattr(client, 'post', lambda endpoint, payload, **kwargs: wo.submit(payload))
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda event: None)
    request = mcp_types.CallToolRequest(method='tools/call', params=mcp_types.CallToolRequestParams(
        name='local_ai_work', arguments={'action':'submit', 'root':str(tmp_path.resolve()), 'task':'inspect', 'acceptance_criteria':['done'], field:None}))
    try:
        result = asyncio.run(mcp_server.mcp._mcp_server.request_handlers[mcp_types.CallToolRequest](request)).root
        assert result.structuredContent['success'] is False
        assert wo.stats()['states'] == {}
    finally:
        wo.close()


def test_mcp_work_does_not_promote_scalar_acceptance_criteria(tmp_path, monkeypatch):
    from local_ai_hub import mcp_server
    wo = WorkOrchestrator({"work_orchestrator": {"enabled": True}}, tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(wo, '_ensure_workers', lambda: None)
    client = mcp_server.HubClient(auto_start=False)
    monkeypatch.setattr(mcp_server.FEATURES, 'work_orchestrator', True)
    monkeypatch.setattr(mcp_server, 'CLIENT', client)
    monkeypatch.setattr(client, 'post', lambda endpoint, payload, **kwargs: wo.submit(payload))
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda event: None)
    try:
        result = mcp_server.local_ai_work(action='submit', root=str(tmp_path.resolve()), task='inspect', acceptance_criteria='done')
        assert result['success'] is False
        assert wo.stats()['states'] == {}
    finally:
        wo.close()


def test_fallback_plan_inspects_the_actual_task(tmp_path, monkeypatch):
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(wo, "_ask", lambda *_args, **_kwargs: {"success": True, "text": "not a plan"})
    try:
        task = "Add --output to the CSV export CLI"
        plan = wo._plan(str(tmp_path), task, {"acceptance_criteria": ["output is saved"]}, {})
        assert plan["steps"][0]["kind"] == "inspect"
        assert plan["steps"][0]["task"] == task
    finally:
        wo.close()


def test_patch_paths_rejects_traversal_and_absolute_paths():
    with pytest.raises(ValueError):
        _patch_paths("--- a/../secret\n+++ b/../secret\n@@ -1 +1 @@\n-x\n+y\n")
    with pytest.raises(ValueError):
        _patch_paths("--- a/x\n+++ C:/temp/x\n@@ -1 +1 @@\n-x\n+y\n")
    assert _patch_paths("--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-x\n+y\n") == ["x.py"]


def test_patch_paths_handles_rename_and_header_like_hunk_content():
    rename = "--- a/old.txt\n+++ b/new.txt\n@@ -1 +1 @@\n-old\n+new\n"
    assert _patch_paths(rename) == ["old.txt", "new.txt"]
    paths, creates, deletes = _patch_changes(rename)
    assert paths == ["old.txt", "new.txt"]
    assert creates == {"new.txt"} and deletes == {"old.txt"}
    tricky = "--- a/x.txt\n+++ b/x.txt\n@@ -1 +1 @@\n--- looks-like-header\n+++ still-hunk-content\n"
    assert _patch_paths(tricky) == ["x.txt"]


def test_rename_cannot_bypass_create_delete_permissions(tmp_path):
    root = init_repo(tmp_path)
    patch = "--- a/a.txt\n+++ b/renamed.txt\n@@ -1 +1 @@\n-old\n+new\n"
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", FakeServices(patch), None, FakeLeases(), FakeArtifacts())
    try:
        with pytest.raises(PermissionError, match="creation disabled"):
            wo._apply_patch(root, patch, "wo1", [], permissions={"create": False, "delete": True})
        with pytest.raises(PermissionError, match="deletion disabled"):
            wo._apply_patch(root, patch, "wo1", [], permissions={"create": True, "delete": False})
        assert (root / "a.txt").read_text(encoding="utf-8") == "old\n"
        assert not (root / "renamed.txt").exists()
    finally:
        wo.close()


def test_response_projection_is_field_selectable_and_bounded():
    value = {"success": True, "status": "complete", "work_id": "wo1", "summary": "x" * 3000, "steps": list(range(100)), "plan": {"summary": "requested detail"}, "secret": "not requested"}
    compact = project_response(value, profile="compact", return_fields=["summary"], max_output_tokens=100)
    assert compact["success"] is True and compact["work_id"] == "wo1"
    assert "secret" not in compact and "steps" not in compact
    assert len(json.dumps(compact)) < 1000
    minimal = project_response(value, profile="minimal")
    assert set(minimal) <= {"success", "status", "work_id", "task_id", "handoff_id", "artifact_id", "error", "needs_agent"}
    explicit = project_response(value, profile="compact", return_fields=["plan"], max_output_tokens=100)
    assert explicit["plan"]["summary"] == "requested detail"
    assert "summary" not in explicit


def test_work_order_executes_patch_validates_and_handoffs(tmp_path):
    root = init_repo(tmp_path)
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
    artifacts = FakeArtifacts(); services = FakeServices(patch)
    task_id = "work-order-success"
    verification_store = owned_verification_context(tmp_path, root, artifacts, task_id)
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts, verification_store=verification_store)
    try:
        sub = wo.submit({"root": str(root.resolve()), "task": "change old to new", "task_id": task_id, "acceptance_criteria": ["a.txt contains new"], "response_profile": "compact"})
        res = wait_terminal(wo, sub["work_id"], timeout=30)
        assert res["status"] == "complete", res
        assert (root / "a.txt").read_text(encoding="utf-8") == "new\n"
        assert res["changed_files"] == ["a.txt"]
        assert res["validation"]["passed"] is True
        assert res["artifact_id"] in artifacts.data
        handoff_report = json.loads(artifacts.data[res["artifact_id"]]["text"])
        assert handoff_report["verification_receipts"] == res["verification_receipts"]
        journal_dir = tmp_path / "state" / "work_journals"
        cleanup_deadline = time.monotonic() + 2.0
        while list(journal_dir.glob("*.json")) and time.monotonic() < cleanup_deadline:
            time.sleep(0.01)
        assert not list(journal_dir.glob("*.json"))
    finally:
        wo.close()






def test_work_order_rolls_back_when_validation_fails(tmp_path):
    root = init_repo(tmp_path)
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
    state_dir = tmp_path / "state"
    artifacts = FakeArtifacts(); services = FakeServices(patch, validation_ok=False)
    wo = WorkOrchestrator(config(tmp_path), state_dir, services, None, FakeLeases(), artifacts)
    try:
        sub = wo.submit({"root": str(root.resolve()), "task": "change old to new", "acceptance_criteria": ["a.txt contains new"], "response_profile": "debug"})
        res = wait_terminal(wo, sub["work_id"])
        assert res["status"] == "failed"
        assert (root / "a.txt").read_text(encoding="utf-8") == "old\n"
        assert "rolled back" in res["summary"]
    finally:
        wo.close()

    restarted = WorkOrchestrator(config(tmp_path), state_dir, services, None, FakeLeases(), artifacts)
    try:
        after_restart = restarted.get(sub["work_id"], profile="debug")
        assert after_restart["status"] == "failed", after_restart
        assert after_restart["error"] == res["error"]
        assert (root / "a.txt").read_text(encoding="utf-8") == "old\n"
    finally:
        restarted.close()


def test_edit_retries_stop_at_configured_attempt_limit(tmp_path):
    root = init_repo(tmp_path)
    services = FakeServices("")
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), FakeArtifacts())
    wo.step_retry_limit = 1
    try:
        submitted = wo.submit({
            "root": str(root.resolve()),
            "task": "change old to new",
            "acceptance_criteria": ["a.txt contains new"],
            "response_profile": "debug",
        })
        result = wait_terminal(wo, submitted["work_id"])

        assert result["status"] == "failed", result
        assert "no unified diff" in result.get("error", "")
        assert services.delegate_calls == 3  # one plan and exactly two edit attempts
        assert (root / "a.txt").read_text(encoding="utf-8") == "old\n"
    finally:
        wo.close()


def test_cancel_after_receipt_collection_preserves_receipts_and_rolls_back(tmp_path):
    root = init_repo(tmp_path)
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"

    class BlockingVerificationServices(FakeServices):
        def __init__(self):
            super().__init__(patch)
            self.verification_started = threading.Event()
            self.release_verification = threading.Event()

        def second_opinion(self, args):
            self.verify_calls += 1
            if self.verify_calls >= 2:
                self.verification_started.set()
                if not self.release_verification.wait(timeout=5):
                    return {"success": False, "text": "verification wait expired"}
            return {"success": True, "text": json.dumps({
                "passed": True, "summary": "verified",
                "criteria": [{"criterion": "a.txt contains new", "passed": True}], "risks": [],
            })}

    services = BlockingVerificationServices()
    artifacts = FakeArtifacts()
    task_id = "work-order-cancelled"
    verification_store = owned_verification_context(tmp_path, root, artifacts, task_id)
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts, verification_store=verification_store)
    try:
        submitted = wo.submit({
            "root": str(root.resolve()),
            "task": "change old to new",
            "task_id": task_id,
            "acceptance_criteria": ["a.txt contains new"],
            "response_profile": "debug",
        })
        assert services.verification_started.wait(timeout=5)
        cancellation = wo.cancel(submitted["work_id"])
        services.release_verification.set()
        result = wait_terminal(wo, submitted["work_id"])

        assert cancellation["status"] == "cancelling"
        assert result["status"] == "cancelled", result
        assert (root / "a.txt").read_text(encoding="utf-8") == "old\n"
        assert result.get("rolled_back") is True
        assert result.get("verification_receipts")
    finally:
        services.release_verification.set()
        wo.close()


def test_final_validation_runs_for_evidence_criteria_without_changes(tmp_path):
    root = init_repo(tmp_path)

    class NoChangeTestServices(FakeServices):
        def __init__(self):
            super().__init__("")
            self.validation_runs = []

        def delegate_repo(self, args):
            self.delegate_calls += 1
            if self.delegate_calls == 1:
                return {"success": True, "text": json.dumps({
                    "summary": "verify existing repository",
                    "needs_agent": False,
                    "steps": [
                        {"id": "inspect", "kind": "inspect", "task": "inspect", "depends_on": [], "acceptance": []},
                        {"id": "review", "kind": "review", "task": "confirm suite remains valid", "depends_on": ["inspect"], "acceptance": []},
                    ],
                    "validation_commands": ["pytest -q tests"],
                })}
            return {"success": True, "text": "{}"}

        def second_opinion(self, args):
            return {"success": True, "text": json.dumps({
                "passed": True,
                "summary": "suite verified",
                "criteria": [{"criterion": "pytest suite", "passed": True}],
                "risks": [],
            })}

        def command(self, args):
            if args.get("action") == "discover":
                return {"success": True, "validation_commands": ["pytest -q tests"]}
            self.validation_runs.append(args["command"])
            revision = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            return {
                "success": True, "exit_code": 0, "execution_id": "pytest-run-1",
                "repository_revision": revision,
            }

    services = NoChangeTestServices()
    artifacts = FakeArtifacts()
    task_id = "work-order-final-validation"
    verification_store = owned_verification_context(tmp_path, root, artifacts, task_id)
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts, verification_store=verification_store)
    try:
        submitted = wo.submit({
            "root": str(root.resolve()),
            "task": "verify the existing test suite",
            "task_id": task_id,
            "acceptance_criteria": ["pytest suite"],
            "response_profile": "debug",
        })
        result = wait_terminal(wo, submitted["work_id"])

        assert result["status"] == "complete", result
        assert result["changed_files"] == []
        assert services.validation_runs == ["pytest -q tests"]
        assert result["verification"]["receipt_gate"]["complete"] is True
    finally:
        wo.close()


def test_integrated_profile_contains_notebook_safe_limits():
    from local_ai_hub.hardware import profile_overrides
    p = profile_overrides("integrated", {"gpus": [{"vendor":"intel","integrated":True}]})
    assert p["scheduler"]["max_parallel"] == 1
    assert p["scheduler"]["max_queue"] == 32
    assert "max_queued_per_tenant" not in p["scheduler"]
    assert "max_inflight_per_tenant" not in p["scheduler"]
    assert p["async_jobs"]["max_pending"] == 16
    assert p["prewarm"]["enabled"] is False
    assert p["preprocessing"]["idle_grace_seconds"] == 30.0
    assert p["code_intelligence"]["max_sessions_per_backend"] == 2
    assert p["headless"]["max_sessions_per_backend"] == 2
    assert p["debug_traces"]["max_bytes"] == 134217728
    assert p["work_orchestrator"]["max_pending_work_orders"] == 8
    assert p["work_orchestrator"]["worker_idle_seconds"] == 30


def test_work_worker_is_lazy_until_submit(tmp_path):
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", FakeServices(patch), None, FakeLeases(), FakeArtifacts())
    try:
        assert wo.stats()["active_workers"] == 0
    finally:
        wo.close()


def test_idle_worker_retires_cleanly_and_can_restart(tmp_path):
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
    root = init_repo(tmp_path)
    services = FakeServices(patch)
    artifacts = FakeArtifacts()
    task_id = "work-order-restarted-worker"
    verification_store = owned_verification_context(tmp_path, root, artifacts, task_id)
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts, verification_store=verification_store)
    try:
        wo.worker_idle_seconds = 0.05
        wo._ensure_workers()
        deadline = time.time() + 2
        while time.time() < deadline and wo.stats()["active_workers"]:
            time.sleep(0.02)
        assert wo.stats()["active_workers"] == 0
        with wo._lock:
            assert not wo._workers
        sub = wo.submit({"root": str(root.resolve()), "task": "change old to new", "task_id": task_id, "acceptance_criteria": ["a.txt contains new"]})
        final = wait_terminal(wo, sub["work_id"])
        assert final["status"] == "complete"
    finally:
        wo.close()


class BlockingReviewServices(FakeServices):
    def __init__(self, patch: str):
        super().__init__(patch)
        self.prompts = []
        self.block_once = True

    def delegate_repo(self, args):
        self.prompts.append(str(args.get("task", "")))
        if "PLAN A CODING WORK ORDER" in str(args.get("task", "")):
            self.delegate_calls += 1
            plan = {
                "summary": "change a.txt safely", "needs_agent": False,
                "steps": [
                    {"id":"s1","kind":"edit","task":"change old to new","depends_on":[],"acceptance":["a.txt contains new"]},
                    {"id":"s2","kind":"validate","task":"validate","depends_on":["s1"],"acceptance":["a.txt contains new"]},
                    {"id":"s3","kind":"review","task":"review","depends_on":["s2"],"acceptance":["a.txt contains new"]},
                ],
                "validation_commands": ["git diff --check"],
            }
            return {"success": True, "text": json.dumps(plan)}
        self.delegate_calls += 1
        return {"success": True, "text": self.patch}

    def second_opinion(self, args):
        if self.block_once:
            self.block_once = False
            return {"success": True, "text": json.dumps({
                "passed": False, "summary": "need API-shape decision", "criteria": [], "risks": [],
                "needs_agent": True, "question": "Preserve API shape?",
            })}
        return super().second_opinion(args)


def test_needs_agent_rolls_back_then_continue_replans_with_answer(tmp_path):
    root = init_repo(tmp_path)
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
    services = BlockingReviewServices(patch)
    artifacts = FakeArtifacts()
    task_id = "work-order-continued"
    verification_store = owned_verification_context(tmp_path, root, artifacts, task_id)
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts, verification_store=verification_store)
    try:
        sub = wo.submit({"root": str(root.resolve()), "task": "change old to new", "task_id": task_id, "acceptance_criteria": ["a.txt contains new"], "response_profile": "debug"})
        blocked = wait_terminal(wo, sub["work_id"])
        assert blocked["status"] == "needs_agent"
        assert blocked["rolled_back"] is True
        assert (root / "a.txt").read_text(encoding="utf-8") == "old\n"
        resumed = wo.continue_work(sub["work_id"], "Yes, preserve API shape")
        assert resumed["success"] is True
        final = wait_terminal(wo, sub["work_id"])
        assert final["status"] == "complete", final
        assert (root / "a.txt").read_text(encoding="utf-8") == "new\n"
        assert any("AGENT ANSWER TO PRIOR BLOCKER" in prompt and "preserve API shape" in prompt for prompt in services.prompts)
    finally:
        wo.close()


class RepairServices(FakeServices):
    def __init__(self):
        super().__init__("")
        self.run_calls = 0

    def delegate_repo(self, args):
        self.delegate_calls += 1
        if self.delegate_calls == 1:
            return {"success": True, "text": json.dumps({
                "summary": "repairable change", "needs_agent": False,
                "steps": [
                    {"id":"s1","kind":"edit","task":"change old to new","depends_on":[],"acceptance":["a.txt contains fixed"]},
                    {"id":"s2","kind":"validate","task":"validate","depends_on":["s1"],"acceptance":["a.txt contains fixed"]},
                ],
                "validation_commands": ["git diff --check"],
            })}
        if self.delegate_calls == 2:
            return {"success": True, "text": "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"}
        return {"success": True, "text": "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-new\n+fixed\n"}

    def command(self, args):
        if args.get("action") == "discover":
            return {"success": True, "validation_commands": ["git diff --check"]}
        self.run_calls += 1
        if self.run_calls == 1:
            return {"success": False, "exit_code": 1, "error": "new evidence: expected fixed"}
        return {"success": True, "exit_code": 0, "error": ""}

    def second_opinion(self, args):
        return {"success": True, "text": json.dumps({
            "passed": True, "summary": "verified after bounded repair",
            "criteria": [{"criterion":"a.txt contains fixed","passed":True}], "risks": []
        })}


def test_validation_failure_uses_bounded_repair_then_revalidates(tmp_path):
    root = init_repo(tmp_path)
    services = RepairServices()
    artifacts = FakeArtifacts()
    task_id = "work-order-repair"
    verification_store = owned_verification_context(tmp_path, root, artifacts, task_id)
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts, verification_store=verification_store)
    try:
        sub = wo.submit({"root": str(root.resolve()), "task": "make a.txt fixed", "task_id": task_id, "acceptance_criteria": ["a.txt contains fixed"], "response_profile": "debug"})
        final = wait_terminal(wo, sub["work_id"])
        assert final["status"] == "complete", final
        assert (root / "a.txt").read_text(encoding="utf-8") == "fixed\n"
        assert services.delegate_calls >= 3
        assert services.run_calls >= 2
    finally:
        wo.close()


def test_work_order_http_post_transport_routes_to_orchestrator(tmp_path):
    state_dir = tmp_path / "state"
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'''[server]
bind = "127.0.0.1"
port = 11435
state_dir = "{state_dir.as_posix()}"
auto_start_ollama = false

[hardware]
profile = "cpu"
auto_tune = false

[prewarm]
enabled = false

[preprocessing]
enabled = false

[resilience]
watchdog_enabled = false

[code_intelligence]
enabled = false

[background_gpu]
enabled = false

[observability]
enabled = false

[work_orchestrator]
enabled = true
''',
        encoding="utf-8",
    )
    app = LocalAIApp(str(cfg))
    previous = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/work-orders",
            data=json.dumps({"action": "status", "work_id": "missing"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["success"] is False
        assert payload["work_id"] == "missing"
        assert "not found" in payload["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous
        app.close()


def test_work_order_http_schema_rejects_oversized_identifier():
    from local_ai_hub.http_server import Handler, RequestBodyError

    with pytest.raises(RequestBodyError, match="work_id"):
        Handler._validate_payload("/api/work-orders", {"action": "status", "work_id": "x" * 129})

def test_orchestrator_uses_verification_store_from_services(tmp_path):
    services = FakeServices("")
    services.verification_store = object()

    orchestrator = WorkOrchestrator(
        config(tmp_path), tmp_path / "state", services, None, FakeLeases(), FakeArtifacts()
    )

    assert orchestrator.verification_store is services.verification_store

def test_stale_verification_receipt_cannot_complete_work_order(tmp_path):
    from local_ai_hub.agent_verification import VerificationReceipt

    root = init_repo(tmp_path)
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"

    class RevisionServices(FakeServices):
        def __init__(self, patch):
            super().__init__(patch)
            self.run_args = []

        def command(self, args):
            result = super().command(args)
            if args.get("action") == "run":
                self.run_args.append(dict(args))
                revision = subprocess.run(
                    ["git", "-C", str(args["cwd"]), "rev-parse", "--verify", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
                result.update(execution_id="cmd-test-1", repository_revision=revision)
            return result

    class RecordingVerificationStore:
        def __init__(self, task_store):
            self.records = []
            self.task_store = task_store

        def record(self, receipt, *, update_task=True):
            self.records.append((receipt, update_task))
            return receipt

    artifacts = FakeArtifacts()
    from types import SimpleNamespace

    task_id = "task-source-review-1"
    task_owner = "repository-task-owner"

    class TaskStore:
        @staticmethod
        def get(requested_task_id):
            if requested_task_id != task_id:
                return None
            return SimpleNamespace(
                task_id=task_id,
                owner=task_owner,
                checkpoint=SimpleNamespace(state_data={
                    "_agent_task_scope": {
                        "version": 2,
                        "repo_root": str(root.resolve()),
                    },
                }),
            )

    verification_store = RecordingVerificationStore(TaskStore())
    services = RevisionServices(patch)
    wo = WorkOrchestrator(
        config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts,
        verification_store=verification_store,
    )
    persist_receipts = wo._persist_handoff_receipts
    stale_receipt_generations = []

    def stale_receipts(work_id, receipts, validation, *, attempt=None):
        transformed = []
        for receipt in receipts:
            proof = {
                "kind": "work_source_review",
                "passed": True,
                "task_id": receipt.task_id,
                "owner": receipt.owner,
                "repository_revision": receipt.repository_revision,
                "mutation_generation": 0,
                "criteria": [receipt.criterion],
            }
            evidence_id = artifacts.put(json.dumps(proof), kind="source_review")
            transformed.append(VerificationReceipt.create(
                task_id=receipt.task_id,
                criterion=receipt.criterion,
                owner=receipt.owner,
                evidence_id=evidence_id,
                repository_revision=receipt.repository_revision,
                mutation_generation=0,
                evidence_type="source_review",
            ))
            stale_receipt_generations.append(transformed[-1].mutation_generation)
        persisted = persist_receipts(work_id, transformed, validation, attempt=attempt)
        return persisted

    wo._persist_handoff_receipts = stale_receipts
    try:
        submitted = wo.submit({
            "root": str(root.resolve()),
            "task": "change old to new",
            "task_id": task_id,
            "acceptance_criteria": ["a.txt contains new"],
            "response_profile": "debug",
        })
        result = wait_terminal(wo, submitted["work_id"])
        receipt_gate = result.get("verification", {}).get("receipt_gate", {})

        assert result["status"] != "complete", result
        assert "receipt" in result.get("error", "").lower()
        assert "a.txt contains new" in result.get("error", "")
        assert receipt_gate["complete"] is False
        assert receipt_gate["stale_criteria"] == ["a.txt contains new"]
        stale_review_receipts = [
            item for item in result["verification_receipts"]
            if item.get("evidence_type") == "source_review"
        ]
        assert stale_review_receipts
        assert stale_receipt_generations == [0]
        assert verification_store.records
        assert all(update_task is False for _receipt, update_task in verification_store.records)
        assert services.run_args
        assert all(call["record_verification"] is False for call in services.run_args)
    finally:
        wo.close()

def test_local_service_forwards_receipt_opt_out_and_keeps_work_id():
    class Broker:
        def authorize_auxiliary_action(self, action, *, endpoint, task_id=""):
            return {"allowed": True}

        def run(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            return {"success": True}

    broker = Broker()
    services = object.__new__(LocalAIServices)
    services.commands = broker
    services.agent_state = None

    result = services.command({
        "action": "run",
        "command": "python -m pytest -q",
        "cwd": ".",
        "task_id": "work-order-1",
        "criterion": "tests pass",
        "record_verification": False,
    })

    assert result["success"] is True
    assert broker.kwargs["record_verification"] is False
    assert broker.kwargs["task_id"] == "work-order-1"
