# PR #10 Native Desktop Cutover Implementation Plan

> **Execution:** Primary agent owns implementation, integration and review. The Hub plan at `plan_pr10_native_desktop` is the authoritative status tracker; this linked plan records sequence and acceptance only.

**Goal:** Finish PR #10 as a native Rust desktop replacement with no legacy runtime behavior except one-time migration during update.

**Architecture:** Rust/egui desktop uses canonical Python Hub services through bounded typed IPC. Hub data and authorization remain authoritative. Remove the web dashboard and legacy alias; preserve current canonical HTTP, MCP and CLI capabilities.

**Tech Stack:** Rust, egui/eframe, Python Hub, existing CI and platform packaging.

**Spec:** `docs/superpowers/specs/2026-11-27-pr10-native-desktop-design.md`

## Global Constraints

- User's no-backward-compatibility/no-legacy instruction overrides conflicting existing requirements and code.
- Only a one-time, recoverable updater migration for existing installations is allowed.
- Preserve unrelated dirty work and all legitimate master changes.
- Do not report completion without current, scope-matched evidence.
- Respect canonical authorization, branch protections, project safety and test isolation.

## Plan Tasks

### Task 1: Reconcile branch and authoritative state

**Files:** `.local-ai-hub/plans/plan_pr10_native_desktop.plan.json`, `docs/FINAL_COMPLETION_PLAN.md`, `docs/DESKTOP_PARITY.md`.

- [ ] Inspect current PR branch, master, full divergence, worktree and unfinished changes.
- [ ] Map all 35 source sections and historical dashboard/CLI workflows to tracked criteria and parity rows.
- [ ] Record current native, CI, runtime, platform, installer and signing evidence; classify stale, missing and failed receipts.
- [ ] Record external blockers separately from fixable implementation gaps.
- [ ] Preserve no-legacy clarification in the Hub plan. If task-scoped steering API remains unavailable, use supported plan edits and record the exact limitation.

**Acceptance:** No requirement or existing change is silently dropped; active Hub plan and parity register reflect current verified state.

### Task 2: Synchronize PR branch with current master

**Files:** All overlapping paths from the branch/master diff, especially `defaults.toml`, `src/local_ai_hub/defaults.toml`, `src/local_ai_hub/http_server.py`, `src/local_ai_hub/mcp_instrumentation.py`, `src/local_ai_hub/mcp_wire.py`, `src/local_ai_hub/scheduler.py`, `tools/setup.py`, and affected tests.

- [ ] Merge latest master into `feat/native-desktop-hub` without dropping either side's valid behavior.
- [ ] Resolve overlaps by contract and tests, especially MCP diagnostics, scheduler reservations, installer changes and removed dashboard routes.
- [ ] Re-run focused tests for each conflict area and retain exact receipts.

**Acceptance:** Branch contains current master, no unresolved conflicts, unrelated work preserved, focused regressions pass.

### Task 3: Complete native UI and CLI behavior

**Files:** `desktop/src/`, `tools/desktop.py`, `tools/desktop_operator.py`, HTTP/MCP/CLI contracts, `docs/DESKTOP_PARITY.md`, relevant tests.

- [ ] Compare every historical dashboard workflow and current CLI command/argument/error to a native view/action and behavioral test.
- [ ] Complete requests, jobs, work orders, plans, tasks, memory, incidents, knowledge, projects, preprocessing, commands, resources, models, traces, activity, settings, vision, transfers and client integration gaps from the parity audit.
- [ ] Keep backend behavior centralized and all mutations scoped, confirmed and revision-fenced.
- [ ] Remove obsolete web-only code, routes, configuration and CLI alias; keep no fallback browser path.

**Acceptance:** Every relevant parity row has a verified native result or evidenced obsolete disposition; no placeholder or inert control remains.

### Task 4: Enforce one-time migration and remove legacy behavior

**Files:** updater/setup and migration code, dashboard-era configuration/state, migration tests and documentation.

- [ ] Identify old persisted state that needs migration to operate an existing installation.
- [ ] Implement one idempotent updater-only migration with atomicity, integrity checks, recovery and a durable completion marker.
- [ ] Ensure fresh install does not run compatibility logic and migrated installs do not retain legacy runtime branches, aliases or routes.
- [ ] Test old→new update, interruption/recovery, repeat update, and fresh install separately.

**Acceptance:** The single authorized migration succeeds safely; no old runtime behavior survives its completion.

### Task 5: Finish UX, accessibility, reliability and performance

**Files:** `desktop/src/`, bridge/runtime lifecycle, focused native UI and performance tests, `docs/DESKTOP.md`.

- [ ] Complete consistent navigation, typed forms, errors, empty/loading states, keyboard flow, focus, screen-reader labels, HiDPI and large-list behavior.
- [ ] Exercise independent Hub/desktop lifecycle, service managers, multiple instances and failure/recovery paths.
- [ ] Measure startup, ready time, idle/peak CPU and RSS, GPU, IPC, online/offline and long-run behavior with recorded platform/method.
- [ ] Audit authorization, process ownership, path/TOCTOU, secrets, limits, concurrency, cancellation, unknown outcomes and shutdown.

**Acceptance:** Required risks have regression coverage; actual measures and supported platform behavior are documented.

### Task 6: Finish installer, release and platform support

**Files:** `.github/workflows/desktop.yml`, `.github/workflows/release.yml`, `tools/install_desktop.py`, updater/setup and release manifests/docs.

- [ ] Verify first install, one-time migration, independent app/Hub updates, rollback, interrupted recovery, headless preference and uninstall.
- [ ] Verify Windows x64, Linux x64, macOS Intel and Apple Silicon runtime, not just builds; assess ARM64 without unsupported claims.
- [ ] Complete dependency/license inventory, notices, lockfile, SBOM where appropriate, security checks, signing and notarization automation/gates.
- [ ] Keep external credentials/identity blockers explicit; do not fabricate signatures or receipts.

**Acceptance:** All platform and package claims match actual checks and artifacts; installer/update behavior is recoverable and integrity-checked.

### Task 7: Run full validation and independent audit

**Files:** Relevant source/tests/workflows and all user-facing documentation.

- [ ] Run fresh Rust format, Clippy, locked build and tests; focused bridge, contract, security and end-to-end checks.
- [ ] Run the complete supported Python suite using `pytest --run-all` or complete fresh CI shards; preserve counts and artifacts.
- [ ] Pass coverage, contract, source/citation, entrypoint, package, dependency/security, release and repository gates without lowering thresholds.
- [ ] Independently audit the complete PR diff against all 35 sections and the full parity/CLI inventory; fix and reverify every fixable blocker.
- [ ] Update documentation and Hub plan with actual results, not historical narrative.

**Acceptance:** Every required gate is current and passing, or its exact external blocker is recorded with all independent work complete.

### Task 8: Deliver PR #10 into master

**Files:** PR #10 and `feat/native-desktop-hub`.

- [ ] Commit and push verified changes to the existing feature branch; refresh PR description and draft state only when gates qualify.
- [ ] Verify required checks on the exact integrated head and respect branch protection.
- [ ] Merge PR #10, verify merged status and SHA, update local master, and verify post-merge CI.
- [ ] Update the authoritative Hub plan with authentic receipts and classify/clean work artifacts safely.

**Acceptance:** PR #10 is merged to master, actual post-merge state is verified, and the final report links evidence and external blockers.
