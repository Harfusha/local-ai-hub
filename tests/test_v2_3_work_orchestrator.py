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
from local_ai_hub.work_orchestrator import WorkOrchestrator, _patch_changes, _patch_paths, _stable_toposort_steps


class FakeArtifacts:
    def __init__(self): self.data = {}
    def put(self, text, tenant, kind):
        key = f"a{len(self.data)+1}"
        self.data[key] = {"text": text, "tenant": tenant, "kind": kind}
        return key


class FakeLeases:
    def claim_batch(self, tenant, root, paths, ttl_seconds=900, purpose=""):
        return {"success": True, "lease_id": "lease1", "paths": paths}
    def release(self, tenant, lease_id=""):
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
    def delegate_repo(self, args, tenant):
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
    def second_opinion(self, args, tenant):
        self.verify_calls += 1
        return {"success": True, "text": json.dumps({
            "passed": True, "summary": "verified", "criteria": [{"criterion":"a.txt contains new","passed":True}], "risks": []
        })}
    def command(self, args, tenant):
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


def wait_terminal(wo: WorkOrchestrator, wid: str, timeout=8):
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = wo.get("tenant", wid, profile="debug")
        if res.get("status") in {"complete", "failed", "cancelled", "needs_agent", "partial"}:
            return res
        time.sleep(0.05)
    raise AssertionError(wo.get("tenant", wid, profile="debug"))




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


def test_planner_sanitizes_duplicate_ids_and_non_list_edges(tmp_path):
    class OddPlanServices(FakeServices):
        def delegate_repo(self, args, tenant):
            return {"success": True, "text": json.dumps({
                "summary": "odd planner output",
                "steps": [
                    {"id": "dup", "kind": "inspect", "task": "first", "depends_on": "dup", "acceptance": "not-a-list"},
                    {"id": "dup", "kind": "review", "task": "second", "depends_on": [], "acceptance": []},
                    {"id": "   ", "kind": "unknown", "task": "", "depends_on": [], "acceptance": []},
                ],
            })}
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", OddPlanServices(""), None, FakeLeases(), FakeArtifacts())
    try:
        payload = {"budget": {"max_steps": 16}, "acceptance_criteria": [], "constraints": []}
        plan = wo._plan("tenant", str(tmp_path), "inspect", payload, {})
        ids = [step["id"] for step in plan["steps"]]
        assert len(ids) == len(set(ids)) == 3
        assert all(step["depends_on"] == [] for step in plan["steps"])
        assert all(isinstance(step["acceptance"], list) for step in plan["steps"])
        assert plan["steps"][-1]["kind"] == "inspect"
        assert plan["steps"][-1]["task"]
    finally:
        wo.close()


def test_work_id_is_bounded_before_persistence(tmp_path):
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    root = init_repo(tmp_path)
    try:
        result = wo.submit("tenant", {"root": str(root.resolve()), "task": "inspect", "work_id": "x" * 129})
        assert result["success"] is False
        assert "128" in result["error"]
        assert wo.stats()["states"] == {}
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
            wo._apply_patch(root, patch, "tenant", "wo1", [], permissions={"create": False, "delete": True})
        with pytest.raises(PermissionError, match="deletion disabled"):
            wo._apply_patch(root, patch, "tenant", "wo1", [], permissions={"create": True, "delete": False})
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
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts)
    try:
        sub = wo.submit("tenant", {"root": str(root.resolve()), "task": "change old to new", "acceptance_criteria": ["a.txt contains new"], "response_profile": "compact"})
        res = wait_terminal(wo, sub["work_id"])
        assert res["status"] == "complete", res
        assert (root / "a.txt").read_text(encoding="utf-8") == "new\n"
        assert res["changed_files"] == ["a.txt"]
        assert res["validation"]["passed"] is True
        assert res["artifact_id"] in artifacts.data
        assert not list((tmp_path / "state" / "work_journals").glob("*.json"))
    finally:
        wo.close()


def test_work_order_rolls_back_when_validation_fails(tmp_path):
    root = init_repo(tmp_path)
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
    artifacts = FakeArtifacts(); services = FakeServices(patch, validation_ok=False)
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts)
    try:
        sub = wo.submit("tenant", {"root": str(root.resolve()), "task": "change old to new", "acceptance_criteria": ["a.txt contains new"], "response_profile": "debug"})
        res = wait_terminal(wo, sub["work_id"])
        assert res["status"] == "failed"
        assert (root / "a.txt").read_text(encoding="utf-8") == "old\n"
        assert "rolled back" in res["summary"]
    finally:
        wo.close()


def test_integrated_profile_contains_notebook_safe_limits():
    from local_ai_hub.hardware import profile_overrides
    p = profile_overrides("integrated", {"gpus": [{"vendor":"intel","integrated":True}]})
    assert p["scheduler"]["max_parallel"] == 1
    assert p["scheduler"]["max_queue"] == 32
    assert p["scheduler"]["max_queued_per_tenant"] == 12
    assert p["async_jobs"]["max_pending"] == 16
    assert p["prewarm"]["enabled"] is False
    assert p["preprocessing"]["idle_grace_seconds"] == 15.0
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
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", FakeServices(patch), None, FakeLeases(), FakeArtifacts())
    root = init_repo(tmp_path)
    try:
        wo.worker_idle_seconds = 0.05
        wo._ensure_workers()
        deadline = time.time() + 2
        while time.time() < deadline and wo.stats()["active_workers"]:
            time.sleep(0.02)
        assert wo.stats()["active_workers"] == 0
        with wo._lock:
            assert not wo._workers
        sub = wo.submit("tenant", {"root": str(root.resolve()), "task": "change old to new", "acceptance_criteria": ["a.txt contains new"]})
        final = wait_terminal(wo, sub["work_id"])
        assert final["status"] == "complete"
    finally:
        wo.close()


class BlockingReviewServices(FakeServices):
    def __init__(self, patch: str):
        super().__init__(patch)
        self.prompts = []
        self.block_once = True

    def delegate_repo(self, args, tenant):
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

    def second_opinion(self, args, tenant):
        if self.block_once:
            self.block_once = False
            return {"success": True, "text": json.dumps({
                "passed": False, "summary": "need compatibility decision", "criteria": [], "risks": [],
                "needs_agent": True, "question": "Preserve compatibility?",
            })}
        return super().second_opinion(args, tenant)


def test_needs_agent_rolls_back_then_continue_replans_with_answer(tmp_path):
    root = init_repo(tmp_path)
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
    services = BlockingReviewServices(patch)
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), FakeArtifacts())
    try:
        sub = wo.submit("tenant", {"root": str(root.resolve()), "task": "change old to new", "acceptance_criteria": ["a.txt contains new"], "response_profile": "debug"})
        blocked = wait_terminal(wo, sub["work_id"])
        assert blocked["status"] == "needs_agent"
        assert blocked["rolled_back"] is True
        assert (root / "a.txt").read_text(encoding="utf-8") == "old\n"
        resumed = wo.continue_work("tenant", sub["work_id"], "Yes, preserve compatibility")
        assert resumed["success"] is True
        final = wait_terminal(wo, sub["work_id"])
        assert final["status"] == "complete", final
        assert (root / "a.txt").read_text(encoding="utf-8") == "new\n"
        assert any("AGENT ANSWER TO PRIOR BLOCKER" in prompt and "preserve compatibility" in prompt for prompt in services.prompts)
    finally:
        wo.close()


class RepairServices(FakeServices):
    def __init__(self):
        super().__init__("")
        self.run_calls = 0

    def delegate_repo(self, args, tenant):
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

    def command(self, args, tenant):
        if args.get("action") == "discover":
            return {"success": True, "validation_commands": ["git diff --check"]}
        self.run_calls += 1
        if self.run_calls == 1:
            return {"success": False, "exit_code": 1, "error": "new evidence: expected fixed"}
        return {"success": True, "exit_code": 0, "error": ""}

    def second_opinion(self, args, tenant):
        return {"success": True, "text": json.dumps({
            "passed": True, "summary": "verified after bounded repair",
            "criteria": [{"criterion":"a.txt contains fixed","passed":True}], "risks": []
        })}


def test_validation_failure_uses_bounded_repair_then_revalidates(tmp_path):
    root = init_repo(tmp_path)
    services = RepairServices()
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), FakeArtifacts())
    try:
        sub = wo.submit("tenant", {"root": str(root.resolve()), "task": "make a.txt fixed", "acceptance_criteria": ["a.txt contains fixed"], "response_profile": "debug"})
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
            f"http://127.0.0.1:{server.server_address[1]}/v1/work-orders",
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
        Handler._validate_payload("/v1/work-orders", {"action": "status", "work_id": "x" * 129})
