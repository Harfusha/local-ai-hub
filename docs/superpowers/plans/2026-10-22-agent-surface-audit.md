# Complete Agent Surface Audit Implementation Plan

> Execute inline with `superpowers:executing-plans`. The primary agent owns the audit; do not delegate inventory or review. Existing production integration and budget work retain their owners.

**Goal:** Review every public MCP action, HTTP route and response contract; retain necessary work, gate useful internal diagnostics through the existing dashboard toggle, and remove proven duplicates or dead public contracts.

**Architecture:** Reuse the authored operation registry and AST route inventory. Record an explicit disposition for every surface, with source/consumer justification and response policy. Enforce diagnostic access before execution as well as at the final JSON/MCP boundary. Preserve opaque user documents and actionable outcomes. A deterministic coverage check must reject missing or stale audit rows.

**Tech stack:** Python, AST, existing MCP/HTTP dispatch, pytest. No new dependencies, models or production restarts.

**Specification:** User request in chat 01a1645f-3e11-7680-a6c1-27f1567080e5, 2026-10-22. Initial shared output filter and its 285-test receipt are a baseline, not proof of this full audit.

## Ownership and constraints

- Goal active; Hub task `surface-audit-full-20261022`.
- Preserve the existing dirty `master` overlay. No reset, stash, bulk checkout, external checkout or silent installation.
- Existing integrator owns task-budget backend work and temporarily MCP/operation-registry wiring for that action. Do not overlap those writes.
- Do not mutate the source frozen for the integrator's pytest session 78461 before it stops.
- New diagnostic gates must preserve operational control, task/lease/session/repository identity, errors, evidence, pagination, user memory/configuration and compiler diagnostics.
- Static AST presence does not prove dispatch reachability, complete dynamic response schemas or runtime acceptance. Distinguish reject-only guards and stale declarations from registered public operations.

## Tasks

- [x] Establish source identity, owners and a complete authoritative inventory. Check generated schemas against actual MCP registration; resolve false positives in HTTP inventory and missing dynamic action enums.
- [x] Review each MCP action and HTTP route. Record retain/diagnostic/remove decisions with source or consumer justification; review response fields and opaque documents by operation family.
- [x] Add regression tests demonstrating ghost contracts, duplicate actions/routes, diagnostic preflight bypasses and excess response metadata.
- [x] Remove proven duplicates/dead public contracts from dispatch, schemas, clients and generated guidance. Keep distinct operations with concrete work/consumer justification.
- [x] Gate retained diagnostic operations before execution, including async submissions and alternate HTTP entry points. Keep status/cancel/control usable while detail is disabled.
- [x] Refine output projection with explicit field policies; preserve useful domain data and accurate final wire accounting. Do not silently mutate stored records.
- [x] Save the exhaustive disposition inventory and add a deterministic coverage check against current registries/response fields. New unreviewed surfaces must fail the check.
- [x] Synchronize install/update prompts and affected existing tests. (Verified via `python tools/sync_prompt_policies.py --check`; fresh 2026-10-27 surface audit suite passed 774/774 after removing ten obsolete MCP dispositions and updating the status selector to the brief-only contract).
- [x] Review final changes, checkpoint actual evidence, release owned leases and mark the goal complete. (Fresh `python tools/audit_agent_surface.py` returned success with no errors; both surface test files passed 774/774 in 128.04s. Earlier 744-test counts are historical.)

## Findings established before implementation

- The source MCP registration removed `local_ai_command`, but `generate_mcp_tool_schemas({})` still advertises it through the operation registry. This is a genuine incomplete removal.
- Repository `context_compile`, `verify_receipt` and `verify_completion` duplicate Agent OS coordination endpoints. Canonical ownership belongs to `local_ai_coord`.
- The old status action tuple/guide examples still describe removed status variants.
- The AST coverage inventory includes preflight/rejection-only paths and currently omits dynamic action enums for task/work tools. It cannot be used as an unqualified count of active endpoints.
- The initial diagnostic filter covers common fields and trace/log/timeline reads, but does not classify all diagnostic operations or prevent them from executing.

## Verification log

Current focused batch: `python -m pytest -q tests/test_surface_audit_policy.py tests/test_command_guidance_removed.py tests/test_agent_diagnostic_surface.py --tb=short`: 85 passed, 1 failed. Failure is the mandatory exhaustive-disposition gate, deliberately unresolved while the audit remains incomplete. Earlier 285 PASS predates this audit.

Implemented: HTTP diagnostic preflight including retained async/artifact reads; lightweight status; seven retired HTTP aliases; MCP preflight before diagnostic execution including batch/pipeline/submit; removal of repo context_compile/verify_receipt/verify_completion; stale status fields/scope and guide hint; command generator residuals; equal pagination aliases removed; response-budget internal before-size hidden outside detail.

Inventory tool now reads current source registry (185 MCP actions, 171 POST labels and 65 GET candidates including rejection-only boundaries). `docs/agent-surface-audit.json` is explicitly an UNREVIEWED draft. Do not interpret inventory coverage as completed semantic review or production acceptance. Remaining: examine every response producer/consumer, classify all operations, verify GET reachability/dynamic routes and response fields, scrutinize aggregate telemetry exception and semantic output fields, update affected clients/tests/prompts, complete regression batch and actual diff review. No global suite/restart/install from this chat.

Hub review_diff and second_opinion currently return operational_mode_blocked (gaming), retryable=true; do not poll or silently change operator mode. Native source/test scope follows the current command-removal policy. Existing integrator owns task budget backend, command owner owns commands.py cleanup after owner confirmation. MCP and operation registry have returned to this audit under lease_793a5483b9224e969d6e. Preserve all dirty work.

`nExpanded related batch: 193 passed, 20 failed. Failures include missing exhaustive audit dispositions, stale removed-command tests, diagnostics-off routing/evaluation expectations, and repo phase-contract failures requiring diagnosis. Do not call this candidate passing or ready. Goal service currently reports status blocked (get_goal); no completion claim.

## Resumed with explicit operator authorization

User authorized native work while keeping gaming mode enabled. Goal is active again. Hub leases/review remain gaming-blocked; maintain the existing disjoint writer roster in this plan, without retries or changing live mode. Integrator and command owner were notified. commands.py/services.py belong to command owner; task budget backend belongs to integrator; audit owns its existing HTTP/MCP/policy/manifest/test scope.

Fixed a real forwarding regression: removing receipt from _local_ai_repo_impl had left the public wrapper positional call shifted. Removed receipt from wrapper signature and forwarding, restoring phase/task/session positions. test_mcp_agent_routing.py now removes retired command expectations, explicitly isolates operational mode and debug settings rather than inheriting the live installed state. All 65 routing tests passed (6.14s). The focused earlier policy batch passed 85 with only unfinished exhaustive inventory failing; do not infer complete audit acceptance.

Next: classify the 421 source inventory candidates with real consumers and response policies (currently all unreviewed); improve inventory reachability/field coverage; examine aggregate-report exception and live event/provenance paths; real-store artifact kind test; sync prompts/clients; final related combined batch and diff review. Do not mark goal complete until these remain resolved.

## Current source audit and remaining acceptance (2026-10-23)

Source dispositions now cover 425 operations: 185 MCP actions, 171 POST route labels, 67 GET operations including dynamic swarm and distinct trace detail/metrics, and 2 browser OPTIONS boundaries. Each row has role/reason/response policy and a source-contract snapshot (MCP declared output fields, HTTP literal output fields, response producers and action-selector literals). Dynamic producer domain payloads remain governed by their producer contracts; this is not a closed JSON-schema claim. The gate rejects unreviewed/new/stale rows and changed snapshots. Common field policy distinguishes work evidence, caller-owned documents, diagnostic observations, private accounting, status internals and aggregate metrics.

Additional source fixes from final static review: verification completion is preserved as work evidence; normalized HTTP async submit/job-action spellings cannot evade diagnostics; aggregate reports lost their blanket filter exemption; SSE replay/live frames apply the same wire projection without mutating stored events. Current guide examples now point to brief readiness, not removed status guide. Public command cleanup source belongs to its original owner; internal broker run/discover/patch paths were preserved.

Known completed checks on earlier source candidates: 58 audit policy tests, 65 routing tests; integrator file-only checks HTTP status 4/4, readiness output 3/3, lease 1/1. Operation contracts were 63 pass/1 root-fixture fail; fixture now corrected to the preexisting canonical allowed-root/schema semantics with a new missing-root HTTP rejection regression. These are not final candidate receipts. Larger 943-case run exited 1; later six-file run timed out and was not passed. No timeout increases, skips or xfails were added.

Current CPU owner is the integrator (01a15f47-a804-7290-8d3b-f55b82fbb4b0), sole Git writer. Source/test validation is pending its bounded file-level runs and final combined candidate verification. The integrator temporarily owns only budget-increase transport subsections in operation_contracts.py, mcp_server.py and http_server.py; this audit must review that new action and refresh its explicit disposition after handback, before final freeze. Do not mark the audit goal complete while any required tests or this handback are outstanding. No production restart/install, GPU use or gaming-mode transition is part of this audit.

## Final validation continuation

Current source inventory is 426 operations after the handed-back owner-admin budget control. INSTALL/UPDATE and routing wording are synchronized; API source is frozen. Native receipts directly inspected: integration-cohort-c1c8cca0c7f3 (164 passed, exit 0, sources_unchanged true, all 13 watched hashes match current files) and integration-cohort-f1e4bfe85e10 log (43 budget transport tests passed). Integrator reports manifest gate and 72 contract/status/lease checks passing, plus 581 inventory metadata checks with exact collection coverage; remaining structural groups run sequentially under its exclusive CPU ownership.

Five additional stale status/guide test files have been migrated without API changes: test_audit_action_guide_remediation.py, test_mcp_full_status_identity.py, test_status_telemetry_wire.py, unit/test_guide_cards_status.py and unit/test_mcp_status_canonical_dispatch.py. Readiness identity and wire budgeting remain exercised; aggregate telemetry metric types now use the actual HTTP _send boundary; removed guide/cache/full actions reject before backend access. Await their fresh test results.

Completion review corrected two factual dispositions: GET /api/preprocess is an index-status reader and GET /api/models/manage an installed-model reader; neither is a 405 boundary. The suspected phantom GET timeline was DISPROVED by the actual dispatcher at http_server.py:4607. Its missing facts came from an extractor bug: an empty preflight comparison overwrote an earlier real GET body. The temporary GET removal was fully reverted; HTTP server and diagnostic-policy bytes match their prior frozen hashes (80b9f888... and 989bbe99...). The extractor now merges GET facts and captures response page/return producers. Regression coverage verifies the actual timeline GET is 409 without detail/no backend read and 200 with detail/page data; a separate regression requires its producer and success field in inventory. All 426 operations remain, with two corrected reader dispositions. No needed API was removed. Integrator has the final freeze and the narrow readiness hub_online test assertion correction. Do not mark complete, restart CPU validation in parallel, enlarge timeouts or introduce skips.
