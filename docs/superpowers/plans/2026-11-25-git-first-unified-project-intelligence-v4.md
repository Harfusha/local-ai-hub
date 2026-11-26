# Git-first Unified Project Intelligence V4 Implementation Plan

> **For agentic workers:** execute sequentially with the current owner. Steps use checkbox syntax.

**Goal:** Complete the V4 requirements in PR #9, prove the real cross-clone workflow end to end, then integrate the verified result into `master`.

**Architecture:** Extend existing repository plan, Agent OS, evidence, preprocessing, query, review, HTTP/MCP/CLI, and dashboard owners. Git stores authorized durable project knowledge; rebuildable indexes remain local; private runtime state and credentials remain local. Keep deterministic authorization and verification authoritative.

**Tech Stack:** Python, SQLite, Git, pytest, existing Local AI Hub HTTP/MCP/CLI/dashboard.

**Spec:** [`docs/superpowers/specs/2026-11-25-git-first-unified-project-intelligence-v4.md`](../specs/2026-11-25-git-first-unified-project-intelligence-v4.md)

## Global Constraints

- Use existing canonical Hub services and contracts; no parallel task, knowledge, or persistence system.
- Persist only reviewed, authorized project data; never publish secrets, credentials, private sessions, runtime attempts, locks, or unreviewed model output.
- Laya is advisory only; it cannot mint evidence, approve rules, change task state, grant permissions, verify receipts, merge, or publish Git.
- Preserve user edits and source provenance; fail closed on stale, partial, malformed, untrusted, unsupported, or ambiguous evidence.
- Git operations exposed by the feature remain diagnostic/read-only unless a separately authorized operation already exists.
- All migrations remain idempotent, restartable, recoverable, and explicit about authority; no silent dual-write or stale legacy overwrite.
- Tests use real temporary repositories and independent state directories where specified; do not count mocks or partial scenarios as release acceptance.

## Review Focus

- Concurrent edits and crashes during record publication: prove CAS, atomic recovery, and no lost human edits in the owning storage tests.
- Stale or incomplete source/evidence: prove revalidation, explicit partial status, and fail-closed completion in source dependency and receipt tests.
- Malicious repository paths and imported artifacts: prove traversal/symlink/secret defenses in security fixtures.
- Private/local state crossing clone boundaries: prove exclusion with two independent clones and distinct local state directories.
- Divergent records and stale waivers: prove scoped conflict handling, occurrence identity, expiry, and no silent authority escalation.

---

### Task 1: Close canonical storage and Agent OS authority

**Files:** `src/local_ai_hub/repo_knowledge*.py`, `src/local_ai_hub/repo_task_handoff.py`, `src/local_ai_hub/agent_state_*.py`, `src/local_ai_hub/repo_plan/`, `src/local_ai_hub/evidence.py`, `tools/hubctl.py`; corresponding `tests/test_repo_knowledge*.py`, `tests/test_agent_tasks.py`, migration and handoff tests.

- [ ] Inventory actual durable stores, fields, readers, writers, scopes, cleanup, and permissions; publish ownership ADR and complete storage matrix.
- [ ] Close canonical record schema, portable evidence vs execution digest, CAS, atomic write/recovery, conflict semantics, watcher/freshness, and rebuildable projection gaps.
- [ ] Complete reviewed Agent OS migration for tasks, memory, incidents, decisions, questions, coordination, receipts, work and artifacts; preserve runtime/private state locally.
- [ ] Add red/green tests for each missing contract, including migration replay/rollback, stale writer, crash recovery, path attacks, and record limits.
- [ ] Run focused storage, migration, handoff, and security suites; attach authentic receipts and mark each GIT/UPS/KI requirement accurately.

### Task 2: Complete business intelligence and human workflow

**Files:** existing preprocessing, graph, query/context/review services; `src/local_ai_hub/ui_static/`, `tools/hubctl.py`, HTTP/MCP contracts, provider skills; corresponding feature and contract tests.

- [ ] Map every remaining KI/UPS/GIT requirement to its existing owner and test; reject duplicate subsystems.
- [ ] Complete deterministic extraction, freshness/invalidation, graph/query coverage, business impact, requirement-to-code/test mapping, and ordinary task context.
- [ ] Complete finding lifecycle, review inbox, scoped waivers, human correction, remediation task, and verified resolution behavior.
- [ ] Complete consistent CLI/HTTP/MCP/dashboard workflows and provider guidance without weakening permission or quality gates.
- [ ] Add per-category Laya quality/abstention evidence only where typed contracts and authentic outcomes support it; preserve deterministic fallback.

### Task 3: Prove end-to-end acceptance and repair defects

**Files:** acceptance/security/performance tests, CI workflows, release/selftest tooling, V4 acceptance matrix and docs.

- [ ] Implement every required V4 E01–E18 and UPS-01–14 scenario with actual files, two independent clones, linked worktrees, distinct local state, and applicable browser/API/MCP/CLI paths.
- [ ] Cover bootstrap/trust, import/migration, private-state exclusion, malformed records, divergence, stale evidence, rollback, watcher races, ordinary task lifecycle, review/remediation, and offline headless validation.
- [ ] Run focused tests, full `pytest --run-all -q`, `python tools/release_check.py`, `python -m compileall -q src tools tests`, and `python tools/selftest.py`; fix failures without removing or weakening checks.
- [ ] Measure no-op/churn, p95, store size, and reviewer burden against the exact V4 limits; record environment and raw command results.
- [ ] Update the spec's acceptance ledger only from observed results; disclose any genuinely unavailable external runtime as an explicit blocker.

### Task 4: Integrate and verify on master

**Files:** reviewed PR changes and project plan only; preserve the original dirty checkout.

- [ ] Review complete diff and commits; classify every pre-existing dirty path before integration.
- [ ] Integrate completed, tested commits into `master` without discarding unrelated user work.
- [ ] Re-run required checks on integrated `master`; record exact commit and authentic verification receipts.
- [ ] Update Hub plan status and report local integration separately from remote GitHub PR merge status.
