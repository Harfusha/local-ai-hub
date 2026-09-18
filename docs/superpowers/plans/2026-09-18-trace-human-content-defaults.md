# Trace Human Content Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make human-relevant request/result content visible by default for every trace presentation while keeping technical diagnostics expandable and preserving complete human output.

**Architecture:** Keep the existing presentation dispatch and specialized renderers. Extend the disclosure helper to distinguish primary human groups from optional diagnostic disclosures, defaulting primary groups open and preserving their open state across live rerenders. Render human-facing text and captured output in full after sanitization; keep `traceTechnicalDetails` and diagnostic subdetails closed by default.

**Tech Stack:** Python 3.11+, inline dashboard JavaScript in `src/local_ai_hub/dashboard.py`, pytest, Node.js fixture tests.

---

### Task 1: Add failing default-state coverage

**Files:**
- Modify: `tests/test_dashboard_custom_modals.py` near the existing trace inspector source and fixture tests.
- Reference: `src/local_ai_hub/dashboard.py:2226-2227,2445-2459`.

- [ ] **Step 1: Add source assertions for primary versus technical disclosures.**

Add a test beside the existing `traceTechnicalDetails` source assertions:

```python
def test_trace_primary_groups_open_by_default_and_technical_details_closed() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function tracePresentationGroup") : DASHBOARD_HTML.index(
            "function renderTraceDetail(d)"
        )
    ]
    assert "data-primary-open" in source
    assert "traceTechnicalDetails" not in source

    detail_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    assert '<details class="trace-optional-details" id="traceTechnicalDetails"' in detail_source
    assert "traceTechnicalDetails' open" not in detail_source
```

- [ ] **Step 2: Add a JavaScript fixture proving human content is visible without opening technical details and is not shortened.**

Add a fixture test using the existing dashboard JavaScript harness. Construct command data with `presentation.kind = 'command'`, `stdout = 'x'.repeat(9000)`, and a technical panel. Assert the rendered HTML contains the complete stdout, the first `trace-primary-group` has `open`, and `traceTechnicalDetails` does not have `open`.

- [ ] **Step 3: Run the focused tests and verify RED.**

Run:

```powershell
python -m pytest -q tests/test_dashboard_custom_modals.py -k "primary_groups_open or human_content"
```

Expected: failure because primary groups currently render closed and do not expose an explicit primary-open contract.

### Task 2: Implement primary human disclosure behavior

**Files:**
- Modify: `src/local_ai_hub/dashboard.py:2226-2227,2445-2459`.

- [ ] **Step 1: Add state capture for primary disclosures.**

Introduce a helper adjacent to `captureTraceThinkingDetails` that records `data-trace-primary-group` disclosure state by group key, returning an object. Restore those states after `innerHTML` replacement. Default missing state to open.

- [ ] **Step 2: Mark primary groups explicitly and default them open.**

Change `tracePresentationGroup(title, markup, kind)` so it emits a primary group with a stable `data-trace-primary-group` key and `open` by default. Keep technical disclosures on their existing `trace-optional-details` path.

- [ ] **Step 3: Preserve primary group state during `renderTraceDetail`.**

Capture primary states before replacing `tracePageBody.innerHTML`, then restore them in the existing animation-frame restore callback. Preserve the technical disclosure state exactly as today. Do not alter field values, sanitization, escaping, or output rendering.

- [ ] **Step 4: Run the focused tests and verify GREEN.**

Run:

```powershell
python -m pytest -q tests/test_dashboard_custom_modals.py -k "primary_groups_open or human_content"
```

Expected: PASS.

### Task 3: Cover every presentation type

**Files:**
- Modify: `tests/test_dashboard_custom_modals.py` near existing trace presentation fixture tests.

- [ ] **Step 1: Add fixture cases for every specialized kind.**

Cover `agent_loop`, `model_chat`, `command`, `review`, `repo_intelligence`, `rag_search`, `async_job`, `request_response`, and generic input/output. Each fixture must include one human result value and assert that value occurs before the `traceTechnicalDetails` markup.

- [ ] **Step 2: Add a rerender state test.**

Render a fixture, set the primary result disclosure state to closed, rerender with a live-update payload, and assert it remains closed. Repeat with the technical disclosure open and assert both states survive independently.

- [ ] **Step 3: Run the presentation test group.**

Run:

```powershell
python -m pytest -q tests/test_dashboard_custom_modals.py -k "trace or presentation"
```

Expected: PASS with existing redaction, escaping, empty-value, raw JSON, and technical-detail tests unchanged.

### Task 4: Validate full repository behavior

**Files:**
- Modify: none unless a test exposes a targeted regression.

- [ ] **Step 1: Run dashboard tests through the command broker.**

Run `python -m pytest -q tests/test_dashboard_custom_modals.py` through `local_ai_command` with task id `task_0eaf86a70511` and criterion `dashboard trace human content defaults pass`.

- [ ] **Step 2: Run the required repository checks.**

Run:

```powershell
python tools/release_check.py
python -m compileall -q src mcp tools tests
python -m pytest -q
python tools/selftest.py
```

- [ ] **Step 3: Review the diff and security surface.**

Use `local_ai_repo(action="review_diff")` and `local_ai_repo(action="security_audit")`. Confirm only dashboard rendering/tests/docs plan/spec changed, no raw prompt/output telemetry behavior changed, and no technical disclosure became implicitly public.

- [ ] **Step 4: Attach validation receipts and complete the task contract.**

Record passing command receipts with `local_ai_coord`, then call `verify_completion` for `task_0eaf86a70511`.
