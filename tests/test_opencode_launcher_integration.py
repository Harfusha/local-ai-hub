import json
import base64
import os
import socket
import sqlite3
import subprocess
from contextlib import closing
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from local_ai_hub import http_server
from local_ai_hub.app import LocalAIApp
from local_ai_hub.client import HubClient
from local_ai_hub.opencode_launcher import _run_owned_process, launch_opencode
from local_ai_hub.process_utils import popen_managed, process_owner_record, terminate_tree

ROOT = Path(__file__).resolve().parents[1]
EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/OpenCode-LocalAIHub/2.2.5/opencode.exe"


@pytest.mark.skipif(os.name != "nt" or not EXE.is_file(), reason="verified Windows OpenCode 2.2.5 is not installed")
def test_real_opencode_launcher_with_fake_backend(tmp_path, monkeypatch):
    calls = []
    request_messages = []
    goal_ready = threading.Event()
    goal_settled = threading.Event()
    behavior = {"wait_for_goal": False}
    class Backend(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def do_GET(self):
            if self.path == "/goal-settled":
                goal_settled.set()
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path == "/goal-ready":
                goal_ready.set()
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            assert self.path in {"/api/tags", "/api/ps", "/api/version"}
            data = b'{"models":[{"name":"model-a"}]}' if self.path == "/api/tags" else b'{"version":"0.34.0"}' if self.path == "/api/version" else b'{"models":[]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body.get("model"))
            request_messages.append(json.dumps(body.get("messages", [])))
            if behavior["wait_for_goal"] and not goal_ready.wait(timeout=10):
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            common = {"id": "test", "object": "chat.completion.chunk", "created": 1, "model": "model-a"}
            if behavior.get("invoke_verification") and "actual tool verification probe" in request_messages[-1] and "You name conversations" not in request_messages[-1] and body.get("tools") and not behavior.get("tool_invoked"):
                behavior["tool_invoked"] = True
                behavior["advertised_tools"] = [tool.get("function", {}).get("name") for tool in body["tools"]]
                chunks = ({"index": 0, "delta": {"role": "assistant", "tool_calls": [{"index": 0, "id": "call_verify_1", "type": "function", "function": {"name": "goal_verify", "arguments": '{"alias":"test"}'}}]}, "finish_reason": None},
                          {"index": 0, "delta": {}, "finish_reason": "tool_calls"})
                for choice in chunks:
                    self.wfile.write(("data: " + json.dumps({**common, "choices": [choice]}) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
                return
            for choice in ({"index": 0, "delta": {"role": "assistant", "content": "All done."}, "finish_reason": None},
                           {"index": 0, "delta": {}, "finish_reason": "stop"}):
                self.wfile.write(("data: " + json.dumps({**common, "choices": [choice]}) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
        def log_message(self, *args):
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        hub_port = probe.getsockname()[1]
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "--quiet", str(project)], check=True, timeout=15, capture_output=True)
    (project / "test_failing.py").write_text("def test_expected_behavior():\n    assert 1 == 2\n", encoding="utf-8")
    (project / "test_passing.py").write_text("def test_success():\n    assert 1 == 1\n", encoding="utf-8")
    (project / ".local-ai.toml").write_text('[commands]\ntest = "python -m pytest -q test_passing.py -p no:cacheprovider"\n', encoding="utf-8")
    failed_test = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_failing.py"], cwd=project,
                                 capture_output=True, text=True, timeout=30)
    assert failed_test.returncode == 1 and "1 failed" in failed_test.stdout
    events_path = tmp_path / "events.jsonl"
    wait_path = tmp_path / "wait.json"
    spy = tmp_path / "event-spy"
    spy.mkdir()
    (spy / "package.json").write_text('{"name":"local-event-spy","version":"0.1.0","type":"module","private":true}', encoding="utf-8")
    (spy / "index.js").write_text('''
import { appendFile } from "node:fs/promises"
export default {id:"test.event-spy",async setup(ctx){
 const abort=new AbortController()
 let triggered=false
 void (async()=>{try{for await(const event of ctx.event.subscribe({signal:abort.signal})){
   if(["session.step.ended","session.execution.succeeded"].includes(event.type))
     await appendFile(ctx.options.path,JSON.stringify({type:event.type,data:{sessionID:event.data?.sessionID,snapshot:event.data?.snapshot},durable:event.durable})+"\\n")
   if(event.type === "session.execution.started") {
     if(ctx.options.triggerGoal && !triggered) {
       triggered=true
       void ctx.session.command({sessionID:event.data.sessionID,name:"goal",text:'{"goal":"isolated goal command probe","criteria":["pytest passes"],"maxTurns":1}'})
         .then(()=>fetch(ctx.options.readyURL))
         .catch(async e=>appendFile(ctx.options.waitPath,JSON.stringify({commandError:String(e)})+"\\n"))
     }
     void (async()=>{try{
       await ctx.session.wait({sessionID:event.data.sessionID})
       const info=await ctx.session.get({sessionID:event.data.sessionID})
       await appendFile(ctx.options.waitPath,JSON.stringify({id:info.id,outcome:info.outcome})+"\\n")
     }catch{}})()
   }
 }}catch{}})()
 return ()=>abort.abort()
}}
''', encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nstate_dir="{(tmp_path / "state").as_posix()}"\nport={hub_port}\nollama_url="http://127.0.0.1:{backend.server_port}"\nauto_start_ollama=false\n'
        f'[security]\napi_token="{"x" * 40}"\nallowed_roots=["{project.as_posix()}"]\n[ollama]\nenabled=false\n[llama_cpp]\nmode="off"\n'
        '[background_gpu]\nenabled=false\n[preprocessing]\nenabled=false\n', encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    owner = process_owner_record(os.getpid(), tmp_path / "state", "ollama")
    (tmp_path / "state" / "ollama.owner.json").write_text(json.dumps(owner), encoding="utf-8")
    monkeypatch.setattr(http_server, "APP", app)
    hub_requests = []
    class InstrumentedHubHandler(http_server.Handler):
        def do_POST(self):
            hub_requests.append(self.path)
            return super().do_POST()
    server = http_server.LocalAIHTTPServer(("127.0.0.1", hub_port), InstrumentedHubHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        client = HubClient(config_path=str(config), auto_start=False)
        def run_child(argv, *, cwd, env, timeout):
            runtime = json.loads(env["OPENCODE_CONFIG_CONTENT"])
            runtime["plugins"].append({"package": str(spy), "options": {"path": str(events_path), "waitPath": str(wait_path)}})
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(runtime)
            return _run_owned_process([argv[0], "run", "--standalone", "--model", "local-hub/model-a", "Say OK"], cwd=cwd, env=env, timeout=timeout)
        assert launch_opencode(client, install_dir=ROOT, hub_python=Path(sys.executable), executable=EXE,
                               project=project, model="model-a", run_child=run_child, timeout_seconds=30) == 0
        assert calls and set(calls) == {"model-a:local"}
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        step = next(event for event in events if event["type"] == "session.step.ended")
        end = next(event for event in events if event["type"] == "session.execution.succeeded")
        assert step["data"]["sessionID"] == end["data"]["sessionID"] == step["durable"]["aggregateID"] == end["durable"]["aggregateID"]
        assert isinstance(step["durable"]["seq"], int) and step["durable"]["seq"] < end["durable"]["seq"]
        assert len(step["data"].get("snapshot", "")) in (40, 64)
        waited = json.loads(wait_path.read_text(encoding="utf-8").strip())
        assert waited == {"id": step["data"]["sessionID"], "outcome": "succeeded"}
        replay = r'''
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { makeGoalController } from "./tools/opencode_goal/index.js";
const [step,end]=JSON.parse(readFileSync(0,"utf8")), id=step.data.sessionID, db=new Map();
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>({id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}})}};
const controller=makeGoalController(ctx,{resolveRoot:async p=>p,
 getBoundTaskImpl:async()=>({success:true,task:{checkpoint:{phase:"work"}}}),completeTaskImpl:async()=>({success:false})});
await controller.start(id,{goal:"Fix",taskId:"t",criteria:["pytest"]});
controller.observeStep(step); await controller.settle({...end,id:"actual-end"});
assert.equal((await controller.status(id)).observations.length,1);
'''
        subprocess.run(["node", "--input-type=module", "-e", replay], cwd=ROOT, input=json.dumps([step, end]),
                       capture_output=True, text=True, check=True, timeout=15)
        def run_goal(argv, *, cwd, env, timeout):
            runtime = json.loads(env["OPENCODE_CONFIG_CONTENT"])
            runtime["plugins"].append({"package": str(spy), "options": {"path": str(events_path), "waitPath": str(wait_path), "triggerGoal": True, "readyURL": f"http://127.0.0.1:{backend.server_port}/goal-ready"}})
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(runtime)
            behavior["wait_for_goal"] = True
            return _run_owned_process([argv[0], "run", "--standalone", "--model", "local-hub/model-a", "Start goal probe"],
                                      cwd=cwd, env=env, timeout=timeout)
        assert launch_opencode(client, install_dir=ROOT, hub_python=Path(sys.executable), executable=EXE,
                               project=project, model="model-a", run_child=run_goal, timeout_seconds=30) == 0
        created_tasks = app.agent_tasks.list_tasks(query="isolated goal command probe")
        storage_db = tmp_path / "state" / "opencode-local" / "data" / "opencode" / "opencode.db"
        with closing(sqlite3.connect(f"file:{storage_db.as_posix()}?mode=ro", uri=True)) as db:
            saved_goals = [json.loads(row[0]) for row in db.execute("SELECT value FROM kv WHERE key LIKE 'plugin:%:goal:%'")]
        assert len(created_tasks) == 1
        assert created_tasks[0].contract.goal == "isolated goal command probe"
        assert getattr(created_tasks[0].status, "value", created_tasks[0].status) != "completed"
        assert len(saved_goals) == 1 and saved_goals[0]["taskId"] == created_tasks[0].task_id
        assert saved_goals[0]["status"] != "DONE"
        assert any("Continue the goal: isolated goal command probe" in message for message in request_messages)
        assert (project / "test_failing.py").read_text(encoding="utf-8") == "def test_expected_behavior():\n    assert 1 == 2\n"
        wrapper = tmp_path / "goal-wrapper"
        wrapper.mkdir()
        (wrapper / "package.json").write_text('{"name":"goal-test-wrapper","version":"0.1.0","type":"module","private":true}', encoding="utf-8")
        (wrapper / "index.js").write_text('''
import goal from ''' + json.dumps((ROOT / "tools/opencode_goal/index.js").as_uri()) + '''
export default {id:goal.id,setup(ctx){
 const storage={...ctx.storage,set:async(key,value)=>{
   await ctx.storage.set(key,value)
   if(key.startsWith("goal:") && ["FAILED","BLOCKED","DONE"].includes(value.status) && value.turns > 0 && !value.pendingOperation) await fetch(ctx.options.signalURL)
 }}
 return goal.setup(new Proxy(ctx,{get:(target,key)=>key==="storage"?storage:Reflect.get(target,key)}))
}}
''', encoding="utf-8")
        def run_service(argv, *, cwd, env, timeout):
            behavior["wait_for_goal"] = False
            runtime = json.loads(env["OPENCODE_CONFIG_CONTENT"])
            runtime["plugins"][0]["package"] = str(wrapper)
            runtime["plugins"][0]["options"]["signalURL"] = f"http://127.0.0.1:{backend.server_port}/goal-settled"
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(runtime)
            env["OPENCODE_PASSWORD"] = "isolated-test-password"
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            proc = popen_managed([argv[0], "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                                 cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace")
            ready = threading.Event()
            logs = []
            def drain():
                for line in proc.stdout:
                    logs.append(line)
                    if "http://" in line:
                        ready.set()
            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            try:
                assert ready.wait(timeout=15), "OpenCode test server did not announce its listener"
                auth = base64.b64encode(b"opencode:isolated-test-password").decode("ascii")
                def post(path, payload):
                    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Authorization": "Basic " + auth}, method="POST")
                    with urllib.request.urlopen(request, timeout=20) as response:
                        body = response.read()
                        return json.loads(body) if body else None
                idempotency_session = post("/api/session", {})["data"]["id"]
                prompt_id = "msg_1234567890abcdef1234567890abcdef"
                prompt_payload = {"id": prompt_id, "text": "Unique idempotency probe", "delivery": "queue"}
                first = post(f"/api/session/{idempotency_session}/prompt", prompt_payload)
                post(f"/api/experimental/session/{idempotency_session}/wait", {})
                second = post(f"/api/session/{idempotency_session}/prompt", prompt_payload)
                post(f"/api/experimental/session/{idempotency_session}/wait", {})
                assert first["data"]["id"] == prompt_id == second["data"]["id"]
                assert len([message for message in request_messages if "Unique idempotency probe" in message
                            and "You name conversations" not in message]) == 1
                request = urllib.request.Request(f"http://127.0.0.1:{port}/api/session/{idempotency_session}/context",
                    headers={"Authorization": "Basic " + auth})
                with urllib.request.urlopen(request, timeout=20) as response:
                    context = json.load(response)["data"]
                matching = [message for message in context if message.get("id") == prompt_id]
                assert len(matching) == 1 and matching[0].get("text") == "Unique idempotency probe", context
                assert matching[0].get("type") == "user", context
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/session/{idempotency_session}/message/{prompt_id}",
                    headers={"Authorization": "Basic " + auth})
                with urllib.request.urlopen(request, timeout=20) as response:
                    exact_message = json.load(response)["data"]
                assert exact_message == matching[0]
                try:
                    post(f"/api/session/{idempotency_session}/prompt",
                         {**prompt_payload, "text": "A different prompt using the same ID"})
                except urllib.error.HTTPError as exc:
                    assert 400 <= exc.code < 500
                else:
                    post(f"/api/experimental/session/{idempotency_session}/wait", {})
                with urllib.request.urlopen(request, timeout=20) as response:
                    assert json.load(response)["data"] == exact_message
                assert not any("A different prompt using the same ID" in message for message in request_messages)
                matching_index = context.index(matching[0])
                assert any(message.get("type") == "idle" and message.get("outcome") == "succeeded"
                           for message in context[matching_index + 1:]), context
                request = urllib.request.Request(f"http://127.0.0.1:{port}/api/session/{idempotency_session}",
                    headers={"Authorization": "Basic " + auth})
                with urllib.request.urlopen(request, timeout=20) as response:
                    session_info = json.load(response)["data"]
                assert session_info.get("outcome") == "succeeded", session_info
                recovery_session = post("/api/session", {})["data"]["id"]
                recovery_id = "msg_9876543210abcdef9876543210abcdef"
                recovery_text = ("Continue the goal: Fix\nTask ID: t\nAcceptance criteria:\n- pytest\n"
                                 "Use goal_verify with a configured verification alias to obtain authentic Agent OS receipts; do not claim completion without evidence.")
                post(f"/api/session/{recovery_session}/prompt", {"id": recovery_id, "text": recovery_text, "delivery": "queue"})
                post(f"/api/experimental/session/{recovery_session}/wait", {})
                def get_session_data(path):
                    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Authorization": "Basic " + auth})
                    with urllib.request.urlopen(request, timeout=20) as response:
                        return json.load(response)["data"]
                recovery_info = get_session_data(f"/api/session/{recovery_session}")
                recovery_context = get_session_data(f"/api/session/{recovery_session}/context")
                recovery_script = r'''
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {makeGoalController} from "./tools/opencode_goal/index.js";
const {info,history,promptId}=JSON.parse(readFileSync(0,"utf8"));let prompts=0;
let state={goal:"Fix",taskId:"t",criteria:["pytest"],root:info.location.directory,epoch:"epoch",
 status:"BLOCKED",outcomeUnknown:true,pendingOperation:"prompt_admission",pendingPromptId:promptId};
const ctx={storage:{get:async()=>structuredClone(state),set:async(_k,v)=>{state=structuredClone(v)}},
 session:{get:async()=>info,context:async()=>history,prompt:async()=>{prompts++}}};
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true})});
const result=await c.resume(info.id);assert.equal(result.status,"PAUSED");assert.equal(prompts,0);
'''
                subprocess.run(["node", "--input-type=module", "-e", recovery_script], cwd=ROOT,
                               input=json.dumps({"info": recovery_info, "history": recovery_context, "promptId": recovery_id}),
                               capture_output=True, text=True, check=True, timeout=15)
                session = post("/api/session", {})["data"]["id"]
                prior_requests = len(request_messages)
                post(f"/api/session/{session}/command", {"name": "goal", "text": json.dumps({"goal":"persistent goal probe","criteria":["pytest passes"],"maxTurns":2})})
                assert goal_settled.wait(timeout=20), "goal did not persist a settled turn"
                goal_requests = [message for message in request_messages[prior_requests:]
                                 if "Continue the goal: persistent goal probe" in message and "You name conversations" not in message]
                assert len(goal_requests) == 2
                goal_settled.clear()
                behavior["invoke_verification"] = True
                tool_session = post("/api/session", {})["data"]["id"]
                post(f"/api/session/{tool_session}/command", {"name": "goal", "text": json.dumps({"goal":"actual tool verification probe","criteria":["test"],"maxTurns":1})})
                assert goal_settled.wait(timeout=30), "goal verification did not settle"
                tool_tasks = app.agent_tasks.list_tasks(query="actual tool verification probe")
                assert len(tool_tasks) == 1 and behavior.get("tool_invoked")
                if tool_tasks[0].status.value != "completed":
                    raise AssertionError(json.dumps({"tools": behavior.get("advertised_tools"), "context": get_session_data(f"/api/session/{tool_session}/context")}))
                assert "/api/agent-state/verification" in hub_requests
                behavior["invoke_verification"] = False
                goal_settled.clear()
                goal_ready.clear()
                behavior["wait_for_goal"] = True
                success_session = post("/api/session", {})["data"]["id"]
                behavior["success_session"] = success_session
                post(f"/api/session/{success_session}/command", {"name": "goal", "text": json.dumps({"goal":"verified completion probe","criteria":["pytest passes"],"maxTurns":1})})
                tasks = app.agent_tasks.list_tasks(query="verified completion probe")
                assert len(tasks) == 1
                forged = urllib.request.Request(
                    f"http://127.0.0.1:{hub_port}/api/agent-state/verification",
                    data=json.dumps({"action": "receipt", "root": str(project),
                                     "receipt": {"task_id": tasks[0].task_id, "criterion": "pytest passes",
                                                 "passed": True, "evidence_id": "nonexistent-evidence"}}).encode(),
                    headers={"Content-Type": "application/json", "X-LocalAI-Token": env["LOCAL_AI_HUB_TOKEN"],
                             "X-LocalAI-Agent": "cloud-agent"}, method="POST")
                with pytest.raises(urllib.error.HTTPError) as rejected:
                    urllib.request.urlopen(forged, timeout=10)
                assert rejected.value.code == 400
                rejected.value.close()
                assert app.agent_tasks.get(tasks[0].task_id).status.value != "completed"
                receipt = app.commands.run("python -m pytest -q test_passing.py -p no:cacheprovider", str(project),
                                           timeout=30, task_id=tasks[0].task_id, criterion="pytest passes", bypass_cache=True)
                proof = receipt.get("verification_receipt", {})
                assert receipt.get("exit_code") == 0 and proof.get("passed") is True, receipt
                assert proof.get("task_id") == tasks[0].task_id and proof.get("criterion") == "pytest passes"
                assert proof.get("owner") == "opencode-local" and proof.get("evidence_id") and proof.get("command_id")
                goal_ready.set()
                assert goal_settled.wait(timeout=20), "verified goal did not persist a settled turn"
                goal_settled.clear()
                goal_ready.clear()
                behavior["wait_for_goal"] = True
                restart_session = post("/api/session", {})["data"]["id"]
                before_restart = len(request_messages)
                post(f"/api/session/{restart_session}/command", {"name": "goal", "text": json.dumps({"goal":"restart goal probe","criteria":["pytest passes"],"maxTurns":1})})
                post(f"/api/session/{restart_session}/command", {"name": "goal", "text": "pause"})
                with closing(sqlite3.connect(f"file:{storage_db.as_posix()}?mode=ro", uri=True)) as db:
                    paused = [json.loads(row[0]) for row in db.execute("SELECT value FROM kv WHERE key LIKE 'plugin:%:goal:%'")]
                paused = next(item for item in paused if item["goal"] == "restart goal probe")
                assert paused["status"] == "PAUSED" and not paused.get("outcomeUnknown")
                goal_ready.set()
                post(f"/api/experimental/session/{restart_session}/wait", {})
                before_relaunch = [message for message in request_messages[before_restart:]
                                   if "Continue the goal: restart goal probe" in message and "You name conversations" not in message]
                assert len(before_relaunch) == 1
                assert terminate_tree(proc.pid, process_handle=proc)
                proc.wait(timeout=5)
                reader.join(timeout=3)
                proc.stdout.close()
                ready.clear()
                behavior["wait_for_goal"] = False
                proc = popen_managed([argv[0], "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                                     cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace")
                reader = threading.Thread(target=drain, daemon=True)
                reader.start()
                assert ready.wait(timeout=15), "restarted OpenCode server did not announce its listener"
                post(f"/api/session/{restart_session}/command", {"name": "goal", "text": "resume"})
                assert goal_settled.wait(timeout=20), "resumed goal did not settle"
                after_relaunch = [message for message in request_messages[before_restart:]
                                  if "Continue the goal: restart goal probe" in message and "You name conversations" not in message]
                assert len(after_relaunch) == 2
                return 0
            finally:
                assert terminate_tree(proc.pid, process_handle=proc)
                proc.wait(timeout=5)
                reader.join(timeout=3)
                proc.stdout.close()
        hub_requests.clear()
        assert launch_opencode(client, install_dir=ROOT, hub_python=Path(sys.executable), executable=EXE,
                               project=project, model="model-a", run_child=run_service, timeout_seconds=40) == 0
        persistent_tasks = app.agent_tasks.list_tasks(query="persistent goal probe")
        assert len(persistent_tasks) == 1
        assert getattr(persistent_tasks[0].status, "value", persistent_tasks[0].status) != "completed"
        with closing(sqlite3.connect(f"file:{storage_db.as_posix()}?mode=ro", uri=True)) as db:
            persisted = [json.loads(row[0]) for row in db.execute("SELECT value FROM kv WHERE key LIKE 'plugin:%:goal:%'")]
        saved = next(item for item in persisted if item["goal"] == "persistent goal probe")
        assert saved["taskId"] == persistent_tasks[0].task_id
        assert "/api/agent-state/verification" in hub_requests
        assert saved["turns"] == 2 and saved["status"] == "FAILED"
        assert saved["reason"] == "continuation limit reached"
        successful = next(item for item in persisted if item["goal"] == "verified completion probe")
        assert successful["status"] == "DONE"
        assert app.agent_tasks.get(successful["taskId"]).status.value == "completed"
        recovery = r'''
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {getCompletedTask} from "./tools/opencode_goal/transport.js";
import {makeGoalController} from "./tools/opencode_goal/index.js";
const {state,session,url,token}=JSON.parse(readFileSync(0,"utf8"));
const result=await getCompletedTask(state,session,{baseURL:url,token});
assert.equal(result.success,true);
assert.equal(result.task.status,"completed");
let stored={...state,status:"BLOCKED",turns:0,eventIds:[],pendingOperation:"task_complete",pendingEventId:"recovered-event",outcomeUnknown:true};
let prompts=0;
const ctx={storage:{get:async()=>structuredClone(stored),set:async(_k,v)=>{stored=structuredClone(v)}},
 session:{get:async()=>({location:{directory:state.root}}),prompt:async p=>{prompts++;return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const controller=makeGoalController(ctx,{resolveRoot:async p=>p,transport:{baseURL:url,token}});
const recovered=await controller.resume(session);
assert.equal(recovered.status,"DONE");assert.deepEqual(recovered.eventIds,["recovered-event"]);assert.equal(prompts,0);
'''
        recovery_input = {"state": successful, "session": behavior["success_session"],
                          "url": f"http://127.0.0.1:{hub_port}", "token": "x" * 40}
        subprocess.run(["node", "--input-type=module", "-e", recovery], cwd=ROOT,
                       input=json.dumps(recovery_input), capture_output=True, text=True, check=True, timeout=15)
        stale_recovery = r'''
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {getCompletedTask} from "./tools/opencode_goal/transport.js";
const {state,session,url,token}=JSON.parse(readFileSync(0,"utf8"));
const result=await getCompletedTask(state,session,{baseURL:url,token});
assert.equal(result.success,false);
'''
        evidence_file = project / "test_passing.py"
        original_evidence = evidence_file.read_bytes()
        try:
            evidence_file.write_bytes(original_evidence + b"\n# changed after verification\n")
            subprocess.run(["node", "--input-type=module", "-e", stale_recovery], cwd=ROOT,
                           input=json.dumps(recovery_input), capture_output=True, text=True, check=True, timeout=15)
        finally:
            evidence_file.write_bytes(original_evidence)
        restarted = next(item for item in persisted if item["goal"] == "restart goal probe")
        assert len(app.agent_tasks.list_tasks(query="restart goal probe")) == 1 and restarted["turns"] == 1
        assert restarted["status"] == "FAILED" and restarted["reason"] == "continuation limit reached"
        assert calls and set(calls) == {"model-a:local"}
        create_lost = r'''
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {makeGoalController} from "./tools/opencode_goal/index.js";
const {root,url,token}=JSON.parse(readFileSync(0,"utf8")),db=new Map(),prompts=[]; let committed=false;
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:root}}),prompt:async p=>{prompts.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const fetchImpl=async (url,opts)=>{const response=await fetch(url,opts); if(JSON.parse(opts.body).action==="create"){
 const payload=await response.json(); committed=response.ok && payload.success===true;
 throw new Error("simulated lost response after server commit");} return response};
const controller=makeGoalController(ctx,{resolveRoot:async p=>p,transport:{baseURL:url,token,fetchImpl}});
await assert.rejects(controller.start("recovery-session",{goal:"Recover",criteria:["pytest"]}));
assert.equal(committed,true,"server did not confirm task creation before the simulated response loss");
assert.equal(prompts.length,0); const state=await controller.status("recovery-session");
assert.equal(state.pendingOperation,"task_create"); console.log(JSON.stringify(state));
'''
        resume = r'''
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {makeGoalController} from "./tools/opencode_goal/index.js";
import {getBoundTask} from "./tools/opencode_goal/transport.js";
const {root,url,token,state}=JSON.parse(readFileSync(0,"utf8")),db=new Map([["goal:recovery-session",state]]),prompts=[];
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:root}}),prompt:async p=>{prompts.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const controller=makeGoalController(ctx,{resolveRoot:async p=>p,transport:{baseURL:url,token}});
await controller.resume("recovery-session");
if((await controller.status("recovery-session")).status!=="CONTINUE") {
 const response=await fetch(url+"/api/agent-state/tasks",{method:"POST",headers:{"Content-Type":"application/json","X-LocalAI-Token":token,"X-LocalAI-Agent":"opencode-local"},body:JSON.stringify({action:"get",root,task_id:state.taskId})});
 console.error(JSON.stringify(await response.json()),JSON.stringify(await getBoundTask(state,"recovery-session",{baseURL:url,token})));
}
assert.equal((await controller.status("recovery-session")).status,"CONTINUE");
assert.equal(prompts.length,1);
'''
        args = {"root": str(project.resolve()), "url": f"http://127.0.0.1:{hub_port}", "token": "x" * 40}
        pending = subprocess.run(["node", "--input-type=module", "-e", create_lost], cwd=ROOT, input=json.dumps(args),
                                 capture_output=True, text=True, check=True, timeout=20)
        resumed = subprocess.run(["node", "--input-type=module", "-e", resume], cwd=ROOT,
                                 input=json.dumps({**args, "state": json.loads(pending.stdout)}),
                                 capture_output=True, text=True, timeout=20)
        assert resumed.returncode == 0, resumed.stderr
        assert app.opencode_provider.status()["state"] == "stopped"
        assert not app.scheduler.foreground_busy()
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=3)
        app.close(timeout=10)
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=3)
