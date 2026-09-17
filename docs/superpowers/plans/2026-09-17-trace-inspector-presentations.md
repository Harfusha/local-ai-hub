# Trace Inspector Request Presentations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render each retained trace in the most useful request-specific format, with local-model traces presented as chat sessions and technical metadata kept optional.

**Architecture:** Keep the existing debug-trace API and SQLite schema unchanged. Extend the client-side `traceDisplayModel` with deterministic presentation classification and bounded normalized data, then dispatch to focused renderers from `renderTracePresentation(model)`. Preserve the current universal summary, redaction, incremental polling, and raw fallback under collapsed technical details.

**Tech Stack:** Python-generated HTML, browser JavaScript/CSS embedded in `src/local_ai_hub/dashboard.py`, pytest contract tests, Node.js fixture snippets already used by dashboard tests.

---

## File map

- Modify `src/local_ai_hub/dashboard.py:738-742` for presentation CSS and `:1985-2075` for trace data normalization/render dispatch.
- Modify `tests/test_dashboard_custom_modals.py:330-470` for JavaScript contract and fixture tests.
- Modify `docs/DASHBOARD.md:13-18` to document request-specific trace views.
- Do not modify `src/local_ai_hub/debug_traces.py`, HTTP routes, or SQLite schema.

### Task 1: Add classifier and normalized presentation fixtures

**Files:**
- Modify: `tests/test_dashboard_custom_modals.py`
- Modify: `src/local_ai_hub/dashboard.py`

- [ ] **Step 1: Write failing classifier tests**

Add tests that extract the dashboard helper source and require these stable kinds and precedence:

```python
def test_trace_inspector_classifies_request_presentations() -> None:
    assert "function tracePresentationKind(model)" in DASHBOARD_HTML
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function tracePresentationKind(model)") : DASHBOARD_HTML.index(
            "function traceAvailability("
        )
    ]
    for kind in [
        "agent_loop", "model_chat", "command", "review",
        "repo_intelligence", "rag_search", "async_job", "request_response",
    ]:
        assert kind in source
    assert source.index("agent_loop") < source.index("model_chat")


def test_trace_inspector_normalizes_model_chat_turns_and_tools() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function tracePresentationData(model)") : DASHBOARD_HTML.index(
            "function traceAvailability("
        )
    ]
    assert "chatTurns" in source
    assert "toolInteractions" in source
    assert "traceSanitizeValue" in source
    assert "traceBoundedEvents" in source
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py -k "classifies_request_presentations or normalizes_model_chat_turns" --tb=short
```

Expected: FAIL because `tracePresentationKind` and `tracePresentationData` do not exist.

- [ ] **Step 3: Implement deterministic classification**

Insert before `traceDisplayModel`:

```javascript
function tracePresentationKind(model){
  const action=String(model.identity?.action||model.session?.action||'').toLowerCase();
  const kind=String(model.session?.kind||'').toLowerCase();
  const events=model.events||[];
  const hasModel=model.modelExecutions?.length>0||traceRecorded(model.input)||traceRecorded(model.output);
  const hasTools=model.toolCalls?.length>0;
  if(hasModel&&hasTools)return 'agent_loop';
  if(hasModel)return 'model_chat';
  if(kind==='async_job'||model.correlations?.async_job_id||model.correlations?.scheduler_job_id)return 'async_job';
  if(action==='/api/command'||action.includes('/command'))return 'command';
  if(/\/review|\/diff|review|diff/.test(action))return 'review';
  if(/repo|code|git|symbol|impact|test|resolve|ast|topology/.test(action))return 'repo_intelligence';
  if(/rag|search|query|retriev|embed/.test(action))return 'rag_search';
  if(events.length||traceRecorded(model.response)||traceRecorded(model.input))return 'request_response';
  return 'request_response';
}
```

Keep `agent_loop` before `model_chat`; model traces with tools must not lose their tool presentation. Normalize action matching only; do not expose new raw fields.

- [ ] **Step 4: Implement bounded normalized data**

Add helpers:

```javascript
function traceChatTurns(events){
  const turns=[],list=events||[];let current=null;
  list.forEach(event=>{
    const type=String(event?.event_type||''),payload=traceSanitizeValue(event?.payload||{});
    if(type==='model_request'){
      current={step:payload.step||turns.length+1,input:payload,output:'',tools:[]};
      turns.push(current);
    }else if(current&&(type==='output_stream'||type==='output_delta')){
      current.output+=String(payload.text||'');
    }else if(current&&type==='tool_call')current.tools.push({call:payload,result:null});
    else if(current&&type==='tool_result'){
      const callId=payload.call_id||'',match=current.tools.slice().reverse().find(item=>!item.result&&(!callId||item.call.call_id===callId));
      if(match)match.result=payload;
    }
  });
  return turns.slice(-100);
}
function tracePresentationData(model){
  const events=model.events||[],turns=traceChatTurns(events);
  return {kind:tracePresentationKind(model),chatTurns:turns,toolInteractions:model.toolCalls||[],requestEnvelope:model.session?.request||{},modelInput:model.input,modelOutput:model.output,command:traceFirstRecorded(events,['command','cmd']),review:traceFirstRecorded(events,['diff','findings','recommendation']),repoOperation:traceFirstRecorded(events,['root','query','symbols','files']),retrieval:traceFirstRecorded(events,['sources','results','hits','answer']),lifecycle:model.lifecycle};
}
```

Use existing bounded/sanitized `model.events`; never re-read unbounded raw session fields. Extend `traceDisplayModel` with `presentation=tracePresentationData(model)` and return it.

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py -k "classifies_request_presentations or normalizes_model_chat_turns" --tb=short
```

Expected: PASS. Commit:

```bash
git add src/local_ai_hub/dashboard.py tests/test_dashboard_custom_modals.py
git commit -m "feat(dashboard): classify trace presentations"
```

### Task 2: Add model-chat and agent-loop renderers

**Files:**
- Modify: `tests/test_dashboard_custom_modals.py`
- Modify: `src/local_ai_hub/dashboard.py`

- [ ] **Step 1: Write failing renderer tests**

Add static contracts:

```python
def test_trace_inspector_has_model_chat_and_agent_loop_renderers() -> None:
    for name in [
        "renderModelChatPresentation",
        "renderAgentLoopPresentation",
        "trace-chat-output",
        "trace-chat-input",
        "trace-tool-interaction",
    ]:
        assert name in DASHBOARD_HTML
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderModelChatPresentation") : DASHBOARD_HTML.index(
            "function traceAvailability("
        )
    ]
    assert "model output" in source.lower()
    assert "model input" in source.lower()
    assert "chatTurns" in source
```

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py -k "model_chat_and_agent_loop" --tb=short
```

Expected: FAIL because renderers and CSS do not exist.

- [ ] **Step 3: Add chat CSS**

Add responsive styles beside the existing trace styles:

```css
.trace-chat-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}
.trace-chat-column{min-width:0;border:1px solid #33485f;border-radius:8px;overflow:hidden;background:#0d141c}
.trace-chat-column.output{border-color:#397658}.trace-chat-column.input{border-color:#41659a}
.trace-chat-column>h3{margin:0;padding:9px 11px;background:#151d26;font-size:11px;text-transform:uppercase}
.trace-chat-body{padding:10px;min-width:0}.trace-chat-message{border:1px solid #2d3d4e;border-radius:7px;margin:0 0 8px;overflow:hidden}
.trace-chat-message-head{padding:7px 9px;background:#151d26;font-size:10px;font-weight:700}
.trace-chat-message-body{padding:9px;overflow-wrap:anywhere}.trace-tool-interaction{margin:8px 0;border-left:3px solid #a78bfa}
@media(max-width:760px){.trace-chat-grid{grid-template-columns:1fr}}
```

- [ ] **Step 4: Implement model-chat renderer**

Implement `renderModelChatPresentation(model)` with output left and input right. Each turn must render role-labelled input, output text, step number, model name, and explicit empty/unavailable states. Use `renderAny`, `promptBlock`, `esc`, and existing bounded values. Do not place universal metadata in either column.

- [ ] **Step 5: Implement agent-loop renderer**

Implement `renderAgentLoopPresentation(model)` by rendering the same two-column chat view and inserting each paired tool call/result as a collapsed `.trace-tool-interaction` card between turns. Show tool name, call ID, arguments, result/error, and status; use `renderAny` for payloads.

- [ ] **Step 6: Wire focused dispatcher branch and verify GREEN**

Add:

```javascript
function renderTracePresentation(model){
  switch(model.presentation?.kind){
    case 'agent_loop':return renderAgentLoopPresentation(model);
    case 'model_chat':return renderModelChatPresentation(model);
    default:return renderRequestResponsePresentation(model);
  }
}
```

Run:

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py -k "model_chat_and_agent_loop or trace_inspector" --tb=short
```

Expected: PASS. Commit:

```bash
git add src/local_ai_hub/dashboard.py tests/test_dashboard_custom_modals.py
git commit -m "feat(dashboard): render model traces as chat sessions"
```

### Task 3: Add command, review, repository, RAG, async, and fallback renderers

**Files:**
- Modify: `tests/test_dashboard_custom_modals.py`
- Modify: `src/local_ai_hub/dashboard.py`

- [ ] **Step 1: Write one contract test per renderer**

Add a test requiring named functions and primary labels:

```python
def test_trace_inspector_has_request_specific_renderers() -> None:
    expected = {
        "renderCommandPresentation": "stdout",
        "renderReviewPresentation": "findings",
        "renderRepoIntelligencePresentation": "repository",
        "renderRagSearchPresentation": "retrieved",
        "renderAsyncJobPresentation": "lifecycle",
        "renderRequestResponsePresentation": "response",
    }
    for function_name, marker in expected.items():
        assert function_name in DASHBOARD_HTML
        assert marker in DASHBOARD_HTML
```

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py -k request_specific_renderers --tb=short
```

Expected: FAIL because the specialized functions do not exist.

- [ ] **Step 3: Implement command and review renderers**

`renderCommandPresentation(model)` renders command/arguments on top, then two scrollable columns for stdout and stderr, followed by exit state, retries, and duration. `renderReviewPresentation(model)` renders request/diff/context on the left and findings/recommendation on the right; severity counts stay in the header.

- [ ] **Step 4: Implement repository and RAG renderers**

`renderRepoIntelligencePresentation(model)` renders repository identity, operation/query, context summary, files/symbols/results. `renderRagSearchPresentation(model)` renders query, ranked retrieved sources with score/provider, answer, and truncation state. Long source payloads stay collapsed.

- [ ] **Step 5: Implement async and generic renderers**

`renderAsyncJobPresentation(model)` renders lifecycle state, queue wait, attempts/retries, worker input, result/error, and scheduler/job IDs. `renderRequestResponsePresentation(model)` renders request envelope, response, status, timing, and error with explicit unavailable states.

- [ ] **Step 6: Complete dispatcher and verify GREEN**

Extend the dispatcher with all kinds, keeping `request_response` as the default. Run:

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py -k "request_specific_renderers or trace_inspector" --tb=short
```

Expected: PASS. Commit:

```bash
git add src/local_ai_hub/dashboard.py tests/test_dashboard_custom_modals.py
git commit -m "feat(dashboard): add request-specific trace views"
```

### Task 4: Integrate primary presentation with optional technical details

**Files:**
- Modify: `tests/test_dashboard_custom_modals.py`
- Modify: `src/local_ai_hub/dashboard.py:2050-2080`

- [ ] **Step 1: Write failing integration contracts**

Require `renderTracePresentation(model)` to appear before the collapsed technical details and require existing tabs/raw fallback to remain inside that details block.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py -k "presentation_before_optional_details" --tb=short
```

Expected: FAIL until `renderTraceDetail` uses the dispatcher.

- [ ] **Step 3: Replace primary card assembly**

In `renderTraceDetail`, keep the existing header and universal summary data, then render:

```javascript
const presentationMarkup=renderTracePresentation(model);
const optionalMarkup=`<details class="trace-optional-details"><summary>Technical details · ${panels.length} optional views</summary><div class="trace-optional-body">${universalSummary}<nav class="trace-tabs" role="tablist" aria-label="Trace views">${tabs}</nav>${panelMarkup}</div></details>`;
$('tracePageBody').innerHTML=`<div class="human-shell">${header}${presentationMarkup}${optionalMarkup}</div>`;
```

Preserve scroll capture/restore, redaction toggle, tab ARIA attributes, and incremental polling.

- [ ] **Step 4: Verify GREEN and run focused suite**

Run:

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py tests/test_debug_traces.py tests/test_debug_trace_request_summary.py -k trace --tb=short
```

Expected: all selected tests pass. Commit:

```bash
git add src/local_ai_hub/dashboard.py tests/test_dashboard_custom_modals.py
git commit -m "feat(dashboard): dispatch trace-specific primary views"
```

### Task 5: Document views and run full verification

**Files:**
- Modify: `docs/DASHBOARD.md`
- Modify: `tests/test_dashboard_custom_modals.py`

- [ ] **Step 1: Update dashboard documentation**

Document that Trace Inspector selects model chat, tool loop, command, review, repository, RAG, async-job, or request/response layouts from existing trace fields; technical details remain collapsed and redaction remains enabled by default.

- [ ] **Step 2: Add missing-field and redaction contracts**

Add tests proving unknown actions use `request_response`, missing prompt/output show explicit unavailable states, long payloads remain bounded, and sensitive keys stay redacted until reveal.

- [ ] **Step 3: Run focused and full suites**

Run:

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py tests/test_debug_traces.py tests/test_debug_trace_request_summary.py --tb=short
python -m pytest -q --tb=short
git diff --check
```

Expected: focused tests pass; full suite reports zero failures; diff check is clean.

- [ ] **Step 4: Restart hub and manually inspect representative traces**

Run `python tools/service.py restart`, then inspect one trace from each family in the browser. Confirm model output is left, full model input is right, filters do not hide content unexpectedly, optional details open correctly, and a trace without payloads remains readable.

- [ ] **Step 5: Commit documentation and final changes**

```bash
git add src/local_ai_hub/dashboard.py tests/test_dashboard_custom_modals.py docs/DASHBOARD.md
git commit -m "feat(dashboard): specialize trace inspector views"
```
