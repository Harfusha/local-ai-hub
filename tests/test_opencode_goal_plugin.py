from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_goal_verification_transport_binds_request_and_session():
    script = r'''
import assert from "node:assert/strict";
import {runProjectCommand} from "./tools/opencode_goal/transport.js";
let sent;
const result=await runProjectCommand({root:"C:/repo",taskId:"task",criteria:["test"]},"session","test","a".repeat(32),
 {baseURL:"http://127.0.0.1:11435",fetchImpl:async(url,opts)=>{
  sent={url,opts};return new Response(JSON.stringify({success:true,verification_receipt:{evidence_id:"e"}}));
 }});
assert.equal(result.verification_receipt.evidence_id,"e");
assert.equal(sent.opts.headers["X-LocalAI-Request-ID"],"a".repeat(32));
assert.equal(sent.opts.headers["X-LocalAI-Token"],undefined);
assert.equal(sent.opts.headers.Authorization,undefined);
assert.deepEqual(JSON.parse(sent.opts.body),{action:"project_command",root:"C:/repo",task_id:"task",session_id:"session",alias:"test"});
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_verification_tool_requires_shell_permission():
    script = r'''
import assert from "node:assert/strict";
import plugin from "./tools/opencode_goal/index.js";
let tool, requested, writes=0;
const ctx={options:{hubURL:"http://127.0.0.1:11435"},
 command:{transform:async f=>f({add:()=>{}})},tool:{transform:async f=>f({add:t=>{tool=t}})},
 permission:{assert:async p=>{requested=p;throw new Error("denied")}},
 storage:{get:async()=>null,set:async()=>{writes++}},
 event:{subscribe:async function*(){await new Promise(()=>{})}}};
const stop=await plugin.setup(ctx);
assert.equal(tool.name,"goal_verify");
await assert.rejects(tool.execute({alias:"test"},{sessionID:"s",agent:"reviewer",messageID:"m",id:"i"}),/denied/);
assert.equal(requested.action,"shell");assert.equal(requested.sessionID,"s");assert.equal(writes,0);
stop();
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_goal_verification_records_intent_and_blocks_uncertain_repeat():
    script = r'''
import assert from "node:assert/strict";
import {makeGoalController} from "./tools/opencode_goal/index.js";
const db=new Map(), calls=[];
const initial={root:"C:/repo",taskId:"task",epoch:"epoch",status:"CONTINUE",goal:"Fix",criteria:["pytest"]};
db.set("goal:s",initial);
const ctx={storage:{get:async k=>structuredClone(db.get(k)),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({id:"s",location:{directory:"C:/repo"}})}};
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true}),
 runProjectCommandImpl:async(state,id,alias,requestId)=>{
  calls.push({state,id,alias,requestId});
  assert.equal(db.get("goal-verify:s").status,"pending");
  return {success:false,outcome_unknown:true};
 }});
const result=await c.verifyProject("s","pytest");
assert.equal(result.outcome_unknown,true);
assert.match(calls[0].requestId,/^[a-f0-9]{32}$/);
assert.equal(calls[0].state.taskId,"task");
assert.equal(calls[0].id,"s");
assert.equal((await c.verifyProject("s","pytest")).outcome_unknown,true);
assert.equal(calls.length,1);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_pause_during_goal_verification_preserves_uncertainty():
    script = r'''
import assert from "node:assert/strict";
import {makeGoalController} from "./tools/opencode_goal/index.js";
const db=new Map([["goal:s",{root:"C:/repo",taskId:"task",epoch:"e",status:"CONTINUE",goal:"Fix",criteria:["test"]}]]);
let started,release;const ready=new Promise(r=>started=r),wait=new Promise(r=>release=r);
const ctx={storage:{get:async k=>structuredClone(db.get(k)),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}})}};
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true}),
 runProjectCommandImpl:async()=>{started();await wait;return {success:true}}});
const call=c.verifyProject("s","test");await ready;await c.pause("s");release();
assert.equal((await call).outcome_unknown,true);
assert.equal((await c.status("s")).status,"PAUSED");
assert.equal((await c.status("s")).outcomeUnknown,true);
assert.equal(db.get("goal-verify:s").status,"pending");
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_cancelled_tool_keeps_verification_outcome_unknown():
    script = r'''
import assert from "node:assert/strict";
import {makeGoalController} from "./tools/opencode_goal/index.js";
const db=new Map([["goal:s",{root:"C:/repo",taskId:"task",epoch:"e",status:"CONTINUE",goal:"Fix",criteria:["test"]}]]);
let started;const ready=new Promise(r=>started=r),abort=new AbortController();
const ctx={storage:{get:async k=>structuredClone(db.get(k)),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}})}};
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true}),
 runProjectCommandImpl:async(_state,_id,_alias,_request,options)=>{started();await new Promise(r=>options.signal.addEventListener("abort",r,{once:true}));return {success:true}}});
const call=c.verifyProject("s","test",abort.signal);await ready;abort.abort();
assert.equal((await call).outcome_unknown,true);
assert.equal(db.get("goal-verify:s").status,"pending");
assert.equal((await c.verifyProject("s","test")).outcome_unknown,true);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_prompt_recovery_requires_matching_terminal_history_and_binding():
    script = r'''
import assert from "node:assert/strict";
import {makeGoalController} from "./tools/opencode_goal/index.js";
for (const variant of ["valid","missing","wrong-text","foreign-user","unfinished","binding","busy","wrong-session","duplicate","failed","failed-first","interrupted-first","multiple-idles"]) {
 const db=new Map();let submitted, calls=0, bound=true;
 const ctx={storage:{get:async k=>structuredClone(db.get(k)),set:async(k,v)=>db.set(k,structuredClone(v))},
  session:{get:async()=>({id:variant==="wrong-session"?"other":"s",location:{directory:"C:/repo"},
   outcome:variant==="failed"?"failed":"succeeded",time:{busy:variant==="busy"?3:1,idle:2}}),
   prompt:async p=>{calls++;submitted=p},context:async()=>{
    if(variant==="missing")return [];
    const msg={id:submitted.id,type:"user",text:variant==="wrong-text"?"different":submitted.text};
    return [msg,...(variant==="duplicate"?[msg]:[]),...(variant==="foreign-user"?[{id:"foreign",type:"user",text:"other"}]:[]),
     ...(["failed-first","interrupted-first","multiple-idles"].includes(variant)?[{id:"earlier-idle",type:"idle",outcome:variant==="failed-first"?"failed":variant==="interrupted-first"?"interrupted":"succeeded"}]:[]),
     ...(variant==="unfinished"?[]:[{id:"idle-1",type:"idle",outcome:"succeeded"}])];
   }}};
 const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:bound})});
 await c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
 if(variant==="binding") bound=false;
 const state=await c.resume("s");
 assert.equal(state.status,variant==="valid"?"PAUSED":"BLOCKED",variant);
 assert.equal(calls,1,variant);
 if(variant==="valid")assert.equal(state.pendingOperation,undefined);
}
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_pause_wins_during_prompt_history_recovery():
    script = r'''
import assert from "node:assert/strict";
import {makeGoalController} from "./tools/opencode_goal/index.js";
let entered,release,submitted,calls=0;const started=new Promise(r=>entered=r),pending=new Promise(r=>release=r),db=new Map();
const ctx={storage:{get:async k=>structuredClone(db.get(k)),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({id:"s",location:{directory:"C:/repo"},outcome:"succeeded",time:{busy:1,idle:2}}),
  prompt:async p=>{calls++;submitted=p},context:async()=>{entered();await pending;return [
   {id:submitted.id,type:"user",text:submitted.text},{id:"idle-1",type:"idle",outcome:"succeeded"}]}}};
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true})});
await c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
const recovery=c.resume("s");await started;await c.pause("s");release();await recovery;
const state=await c.status("s");assert.equal(state.status,"PAUSED");
assert.equal(state.pendingOperation,"prompt_admission");assert.equal(state.outcomeUnknown,true);assert.equal(calls,1);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_prompt_admission_requires_exact_acknowledgement():
    script = r'''
import assert from "node:assert/strict";
import {makeGoalController} from "./tools/opencode_goal/index.js";
for (const variant of ["missing", "wrong-id", "wrong-session", "wrong-text", "valid"]) {
 const db=new Map();
 const ctx={storage:{get:async k=>structuredClone(db.get(k)),set:async(k,v)=>db.set(k,structuredClone(v))},
  session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{
   if(variant==="missing")return undefined;
   return {id:variant==="wrong-id"?"msg_wrong":p.id,sessionID:variant==="wrong-session"?"other":p.sessionID,type:"user",
    payload:{text:variant==="wrong-text"?"different prompt":p.text}};
  }}};
 const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true})});
 await c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
 const state=await c.status("s");
 assert.equal(state.status,variant==="valid"?"CONTINUE":"BLOCKED",variant);
 if(variant!=="valid") {assert.equal(state.outcomeUnknown,true);assert.equal(state.pendingOperation,"prompt_admission")}
}
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_completed_task_recovery_requires_exact_binding_and_fresh_receipts():
    script = r'''
import assert from "node:assert/strict";
import {getCompletedTask} from "./tools/opencode_goal/transport.js";
const state={goal:"Fix",taskId:"t",root:"C:/repo",criteria:["pytest"]};
const task={task_id:"t",status:"completed",owner:"opencode-local",context:{session_id:"s"},
 contract:{goal:"Fix",acceptance_criteria:["pytest"]},checkpoint:{state_data:{_agent_task_scope:{version:2,repo_root:"C:/repo"}}}};
let current=structuredClone(task), stale=false, calls=[];
const options={baseURL:"http://127.0.0.1:11435",fetchImpl:async(url,req)=>{
 calls.push([url,JSON.parse(req.body)]);
 if(url.endsWith("/tasks"))return new Response(JSON.stringify({success:true,task:current}),{status:200});
 return new Response(JSON.stringify({success:true,completion:{task_id:"t",complete:!stale,
 satisfied_criteria:stale?[]:["pytest"],unsatisfied_criteria:[],stale_criteria:stale?["pytest"]:[]}}),{status:200});
}};
assert.equal((await getCompletedTask(state,"s",options)).success,true);
assert.deepEqual(calls.map(item=>item[1].action),["get","completion"]);
stale=true; assert.equal((await getCompletedTask(state,"s",options)).success,false);
stale=false; current={...task,owner:"other"};
assert.equal((await getCompletedTask(state,"s",options)).success,false);
current={...task,status:"active"};
assert.equal((await getCompletedTask(state,"s",options)).success,false);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_resume_reconciles_only_confirmed_completed_task():
    script = r'''
import assert from "node:assert/strict";
import {makeGoalController} from "./tools/opencode_goal/index.js";
const db=new Map();let confirmed=false,prompts=0;
const ctx={storage:{get:async k=>structuredClone(db.get(k)),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts++;return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const task={task_id:"t",status:"completed",contract:{acceptance_criteria:["pytest"]}};
const options={resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true}),
 getCompletedTaskImpl:async()=>confirmed?{success:true,task}:{success:false}};
const controller=makeGoalController(ctx,options);
await controller.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
const initial=await controller.status("s");
db.set("goal:s",{...initial,status:"BLOCKED",pendingOperation:"task_complete",pendingEventId:"event-1",outcomeUnknown:true});
await controller.resume("s");
assert.equal((await controller.status("s")).status,"BLOCKED");
confirmed=true;
const recovered=await controller.resume("s");
assert.equal(recovered.status,"DONE");
assert.deepEqual(recovered.eventIds,["event-1"]);
assert.equal(recovered.pendingOperation,undefined);
assert.equal(prompts,1);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_pause_wins_during_completed_task_reconciliation():
    script = r'''
import assert from "node:assert/strict";
import {makeGoalController} from "./tools/opencode_goal/index.js";
let entered, release; const started=new Promise(r=>entered=r), pending=new Promise(r=>release=r), db=new Map();
const ctx={storage:{get:async k=>structuredClone(db.get(k)),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>({id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}})}};
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true}),
 getCompletedTaskImpl:async()=>{entered();await pending;return {success:true,task:{task_id:"t",status:"completed",contract:{acceptance_criteria:["pytest"]}}}}});
await c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
const initial=await c.status("s");
db.set("goal:s",{...initial,status:"BLOCKED",pendingOperation:"task_complete",pendingEventId:"event-1",outcomeUnknown:true});
const recovering=c.resume("s");await started;await c.pause("s");release();await recovering;
const state=await c.status("s");assert.equal(state.status,"PAUSED");assert.equal(state.outcomeUnknown,true);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_task_completion_waits_for_recorded_intent():
    script = r'''
import assert from "node:assert/strict";
import {completeTask} from "./tools/opencode_goal/transport.js";
let entered, release, requests=[];
const started=new Promise(r=>entered=r), pending=new Promise(r=>release=r);
const state={goal:"Fix",taskId:"t",root:"C:/repo",criteria:["pytest"]};
const options={baseURL:"http://127.0.0.1:11435",sessionId:"s",onMutationStart:async()=>{entered();return await pending},
 fetchImpl:async url=>{requests.push(url);return new Response(JSON.stringify({success:true,completion:{task_id:"t",complete:true,
 satisfied_criteria:["pytest"],unsatisfied_criteria:[],stale_criteria:[]}}),{status:200})}};
const completing=completeTask(state,options);
await started;
assert.equal(requests.length,1);
release(false);
const result=await completing;
assert.equal(result.success,false);
assert.equal(result.outcome_unknown,false);
assert.equal(requests.length,1);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_process_exit_during_task_completion_preserves_unknown_mutation(tmp_path):
    storage_path = tmp_path / "goal.json"
    prelude = r'''
import assert from "node:assert/strict";
import {readFile,writeFile} from "node:fs/promises";
import {makeGoalController} from "./tools/opencode_goal/index.js";
const path=process.argv[1];
const storage={get:async()=>{try{return JSON.parse(await readFile(path,"utf8"))}catch(e){if(e.code==="ENOENT")return undefined;throw e}},
 set:async(_k,v)=>writeFile(path,JSON.stringify(v))};
'''
    first = prelude + r'''
const ctx={storage,session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>({id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}})}};
const controller=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true}),
 completeTaskImpl:async(_state,options)=>{assert.equal(await options.onMutationStart(),true);process.exit(19)}});
await controller.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
await controller.settle({id:"event",type:"session.execution.succeeded",data:{sessionID:"s"}});
'''
    second = prelude + r'''
let prompts=0;
const ctx={storage,session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts++;return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const controller=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true})});
const state=await controller.resume("s");
assert.equal(state.status,"BLOCKED");
assert.equal(state.pendingOperation,"task_complete");
assert.equal(state.outcomeUnknown,true);
assert.equal(prompts,0);
'''
    first_result = subprocess.run(["node", "--input-type=module", "-e", first, str(storage_path)], cwd=ROOT,
                                  capture_output=True, text=True, timeout=20, check=False)
    assert first_result.returncode == 19, first_result.stderr
    second_result = subprocess.run(["node", "--input-type=module", "-e", second, str(storage_path)], cwd=ROOT,
                                   capture_output=True, text=True, timeout=20, check=False)
    assert second_result.returncode == 0, second_result.stderr


def test_process_exit_during_prompt_preserves_unknown_admission(tmp_path):
    storage_path = tmp_path / "goal.json"
    prelude = r'''
import assert from "node:assert/strict";
import {readFile, writeFile} from "node:fs/promises";
import {makeGoalController} from "./tools/opencode_goal/index.js";
const path=process.argv[1];
const storage={get:async()=>{try{return JSON.parse(await readFile(path,"utf8"))}catch(e){if(e.code==="ENOENT")return undefined;throw e}},
 set:async(_k,v)=>writeFile(path,JSON.stringify(v))};
'''
    first = prelude + r'''
const ctx={storage,session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async()=>process.exit(17)}};
const controller=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true})});
await controller.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
'''
    second = prelude + r'''
let prompts=0;
const ctx={storage,session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts++;return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const controller=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true})});
const state=await controller.resume("s");
assert.equal(state.status,"BLOCKED");
assert.equal(state.pendingOperation,"prompt_admission");
assert.equal(state.outcomeUnknown,true);
assert.match(state.pendingPromptId,/^msg_[a-f0-9]{32}$/);
assert.equal(prompts,0);
'''
    first_result = subprocess.run(["node", "--input-type=module", "-e", first, str(storage_path)], cwd=ROOT,
                                  capture_output=True, text=True, timeout=20, check=False)
    assert first_result.returncode == 17, first_result.stderr
    second_result = subprocess.run(["node", "--input-type=module", "-e", second, str(storage_path)], cwd=ROOT,
                                   capture_output=True, text=True, timeout=20, check=False)
    assert second_result.returncode == 0, second_result.stderr


def test_prompt_intent_is_durable_before_admission_and_cleared_after_confirmation():
    script = r'''
import assert from "node:assert/strict";
import {makeGoalController} from "./tools/opencode_goal/index.js";
let entered, release, sent;
const started = new Promise(r => entered = r), pending = new Promise(r => release = r), db = new Map();
const ctx = {storage:{get:async k=>structuredClone(db.get(k)),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async input=>{sent=input;entered();await pending;return {id:input.id,sessionID:input.sessionID,type:"user",payload:{text:input.text}}}}};
const controller=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true})});
const start=controller.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]},"queue");
await started;
const recorded=await controller.status("s");
assert.equal(recorded.status,"BLOCKED");
assert.equal(recorded.pendingOperation,"prompt_admission");
assert.equal(recorded.outcomeUnknown,true);
assert.match(recorded.pendingPromptId,/^msg_[a-f0-9]{32}$/);
assert.equal(recorded.pendingPromptId,sent.id);
assert.equal(recorded.pendingDelivery,"queue");
release(); await start;
const complete=await controller.status("s");
assert.equal(complete.status,"CONTINUE");
assert.equal(complete.pendingOperation,undefined);
assert.equal(complete.outcomeUnknown,undefined);
assert.equal(complete.pendingPromptId,undefined);
assert.equal(complete.pendingDelivery,undefined);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_controllers_in_one_module_do_not_resume_same_goal_twice():
    script = r'''
import assert from "node:assert/strict";
import {makeGoalController} from "./tools/opencode_goal/index.js";
const db=new Map(), prompts=[];
const ctx={storage:{get:async k=>structuredClone(db.get(k)),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const options={resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true})};
const first=makeGoalController(ctx,options), second=makeGoalController(ctx,options);
await first.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
await first.pause("s"); prompts.length=0;
await Promise.all([first.resume("s"),second.resume("s")]);
assert.equal(prompts.length,1);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_event_stream_loss_does_not_abort_another_controllers_session():
    script = r'''
import assert from "node:assert/strict";
import {makeGoalController} from "./tools/opencode_goal/index.js";
let release,entered; const pending=new Promise(r=>release=r),started=new Promise(r=>entered=r),db=new Map(),prompts=[];
const ctx={storage:{get:async k=>structuredClone(db.get(k)),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts.push(p.sessionID);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const first=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true})});
const second=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>{entered();await pending;return {success:true}}});
await first.start("first",{goal:"Fix",taskId:"a",criteria:["pytest"]});
const starting=second.start("second",{goal:"Fix",taskId:"b",criteria:["pytest"]});
await started; await first.eventStreamLost(); release(); await starting;
assert.equal((await second.status("second")).status,"CONTINUE");
assert.deepEqual(prompts,["first","second"]);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_unconfirmed_creation_recovers_only_after_exact_task_binding():
    script = r'''
import assert from "node:assert/strict";
import { makeGoalController } from "./tools/opencode_goal/index.js";
const db=new Map(), prompts=[];
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const first=makeGoalController(ctx,{resolveRoot:async p=>p,createTaskImpl:async()=>({success:false})});
await assert.rejects(first.start("s",{goal:"Fix",criteria:["pytest"]}));
const pending=await first.status("s");
assert.equal(pending.pendingOperation,"task_create");
assert.equal(pending.outcomeUnknown,true);
let bound=false;
const restarted=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:bound})});
await restarted.resume("s");
assert.equal((await restarted.status("s")).outcomeUnknown,true);
assert.equal(prompts.length,0);
bound=true; await restarted.resume("s");
const recovered=await restarted.status("s");
assert.equal(recovered.status,"CONTINUE");
assert.equal(recovered.outcomeUnknown,undefined);
assert.equal(recovered.pendingOperation,undefined);
assert.equal(prompts.length,1);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_pause_during_uncertain_creation_reconciliation_prevents_prompt():
    script = r'''
import assert from "node:assert/strict";
import { makeGoalController } from "./tools/opencode_goal/index.js";
let release, entered;
const pending=new Promise(r=>release=r), started=new Promise(r=>entered=r), db=new Map(), prompts=[];
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const first=makeGoalController(ctx,{resolveRoot:async p=>p,createTaskImpl:async()=>({success:false})});
await assert.rejects(first.start("s",{goal:"Fix",criteria:["pytest"]}));
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>{entered();await pending;return {success:true}}});
const resuming=c.resume("s"); await started; await c.pause("s"); release(); await resuming;
assert.equal((await c.status("s")).status,"PAUSED");
assert.equal((await c.status("s")).outcomeUnknown,true);
assert.equal(prompts.length,0);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_goal_stagnation_uses_ordered_snapshots_and_task_checkpoint():
    script = r'''
import assert from "node:assert/strict";
import { makeGoalController } from "./tools/opencode_goal/index.js";
const db=new Map(), prompts=[]; let checkpoint={phase:"editing",state_data:{progress:0}};
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true,task:{checkpoint}}),completeTaskImpl:async()=>({success:false})});
await c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
async function turn(n,snapshot="a".repeat(40)) {
 c.observeStep({type:"session.step.ended",data:{sessionID:"s",snapshot},durable:{aggregateID:"s",seq:n*2}});
 await c.settle({id:String(n),type:"session.execution.succeeded",data:{sessionID:"s"},durable:{aggregateID:"s",seq:n*2+1}});
}
await turn(1); await turn(2); checkpoint={phase:"editing",state_data:{progress:1}}; await turn(3);
assert.equal((await c.status("s")).status,"CONTINUE");
await turn(4); await turn(5);
assert.equal((await c.status("s")).status,"BLOCKED");
assert.match((await c.status("s")).reason,/stagnation/i);
assert.equal(prompts.length,5);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_goal_ignores_missing_or_out_of_order_snapshots():
    script = r'''
import assert from "node:assert/strict";
import { makeGoalController } from "./tools/opencode_goal/index.js";
const db=new Map();
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>({id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}})}};
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true,task:{checkpoint:{phase:"work"}}}),completeTaskImpl:async()=>({success:false})});
await c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
function step(seq,snapshot="a".repeat(40)){c.observeStep({type:"session.step.ended",data:{sessionID:"s",snapshot},durable:{aggregateID:"s",seq}})}
async function end(seq){await c.settle({id:String(seq),type:"session.execution.succeeded",data:{sessionID:"s"},durable:{aggregateID:"s",seq}})}
step(2); await end(3); step(4); await end(5);
step(4); await end(7); // A stale step cannot be reused for a new turn.
assert.deepEqual((await c.status("s")).observations,[]);
step(8,"invalid"); await end(9);
assert.equal((await c.status("s")).status,"CONTINUE");
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_missing_assistant_observation_does_not_imply_stagnation():
    script = r'''
import assert from "node:assert/strict";
import { makeGoalController } from "./tools/opencode_goal/index.js";
const db=new Map(), prompts=[];
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}},context:async()=>[]}};
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true}),completeTaskImpl:async()=>({success:false})});
await c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
for(let i=0;i<3;i++) await c.settle({id:String(i),type:"session.execution.succeeded",data:{sessionID:"s"}});
const state=await c.status("s");
assert.equal(state.status,"CONTINUE");
assert.deepEqual(state.observations,[]);
assert.equal(prompts.length,4);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_event_stream_loss_blocks_active_goal_and_future_prompts():
    script = r'''
import assert from "node:assert/strict";
import { makeGoalController } from "./tools/opencode_goal/index.js";
const db=new Map(), prompts=[];
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true})});
await c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
assert.equal(prompts.length,1);
await c.eventStreamLost();
assert.equal((await c.status("s")).status,"BLOCKED");
assert.equal((await c.status("s")).outcomeUnknown,true);
await assert.rejects(c.resume("s"),/event stream/i);
await assert.rejects(c.start("other",{goal:"Fix",taskId:"t",criteria:["pytest"]}),/event stream/i);
assert.equal(prompts.length,1);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_plugin_closed_event_stream_rejects_new_goal():
    script = r'''
import assert from "node:assert/strict";
import plugin from "./tools/opencode_goal/index.js";
let command;
const ctx={options:{hubURL:"http://127.0.0.1:11435"},
 tool:{transform:async f=>f({add:()=>{}})}, command:{transform:async f=>f({add:definition=>{command=definition}})},
 event:{subscribe:async function*(){}}, storage:{get:async()=>undefined,set:async()=>{}}, session:{}};
const stop=await plugin.setup(ctx);
await new Promise(resolve=>setImmediate(resolve));
await assert.rejects(command.execute({sessionID:"s",prompt:{text:'/goal {"goal":"Fix","criteria":["pytest"]}'}}),/event stream/i);
stop();
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_event_stream_loss_during_binding_prevents_prompt():
    script = r'''
import assert from "node:assert/strict";
import { makeGoalController } from "./tools/opencode_goal/index.js";
let release, entered;
const pending=new Promise(r=>release=r), started=new Promise(r=>entered=r), db=new Map(), prompts=[];
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>{entered();await pending;return {success:true}}});
const starting=c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
await started; await c.eventStreamLost(); release(); await starting;
assert.equal((await c.status("s")).status,"BLOCKED");
assert.equal((await c.status("s")).outcomeUnknown,true);
assert.equal(prompts.length,0);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_existing_goal_task_requires_exact_root_owner_session_and_contract():
    script = r'''
import assert from "node:assert/strict";
import { createGoal } from "./tools/opencode_goal/core.js";
import { getBoundTask } from "./tools/opencode_goal/transport.js";
const state=createGoal({goal:"Fix",taskId:"t",root:"C:/repo",criteria:["pytest"]});
const good={task_id:"t",status:"active",owner:"opencode-local",context:{session_id:"s"},contract:{goal:"Fix",acceptance_criteria:["pytest"]},checkpoint:{state_data:{_agent_task_scope:{version:2,repo_root:"C:/repo"}}}};
const request=task=>async (url, options)=>{
  assert.deepEqual(JSON.parse(options.body),{action:"get",root:"C:/repo",task_id:"t"});
  return new Response(JSON.stringify({success:true,task}),{status:200});
};
const opts=task=>({baseURL:"http://127.0.0.1:11435",fetchImpl:request(task)});
assert.equal((await getBoundTask(state,"s",opts(good))).success,true);
for(const bad of [{...good,owner:"other"},{...good,context:{session_id:"other"}},
 {...good,checkpoint:{state_data:{_agent_task_scope:{version:2,repo_root:"C:/other"}}}},
 {...good,contract:{goal:"Different",acceptance_criteria:["pytest"]}},
 {...good,contract:{goal:"Fix",acceptance_criteria:["other"]}}, {...good,status:"completed"}]) {
 assert.equal((await getBoundTask(state,"s",opts(bad))).success,false);
}
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_controller_does_not_prompt_for_unverified_existing_task():
    script = r'''
import assert from "node:assert/strict";
import { makeGoalController } from "./tools/opencode_goal/index.js";
const db=new Map(), prompts=[];
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
let valid=false;
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:valid})});
await c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
assert.equal((await c.status("s")).status,"BLOCKED");
await c.resume("s");
assert.equal((await c.status("s")).status,"BLOCKED");
assert.equal(prompts.length,0);
valid=true; await c.resume("s");
assert.equal((await c.status("s")).status,"CONTINUE");
assert.equal(prompts.length,1);
valid=false;
ctx.session.context=async()=>[{type:"assistant",content:[]}];
await c.settle({id:"event",type:"session.execution.succeeded",data:{sessionID:"s"}});
assert.equal((await c.status("s")).status,"BLOCKED");
assert.equal(prompts.length,1);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_pause_during_existing_task_binding_prevents_prompt():
    script = r'''
import assert from "node:assert/strict";
import { makeGoalController } from "./tools/opencode_goal/index.js";
const db=new Map(), prompts=[]; let release,entered;
const pending=new Promise(r=>release=r),started=new Promise(r=>entered=r);
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>{entered();await pending;return {success:true}}});
const starting=c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
await started; await c.pause("s"); release(); await starting;
assert.equal((await c.status("s")).status,"PAUSED"); assert.equal(prompts.length,0);
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_goal_state_machine_uses_server_receipt_gate_and_bounded_continuation():
    script = r'''
import assert from "node:assert/strict";
import { createGoal, settleGoal, pauseGoal, resumeGoal } from "./tools/opencode_goal/core.js";
const spec = {goal: "Fix test", taskId: "task-1", root: "C:/repo", criteria: ["pytest passes"]};
const initial = createGoal(spec);
assert.equal(initial.maxTurns, 20);
assert.throws(() => createGoal({...spec, criteria: []}));
assert.throws(() => createGoal({...spec, root: "relative/project"}));
let state = settleGoal(initial, {id: "1", type: "succeeded", observation: "same", verification: {success: false, error: "test failed"}});
assert.equal(state.status, "CONTINUE");
assert.notEqual(state.status, "DONE");
assert.deepEqual(settleGoal(state, {id: "1", type: "succeeded"}), state);
state = settleGoal(state, {id: "2", type: "succeeded", observation: "same", verification: {success: false}});
state = settleGoal(state, {id: "3", type: "succeeded", observation: "same", verification: {success: false}});
assert.equal(state.status, "BLOCKED");
assert.match(state.reason, /stagnation/i);
let gap = settleGoal(initial, {id: "g1", type: "succeeded", observation: "same", verification: {success: false}});
gap = settleGoal(gap, {id: "g2", type: "succeeded", verification: {success: false}});
gap = settleGoal(gap, {id: "g3", type: "succeeded", observation: "same", verification: {success: false}});
assert.deepEqual(gap.observations, ["same"]);
assert.equal(gap.status, "CONTINUE");
let fresh = createGoal(spec);
fresh = settleGoal(fresh, {id: "x", type: "succeeded", observation: "x", verification: {success: true, task: {task_id: "other", status: "completed", contract: {acceptance_criteria: ["pytest passes"]}}}});
assert.equal(fresh.status, "CONTINUE");
fresh = settleGoal(fresh, {id: "y", type: "succeeded", observation: "y", verification: {success: true, task: {task_id: "task-1", status: "completed", contract: {acceptance_criteria: ["pytest passes"]}}}});
assert.equal(fresh.status, "DONE");
let paused = pauseGoal(createGoal(spec), "user paused");
paused = JSON.parse(JSON.stringify(paused));
assert.equal(settleGoal(paused, {id: "z", type: "succeeded", verification: {success: true}}).status, "PAUSED");
assert.equal(resumeGoal(paused).status, "CONTINUE");
assert.equal(settleGoal(createGoal(spec), {id: "i", type: "interrupted"}).status, "PAUSED");
assert.equal(settleGoal(createGoal(spec), {id: "f", type: "failed"}).status, "FAILED");
const unknown = settleGoal(createGoal(spec), {id: "u", type: "succeeded", observation: "changed", verification: {success: false, outcome_unknown: true}});
assert.equal(unknown.status, "BLOCKED");
assert.match(unknown.reason, /unknown/i);
assert.equal(resumeGoal(unknown).status, "BLOCKED");
assert.equal(settleGoal(createGoal(spec), {id:"u2",type:"succeeded",verification:{success:false,verification_unavailable:true}}).status, "BLOCKED");
let limited = createGoal({...spec, maxTurns: 1});
limited = settleGoal(limited, {id: "e", type: "succeeded", observation: "new", verification: {success: false}});
assert.equal(limited.status, "FAILED");
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], cwd=ROOT,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_goal_completion_transport_is_loopback_only_and_sends_exact_contract():
    script = r'''
import assert from "node:assert/strict";
import { createGoal } from "./tools/opencode_goal/core.js";
import { completeTask as completeTaskRaw } from "./tools/opencode_goal/transport.js";
const completeTask = (state, options) => completeTaskRaw(state, {sessionId:"s", ...options});
const state = createGoal({goal: "Fix", taskId: "one", root: "C:/repo", criteria: ["pytest"]});
let calls = 0;
const send = async (url, options) => {
  calls++;
  assert.equal(options.redirect, "error");
  assert.equal(options.headers["X-LocalAI-Token"], undefined);
  assert.equal(options.headers.Authorization, undefined);
  if (url.endsWith("/api/agent-state/verification")) {
    assert.deepEqual(JSON.parse(options.body), {action:"completion",root:"C:/repo",task_id:"one"});
    return new Response(JSON.stringify({success:true,completion:{task_id:"one",complete:true,satisfied_criteria:["pytest"],unsatisfied_criteria:[],stale_criteria:[]}}), {status:200});
  }
  assert.equal(url, "http://127.0.0.1:11435/api/agent-state/tasks");
  assert.deepEqual(JSON.parse(options.body), {action: "complete", root: "C:/repo", task_id: "one", expected_criteria: ["pytest"], expected_binding:{goal:"Fix",session_id:"s"}});
  return new Response(JSON.stringify({success: true, task: {task_id:"one", status:"completed", owner:"opencode-local", context:{session_id:"s"}, contract:{goal:"Fix",acceptance_criteria:["pytest"]}, checkpoint:{state_data:{_agent_task_scope:{version:2,repo_root:"C:/repo"}}}}}), {status: 200});
};
assert.equal((await completeTask(state, {baseURL:"http://127.0.0.1:11435", fetchImpl:send})).success, true);
await assert.rejects(completeTask(state, {baseURL:"http://example.com:11435", fetchImpl:send}));
await assert.rejects(completeTask(state, {baseURL:"http://127.0.0.1:11435/other", fetchImpl:send}));
await assert.rejects(completeTask({...state,root:"relative"}, {baseURL:"http://127.0.0.1:11435", fetchImpl:send}));
await assert.rejects(completeTask({...state,criteria:[]}, {baseURL:"http://127.0.0.1:11435", fetchImpl:send}));
assert.equal(calls, 2);
let pendingCalls=0;
const pending = await completeTask(state, {baseURL:"http://127.0.0.1:11435", fetchImpl:async () => {pendingCalls++; return new Response(JSON.stringify({success:true,completion:{task_id:"one",complete:false,satisfied_criteria:[],unsatisfied_criteria:["pytest"],stale_criteria:[]}}), {status:200})}});
assert.equal(pending.success, false);
assert.equal(pending.outcome_unknown, false);
assert.equal(pendingCalls, 1);
const uncertain = await completeTask(state, {baseURL:"http://127.0.0.1:11435", fetchImpl:async () => { throw new Error("socket closed") }});
assert.equal(uncertain.outcome_unknown, false);
assert.equal(uncertain.verification_unavailable, true);
const serverError = await completeTask(state, {baseURL:"http://127.0.0.1:11435", fetchImpl:async () => new Response("error", {status: 500})});
assert.equal(serverError.outcome_unknown, false);
let phase=0;
const mutationUnknown = await completeTask(state, {baseURL:"http://127.0.0.1:11435", fetchImpl:async () => {
  if (phase++ === 0) return new Response(JSON.stringify({success:true,completion:{task_id:"one",complete:true,satisfied_criteria:["pytest"],unsatisfied_criteria:[],stale_criteria:[]}}), {status:200});
  throw new Error("connection lost");
}});
assert.equal(mutationUnknown.outcome_unknown, true);
let phase2=0;
const malformed = await completeTask(state, {baseURL:"http://127.0.0.1:11435", fetchImpl:async () => {
  if (phase2++ === 0) return new Response(JSON.stringify({success:true,completion:{task_id:"one",complete:true,satisfied_criteria:["pytest"],unsatisfied_criteria:[],stale_criteria:[]}}), {status:200});
  return new Response(JSON.stringify({success:true,task:{task_id:"other",status:"completed"}}), {status:200});
}});
assert.equal(malformed.outcome_unknown, true);
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], cwd=ROOT,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_controller_persists_restarts_deduplicates_and_pause_wins_inflight():
    script = r'''
import assert from "node:assert/strict";
import { makeGoalController } from "./tools/opencode_goal/index.js";
const db = new Map(); const sent=[];
const ctx = {
  storage: {get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
  session: {get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{sent.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}},context:async()=>[{type:"assistant",content:[{type:"text",text:"work"}]}]},
};
const opts={resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true}),completeTaskImpl:async()=>({success:false,outcome_unknown:false})};
let c=makeGoalController(ctx,opts);
await c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
assert.equal(sent.length,1);
await c.settle({id:"e1",type:"session.execution.succeeded",data:{sessionID:"s"}});
assert.equal(sent.length,2);
await c.settle({id:"e1",type:"session.execution.succeeded",data:{sessionID:"s"}});
assert.equal(sent.length,2);
c=makeGoalController(ctx,opts);
assert.equal((await c.status("s")).turns,1);
await c.pause("s");
await c.settle({id:"e2",type:"session.execution.succeeded",data:{sessionID:"s"}});
assert.equal((await c.status("s")).status,"PAUSED");
assert.equal(sent.length,2);
await c.resume("s");
assert.equal(sent.length,3);
let release; let pending = new Promise(r=>release=r);
c=makeGoalController(ctx,{...opts,completeTaskImpl:async()=>{await pending; return {success:true,task:{task_id:"t",status:"completed",contract:{acceptance_criteria:["pytest"]}}}}});
const settling=c.settle({id:"e3",type:"session.execution.succeeded",data:{sessionID:"s"}});
await new Promise(r=>setTimeout(r,20));
await c.pause("s");
release(); await settling;
assert.equal((await c.status("s")).status,"PAUSED");
assert.equal(sent.length,3);
await c.resume("s");
let release2; let pending2 = new Promise(r=>release2=r);
c=makeGoalController(ctx,{...opts,completeTaskImpl:async(_state,options)=>{await options.onMutationStart(); await pending2; return {success:false,outcome_unknown:true}}});
const running=c.settle({id:"e4",type:"session.execution.succeeded",data:{sessionID:"s"}});
await new Promise(r=>setTimeout(r,20));
await c.settle({id:"interrupt",type:"session.execution.interrupted",data:{sessionID:"s"}});
release2(); await running;
const interrupted=await c.status("s");
assert.equal(interrupted.status,"PAUSED");
assert.equal(interrupted.outcomeUnknown,true);
await c.resume("s");
assert.equal((await c.status("s")).status,"PAUSED");
const db2=new Map(); const ctx2={...ctx,storage:{get:async k=>db2.get(k),set:async(k,v)=>db2.set(k,structuredClone(v))}};
const broken=makeGoalController(ctx2,{...opts,completeTaskImpl:async()=>{throw new Error("offline")}});
await broken.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
await broken.settle({id:"broken",type:"session.execution.succeeded",data:{sessionID:"s"}});
assert.equal((await broken.status("s")).status,"BLOCKED");
const db3=new Map();
const ctx3={storage:{get:async k=>db3.get(k),set:async(k,v)=>db3.set(k,structuredClone(v))},session:{...ctx.session,prompt:async()=>{throw new Error("admission failed")}}};
const admission=makeGoalController(ctx3,opts);
await assert.rejects(admission.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]}));
assert.equal((await admission.status("s")).status,"BLOCKED");
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], cwd=ROOT,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_goal_status_reports_without_queueing_a_model_turn():
    script = r'''
import assert from "node:assert/strict";
import plugin from "./tools/opencode_goal/index.js";
let command; const messages=[];
const ctx={options:{hubURL:"http://127.0.0.1:11435"},storage:{get:async()=>undefined},
  tool:{transform:async callback=>callback({add:()=>{}})}, command:{transform:async callback=>callback({add:value=>{command=value}})},
  session:{synthetic:async value=>messages.push(value)},
  event:{subscribe:async function*(){}}};
await assert.rejects(plugin.setup({...ctx,options:{hubURL:"https://example.com"}}),/loopback/);
await assert.rejects(plugin.setup({...ctx,options:{hubURL:"http://127.0.0.1:11435",tokenEnv:"LOCAL_AI_HUB_MISSING_TEST_TOKEN"}}),/removed/);
const cleanup=await plugin.setup(ctx);
await assert.rejects(command.execute({sessionID:"s",prompt:{text:"status"}}), /NO_GOAL/);
assert.equal(messages.length,0);
cleanup();
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], cwd=ROOT,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_pause_during_settlement_commit_does_not_resume():
    script = r'''
import assert from "node:assert/strict";
import { makeGoalController } from "./tools/opencode_goal/index.js";
const db=new Map(),prompts=[];let release,entered;
const pending=new Promise(r=>release=r), started=new Promise(r=>entered=r);
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>{if(v.turns===1 && v.status==="CONTINUE"){entered();await pending}db.set(k,structuredClone(v))}},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}},context:async()=>[{type:"assistant",content:[{type:"text",text:"work"}]}]}};
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true}),completeTaskImpl:async()=>({success:false})});
await c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
const settle=c.settle({id:"e",type:"session.execution.succeeded",data:{sessionID:"s"}});
await started;const pause=c.pause("s");release();await Promise.all([settle,pause]);
assert.equal((await c.status("s")).status,"PAUSED");assert.equal(prompts.length,1);
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], cwd=ROOT,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_completion_event_during_prompt_admission_is_not_dropped():
    script = r'''
import assert from "node:assert/strict";
import { makeGoalController } from "./tools/opencode_goal/index.js";
const db=new Map();let c;let prompts=0;
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),context:async()=>[{type:"assistant",content:[{type:"text",text:"work"}]}],
 prompt:async p=>{prompts++;if(prompts===1)await c.settle({id:"early",type:"session.execution.succeeded",data:{sessionID:"s"}});return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true}),completeTaskImpl:async()=>({success:false})});
await c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
await new Promise(r=>setTimeout(r,30));
assert.equal((await c.status("s")).turns,1);assert.equal(prompts,2);
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], cwd=ROOT,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_pause_during_unconfirmed_prompt_does_not_allow_retry():
    script = r'''
import assert from "node:assert/strict";
import { makeGoalController } from "./tools/opencode_goal/index.js";
const db=new Map();let release,entered;
const pending=new Promise(r=>release=r),started=new Promise(r=>entered=r);
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
 session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{entered();await pending;return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const c=makeGoalController(ctx,{resolveRoot:async p=>p,getBoundTaskImpl:async()=>({success:true})});
const starting=c.start("s",{goal:"Fix",taskId:"t",criteria:["pytest"]});
await started;await c.pause("s");release();assert.equal((await starting).status,"PAUSED");
const state=await c.status("s");assert.equal(state.status,"PAUSED");assert.equal(state.outcomeUnknown,true);
await c.resume("s");assert.equal((await c.status("s")).status,"PAUSED");
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], cwd=ROOT,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_goal_can_create_a_bound_task_and_stops_on_unknown_creation():
    script = r'''
import assert from "node:assert/strict";
import { makeGoalController } from "./tools/opencode_goal/index.js";
import { createTask } from "./tools/opencode_goal/transport.js";
const db=new Map(), prompts=[], calls=[];
const ctx={storage:{get:async k=>db.get(k),set:async(k,v)=>db.set(k,structuredClone(v))},
  session:{get:async()=>({location:{directory:"C:/repo"}}),prompt:async p=>{prompts.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const makeResult=(state,id)=>({success:true,task:{task_id:state.taskId,status:"planned",owner:"opencode-local",
  context:{session_id:id},contract:{goal:state.goal,acceptance_criteria:state.criteria},
  checkpoint:{state_data:{_agent_task_scope:{version:2,repo_root:state.root}}}}});
const create=async(state,id)=>{calls.push([state,id]);return makeResult(state,id)};
let c=makeGoalController(ctx,{resolveRoot:async p=>p,createTaskImpl:create});
const state=await c.start("s",{goal:"Fix",criteria:["pytest passes"]});
assert.match(state.taskId,/^goal-/);assert.equal(prompts.length,1);assert.equal(calls.length,1);
assert.equal((await c.status("s")).status,"CONTINUE");
const bad=makeGoalController(ctx,{resolveRoot:async p=>p,createTaskImpl:async()=>({success:false,outcome_unknown:true})});
await assert.rejects(bad.start("s2",{goal:"Fix",criteria:["pytest passes"]}));
assert.equal((await bad.status("s2")).status,"BLOCKED");
assert.equal((await bad.status("s2")).outcomeUnknown,true);assert.equal(prompts.length,1);
let release;const pending=new Promise(r=>release=r);
const slow=makeGoalController(ctx,{resolveRoot:async p=>p,createTaskImpl:async(state,id)=>{await pending;return makeResult(state,id)}});
const starting=slow.start("s3",{goal:"Fix",criteria:["pytest passes"]});
await new Promise(r=>setTimeout(r,20));
await assert.rejects(slow.start("s3",{goal:"Duplicate",criteria:["pytest passes"]}));
await slow.pause("s3");release();await starting;
assert.equal((await slow.status("s3")).status,"PAUSED");
assert.equal((await slow.status("s3")).outcomeUnknown,true);assert.equal(prompts.length,1);
let releaseOld;const oldPending=new Promise(r=>releaseOld=r);
const old=makeGoalController(ctx,{resolveRoot:async p=>p,completeTaskImpl:async()=>({success:false}),createTaskImpl:async(state,id)=>{await oldPending;return makeResult(state,id)}});
const oldStart=old.start("s-old",{goal:"Fix",criteria:["pytest passes"]});
await new Promise(r=>setTimeout(r,20));
await old.settle({id:"previous-run",type:"session.execution.succeeded",data:{sessionID:"s-old"}});
releaseOld();await oldStart;await new Promise(r=>setTimeout(r,20));
assert.equal((await old.status("s-old")).turns,0);assert.equal((await old.status("s-old")).status,"CONTINUE");
let releaseWrite;const writePending=new Promise(r=>releaseWrite=r);let enteredWrite;
const writeStarted=new Promise(r=>enteredWrite=r);const db4=new Map(), prompts4=[];
const ctx4={storage:{get:async k=>db4.get(k),set:async(k,v)=>{
  if(v.status==="CONTINUE" && db4.has(k)){enteredWrite();await writePending}db4.set(k,structuredClone(v))}},
  session:{get:ctx.session.get,prompt:async p=>{prompts4.push(p);return {id:p.id,sessionID:p.sessionID,type:"user",payload:{text:p.text}}}}};
const racing=makeGoalController(ctx4,{resolveRoot:async p=>p,createTaskImpl:create});
const racingStart=racing.start("s4",{goal:"Fix",criteria:["pytest passes"]});
await writeStarted;const racingPause=racing.pause("s4");releaseWrite();
await Promise.all([racingStart,racingPause]);
assert.equal((await racing.status("s4")).status,"PAUSED");assert.equal(prompts4.length,0);
let body;
const result=await createTask({...state},"s",{baseURL:"http://127.0.0.1:11435",fetchImpl:async(_url,opts)=>{
  body=JSON.parse(opts.body);return new Response(JSON.stringify(makeResult(state,"s")),{status:200})}});
assert.equal(result.success,true);assert.equal(body.action,"create");assert.equal(body.task_id,state.taskId);
assert.equal(body.context.session_id,"s");assert.deepEqual(body.contract.acceptance_criteria,state.criteria);
const malformed=await createTask({...state},"s",{baseURL:"http://127.0.0.1:11435",fetchImpl:async()=>new Response('{"success":true,"task":{}}',{status:200})});
assert.equal(malformed.outcome_unknown,true);
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], cwd=ROOT,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
