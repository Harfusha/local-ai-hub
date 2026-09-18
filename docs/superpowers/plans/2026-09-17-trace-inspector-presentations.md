# Trace Inspector Human-First Presentations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace JSON-shaped Trace Inspector primary views with concise, request-specific human presentations while preserving complete technical diagnostics behind a collapsed disclosure.

**Architecture:** Keep the existing client-side `tracePresentationKind`, normalized presentation payloads, specialized renderer functions, debug-trace API, SQLite data, polling, redaction, and raw fallback. Tighten the shared presentation-field layer so empty/internal/duplicate values disappear from the primary view, and use semantic cards/lists/code blocks/timeline rows for structured values instead of handing whole objects to the generic renderer.

**Tech Stack:** Python-generated HTML, browser JavaScript/CSS embedded in `src/local_ai_hub/dashboard.py`, pytest source-contract tests, and Node.js runtime fixtures already used by `tests/test_dashboard_custom_modals.py`.

---

## Baseline and file map

- `src/local_ai_hub/dashboard.py:575-583` owns Trace Inspector CSS; `:2110-2245` owns normalized payload helpers and request-specific renderers; `:2290-2315` owns detail assembly and technical disclosure.
- `tests/test_dashboard_custom_modals.py:328-1170` contains sanitizer, classifier, renderer, runtime, and integration contracts. Extend these tests before changing JavaScript.
- `tests/test_dashboard_operational_surfaces.py` has an existing uncommitted live-event-to-trace link change. Preserve it byte-for-byte; do not stage or rewrite it as part of this work.
- `src/local_ai_hub/dashboard.py` has an existing uncommitted `data-trace-id` change in `renderEvents`. Preserve that hunk byte-for-byte.
- `docs/DASHBOARD.md` documents dashboard behavior and may receive one short Trace Inspector UX note.
- Do not modify `src/local_ai_hub/debug_traces.py`, trace HTTP routes, persistence schema, or model execution behavior.

Before editing, save the two existing diffs with `git diff -- src/local_ai_hub/dashboard.py tests/test_dashboard_operational_surfaces.py`. Never use reset/checkout to clean them.

### Task 1: Characterize the human-first contract with failing tests

**Files:**
- Test: `tests/test_dashboard_custom_modals.py`
- Modify: `src/local_ai_hub/dashboard.py` only after the tests fail for the intended reason.

- [ ] **Step 1: Add the omission contract.** Append this test beside the existing Trace Inspector contracts:

```python
def test_trace_primary_fields_hide_empty_internal_and_duplicate_values() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function tracePresentationField(") : DASHBOARD_HTML.index(
            "function tracePresentationColumns("
        )
    ]
    assert "traceMeaningfulValue" in source
    assert "internal" in source.lower()
    assert "duplicate" in source.lower()
    assert "return ''" in source


def test_trace_primary_presentations_use_semantic_value_renderers() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderCommandPresentation") : DASHBOARD_HTML.index(
            "function traceHumanTitle("
        )
    ]
    for marker in [
        "traceSummaryCard",
        "traceCodeBlock",
        "traceList",
        "traceTimeline",
    ]:
        assert marker in source
    assert "renderAny(value)" not in source


def test_trace_technical_details_are_closed_by_default() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    assert '<details id="traceTechnicalDetails"' in source
    assert "trace-optional-details" in source
    assert ".open=true" not in source
```

- [ ] **Step 2: Run the new tests and confirm RED.**

Run:

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py -k "primary_fields_hide or semantic_value_renderers or technical_details_are_closed" --tb=short
```

Expected: FAIL because current field helpers allow generic object rendering and the new semantic helper markers do not yet exist. If collection fails before assertions, fix only the test slice boundaries and rerun until the failure is an assertion failure.

- [ ] **Step 3: Commit only the new tests.**

```bash
git add tests/test_dashboard_custom_modals.py
git commit -m "test(dashboard): define human-first trace presentation contract"
```

Do not stage `src/local_ai_hub/dashboard.py` or `tests/test_dashboard_operational_surfaces.py` in this commit.

### Task 2: Make shared primary-value rendering human-first

**Files:**
- Modify: `src/local_ai_hub/dashboard.py` in the Trace Inspector helper block immediately before `tracePresentationColumns`.
- Test: `tests/test_dashboard_custom_modals.py` from Task 1.

- [ ] **Step 1: Implement a single meaningful-value predicate.** Add a helper with this behavior:

```javascript
function traceMeaningfulValue(value,key=''){
  const name=String(key||'').toLowerCase();
  if(value===undefined||value===null||value==='')return false;
  if(typeof value==='string'&&/^(empty|none|null|n\/a|unknown)$/i.test(value.trim()))return false;
  if(Array.isArray(value))return value.some(item=>traceMeaningfulValue(item));
  if(typeof value==='object')return Object.entries(value).some(([childKey,childValue])=>traceMeaningfulValue(childValue,childKey));
  if(/(^|_)(id|ids|lease_id|session_id|clone_id|worktree_id|repository_id|task_id)$/.test(name))return false;
  return true;
}
```

Keep identifiers available in the technical disclosure; this predicate applies only to primary human fields. Do not alter `traceSanitizeValue` or redaction behavior.

- [ ] **Step 2: Implement semantic primitives.** Add these helpers and route every primary renderer through them:

```javascript
function traceSummaryCard(title,value,budget,options={}){
  if(!traceMeaningfulValue(value,options.key||title))return '';
  return `<section class="trace-summary-card ${esc(options.tone||'')}" data-field="${esc(options.key||title)}"><h3>${esc(title)}</h3><div class="trace-summary-value">${traceReadableMarkup(value,budget,options.limit||4000)}</div></section>`;
}
function traceCodeBlock(title,value,budget,options={}){
  if(!traceMeaningfulValue(value,options.key||title))return '';
  return `<section class="trace-code-card"><h3>${esc(title)}</h3><pre class="trace-output">${esc(traceInlineText(value,options.limit||8000))}</pre></section>`;
}
function traceList(title,items,budget,renderItem){
  const values=(Array.isArray(items)?items:[]).filter(item=>traceMeaningfulValue(item));
  if(!values.length)return '';
  return `<section class="trace-list-card"><h3>${esc(title)} <span class="tiny">${values.length}</span></h3><div>${values.map((item,index)=>renderItem(item,index,budget)).join('')}</div></section>`;
}
function traceHumanFields(fields,budget){
  return fields.map(field=>field.kind==='code'?traceCodeBlock(field.label,field.value,budget,field):traceSummaryCard(field.label,field.value,budget,field)).join('');
}
```

`traceInlineText` must stay bounded and escaped at the final HTML boundary. Never call `String(object)` for a structured value.

- [ ] **Step 3: Replace generic object fields in `tracePresentationField`.** Preserve its current label/fallback API for technical panels, but add a primary-mode option. Primary mode returns an empty string for omitted values, uses `traceList` for arrays, `traceCodeBlock` for stdout/stderr/diff/prompt/output, and `traceSummaryCard` for scalar or small structured values. Technical mode continues to use the existing bounded `renderAny` output.

- [ ] **Step 4: Run the Task 1 tests and the existing presentation contracts.**

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py -k "primary_fields_hide or semantic_value_renderers or technical_details_are_closed or trace_inspector" --tb=short
```

Expected: the new omission and semantic tests pass, with no failure in existing sanitizer, redaction, classifier, or runtime contracts.

- [ ] **Step 5: Commit the shared renderer change.**

```bash
git add src/local_ai_hub/dashboard.py tests/test_dashboard_custom_modals.py
git commit -m "feat(dashboard): hide trace presentation noise"
```

Before staging, confirm the pre-existing `renderEvents` `data-trace-id` hunk remains unchanged; if needed, stage only the Trace Inspector hunks.

### Task 3: Convert every specialized presentation to semantic layouts

**Files:**
- Modify: `src/local_ai_hub/dashboard.py:2214-2244` and adjacent Trace Inspector CSS.
- Test: `tests/test_dashboard_custom_modals.py`.

- [ ] **Step 1: Add renderer-specific failing assertions.** Extend the existing request-specific renderer test with these semantic markers:

```python
def test_trace_renderers_do_not_dump_primary_structured_objects() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderCommandPresentation") : DASHBOARD_HTML.index(
            "function traceHumanTitle("
        )
    ]
    for function_name in [
        "renderCommandPresentation",
        "renderReviewPresentation",
        "renderRepoIntelligencePresentation",
        "renderRagSearchPresentation",
        "renderAsyncJobPresentation",
        "renderRequestResponsePresentation",
    ]:
        start = source.index(f"function {function_name}")
        end = source.find("\n function ", start + 10)
        body = source[start:] if end < 0 else source[start:end]
        assert "traceSummaryCard" in body or "traceList" in body or "traceCodeBlock" in body
        assert "renderAny(" not in body
```

- [ ] **Step 2: Run RED.**

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py -k "do_not_dump_primary_structured_objects" --tb=short
```

Expected: FAIL for at least one current renderer because it still routes a structured value through `tracePresentationField`/generic rendering without a semantic primitive.

- [ ] **Step 3: Refine the model/agent layouts.** Keep `renderModelChatPresentation` as output-left/input-right on desktop and stacked on narrow screens. Render each message as a role-labelled card; render tool calls/results as timeline cards with name, status, and a collapsed bounded payload. Do not show IDs unless needed to pair a tool result.

- [ ] **Step 4: Refine command/review layouts.** Command view shows command, arguments only when meaningful, stdout/stderr as code blocks, and exit/retry/duration as compact status cards. Review view shows request/context/diff, findings as a severity list, and recommendation/status; omit empty columns.

- [ ] **Step 5: Refine repository/RAG layouts.** Repository view shows operation, repository label, query, concise result, and files/symbols as lists. RAG view shows query, count, ranked source rows with path/location/provider/score, snippet, answer, and truncation; source payload objects remain collapsed.

- [ ] **Step 6: Refine async/request-response/fallback layouts.** Async view shows lifecycle/status, queue wait, retries, result, and error. Request/response shows request, response, status, timing, and error. Unknown/malformed payloads use the same readable fallback with an explicit unavailable state only for fields necessary to understand the failure.

- [ ] **Step 7: Add compact responsive CSS and run renderer tests.** Add styles for `.trace-summary-card`, `.trace-code-card`, `.trace-list-card`, `.trace-timeline-row`, and narrow-screen stacking beside existing trace styles. Then run:

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py -k "trace_renderer or trace_inspector or model_chat or agent_loop or review_severity" --tb=short
```

Expected: all selected tests pass; no `[object Object]` appears in Node fixture output.

- [ ] **Step 8: Commit specialized layouts.**

```bash
git add src/local_ai_hub/dashboard.py tests/test_dashboard_custom_modals.py
git commit -m "feat(dashboard): render trace payloads as semantic views"
```

### Task 4: Keep technical diagnostics complete but secondary

**Files:**
- Modify: `src/local_ai_hub/dashboard.py:2294-2315`.
- Test: `tests/test_dashboard_custom_modals.py`.

- [ ] **Step 1: Add integration assertions.** Require the generated order to be header → `renderTracePresentation(model)` → closed `#traceTechnicalDetails`, and require the technical block to retain universal summary, tabs, timeline, raw JSON, and redaction controls.

- [ ] **Step 2: Run RED.**

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py -k "presentation_before_optional_details or preserves_outer_technical_details" --tb=short
```

Expected: the test fails only if the current assembly still exposes a technical panel before the primary content or opens it by default.

- [ ] **Step 3: Implement the disclosure order.** Keep the existing state capture/restore code. Generate:

```javascript
const presentationMarkup=renderTracePresentation(model);
const technicalMarkup=`<details id="traceTechnicalDetails" class="trace-optional-details"><summary>Technical details</summary><div class="trace-optional-body">${universalSummary}<nav class="trace-tabs" role="tablist" aria-label="Trace views">${tabs}</nav>${panelMarkup}</div></details>`;
body.innerHTML=`<div class="human-shell">${header}${presentationMarkup}${technicalMarkup}</div>`;
```

Apply `traceOptionalDetailsOpen` only when restoring a previously opened disclosure; never add `open` on a first render. Preserve tab ARIA state, thinking-detail state, scroll positions, polling updates, and redaction reveal behavior.

- [ ] **Step 4: Run integration and regression tests.**

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py tests/test_debug_traces.py tests/test_debug_trace_request_summary.py -k "trace" --tb=short
```

Expected: zero failures, including malformed event, bounded payload, redaction, and tab-preservation tests.

- [ ] **Step 5: Commit integration.**

```bash
git add src/local_ai_hub/dashboard.py tests/test_dashboard_custom_modals.py
git commit -m "feat(dashboard): make trace technical details optional"
```

Do not stage the unrelated live-event link change when committing.

### Task 5: Document, validate, and manually inspect

**Files:**
- Modify: `docs/DASHBOARD.md` only if the Trace Inspector section exists and needs the new default behavior documented.
- Test: `tests/test_dashboard_custom_modals.py`.

- [ ] **Step 1: Add one documentation paragraph.** State that Trace Inspector chooses a request-specific human layout, hides empty/internal/duplicate metadata by default, and keeps complete sanitized raw/technical views behind collapsed Technical details.

- [ ] **Step 2: Run repository tools.** The bundled `ensure-tools.ps1` path is unavailable in this checkout, so use the repository command broker first and do one bounded native fallback only if it returns terminal/non-retryable:

```text
local_ai_command(action="run", command="python -m pytest -q tests/test_dashboard_custom_modals.py tests/test_debug_traces.py tests/test_debug_trace_request_summary.py --tb=short", cwd="C:\\Users\\Adam\\.local-ai-hub")
local_ai_command(action="run", command="python -m compileall -q src mcp tools tests", cwd="C:\\Users\\Adam\\.local-ai-hub")
local_ai_command(action="run", command="python tools/release_check.py", cwd="C:\\Users\\Adam\\.local-ai-hub")
local_ai_command(action="run", command="python -m pytest -q --tb=short", cwd="C:\\Users\\Adam\\.local-ai-hub")
```

Expected: each command reports success with zero failures. Also run `git diff --check` through the command broker.

- [ ] **Step 3: Inspect representative browser traces.** Use the existing dashboard service/browser and inspect one model chat, agent loop, command, review, repository, RAG, async-job, request/response, and malformed trace. Confirm the first screen is readable, empty rows are absent, technical details start closed, raw JSON remains available after expanding, and narrow layout stacks without horizontal overflow.

- [ ] **Step 4: Review the final diff and preserve existing work.** Run `git diff --stat`, `git diff --check`, and `git diff -- src/local_ai_hub/dashboard.py tests/test_dashboard_operational_surfaces.py`. Confirm the pre-existing live-event link hunk is unchanged and only intended Trace Inspector/docs/test changes were added.

- [ ] **Step 5: Commit documentation and final scoped changes.** Stage only intended hunks; leave unrelated user edits unstaged if they are not part of the final patch.

```bash
git add docs/DASHBOARD.md tests/test_dashboard_custom_modals.py
git commit -m "docs(dashboard): describe human-first trace inspector"
```
