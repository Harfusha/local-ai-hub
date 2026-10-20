# Audit Remediation Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans in this checkout. The primary agent implements, reviews and integrates; no routine delegation.

**Goal:** Repair confirmed F01–F24 defects and implement or explicitly resolve all R01–R16 recommendations from the 2026-10-20 application audit.

**Architecture:** Preserve the single-owner installation and canonical repository/task/session scopes. Fix each defect at its responsible boundary, reuse existing path and persistence policies, and extract small cohesive helpers where that reduces the audited monoliths. Do not add deprecated aliases or runtime data migrations.

**Tech Stack:** Python 3.11+, SQLite, standard-library HTTP, MCP, vanilla dashboard JavaScript, pytest, GitHub Actions.

**Spec:** `AGENTS.md`, `docs/superpowers/specs/2026-10-07-simplified-worktree-integration.md`, and the audit HTML/JSON under `C:/Users/Adam/.codex/visualizations/2026/10/20/01a1584b-7f42-7240-9b36-22be709b1257/`.

**Current acceptance state:** Initial repairs are integrated in `5854caa7`. The full-suite pass exposed missing nested context diagnostics, stale test fixtures and generated policies exceeding the Antigravity cap. The follow-up repairs preserve strict identity validation, bounded HTTP reads and the unchanged 23,900-byte limit. Shard progress now waits for fixture teardown; final manifest persistence remains mandatory. Run the complete frozen-candidate suite after these repairs; interrupted or failed partitions are not acceptance evidence.

**F02 data repair:** Original misfiled Shpotify record `mem_cf5858e8e065` is preserved in quarantine (`req_c6a0596eea02`). Active replacement `mem_db308e7f307d` explicitly labels external historical context and does not invent a repository root.

**Production gate:** Preserve historical archives in place; back up active state, installed environment and configuration before managed setup. Complete the current 138-package advisory assessment and the hash-pinned `aiohttp`/`urllib3` security update. Preserve the actual installation, HTTP/MCP, browser and process/resource results in the existing audit checkpoint directory. Production acceptance remains pending until those gates finish.

## Current state

- Owner: `audit-remediation-20261020` (Codex primary).
- Baseline: clean `master`, `9dbd92fe0d8e26d291497db979b3ca44196196bf`.
- Hub task: `audit-remediation-20261020`; writer lease covers source/tests/tools/workflows/prompts/plans.
- Status: implementation in progress; no release or runtime acceptance claimed.
- Next: run final lint/coverage and disjoint full-suite validation, validate built wheel/runtime contracts, then finish the operator-authorized complete production installation.
- Integration checkpoint: first full-suite partition executed every one of its765 selected identities; one MCP HTTP-error propagation regression was fixed and its46-test transport/guide/CLI cohort passed. Canonical installer requirements now retain the PyJWT security floor. CLI missing inventories report unreported rather than zero. The actual isolated wheel smoke exposed invalid port0 and unrequested compact cache fields; both smoke harness defects were repaired and actual MCP initialize/list/call passed for preliminary wheel4b124761ce8732feec0166af51e573a5c0a376e7011a9d6dd5e29ea199a6d084. Final wheel must be rebuilt from the integrated candidate.
- The original branch-coverage ratchet passed before being raised from actual183-test evidence and expanded to11 modules. Final full-suite validation remains pending; no release acceptance claimed.
- Latest full-suite attempt: JUnit reports 2764 cases, 9 failures, 1 teardown error and 31 skips in 1109.574 seconds; stopped after ten failures. This is not a complete-suite result.
- Follow-up regression cohort: SQLite private WAL snapshot, async close, HTTP mode, dashboard and budget fixture repairs passed the relevant targeted tests; Ollama HTTP-error body deadline has a real slow-server regression.
- Operator-approved limits are now 7200 seconds and 200 external calls; prior consumption was preserved through PolicyEngine.set_budget. Exact before/after records are outside the repository in approved-audit-budget-result.json. Tests continue through the broker under the original task.
- CUDA NLP models now load and infer in owned processes. Actual-child timeout/reap, isolated fake-model worker integration, cleanup retry and existing backend cohorts pass (62 tests before the final cleanup-retry cases). No physical CUDA model quality/performance claim.
- Retrieval: seven current source-symbol cases compared with the real saved baseline; signed recall/rank/citation/location-sufficiency deltas are zero. Three bounded natural-language architecture diagnostics measured separately. No model-quality or whole-repository ranking improvement claim.
- Release: build dependencies are hash-pinned (including required Windows colorama), runtime dependencies constrained to a versioned baseline, CycloneDX SBOM scope declared incomplete, advisory scans fail closed. Live OSV detected vulnerable installed PyJWT2.13.0; explicit metadata floor and baseline now require2.15.1. Hash-verified production dependency update completed, mismatch-JWK RED/GREEN regression and pip check pass; candidate baseline OSV batch returned32 complete results with no advisories. Hub restart and full installation still pending.
- Historical audit evidence is immutable. Record corrections here rather than overwriting old observations.

## Global constraints

- Preserve API token protection, command authorization, writer leases, path confinement and explicit task/session ownership.
- Never restore tenant fields, identity aliases, scope coercion or fabricated receipts.
- All tests/builds use `local_ai_command` with this task and a concrete criterion. Keep full output in JUnit/coverage artifacts when needed.
- Work directly in this clean master checkout. Preserve any later foreign changes. No reset/stash/clean or unrelated Git writes.
- No production configuration/data conversion, deployment, service restart, model pull or destructive cleanup is required to make source fixes reviewable.
- Synchronize tool/default/schema changes into both canonical agent prompts.
- Tests with injected barriers inside a newly serialized critical section must be rewritten to coordinate callers before entry; do not retain artificial deadlocks as regression expectations.

## Review focus

Cross-instance SQLite increments; storage errors without a cache; expired/replaced async attempts; malformed falsey inputs; symlink/junction and oversized manifest inputs; omitted versus empty runtime data; minimum response budgets; cleanup after partial failure; Windows process/file locking.

## 1. Integrity and confinement

- [x] **F03/F04 — budgets.** `agent_policy.py`, `tests/test_agent_policy.py`, new audit regression tests. Make increments atomic across engines/processes, serialize in-memory updates, preserve configured maxima, and fail closed on durable read/write failure. Update old tests that intentionally expected fail-open behavior. Test concurrent engines, read/write/init errors, reset/set interactions and clean error messages.
- [x] **F05 — configuration.** `config.py` and a bounded portable file-lock helper; runtime configuration tests. Serialize read/merge/reset/replace across threads/processes, use unique temporary files, clean failures, and preserve unrelated keys. Test simultaneous distinct patches and failed replace.
- [x] **F18/F19/F20 — async jobs.** `async_jobs.py`, `tests/test_async_jobs.py`, new audit tests. Finalization must retain attempt/state/lease/expiry ownership before artifact, task or receipt publication. Require an explicit boolean success. Always clean local resources after a DB failure; retain safe repeated close. Test old/new attempts, cancellation/expiry and malformed success.
- [x] **F21/F22 — package audit.** Extract dependency inventory/audit logic from `deterministic.py` into a focused module. Strict root/manifest confinement, reparse checks and byte limits before reading. Unsupported or malformed formats never report clean; expose parse/resolution/advisory completeness and provenance. Preserve supported vulnerability detections. Test traversal, outside roots, symlinks, size caps, parse failures and unresolved dependencies.
- [ ] Run one combined regression cohort for policy/config/async/package audit and related existing contracts. Record the actual command/result below.

## 2. Identity and response contracts

- [ ] **F01/F02 — context/memory ownership.** `mcp_server.py`, `task_context.py`, repository memory binding. Trace the current symptom to its owner; reject implicit cross-root/session task adoption and preserve canonical repository memory selection. Do not delete historical contaminated records or invent their origin. Add two-root/two-session regressions and provenance diagnostics.
- [ ] **F06/F07 — transport bounds.** `http_server.py`, `ollama.py`, `llama_cpp.py`. Apply one total request-head deadline, bounded response bytes and end-to-end metadata deadlines; preserve cancellation/process cleanup. Test slow drip, oversized response and normal reuse.
- [ ] **F08/F10/F11/F13 — exact context/projection.** `mcp_server.py`, `task_context.py`, `agent_policy.py`. Keep coverage in [0,1] with correct denominator, validate identities and boolean flags without coercion, report the exhausted budget channel, and produce useful bounded context envelopes/artifact references. Test minimal/compact profiles and the smallest supported budgets.
- [ ] **F09 — dashboard config validation.** `http_server.py`, config validators. Exact bool types; list/dict/scalar errors return explicit structured validation failures before mutation.
- [ ] **F12 — command evidence.** `commands.py`, artifact persistence/projection. Persist retrievable complete bounded logs before truncating previews; retain truncation/capture flags and exact execution identity. Test long stdout/stderr and storage failures.
- [x] **F14 — diagram metadata.** `rag.py`. Reject reserved client metadata keys or isolate user metadata, then apply canonical source metadata. Test conflicting path/type and normal captions.
- [x] **F15/F16 — parallel command helper.** `commands.py`. Validate the entire batch before launching, reject duplicate IDs and unknown keys, forward exact supported task/criterion/fencing parameters, aggregate every accepted result. Test both completion orders.
- [x] **F17 — reference fallback.** `external_tools.py`, `code_index.py`. Call actual references, retain backend failure/completeness and never relabel definitions. Test multiple callers, missing backend and failed index.
- [ ] Run the related combined contract regression cohort; inspect indexed impact/review before final validation.

## 3. Dashboard and operator truthfulness

- [ ] **F23 — resident model inventory.** `dashboard.py`. Missing inventory is unknown; empty verified inventory is none. Fetch a bounded inventory for the model panel or retain an explicitly aged known snapshot. Test absent/empty/nonempty/stale payloads.
- [ ] **F24 — memory filters.** Derive supported scope/kind options from canonical enums and retain all valid choices. Keep incidents separate. Test generated options and filtered fixtures.
- [ ] **R11 — diagram mode.** Clearly label raster indexing as metadata-only when OCR/vision was not used; offer only actually supported explicit processing, never automatic model download.
- [ ] **R15 — trace polling.** Separate small operations summaries from detailed trace lists. Avoid repeatedly loading/rendering hidden details; preserve live queue visibility and visibility cancellation. Measure request bytes and cadence, then test tab transitions.
- [ ] **R16 — workspace lifecycle.** Show root identity, availability/verification age and clear unknown reasons with filters. Provide a review-only cleanup proposal, not automatic deletion.
- [ ] Verify desktop/mobile and navigation in the actual dashboard only when the running instance contains the candidate source. Otherwise use an isolated candidate preview and label runtime provenance explicitly.

## 4. Reliability, maintainability and release checks

- [ ] **R01 — API token policy.** Make defaults, validation, installation prompts and authorization tests agree. Preserve the documented loopback trust boundary or enforce a generated token consistently; do not silently invalidate an installed instance.
- [ ] **R02 — model lifecycle.** Bound lock acquisition, expose wait/load/unload timing, and route unpreemptable backend work through the existing owned process boundary where supported. Explicitly report unsupported cancellation rather than pretending a thread timeout stops a driver call.
- [ ] **R03 — telemetry durability.** Distinguish drained from persisted/lost, with explicit counters/result semantics. Test an accepted event lost during writer failure.
- [ ] **R04 — shutdown.** Track per-component cleanup results, log one concise failure summary, and permit safe bounded repeated cleanup. Inject failures into each phase without hiding remaining workers.
- [ ] **R05 — Windows CI.** Add scheduled/release full-suite Windows coverage using existing supported Python versions; keep ordinary push costs bounded.
- [ ] **R06 — coverage.** Measure critical-module branch coverage and establish a ratchet from the real baseline; never invent a threshold percentage.
- [ ] **R07 — monolith extraction.** Extract the repaired dependency audit, transport/response validators and dashboard contract helpers at existing interfaces. Keep public tool count and behavior; avoid a wholesale unrelated rewrite.
- [ ] **R08 — action schemas.** Generate compact action-specific help/errors/examples from the canonical schema, with parity tests and unchanged eight-tool surface.
- [ ] **R09/R10 — retrieval/review evaluations.** Add deterministic gold cases for production entrypoint ranking, source/test separation and citation/verdict consistency. Keep local review advisory; report actual paired evaluation evidence only.
- [ ] **R12 — release dependencies.** Version a verified release toolchain/constraints baseline; save resolved environment/SBOM and run current advisories against resolved versions. Do not claim an offline fixed rule list is current coverage.
- [ ] **R13 — current plan state.** Link this current remediation ledger from the master plan with owner/base/status/next action; retain history as history.
- [ ] **R14 — integrated evidence.** Run targeted regressions, then a bounded integrated/full-suite strategy, release/source checks and isolated wheel/install smoke. Runtime acceptance requires candidate provenance and explicit production deployment ownership.
- [ ] Synchronize `docs/INSTALL_PROMPT.md` and `docs/UPDATE_PROMPT.md`, review the full diff, obtain a bounded semantic second opinion, and record real receipts/remaining limits.

## Execution ledger

- 2026-10-20: user authorized the plan and all audit repairs. Source baseline confirmed clean and unchanged. Hub adaptive context reproduced F13 (budget error), so exact source artifacts are authoritative. Optional token-economizer setup script is absent; no tools were installed and no native discovery bypass used.
- Ruling: recommendations are acceptance targets, not proof of defects. Recheck facts before choosing implementation; record false-positive or superseded claims with evidence instead of forcing code changes.
- Ruling: code, tests, documentation and isolated validation are authorized now. Production data deletion/conversion and release deployment remain separate concrete actions; do not pretend source verification proves them.

- Integrity gate: `tests/test_audit_remediation.py tests/test_agent_policy.py tests/test_async_jobs.py tests/test_external_tools.py tests/test_resource_backpressure.py`: **94 passed, 1 skipped**, req_3c9ff40876be, receipt rcpt_55de777dd0de. All 11 new integrity regressions passed after their observed failures.
- Ownership/protocol gate: `tests/test_agent_os_auto_integration.py tests/test_audit_protocol_remediation.py`: **46 passed**, req_30f623663fbe, receipt rcpt_9eafb91052aa. F01 root cause proved independently at both command and HTTP context boundaries; implicit repository-task adoption removed. F08/F10 passed their new cases; F11/F13 and remaining envelope cases still open.
- Ruling: review_diff req_3c9ff66879c0 was advisory with degraded counter-review. Its removed-public-symbol warning names a formerly nested `parse_v` implementation detail, not an exported API. Source and actual tests remain authoritative.

## Active continuation — 2026-10-20

- New lease: lease_0c321ac8fb97470ba982; baseline HEAD unchanged. Draft source hashes matched before applying all three patches.
- Prepared regressions reproduced failures before application. Context pointer identity, nested completeness and lock descriptor cleanup are now implemented.
- Public action guide failure was a missing declared output variant; fixed without disabling MCP output validation.
- Current combined audit regression cohort: 132 passed (req_8caaf7883b1b). Measured Windows/Python 3.13 branch baseline recorded and checked (req_39c6ccb87ae2, req_2d834cb4aa1c); no invented percentages.
- Bounded fresh named-source goldset: 7 cases passed (req_662e1f02473d). Scope is explicitly not whole-repository or semantic model-quality acceptance. A separate real local review made an unsupported claim; rejected after exact source review, retained as advisory evidence.
- Weekly/tag full Windows CI, critical coverage job, hash-pinned release build tools, resolved inventory/lock output and fail-closed current advisory assessment added. Hosted execution, installed candidate UI and final full suite remain pending.
- F02 historical record declares Hub repository identity; present evidence does not prove a current repository-selection bypass. Do not move/delete historical records based on their content.
- F09 numeric bool acceptance was confirmed; objects already returned 400. F12 respects diagnostic capture being disabled and explains unavailable recovery. These correct the stronger initial audit interpretations.
- Broader lint exposed pre-existing unused imports/locals and one shadowed stat binding; source-level cleanup included in this owned change. Final lint and integrated gates follow.
- This ledger supersedes the stale initial Next line and does not claim release, production cutover, GPU preemption or deployment.
