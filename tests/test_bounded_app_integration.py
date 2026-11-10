import json
import threading
import pytest

from local_ai_hub.app import LocalAIApp
from test_work_orchestrator import init_repo, wait_terminal


@pytest.mark.parametrize("scenario", ["allowed", "denied", "qualified_tools", "unadvertised_tool", "handoff_storage_none", "handoff_storage_error", "handoff_keep"])
def test_registered_mcp_http_bounded_patch_and_real_broker(tmp_path, monkeypatch, scenario):
    import asyncio
    from local_ai_hub import http_server, mcp_server
    from local_ai_hub.client import HubClient

    root = init_repo(tmp_path)
    (root / "test_sample.py").write_text(
        "from pathlib import Path\n\ndef test_change():\n    assert Path('a.txt').read_text().strip() == 'new'\n",
        encoding="utf-8",
    )
    config = tmp_path / "isolated.toml"
    config.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\nauto_start_ollama = false\n[ollama]\nenabled = true\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[security]\nallowed_roots = ["
        + json.dumps(str(root)) + "]\n[hardware]\nprofile = \"high\"\n"
        + "[features]\nbounded_local_work = true\n[work_orchestrator]\nenabled = true\n", encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HubClient(config_path=str(config), auto_start=False)
    client._http_port = server.server_address[1]
    client.base_url = f"http://127.0.0.1:{client._http_port}"
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server.FEATURES, "work_orchestrator", True)
    monkeypatch.setattr(mcp_server.FEATURES, "hardware_profile", "high")
    monkeypatch.setattr(mcp_server.FEATURES, "bounded_work_tier", True)
    monkeypatch.setattr(mcp_server.FEATURES, "bounded_work_qualified", True)
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **kwargs: None)
    if scenario in {"handoff_storage_none", "handoff_storage_error", "handoff_keep"}:
        original_put = app.artifacts.put
        def fail_handoff(text, *, kind, **kwargs):
            if kind == "work-handoff":
                if scenario in {"handoff_storage_none", "handoff_keep"}:
                    return None
                raise OSError("handoff storage unavailable")
            return original_put(text, kind=kind, **kwargs)
        monkeypatch.setattr(app.artifacts, "put", fail_handoff)
    calls = []
    tool_calls = []
    model_requests = []

    if scenario in {"qualified_tools", "unadvertised_tool"}:
        from types import SimpleNamespace
        from local_ai_hub.tool_agent import ToolAwareLocalAgent
        from test_bounded_tool_qualification import _fixture

        qualification_config, _, evidence, _, _ = _fixture()
        app.work_orchestrator._tool_qualification_config = qualification_config
        original_get = app.artifacts.get
        def get_artifact(artifact_id, **kwargs):
            if artifact_id in evidence:
                return {"success": True, "artifact_id": artifact_id, "next_offset": None, **evidence[artifact_id]}
            return original_get(artifact_id, **kwargs)
        monkeypatch.setattr(app.artifacts, "get", get_artifact)

        class Runtime:
            def model_digest(self, model):
                return "a" * 64
            def request(self, endpoint, payload=None, **kwargs):
                assert endpoint == "/api/show"
                return {"capabilities": ["completion", "tools"]}
            def request_interruptible(self, endpoint, payload, **kwargs):
                model_requests.append(payload)
                if len(model_requests) == 1:
                    if scenario == "unadvertised_tool":
                        return {"message": {"role": "assistant", "content": "", "tool_calls": [
                            {"id": "bad-call", "function": {"name": "run_command", "arguments": {"command": "delete_all"}}}]}}
                    return {"message": {"role": "assistant", "content": "", "tool_calls": [
                        {"id": "call-1", "function": {"name": "repo_search", "arguments": {"query": "old"}}}]}}
                assert any(m.get("role") == "tool" and "a.txt" in m.get("content", "") for m in payload["messages"])
                return {"message": {"role": "assistant", "content": "inspection FACT-FROM-TOOL"}}

        execution = SimpleNamespace(cache_scope=lambda: {"num_ctx": 16384})
        monkeypatch.setattr(app.services, "runtime", Runtime())
        monkeypatch.setattr(app.services, "model_policy", SimpleNamespace(
            profile=lambda *a, **k: execution,
            apply_payload=lambda model, payload, **kwargs: (payload, execution)))
        monkeypatch.setattr(app.services, "scheduler", SimpleNamespace(submit=lambda model, execute, **kwargs: execute()))
        agent = ToolAwareLocalAgent(app.config, app.services, app.preprocessor, SimpleNamespace(workspace_id=lambda value: "test"))
        actual_execute_tool = agent._execute_tool
        def observe_tool(name, args, bound_root, workspace):
            result = actual_execute_tool(name, args, bound_root, workspace)
            tool_calls.append((name, bound_root))
            return result
        agent._execute_tool = observe_tool
        monkeypatch.setattr(app.services, "tool_agent", agent)

    def delegate(*_args, **_kwargs):
        calls.append(_args[0])
        if len(calls) == 1:
            steps = []
            if scenario in {"qualified_tools", "unadvertised_tool"}:
                steps.append({"id": "inspect", "kind": "inspect", "task": "find old", "depends_on": []})
            steps.extend([
                {"id": "edit", "kind": "edit", "task": "change", "depends_on": ["inspect"] if steps else []},
                {"id": "validate", "kind": "validate", "task": "test", "depends_on": ["edit"]},
            ])
            return {"success": True, "text": json.dumps({"summary": "change", "steps": steps})}
        return {"success": True, "text": "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"}

    monkeypatch.setattr(app.services, "delegate_repo", delegate)
    monkeypatch.setattr(app.services, "second_opinion", lambda *_a, **_kw: {
        "success": True, "text": json.dumps({"passed": True, "summary": "checked",
        "criteria": [{"criterion": "test passes", "passed": True}], "risks": []})})

    def call(arguments):
        response = asyncio.run(mcp_server.mcp.call_tool("local_ai_work", arguments))
        return response[1]

    try:
        submitted = call({"action": "submit", "root": str(root), "task": "change file",
            "mode": "bounded", "acceptance_criteria": ["test passes"], "allowed_paths": ["test_sample.py" if scenario == "denied" else "a.txt"],
            "approved_commands": ["python -m pytest -q test_sample.py"],
            "permissions": {"edit": True, "tests": True, "build": True},
            "budget": {"max_steps": 8, "max_seconds": 90, "max_llm_calls": 8},
            "keep_failed_workspace": scenario == "handoff_keep"})
        assert submitted["success"] is True, submitted
        handoff = call({"action": "wait", "root": str(root), "work_id": submitted["work_id"],
                        "timeout_seconds": 60, "response_profile": "standard"})
        assert handoff["status"] == ("failed" if scenario in {"denied", "handoff_storage_none", "handoff_storage_error", "handoff_keep"} else "needs_agent"), handoff
        assert handoff["success"] is False
        report = json.loads(app.artifacts.get(handoff["artifact_id"], max_chars=30000)["text"])
        if scenario not in {"denied", "handoff_storage_none", "handoff_storage_error", "handoff_keep"}:
            assert handoff["requires_primary_review"] is True
            assert report["validation"][0]["command"] == "python -m pytest -q test_sample.py"
            assert report["validation"][0]["exit_code"] == 0
        elif scenario == "denied":
            assert report["validation"] == []
        else:
            assert report["validation"][0]["exit_code"] == 0
            assert "handoff" in handoff["error"]
        if scenario == "qualified_tools":
            assert handoff["local_exploration_status"] == "completed"
            assert tool_calls == [("repo_search", str(root))]
            assert len(model_requests) == 2
            assert "inspection FACT-FROM-TOOL" in calls[1]["context"]
        if scenario == "unadvertised_tool":
            assert handoff["local_exploration_status"] == "unavailable"
            inspection = next(step for step in report["steps"] if step["kind"] == "inspect")
            assert inspection["local_exploration"]["status"] == "unavailable"
            assert tool_calls == []
            minimal = call({"action": "get", "root": str(root), "work_id": submitted["work_id"],
                            "response_profile": "minimal", "return_fields": ["summary"],
                            "max_output_tokens": 128, "max_response_tokens": 512})
            assert minimal["local_exploration_status"] == "unavailable", minimal
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == ("old" if scenario in {"denied", "handoff_storage_none", "handoff_storage_error"} else "new")
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        app.close()


def test_mcp_claim_budget_preserves_real_lease_identity(tmp_path, monkeypatch):
    import asyncio
    from local_ai_hub import http_server, mcp_server
    from local_ai_hub.client import HubClient

    root = init_repo(tmp_path)
    config = tmp_path / "isolated.toml"
    config.write_text("[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\nauto_start_ollama = false\n[ollama]\nenabled = true\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[security]\nallowed_roots = ["
        + json.dumps(str(root)) + "]\n", encoding="utf-8")
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HubClient(config_path=str(config), auto_start=False)
    client._http_port = server.server_address[1]
    client.base_url = f"http://127.0.0.1:{client._http_port}"
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    def call(arguments):
        return asyncio.run(mcp_server.mcp.call_tool("local_ai_coord", arguments))[1]
    try:
        common = {"root": str(root), "owner": "test-owner"}
        denied = call({**common, "action": "claim", "paths": ["a.txt"], "purpose": "test",
                       "max_response_tokens": 350})
        assert denied["success"] is False and denied["operation_not_started"] is True, denied
        claimed = call({**common, "action": "claim", "paths": ["a.txt"], "purpose": "test",
                        "max_response_tokens": 512})
        assert claimed["success"] is True and claimed["mutation_applied"] is True, claimed
        assert claimed["lease_id"].startswith("lease_")
        too_small = call({**common, "action": "release", "lease_id": claimed["lease_id"],
                          "max_response_tokens": 350})
        assert too_small["success"] is False and too_small["operation_not_started"] is True, too_small
        released = call({**common, "action": "release", "lease_id": claimed["lease_id"],
                         "max_response_tokens": 512})
        assert released["success"] is True and released["released_rows"] == 1 and released["mutation_applied"] is True, released
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        app.close()


def test_mcp_reports_active_bounded_deadline_without_terminal_handoff(tmp_path, monkeypatch):
    import asyncio
    import time as real_time
    import local_ai_hub.work_orchestrator as work_module
    from local_ai_hub import http_server, mcp_server
    from local_ai_hub.client import HubClient

    class Clock:
        expired = False
        def monotonic(self):
            return real_time.monotonic() + (120 if self.expired else 0)
        def __getattr__(self, name):
            return getattr(real_time, name)

    clock = Clock()
    monkeypatch.setattr(work_module, "time", clock)
    root = init_repo(tmp_path)
    config = tmp_path / "isolated.toml"
    config.write_text("[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\nauto_start_ollama = false\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[security]\nallowed_roots = ["
        + json.dumps(str(root)) + "]\n[hardware]\nprofile = \"high\"\n"
        + "[features]\nbounded_local_work = true\n[work_orchestrator]\nenabled = true\n", encoding="utf-8")
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HubClient(config_path=str(config), auto_start=False)
    client._http_port = server.server_address[1]
    client.base_url = f"http://127.0.0.1:{client._http_port}"
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server.FEATURES, "work_orchestrator", True)
    monkeypatch.setattr(mcp_server.FEATURES, "hardware_profile", "high")
    monkeypatch.setattr(mcp_server.FEATURES, "bounded_work_tier", True)
    monkeypatch.setattr(mcp_server.FEATURES, "bounded_work_qualified", True)
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **kwargs: None)
    entered, release = threading.Event(), threading.Event()
    def stalled(*_args, **_kwargs):
        entered.set()
        assert release.wait(10)
        return {"success": False, "error": "backend stopped"}
    monkeypatch.setattr(app.services, "delegate_repo", stalled)
    def call(arguments):
        return asyncio.run(mcp_server.mcp.call_tool("local_ai_work", arguments))[1]

    try:
        submitted = call({"action": "submit", "root": str(root), "task": "change file", "mode": "bounded",
            "acceptance_criteria": ["test passes"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "permissions": {"edit": True, "tests": True, "build": True},
            "budget": {"max_steps": 8, "max_seconds": 60}})
        assert submitted["success"] is True, submitted
        assert entered.wait(10)
        clock.expired = True
        for action in ("status", "get", "wait"):
            args = {"action": action, "root": str(root), "work_id": submitted["work_id"],
                    "response_profile": "minimal", "max_response_tokens": 512}
            if action == "wait":
                args["timeout_seconds"] = 0
            if action == "get":
                args["return_fields"] = ["summary"]
            result = call(args)
            assert result["success"] is False and result["timed_out"] is True, result
            assert result["in_progress"] is True and result["status"] == "planning", result
        assert (root / "a.txt").read_text().strip() == "old"
        release.set()
        handoff = wait_terminal(app.work_orchestrator, submitted["work_id"], timeout=10)
        assert handoff["status"] == "failed", handoff
        assert (root / "a.txt").read_text().strip() == "old"
    finally:
        release.set()
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        app.close()


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


def test_bounded_i2_patch_runs_in_real_browser(tmp_path, monkeypatch):
    import difflib
    import shutil
    import subprocess
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path

    from local_ai_hub.process_utils import hidden_run_kwargs
    from tools.prepare_local_model_eval_fixture import prepare_fixture

    candidates = [shutil.which("chromium"), shutil.which("google-chrome"),
                  r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
    browser = next((p for p in candidates if p and Path(p).is_file()), None)
    if not browser:
        pytest.skip("A Chromium-compatible browser is required for this UI integration test")

    root = tmp_path / "fixture"
    prepare_fixture(root, "I2")
    before = (root / "index.html").read_text(encoding="utf-8")
    after = ('<button id="toggle" aria-expanded="false">Details</button>\n'
             '<div id="panel" hidden>Details text</div>\n<script>\n'
             'const button = document.getElementById("toggle");\n'
             'const panel = document.getElementById("panel");\n'
             'button.onclick = () => {\n  const expanded = panel.hidden;\n'
             '  panel.hidden = !expanded;\n  button.setAttribute("aria-expanded", String(expanded));\n'
             '};\n</script>\n')
    patch_text = "".join(difflib.unified_diff(before.splitlines(keepends=True),
        after.splitlines(keepends=True), fromfile="a/index.html", tofile="b/index.html"))
    probe = b'''<!doctype html><body data-result="pending"><iframe id="subject" src="/index.html"></iframe>
<script>document.getElementById("subject").onload = function () {
  try {
    const d = this.contentDocument, b = d.getElementById("toggle"), p = d.getElementById("panel");
    let ok = p.hidden && b.getAttribute("aria-expanded") === "false";
    b.click(); ok = ok && !p.hidden && b.getAttribute("aria-expanded") === "true";
    b.click(); ok = ok && p.hidden && b.getAttribute("aria-expanded") === "false";
    document.body.dataset.result = ok ? "pass" : "fail";
  } catch (e) { document.body.dataset.result = "error"; }
};</script>'''

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/probe":
                return super().do_GET()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(probe)))
            self.end_headers()
            self.wfile.write(probe)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def browser_result(profile):
        result = subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--disable-background-networking", "--no-proxy-server",
            "--user-data-dir=" + str(tmp_path / profile), "--virtual-time-budget=3000", "--dump-dom",
            f"http://127.0.0.1:{server.server_address[1]}/probe"], capture_output=True,
            text=True, timeout=30, **hidden_run_kwargs())
        assert result.returncode == 0, result.stderr[-1000:]
        return result.stdout

    try:
        assert 'data-result="fail"' in browser_result("baseline-browser")
        config = tmp_path / "isolated.toml"
        config.write_text("[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
            + "\nauto_start_ollama = false\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
            + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
            + "\n[preprocessing]\nenabled = false\n[security]\nallowed_roots = ["
            + json.dumps(str(root)) + "]\n", encoding="utf-8")
        app = LocalAIApp(str(config))
        try:
            calls = []
            def delegate(args, **_kwargs):
                calls.append(args)
                if len(calls) == 1:
                    return {"success": True, "text": json.dumps({"summary": "fix toggle", "steps": [
                        {"id": "edit", "kind": "edit", "task": "fix toggle", "depends_on": []},
                        {"id": "validate", "kind": "validate", "task": "run tests", "depends_on": ["edit"]}]})}
                return {"success": True, "text": patch_text}

            monkeypatch.setattr(app.services, "delegate_repo", delegate)
            monkeypatch.setattr(app.services, "second_opinion", lambda *_a, **_kw: {
                "success": True, "text": json.dumps({"passed": True, "summary": "simulated review",
                    "criteria": [{"criterion": "toggle works", "passed": True}], "risks": []})})
            submitted = app.work_orchestrator.submit({"root": str(root), "task": "Fix the details toggle and aria-expanded",
                "mode": "bounded", "acceptance_criteria": ["toggle works"], "allowed_paths": ["index.html"],
                "approved_commands": ["python -m pytest -q tests/test_ui.py"],
                "permissions": {"edit": True, "tests": True, "build": True},
                "budget": {"max_steps": 8, "max_seconds": 90}})
            assert submitted["success"] is True, submitted
            handoff = wait_terminal(app.work_orchestrator, submitted["work_id"], timeout=60)
            assert handoff["status"] == "needs_agent" and handoff["success"] is False, handoff
            assert handoff["requires_primary_review"] is True
            report = json.loads(app.artifacts.get(handoff["artifact_id"], max_chars=30000)["text"])
            assert report["validation"][0]["exit_code"] == 0
            assert (root / "index.html").read_text(encoding="utf-8") == after
            assert 'data-result="pass"' in browser_result("patched-browser")
            diff = subprocess.run(["git", "-C", str(root), "diff", "--name-only"],
                                  capture_output=True, text=True, check=True, **hidden_run_kwargs())
            assert diff.stdout.splitlines() == ["index.html"]
        finally:
            app.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


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
