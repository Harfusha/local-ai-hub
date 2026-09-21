# Trace Inspector Full Payload Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Trace Inspector display truncation markers and raise trace storage defaults so retained payloads remain visible.

**Architecture:** Keep `DebugTraceStore` as a bounded storage boundary, increasing only its default event/text sizes. Replace dashboard presentation helpers that inject synthetic markers with complete sanitized JSON/HTML rendering; keep redaction and event-count/retention bounds.

**Tech Stack:** Python 3.11+, pytest, generated dashboard HTML/JavaScript, SQLite-backed debug traces.

---

### Task 1: Lock the storage defaults and dashboard contract with failing tests

**Files:**
- Modify: `tests/test_debug_traces.py` near `DebugTraceStore` configuration tests
- Modify: `tests/test_dashboard_custom_modals.py` near existing `trace_task8` and Trace Inspector tests

- [x] **Step 1: Add storage-default assertions.** Instantiate `DebugTraceStore` with only the required server state directory and assert `max_event_bytes == 4 * 1024 * 1024` and `max_session_text_bytes == 64 * 1024 * 1024`.

- [ ] **Step 2: Add a failing nested-payload dashboard test.** Use the existing Node probe to render a payload nested beyond four levels and assert the deepest value is visible and the output does not contain `<payload budget truncated>`.

- [ ] **Step 3: Add a failing large-payload dashboard test.** Render a retained string larger than the old presentation budget and assert its tail marker is absent and the rendered output contains the retained content boundary expected by the probe.

- [ ] **Step 4: Run only these new tests.**

Run: `python -m pytest -q tests/test_debug_traces.py tests/test_dashboard_custom_modals.py -k "trace_default_limits or trace_full_payload or trace_task8" --tb=short`

Expected: the new tests fail because the current defaults and dashboard guards still truncate.

### Task 2: Raise bounded trace-store defaults

**Files:**
- Modify: `src/local_ai_hub/debug_traces.py:35-40`
- Test: `tests/test_debug_traces.py`

- [ ] **Step 1: Change only the two defaults.** Set the fallback for `max_event_bytes` to `4 * 1024 * 1024` and the fallback for `max_session_text_bytes` to `64 * 1024 * 1024`. Preserve config overrides and all lower-bound validation.

- [x] **Step 2: Run storage tests.**

Run: `python -m pytest -q tests/test_debug_traces.py -k "default or bound or event" --tb=short`

Expected: PASS.

### Task 3: Remove display-only truncation markers while preserving redaction

**Files:**
- Modify: `src/local_ai_hub/dashboard.py:2094-2111,2174-2213,2265-2303`
- Test: `tests/test_dashboard_custom_modals.py`

- [ ] **Step 1: Replace marker-producing presentation bounds.** Make dashboard value normalization recurse through the complete retained value, preserving the existing sensitive-key filtering and malformed-value handling. Do not emit `<payload budget truncated>`, `… payload budget truncated`, or `… truncated` from normal Trace Inspector renderers.

- [ ] **Step 2: Remove shared presentation-budget omission paths.** Update the primary field, markup-item, aggregate-field, and technical-panel assembly paths so they retain all generated components rather than inserting a marker when a display budget is exceeded.

- [ ] **Step 3: Keep bounded event-count behavior.** Preserve the existing event-count and retention behavior; only remove display-size/depth omissions. Keep HTML escaping and existing redaction unchanged.

- [ ] **Step 4: Run the focused dashboard tests.**

Run: `python -m pytest -q tests/test_dashboard_custom_modals.py -k "trace_inspector or trace_task8 or trace_presentation or trace_model_chat or trace_agent_loop" --tb=short`

Expected: PASS, with no synthetic payload-budget marker in rendered Trace Inspector output.

### Task 4: Verify regression surface

**Files:**
- Review: `src/local_ai_hub/debug_traces.py`
- Review: `src/local_ai_hub/dashboard.py`
- Review: `tests/test_debug_traces.py`
- Review: `tests/test_dashboard_custom_modals.py`

- [ ] **Step 1: Run the full required validation.** Focused dashboard/debug-trace suites, compileall, selftest, and diff check pass. Full pytest exceeded the 180–300 second bounded runner timeout; release-check is blocked by pre-existing generated/runtime artifacts in the workspace.

Run: `python tools/release_check.py`

Run: `python -m compileall -q src mcp tools tests`

Run: `python -m pytest -q`

Run: `python tools/selftest.py`

Expected: all commands pass.

- [x] **Step 2: Review the diff.** Run `git diff --check` and inspect only the scoped files plus the design/plan documents. Confirm unrelated existing changes remain untouched.

- [x] **Step 3: Record the final result.** Report changed defaults, marker behavior, tests run, and remaining limitation: traces captured before this change may already contain backend truncation envelopes.
