# Dashboard Comprehensive UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make Local AI Hub Dashboard actionable, consistent, privacy-safe, and useful for both agent and non-agent traces.

**Architecture:** Keep `src/local_ai_hub/dashboard.py` as static HTML/JavaScript host. Add pure display-model helpers before changing view renderers. Views consume normalized state, freshness, identity, redaction, and availability metadata. HTTP API payloads remain compatible.

**Tech Stack:** Python 3.11, embedded HTML/CSS/vanilla JavaScript, pytest, Chrome.

---

### Task 1: Shared display state

**Files:**
- Modify: `src/local_ai_hub/dashboard.py:645-710, 1692-1724`
- Modify: `tests/test_dashboard_custom_modals.py`

- [ ] Write failing contract test:

```python
def test_dashboard_display_helpers_expose_health_freshness_and_redaction() -> None:
    assert "function dashboardHealth(" in DASHBOARD_HTML
    assert "function dashboardFreshness(" in DASHBOARD_HTML
    assert "function redactDiagnostic(" in DASHBOARD_HTML
```

- [ ] Run `python -m pytest -q tests/test_dashboard_custom_modals.py -k display_helpers --tb=short`. Expect FAIL.
- [ ] Add `dashboardHealth(summary)`, `dashboardFreshness(updated_at)`, and `redactDiagnostic(value)`; return stable display models, mark data older than 120 seconds stale, and replace local roots plus token arguments.
- [ ] Run the same test. Expect PASS.
- [ ] Commit `feat(dashboard): add display state helpers`.

### Task 2: Overview priority surface

**Files:**
- Modify: `src/local_ai_hub/dashboard.py:297-336, 3898-4025`
- Modify: `tests/test_dashboard_custom_modals.py`

- [ ] Write failing test:

```python
def test_overview_has_actionable_health_and_freshness_contract() -> None:
    assert 'id="overviewHealthSummary"' in DASHBOARD_HTML
    assert 'id="overviewFreshness"' in DASHBOARD_HTML
    assert "function renderOverviewHealth(" in DASHBOARD_HTML
    assert "Needs attention" in DASHBOARD_HTML
```

- [ ] Run `python -m pytest -q tests/test_dashboard_custom_modals.py -k overview_health --tb=short`. Expect FAIL.
- [ ] Add alert-first health card, evidence, freshness, and targeted detail link. Keep supporting metrics compact. Label charts with units and render useful empty state.
- [ ] Run the same test. Expect PASS.
- [ ] Commit `feat(dashboard): prioritize overview health`.

### Task 3: Universal Trace Inspector

**Files:**
- Modify: `src/local_ai_hub/dashboard.py:659-711, 1723-1887`
- Modify: `tests/test_dashboard_custom_modals.py`
- Modify: `tests/test_debug_traces.py`
- Modify: `tests/test_debug_trace_request_summary.py`

- [ ] Write failing test:

```python
def test_trace_inspector_supports_universal_and_agent_specific_panels() -> None:
    assert "function traceDisplayModel(" in DASHBOARD_HTML
    assert "Request summary" in DASHBOARD_HTML
    assert "Input unavailable for this request type" in DASHBOARD_HTML
    assert "Model execution" in DASHBOARD_HTML
```

- [ ] Run `python -m pytest -q tests/test_dashboard_custom_modals.py tests/test_debug_traces.py tests/test_debug_trace_request_summary.py -k trace_inspector --tb=short`. Expect FAIL.
- [ ] Implement `traceDisplayModel(detail)` with universal identity, lifecycle, timing, actor, tenant, correlations, retained bytes, input, output, response, errors, events, and model/tool execution fields.
- [ ] Render universal request summary first. Render input/output/model panels only when recorded. Show explicit unavailable state otherwise; default diagnostics stay redacted and use an explicit reveal control.
- [ ] Run the focused trace tests. Expect PASS.
- [ ] Commit `feat(dashboard): improve trace inspector`.

### Task 4: Queue, Agent OS, and operational actions

**Files:**
- Modify: `src/local_ai_hub/dashboard.py:350-454, 3844-3897`
- Modify: `tests/test_dashboard_custom_modals.py`

- [ ] Write failing test asserting `data-trace-available`, `HTTP trace history`, `Agent task runs`, `Delete project`, and `Purge cache`.
- [ ] Run `python -m pytest -q tests/test_dashboard_custom_modals.py -k trace_availability --tb=short`. Expect FAIL.
- [ ] Split request history from task history. Mark summary-only traces before opening detail. Replace icon-only actions with named accessible buttons and impact/confirmation metadata.
- [ ] Run the focused test. Expect PASS.
- [ ] Commit `feat(dashboard): clarify operational work`.

### Task 5: Projects, Bundles, Models/RAG, Reliability, and events

**Files:**
- Modify: `src/local_ai_hub/dashboard.py:3794-3897, 4177-4541`
- Modify: `tests/test_dashboard_custom_modals.py`

- [ ] Write failing test asserting `function repositoryDisplayIdentity(`, `Search workspaces`, `No events match the current filters`, `Restart trend`, and `Bundle contents`.
- [ ] Run `python -m pytest -q tests/test_dashboard_custom_modals.py -k operational_views --tb=short`. Expect FAIL.
- [ ] Add canonical repository identity; group duplicate project/bundle roots; add filters, empty states, workspace search, event severity/source filters, restart/failure trend, and bundle readiness/content summary.
- [ ] Run the focused test. Expect PASS.
- [ ] Commit `feat(dashboard): improve operational views`.

### Task 6: Verification

**Files:**
- Modify: `tests/test_dashboard_custom_modals.py`
- Modify: `tests/test_debug_traces.py`
- Modify: `tests/test_debug_trace_request_summary.py`

- [ ] Add one static contract test requiring `overviewHealthSummary`, `traceDisplayModel(`, explicit unavailable input text, `data-trace-available`, `redactDiagnostic(`, and `repositoryDisplayIdentity(`.
- [ ] Run `python -m pytest -q tests/test_dashboard_custom_modals.py tests/test_debug_traces.py tests/test_debug_trace_request_summary.py --tb=short`. Expect PASS.
- [ ] Run `python tools/release_check.py; python -m compileall -q src mcp tools tests; python -m pytest -q; python tools/selftest.py`. Expect all commands exit 0.
- [ ] Inspect Chrome: Overview alert/freshness; agent and ordinary HTTP trace input/output; default redaction; project grouping; named destructive controls.
- [ ] Commit `test(dashboard): cover operational UX`.
