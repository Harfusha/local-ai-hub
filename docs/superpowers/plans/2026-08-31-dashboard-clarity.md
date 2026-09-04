# Dashboard Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the dashboard operations-first, compact, filterable, and still diagnostically complete.

**Architecture:** Keep the current single-file embedded dashboard and API contract. Change only presentation markup, client-side rendering, and CSS; project details continue through the existing detail modal.

**Tech Stack:** Python raw HTML template, vanilla JavaScript, CSS, pytest, Node syntax check.

---

### Task 1: Add dashboard acceptance tests

**Files:**
- Modify: `tests/test_v1_2_reliability.py`

- [x] Add assertions for the Controls menu, project filters, compact headers, and removal of the repeated phase legend.
- [x] Run the focused dashboard test and confirm it fails before implementation.

### Task 2: Simplify the shell and overview

**Files:**
- Modify: `src/local_ai_hub/dashboard.py`

- [x] Move secondary actions into `<details id="controlMenu">` and retain their existing IDs and handlers.
- [x] Keep only actionable overview cards and combine hardware metrics into `sysUtil`/`sysSub`.
- [x] Add responsive styles for the compact shell and filter bar.

### Task 3: Make Projects operationally scannable

**Files:**
- Modify: `src/local_ai_hub/dashboard.py`

- [x] Replace the 9-column project table and legend with a 5-column table and filter controls.
- [x] Filter and sort the existing `p.projects` array client-side.
- [x] Keep `clickableRow` so full diagnostics remain available on row click.

### Task 4: Verify UI and runtime

**Files:**
- Modify: `tests/test_v1_2_reliability.py` only if a regression is discovered.

- [x] Run compileall, the complete pytest suite, and selftest through Local AI Hub.
- [x] Restart the hub, reload the browser, inspect desktop/narrow screenshots, and verify active/waiting/paused counts.
