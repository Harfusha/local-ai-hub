import json
import threading
import pytest

from local_ai_hub.app import LocalAIApp
from test_work_orchestrator import init_repo, wait_terminal


def test_bounded_model_observation_does_not_infer_missing_identity():
    from local_ai_hub.work_orchestrator import _work_model_observation

    assert _work_model_observation({"route": {"model": "unverified:9b"}, "fallback_used": 0}) == {
        "reported_model": None, "requested_model": None, "fallback_used": None, "identity_verified": False,
    }
    assert _work_model_observation({"model": "bad\nname", "requested_model": 42})["reported_model"] is None


def test_documented_i1_fixture_runs_approved_pytest_through_broker(tmp_path, monkeypatch):
    import difflib
    from tools.prepare_local_model_eval_fixture import prepare_fixture

    root = tmp_path / "fixture"
    prepare_fixture(root, "I1")
    config = tmp_path / "isolated.toml"
    config.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[security]\nallowed_roots = ["
        + json.dumps(str(root)) + "]\n", encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    try:
        originals = {name: (root / name).read_text(encoding="utf-8")
                     for name in ("src/clamp.py", "tests/test_clamp.py")}
        updated = {
            "src/clamp.py": originals["src/clamp.py"].replace(
                "return max(upper, min(lower, value))", "return min(upper, max(lower, value))"),
            "tests/test_clamp.py": originals["tests/test_clamp.py"] + (
                "\n\ndef test_boundaries_and_inverted_bounds():\n"
                "    import pytest\n"
                "    assert [clamp(x, 0, 10) for x in (-1, 0, 10, 11)] == [0, 0, 10, 10]\n"
                "    with pytest.raises(ValueError):\n"
                "        clamp(5, 10, 0)\n"),
        }
        patch_text = "".join("".join(difflib.unified_diff(
            originals[name].splitlines(keepends=True), updated[name].splitlines(keepends=True),
            fromfile="a/" + name, tofile="b/" + name)) for name in originals)
        calls = []

        def delegate(args, **_kwargs):
            calls.append(args)
            if len(calls) == 1:
                return {"success": True, "text": json.dumps({"summary": "fix clamp", "steps": [
                    {"id": "edit", "kind": "edit", "task": "fix clamp and tests", "depends_on": []},
                    {"id": "validate", "kind": "validate", "task": "run tests", "depends_on": ["edit"]},
                ]})}
            return {"success": True, "text": patch_text, "model": "synthetic:9b",
                    "requested_model": "synthetic:9b", "fallback_used": False}

        monkeypatch.setattr(app.services, "delegate_repo", delegate)
        monkeypatch.setattr(app.services, "second_opinion", lambda *_args, **_kwargs: {
            "success": True, "text": json.dumps({"passed": True, "summary": "simulated review",
            "criteria": [{"criterion": "Clamp handles both bounds and inverted bounds", "passed": True},
                         {"criterion": "Meaningful boundary tests pass", "passed": True}], "risks": []})})
        submitted = app.work_orchestrator.submit({
            "root": str(root), "task": "Fix clamp for inclusive bounds; add meaningful boundary tests. Preserve its public signature.",
            "mode": "bounded", "acceptance_criteria": ["Clamp handles both bounds and inverted bounds", "Meaningful boundary tests pass"],
            "allowed_paths": list(originals), "approved_commands": ["python -m pytest -q tests/test_clamp.py"],
            "permissions": {"read": True, "edit": True, "tests": True, "build": True, "network": False,
                            "git_commit": False, "create": False, "delete": False},
            "budget": {"max_steps": 8, "max_seconds": 300},
        })
        assert submitted["success"] is True, submitted
        handoff = wait_terminal(app.work_orchestrator, submitted["work_id"], timeout=60)
        assert handoff["status"] == "needs_agent", handoff
        assert handoff["requires_primary_review"] is True
        report = json.loads(app.artifacts.get(handoff["artifact_id"], max_chars=30000)["text"])
        edit = next(step for step in report["steps"] if step["kind"] == "edit")
        assert edit["model_observations"] == [{"reported_model": "synthetic:9b",
                "requested_model": "synthetic:9b", "fallback_used": False, "identity_verified": False}]
        assert report["validation"][0]["command"] == "python -m pytest -q tests/test_clamp.py"
        assert report["validation"][0]["exit_code"] == 0
        assert all((root / name).read_text(encoding="utf-8") == updated[name] for name in updated)
    finally:
        app.close()


def test_isolated_bounded_work_can_edit_small_ui_and_validate(tmp_path, monkeypatch):
    import subprocess

    root = init_repo(tmp_path)
    (root / "index.html").write_text('<button>Save</button>\n', encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "index.html"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@e",
                    "commit", "-qm", "add ui"], check=True)
    config = tmp_path / "isolated.toml"
    config.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[security]\nallowed_roots = ["
        + json.dumps(str(root)) + "]\n", encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    calls = []
    try:
        def delegate(args, **_kwargs):
            calls.append(args)
            if len(calls) == 1:
                return {"success": True, "text": json.dumps({"summary": "accessible label", "steps": [
                    {"id": "edit", "kind": "edit", "task": "add accessible label", "depends_on": []},
                    {"id": "validate", "kind": "validate", "task": "check diff", "depends_on": ["edit"]},
                ]})}
            return {"success": True, "text": '--- a/index.html\n+++ b/index.html\n@@ -1 +1 @@\n-<button>Save</button>\n+<button aria-label="Save changes">Save</button>\n'}

        monkeypatch.setattr(app.services, "delegate_repo", delegate)
        monkeypatch.setattr(app.services, "second_opinion", lambda *_args, **_kwargs: {
            "success": True, "text": json.dumps({"passed": True, "summary": "checked",
            "criteria": [{"criterion": "button has accessible label", "passed": True}], "risks": []})})
        submitted = app.work_orchestrator.submit({
            "root": str(root), "task": "add an accessible button label", "mode": "bounded",
            "acceptance_criteria": ["button has accessible label"], "allowed_paths": ["index.html"],
            "approved_commands": ["git diff --check"], "budget": {"max_steps": 6, "max_seconds": 90},
            "permissions": {"edit": True, "tests": True, "build": True},
        })
        assert submitted["success"] is True
        handoff = wait_terminal(app.work_orchestrator, submitted["work_id"], timeout=30)
        assert handoff["status"] == "needs_agent", handoff
        assert handoff["requires_primary_review"] is True
        assert 'aria-label="Save changes"' in (root / "index.html").read_text(encoding="utf-8")
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
        artifact = app.artifacts.get(handoff["artifact_id"], max_chars=30000)
        assert artifact["success"] is True
        validation = json.loads(artifact["text"])["validation"]
        assert validation[0]["command"] == "git diff --check"
        assert validation[0]["exit_code"] == 0
    finally:
        app.close()


@pytest.mark.parametrize("task_bound", [False, True])
def test_isolated_app_bounded_work_uses_real_service_and_broker(tmp_path, monkeypatch, task_bound):
    root = init_repo(tmp_path)
    config = tmp_path / "isolated.toml"
    config.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[security]\nallowed_roots = ["
        + json.dumps(str(root)) + "]\n", encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    try:
        assert app.commands.bounded_work_authorizer == app.work_orchestrator.authorize_bounded_command
        calls = []

        def delegate(args, **_kwargs):
            calls.append(args)
            if len(calls) == 1:
                return {"success": True, "text": json.dumps({"summary": "bounded change", "steps": [
                    {"id": "edit", "kind": "edit", "task": "replace old", "depends_on": []},
                    {"id": "validate", "kind": "validate", "task": "check diff", "depends_on": ["edit"]},
                ]})}
            return {"success": True, "text": "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"}

        def review(_args, **_kwargs):
            return {"success": True, "text": json.dumps({"passed": True, "summary": "checked",
                    "criteria": [{"criterion": "a.txt contains new", "passed": True}], "risks": []})}

        monkeypatch.setattr(app.services, "delegate_repo", delegate)
        monkeypatch.setattr(app.services, "second_opinion", review)
        task_id = ""
        finalized = threading.Event()
        if task_bound:
            from local_ai_hub.agent_identity import ScopeContext
            from local_ai_hub.agent_tasks import GoalContract, TaskStatus
            store = app.work_orchestrator.verification_store.task_store
            task = store.create(GoalContract(goal="bounded task"), ScopeContext(task_id="bounded-task"),
                                task_id="bounded-task", actor="owner", repo_root=str(root))
            task_id = task.task_id
            store.transition(task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
            original_finish = store._finish_fenced_work_mutation
            def observe_finish(*args, **kwargs):
                finished = original_finish(*args, **kwargs)
                finalized.set()
                return finished
            monkeypatch.setattr(store, "_finish_fenced_work_mutation", observe_finish)
        requests = []
        guard_seen = []
        original_command = app.services.command
        def observed_command(args, **kwargs):
            requests.append(args.copy())
            if task_bound and args.get("action") == "run":
                guard_seen.append(store.get(task_id).checkpoint.state_data.get("_pending_fenced_work"))
            return original_command(args, **kwargs)
        monkeypatch.setattr(app.services, "command", observed_command)
        result = app.work_orchestrator.submit({
            "root": str(root), "task": "replace old with new", "mode": "bounded",
            "task_id": task_id,
            "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "budget": {"max_steps": 6, "max_seconds": 90},
            "permissions": {"edit": True, "tests": True, "build": True},
        })
        assert result["success"] is True, result
        handoff = wait_terminal(app.work_orchestrator, result["work_id"], timeout=30)
        assert handoff["status"] == "needs_agent", handoff
        assert handoff["requires_primary_review"] is True
        assert handoff["validation"]["receipt_status"] == "not_recorded"
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "new"
        artifact = app.artifacts.get(handoff["artifact_id"], max_chars=30000)
        assert artifact["success"] is True
        report = json.loads(artifact["text"])
        assert report["validation"][0]["command"] == "git diff --check"
        assert report["validation"][0]["exit_code"] == 0
        assert report["validation"][0]["receipt_status"] == "not_recorded"
        assert report["verification_receipts"] == []
        assert requests and all(request.get("record_verification") is False for request in requests)
        if task_bound:
            assert finalized.wait(timeout=5)
            assert guard_seen and guard_seen[0]["work_id"] == result["work_id"]
            assert store.get(task_id).verification_receipts == {}
            assert "_pending_fenced_work" not in store.get(task_id).checkpoint.state_data
    finally:
        app.close()


def test_recovered_work_has_broker_authorizer_before_workers_start(tmp_path, monkeypatch):
    from local_ai_hub.work_orchestrator import WorkOrchestrator

    class Broker:
        bounded_work_authorizer = None

        def set_fencing_lease_store(self, store):
            self.fencing_lease_store = store

        def set_bounded_work_authorizer(self, authorizer):
            self.bounded_work_authorizer = authorizer

    broker = Broker()
    started = []
    monkeypatch.setattr(WorkOrchestrator, "_recover", lambda self: None)
    monkeypatch.setattr(WorkOrchestrator, "_has_queued_work", lambda self: True)

    def start_workers(self):
        started.append(self.commands.bounded_work_authorizer == self.authorize_bounded_command)

    monkeypatch.setattr(WorkOrchestrator, "_ensure_workers", start_workers)
    WorkOrchestrator({}, tmp_path, object(), broker, object(), object())
    assert started == [True]


def test_isolated_app_rejects_patch_outside_allowed_files(tmp_path, monkeypatch):
    root = init_repo(tmp_path)
    foreign = root / "b.txt"
    foreign.write_text("protected\n", encoding="utf-8")
    config = tmp_path / "isolated.toml"
    config.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[security]\nallowed_roots = ["
        + json.dumps(str(root)) + "]\n", encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    try:
        def delegate(args, **_kwargs):
            if args.get("profile") == "planner" or not getattr(delegate, "planned", False):
                delegate.planned = True
                return {"success": True, "text": json.dumps({"summary": "change", "steps": [
                    {"id": "edit", "kind": "edit", "task": "change", "depends_on": []},
                ]})}
            return {"success": True, "model": "synthetic:9b", "text": "--- a/b.txt\n+++ b/b.txt\n@@ -1 +1 @@\n-protected\n+changed\n"}

        monkeypatch.setattr(app.services, "delegate_repo", delegate)
        validation_calls = []
        original_command = app.services.command
        def observe_command(args, **kwargs):
            validation_calls.append(args)
            return original_command(args, **kwargs)
        monkeypatch.setattr(app.services, "command", observe_command)
        result = app.work_orchestrator.submit({
            "root": str(root), "task": "change a.txt", "mode": "bounded",
            "acceptance_criteria": ["a.txt updated"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "budget": {"max_steps": 6, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True},
        })
        assert result["success"] is True, result
        handoff = wait_terminal(app.work_orchestrator, result["work_id"], timeout=30)
        assert handoff["status"] == "failed", handoff
        report = json.loads(app.artifacts.get(handoff["artifact_id"], max_chars=30000)["text"])
        failed_step = report["failed_step"]
        assert failed_step["kind"] == "edit" and failed_step["success"] is False
        assert failed_step["model_observations"]
        assert all(item["reported_model"] == "synthetic:9b" and item["identity_verified"] is False
                   for item in failed_step["model_observations"])
        assert validation_calls == []
        assert foreign.read_text(encoding="utf-8") == "protected\n"
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
    finally:
        app.close()


def test_task_bound_rollback_conflict_preserves_foreign_change_and_barrier(tmp_path, monkeypatch):
    from local_ai_hub.agent_identity import ScopeContext
    from local_ai_hub.agent_tasks import GoalContract, TaskStatus
    root = init_repo(tmp_path)
    config = tmp_path / "isolated.toml"
    config.write_text("[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[work_orchestrator]\nmax_replans = 0"
        + "\n[security]\nallowed_roots = [" + json.dumps(str(root)) + "]\n", encoding="utf-8")
    app = LocalAIApp(str(config))
    try:
        store = app.work_orchestrator.verification_store.task_store
        task = store.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                            task_id="task", actor="owner", repo_root=str(root))
        store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
        calls = []
        def delegate(_args, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                return {"success": True, "text": json.dumps({"summary": "change", "steps": [
                    {"id": "edit", "kind": "edit", "task": "change", "depends_on": []},
                    {"id": "validate", "kind": "validate", "task": "check", "depends_on": ["edit"]}]})}
            return {"success": True, "text": "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"}
        monkeypatch.setattr(app.services, "delegate_repo", delegate)
        command = app.services.command
        def conflicting_command(args, **kwargs):
            if args.get("action") == "run":
                (root / "a.txt").write_text("foreign\n", encoding="utf-8")
            return command(args, **kwargs)
        monkeypatch.setattr(app.services, "command", conflicting_command)
        result = app.work_orchestrator.submit({"root": str(root), "task": "change", "task_id": task.task_id,
            "mode": "bounded", "acceptance_criteria": ["a.txt updated"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --exit-code"], "budget": {"max_steps": 6, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True}})
        assert result["success"] is True
        handoff = wait_terminal(app.work_orchestrator, result["work_id"], timeout=30)
        assert handoff["status"] == "failed"
        assert handoff["task_barrier_status"] == "reconciliation_required"
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "foreign"
        assert "_pending_fenced_work" in store.get(task.task_id).checkpoint.state_data
        assert app.work_orchestrator._load_journal(result["work_id"])
    finally:
        app.close()


@pytest.mark.parametrize("diagnostics_enabled", [False, True])
@pytest.mark.parametrize("task_bound", [False, True])
def test_isolated_app_rolls_back_when_broker_command_fails(tmp_path, monkeypatch, diagnostics_enabled, task_bound):
    root = init_repo(tmp_path)
    config = tmp_path / "isolated.toml"
    config.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[work_orchestrator]\nmax_replans = 0"
        + "\n[features]\nlocal_diagnostic_dispatch = " + str(diagnostics_enabled).lower()
        + "\n[security]\nallowed_roots = [" + json.dumps(str(root)) + "]\n", encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    try:
        task_id = ""
        if task_bound:
            from local_ai_hub.agent_identity import ScopeContext
            from local_ai_hub.agent_tasks import GoalContract, TaskStatus
            store = app.work_orchestrator.verification_store.task_store
            task = store.create(GoalContract(goal="bounded task"), ScopeContext(task_id="bounded-task"),
                                task_id="bounded-task", actor="owner", repo_root=str(root))
            task_id = task.task_id
            store.transition(task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
        calls = []
        diagnostic_calls = []
        def reason(args, *, cancel_event):
            diagnostic_calls.append(args)
            return {"success": True, "text": "advice"}
        monkeypatch.setattr(app.services, "reason", reason)
        def delegate(args, **_kwargs):
            calls.append(args)
            if len(calls) == 1:
                return {"success": True, "text": json.dumps({"summary": "change", "steps": [
                    {"id": "edit", "kind": "edit", "task": "change", "depends_on": []},
                    {"id": "validate", "kind": "validate", "task": "validate", "depends_on": ["edit"]},
                ]})}
            return {"success": True, "text": "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"}

        monkeypatch.setattr(app.services, "delegate_repo", delegate)
        result = app.work_orchestrator.submit({
            "root": str(root), "task": "change a.txt", "mode": "bounded",
            "task_id": task_id,
            "acceptance_criteria": ["a.txt updated"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --exit-code"], "budget": {"max_steps": 6, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True},
        })
        assert result["success"] is True, result
        handoff = wait_terminal(app.work_orchestrator, result["work_id"], timeout=30)
        assert handoff["status"] == "failed", handoff
        assert handoff["success"] is False
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
        report = json.loads(app.artifacts.get(handoff["artifact_id"], max_chars=30000)["text"])
        assert report["rolled_back"] is True
        assert report["validation"][0]["exit_code"] == 1
        assert report["validation"][0]["success"] is False
        assert report["verification_receipts"] == []
        if task_bound:
            state = store.get(task_id).checkpoint.state_data
            assert "_pending_fenced_work" not in state
            assert state["mutation_generation"] >= 2
        assert diagnostic_calls == []
        if diagnostics_enabled:
            hint = handoff["local_handoff"]
            assert hint["artifact_id"] == handoff["artifact_id"]
            assert hint["root"] == str(root)
            assert hint["artifact_tool"] == "local_ai_artifact"
            assert hint["tool"] == "local_ai_task" and hint["action"] == "reason"
            assert hint["requires_primary_review"] is True
            compact = app.work_orchestrator.get(result["work_id"], profile="compact")
            assert compact["local_handoff"] == hint
            from local_ai_hub.response_budget import budget_response
            budgeted = budget_response(compact, max_tokens=512, profile="compact")
            assert budgeted["local_handoff"]["artifact_id"] == handoff["artifact_id"]
            import asyncio
            import copy
            import threading
            from types import SimpleNamespace
            from local_ai_hub import http_server, mcp_server
            from local_ai_hub.client import HubClient
            from local_ai_hub.features import FeatureSet
            previous_app = http_server.APP
            http_server.APP = app
            server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            client_config = tmp_path / "client.toml"
            client_config.write_text(
                f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
                + "state_dir = " + json.dumps(str(tmp_path / "state")) + "\n", encoding="utf-8",
            )
            client = mcp_server._MCPHubClientAdapter(HubClient(config_path=str(client_config), auto_start=False))
            reporter = mcp_server._ProtocolAccountingReporter()
            monkeypatch.setattr(mcp_server, "CLIENT", client)
            monkeypatch.setattr(mcp_server, "CFG", app.config)
            # Expose the MCP tool for transport testing without starting a model.
            feature_config = copy.deepcopy(app.config)
            feature_config.setdefault("ollama", {})["enabled"] = True
            feature_config.setdefault("server", {})["auto_start_ollama"] = False
            monkeypatch.setattr(mcp_server, "FEATURES", FeatureSet(feature_config))
            assert mcp_server.FEATURES.work_orchestrator is True
            monkeypatch.setattr(mcp_server, "ENDPOINT_STATS", app.endpoint_stats)
            monkeypatch.setattr(mcp_server, "_ACCOUNTING_REPORTER", reporter)
            monkeypatch.setattr(mcp_server, "ADOPTION_METRICS", SimpleNamespace(record=lambda *a, **k: None))
            monkeypatch.setattr(mcp_server, "CONTEXT_LEDGER", SimpleNamespace(record=lambda **k: None,
                                                                                adaptive_profile=lambda p: p))
            try:
                mcp_result = asyncio.run(mcp_server.mcp.call_tool("local_ai_work", {
                    "action": "get", "root": str(root), "work_id": result["work_id"],
                    "max_response_tokens": 1000,
                }))[1]
                assert mcp_result["success"] is False, mcp_result
                assert mcp_result.get("status") == "failed", mcp_result
                assert mcp_result["local_handoff"]["artifact_id"] == handoff["artifact_id"]
                assert diagnostic_calls == []
            finally:
                reporter.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                http_server.APP = previous_app
        else:
            assert "local_handoff" not in handoff
    finally:
        app.close()
