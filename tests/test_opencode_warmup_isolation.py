from types import SimpleNamespace
import json
from pathlib import Path
import subprocess
import threading
import urllib.error
import urllib.request

import pytest

from local_ai_hub import http_server


@pytest.mark.parametrize("actor,expected_warmups", [("opencode-local", 0), ("codex", 1)])
def test_task_create_only_skips_adaptive_warmup_for_opencode_local(monkeypatch, tmp_path, actor, expected_warmups):
    warmups = []
    created = []
    task = SimpleNamespace(to_dict=lambda: {"task_id": "goal-1"})
    tasks = SimpleNamespace(
        state_store=SimpleNamespace(enabled=True),
        create=lambda *args, **kwargs: (created.append((args, kwargs)) or task),
    )
    services = SimpleNamespace(schedule_task_context_warmup=lambda *args, **kwargs: warmups.append((args, kwargs)))
    app = SimpleNamespace(config={"server": {"state_dir": str(tmp_path / "state")}}, recovery=None, agent_tasks=tasks, services=services)
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "_trusted_project_context", lambda _root: SimpleNamespace(coordination_id="repo-id"))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/api/agent-state/tasks"
    handler.headers = {"Content-Type": "application/json"}
    handler._authorization_root = str(tmp_path)
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: True
    handler._read_json = lambda: {
        "action": "create", "root": str(tmp_path), "task_id": "goal-1",
        "contract": {"goal": "Fix the bug", "acceptance_criteria": ["pytest passes"]},
        "changed_paths": ["src/app.py"],
    }
    handler._validate_payload = lambda _path, _payload: None
    handler._agent = lambda: actor
    responses = []
    handler._send = lambda status, body: responses.append((status, body))

    handler.do_POST()

    assert responses[0][0] == 200, responses
    assert len(created) == 1
    assert len(warmups) == expected_warmups
    if warmups:
        assert warmups[0][1] == {"root": str(tmp_path), "changed_paths": ["src/app.py"]}


def test_goal_transport_creates_real_bound_task_without_warmup(monkeypatch, tmp_path):
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.ollama import OllamaRuntime
    from local_ai_hub.llama_cpp import LlamaCppRouter

    project = tmp_path / "repo"
    project.mkdir()
    (project / "example.py").write_text("rare_symbol_abc = 42\ndef target_function():\n    return 1\ndef caller_function():\n    return target_function()\n", encoding="utf-8")
    state_dir = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state_dir.as_posix()}"\nauto_start_ollama = false\n'
        '\n[agent_state]\nenabled = true\n[ollama]\nenabled = false\n'
        '[llama_cpp]\nmode = "off"\n[preprocessing]\nenabled = false\ntask_context_warmup = true\n',
        encoding="utf-8",
    )
    generation_attempts = []
    def forbid_generation(*args, **kwargs):
        generation_attempts.append((args, kwargs))
        return {"success": False, "error": "unexpected generation"}
    monkeypatch.setattr(OllamaRuntime, "request_stream", forbid_generation)
    monkeypatch.setattr(LlamaCppRouter, "request_stream", forbid_generation)
    app = LocalAIApp(str(config))
    # Prepare an index with a deterministic fake embedder, then forbid any
    # embedding while the actual local-profile HTTP request is handled.
    monkeypatch.setattr(app.services, "embed", lambda texts, **kw: {"success": True, "embeddings": [[1.0, 0.5] for _ in texts]})
    assert app.rag.index_step(str(project), max_files=10)["success"]
    monkeypatch.setattr(app.services, "embed", lambda *a, **kw: pytest.fail("HTTP search attempted embedding"))
    warmups = []
    delegated = []
    monkeypatch.setattr(app.services, "schedule_task_context_warmup", lambda *a, **k: warmups.append((a, k)))
    monkeypatch.setattr(app.services, "delegate", lambda payload: (delegated.append(payload) or {"success": True}))
    monkeypatch.setattr(http_server, "APP", app)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        script = '''
import { createTask, getBoundTask } from "./tools/opencode_goal/transport.js";
const state={root:process.argv[1],taskId:"goal-real-http",goal:"Fix bug",criteria:["pytest passes"]};
const opts={baseURL:`http://127.0.0.1:${process.argv[2]}`};
const created=await createTask(state,"session-real",opts);
if ((await getBoundTask(state,"session-real",opts)).success !== true) throw Error("valid binding rejected");
if ((await getBoundTask(state,"other-session",opts)).success !== false) throw Error("foreign session accepted");
console.log(JSON.stringify(created));
'''
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script, str(project.resolve()), str(server.server_address[1])],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20, check=False,
        )
        assert result.returncode == 0, result.stderr
        response = json.loads(result.stdout)
        assert response.get("success") is True, response
        task = app.agent_tasks.get("goal-real-http")
        assert task is not None and task.owner == "opencode-local"
        assert task.context.session_id == "session-real"
        assert task.contract.acceptance_criteria == ("pytest passes",)
        assert warmups == []
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        def post(path, payload, actor):
            request = urllib.request.Request(
                endpoint + path, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "X-LocalAI-Agent": actor}, method="POST",
            )
            return urllib.request.urlopen(request, timeout=5)
        with pytest.raises(urllib.error.HTTPError) as denied:
            post("/api/delegate", {"task": "probe"}, "opencode-local")
        assert denied.value.code == 403
        assert json.loads(denied.value.read())["error_code"] == "opencode_local_route_denied"
        assert delegated == []
        with pytest.raises(urllib.error.HTTPError) as action_denied:
            post("/api/agent-state/tasks", {"action": "curate_dataset", "root": str(project.resolve())}, "opencode-local")
        assert action_denied.value.code == 403
        assert json.loads(action_denied.value.read())["error_code"] == "opencode_local_action_denied"
        with post("/api/search", {"root": str(project.resolve()), "query": "rare_symbol_abc", "limit": 5}, "opencode-local") as response:
            search = json.load(response)
        assert search.get("success") is True, search
        assert any(item.get("path") == "example.py" for item in search.get("results", []))
        with post("/api/repo/callers", {"root": str(project.resolve()), "symbol": "target_function"}, "opencode-local") as response:
            callers = json.load(response)
        assert callers.get("success") is True, callers
        assert callers.get("callers"), callers
        with post("/api/rag/search", {"root": str(project.resolve()), "workspace": app.rag.workspace_id(str(project)), "query": "rare_symbol_abc"}, "opencode-local") as response:
            rag_result = json.load(response)
        assert rag_result.get("retrieval_mode") == "lexical_fallback", rag_result
        assert any(item.get("path") == "example.py" for item in rag_result.get("results", []))
        with post("/api/agent-state/memory", {"action": "record", "root": str(project.resolve()), "scope": "repository", "key": "probe-key", "value": "probe-value"}, "opencode-local") as response:
            assert json.load(response).get("success") is True
        with post("/api/agent-state/memory", {"action": "find", "root": str(project.resolve()), "query": "probe-value", "limit": 5}, "opencode-local") as response:
            memory = json.load(response)
        assert memory.get("success") is True, memory
        assert any(record.get("key") == "probe-key" for record in memory.get("records", []))
        assert generation_attempts == []
        with post("/api/delegate", {"task": "probe"}, "codex") as response:
            assert json.load(response)["success"] is True
        assert len(delegated) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        app.close()
