# Existing Task Budget Increase Implementation Plan

> **For agentic workers:** Use this plan in the existing `audit-remediation-20261020` task; do not create a replacement task or reset counters.

**Goal:** Provide a public action for all ordinarily write-authorized callers to increase limits on an existing task while preserving usage counters and recording an auditable change. The operator explicitly removed the special owner/admin-token requirement on 2026-10-23.

**Architecture:** `PolicyEngine` performs an atomic persisted limit-only update and writes an audit row in the same transaction. The coordination action resolves the existing task, verifies its recorded owner and repository scope, then invokes the policy operation; missing task or identity fails closed.

**Tech Stack:** Python 3.11+, SQLite, Local AI MCP coordination contract, pytest.

**Spec:** User request in the active `audit-remediation-20261020` task and current `AGENTS.md` single-owner/task-scope rules.

## Global Constraints

- Update only existing task budgets; only increase limits.
- Preserve all `used_*` counters exactly.
- Preserve the persisted task owner, require a nonempty reason, and write an audit row containing before/after limits, preserved usage, actual transport actor, and timestamp.
- Use public Hub action; never modify SQLite directly or bypass the broker.
- Preserve current dirty files, data, configuration, and release/security gates.
- No deployment or restart without a fresh candidate-bound reason and authorization.

## Review Focus

- Missing task or owner identity rejects before mutation.
- Caller-supplied owner/actor overrides and mismatched repository scope reject before mutation. Ordinary loopback/write callers are permitted; no special owner credential is required.
- Equal/decreased limits reject; omitted limits remain unchanged.
- Malformed values, NaN, infinity, booleans, or empty reason reject.
- Audit failure rolls back the budget update; usage counters remain unchanged on success.

## Current integration checkpoint, 2026-10-23

**Operator policy override, latest:** The human explicitly requested ordinary
access for all Hub clients instead of a special owner/admin credential. The
HTTP action now uses existing write authorization, including canonical loopback
access without a token. Broker/root checks, persisted owner consistency,
strictly increasing limits, unchanged usage/status/owner and atomic audit remain.
Earlier owner/admin requirements below describe superseded history. No API
credential or installation configuration was created or changed. Regression
cohorts `1c2efaa25533` (80), `248807fb3940` (44), `947db0a3f1e4` (21), and
`81a3ca31c88b` (64) all passed. Combined attempt `7ca13b68cfac` timed out and
remains retained; its identical command was not repeated. Current-source package,
activation and actual same-task increase/resume are separate acceptance gates.

Failed tasks can receive an authorized limit increase without resuming, changing
the recorded owner, or resetting usage. This avoids the watchdog race caused by
resuming an already exhausted task before raising its limits. The isolated
budget/receipt/policy cohort `cf3b6d779f8c` passed 76 tests; explicit root and
curation forwarding cohort `dc2e9907bed7` passed 20. Root, reason, authentication,
strict increase-only values, response preflight and atomic audit remain enforced.

The actual live attempt `req_fcd6f83c549a` requested 48,000 compute seconds and
750 external calls, but the running server returned terminal nonretryable 400
`unknown task action`. No limit was changed. Fresh task read `req_75466efe1c16`
still reports failed/watchdog. Last authoritative compute usage is 33,240.9 of
33,000 seconds; external-call usage is not freshly verified. Activate the exact
validated source before the next public increase, then resume the same task.
Do not write task storage directly or manufacture broker receipts.

Whole-candidate run `complete-shards-f5cf96429de9` watches 1,279 release inputs,
candidate `fdef5df7e481a80fba08959c481b4b4d0604983aba03d2394b3dbea1ac812bfb`.
Production acceptance remains open while that run and installed proof are pending.

---

### Task 1: Persisted budget update and authorization

**Files:** `src/local_ai_hub/agent_policy.py`, `src/local_ai_hub/commands.py`, `tests/test_agent_task_budget_increase.py`.

**Interfaces:** Add an increase-only `PolicyEngine` operation with explicit `actor`, `reason`, and proposed limits. `CommandBroker` checks the existing task's recorded owner and root before calling it.

- [x] Add failing tests for preserved counters, strict increase-only validation, owner mismatch, and atomic audit persistence.
- [x] Run focused tests and confirm expected failures.
- [x] Implement transactional audit plus task-owner enforcement.
- [x] Run focused tests and confirm pass.

### Task 2: Public coordination action

**Files:** `src/local_ai_hub/operation_contracts.py`, `src/local_ai_hub/mcp_server.py`, task API dispatch in `src/local_ai_hub/http_server.py` or its registered service, prompt files.

**Interfaces:** Canonical `task_budget_increase` carries `task_id`, explicit absolute root, reason, and proposed limits. The ordinary write-authorized broker resolves the recorded owner on the server; callers cannot substitute an owner. Canonical local access without a token is supported. Route only through the registered server service and existing broker.

- [x] Add failing contract and dispatch tests.
- [x] Wait for the active API-surface audit owner to release overlapping files.
- [x] Add action schema, strict argument validation, server dispatch, and prompt guidance.
- [x] Verify missing owner/task, malformed limits, and successful limit increase behavior.

### Task 3: Candidate validation and acceptance

**Files:** Current dirty candidate only.

- [ ] Review integrated diff and preserve every preexisting dirty change.
- [ ] Run full tests with a non-timeout command and record task-bound receipts.
- [ ] Verify fresh runtime identity for the exact candidate before production acceptance.
- [ ] Leave acceptance open if runtime identity or any criterion lacks fresh evidence.

## Backend source checkpoint, 2026-10-22

Implemented `PolicyEngine.increase_task_budget` and added
`tests/test_agent_task_budget_increase.py`. The backend rechecks persisted task
owner, live status and canonical v2 root inside the same BEGIN IMMEDIATE
transaction as the increase and existing AgentStateStore audit append. No new
audit table; missing task/budget, non-increases, malformed limits, corrupt budget
normalization and missing persistent audit fail closed. Cache updates only after
commit. The actor must be derived by the existing authenticated server task
boundary; it must never be accepted as payload authority.

Syntax-only AST parsing passed for both changed files. Behavioral tests have NOT
run; no passing-test claim. The live task's most recent event snapshot ends at
seq 122: failed/watchdog, reason TASK_BUDGET_EXCEEDED,
used_tokens=0/100000 and used_compute_seconds=33240.9/33000.0s. External-call
usage remains unverified. No production budget changes or counter resets made.

Pending: focused behavioral validation under the authorized accounting boundary,
server-bound actor proof and registered broker/HTTP/MCP wiring by their current
owner, then audited increase and stable resume of the same task. The prior plan's
explicit owner input is NOT authority: do not expose it as an authorization field.
No changes to commands.py, services.py, HTTP/MCP or operation_contracts in this
backend checkpoint. Gaming remains enabled. Audit/UI/command source is still in
motion; no full-suite or release acceptance claim.

## Focused behavioral evidence, 2026-10-23

The new 20-case backend suite completed with JUnit errors=0, failures=0,
skipped=0, time=3.092s in
`state/validation/budget-increase-unit-3a6232441ec1.xml`. This includes owner
changes read from persistent state and two-engine concurrency (one increase,
one rejection, one audit). The driver is no longer live. Its host generation
disappeared before the exit code was delivered: JUnit success is established,
process exit success is NOT established. Do not substitute this for transport
authorization, exact integrated candidate acceptance or a full regression run.

Earlier receipts are preserved: 032baad7be94 had an unclosed SQLite connection
in the test itself (18 assertions passed but exit=1); fixed with contextlib.closing.
91012ec5a369 had one invalid test call missing the required transition
idempotency key (19 passed/1 failed); test call fixed before the latest run.
No warning filters, budget gates, production task state or counters changed.

Public backend interface for future authenticated server wiring:
`increase_task_budget(task_id, *, actor, repo_root, reason, limits)` returning
`success`, `budget`, `before`, `audit_event_id`. Do NOT pass a payload-selected
actor, expose a direct policy bypass, or wire until transport authorization,
bounded response preflight and request-journal behavior are verified. Planned
next validation combines this suite with existing test_agent_policy.py under a
driver that persists command, source identities, timeout and process exit status.

## Related regression receipt and transport finding

`state/validation/budget-policy-regression-c3a0fb2e11b3.json` persists the actual
command, cwd, timestamps, source SHA-256 before/after and exit_code=0. Associated
JUnit/log record 31 passed in 15.02s across the new suite and test_agent_policy.py;
all five tracked source/test identities were unchanged. This supersedes the
missing exit-code evidence for focused backend validation only.

Transport inspection is still a blocker for public activation: current
http_server.Handler._agent() returns the caller-supplied X-LocalAI-Agent header
(or generic). _request_task validates lookup/repository access via
_task_matches_request; it does not itself establish an authenticated task-owner
principal. Therefore deriving the budget actor simply from _agent() is NOT a
proven owner-authentication mechanism. Do not wire this new storage method to that
header as authority. Existing installation authorization/capabilities need
explicit analysis before selecting a supported owner-authorized activation path.
No production limits were changed, no restart made, no full tests started.

## Owner-credential path established, 2026-10-23

Current Handler._authorized distinguishes verified credentials as api_token,
supervisor, action_token or unauthenticated local fallback. For this single-human
installation the existing global owner API token with explicit admin permission
is the appropriate owner authority; X-LocalAI-Agent is still NOT authority.
Public wiring must require _authorized(permission="admin") AND its verified
_authorization_actor == "api_token". Reject supervisor/scoped/local credentials
even if another route would accept them. Run this check before task root binding
or explicitly rebind afterwards: _authorized resets _authorization_root.

Task owner must be loaded by the server from the authorized existing task and
rechecked atomically by the backend; never derive it from credentials or a caller
owner/actor field. Authenticated installation owner authorizes the change, while
task owner remains a separate audit field. Existing admin authorization/result
audit helpers are available and fail closed on unavailable telemetry. Their
route/action registration and response preflight still need actual integration
and regression proof by the HTTP/MCP and broker owners.

Backend signature now additionally requires authorization_actor="api_token",
supplied exclusively from the verified server context. Audit event actor records
that credential kind and payload.task_owner retains the persisted task owner.
Five added regression cases reject supervisor/action_token/local/unrecognized
or empty authority. This is an internal storage precondition, NOT standalone
authentication of arbitrary Python callers, and must never be exposed as a
payload authorization field. Existing 31 PASS receipt predates these changes;
new related validation is pending. The guarded driver did not launch because
live Hub audit pytest PID40732 held the CPU window (identity confirmed).

## Validated backend increment

`state/validation/budget-owner-regression-d465cf5fea00.json` now establishes
exit_code=0 and unchanged tracked source/test identities before/after the run.
The two-file backend/policy regression suite completed with 36 passed in 10.43s,
including all five non-owner credential-kind rejections. Associated XML and log
are saved beside that JSON. No warning suppression or weakened checks.

This increment is suitable for a source commit of agent_policy.py, its dedicated
test module and this plan only. It does NOT activate an HTTP/MCP/broker action,
change the live task budget, repair public ownership authorization by itself,
or establish integrated runtime/release acceptance. Other owners' dirty changes
are excluded from this increment; their handoffs are requested separately.

## Broker integration in progress

Command/services owner released its source scope. Added a separate
CommandBroker.increase_task_budget administrative entry point: requires verified
api_token credential kind plus immutable admin permissions, loads task owner
from task storage and delegates to the atomic policy operation. Six broker cases
were added to the dedicated test module. No public endpoint active yet.

`state/validation/integration-cohort-e876e07a2b56.json` records this enlarged
42-case run reaching 100% item progress but failing to terminate within the
unchanged 60-second ceiling: exit=124. This is NOT a passing receipt. Diagnose
the new broker cases and teardown with stack capture instead of raising limits
or repeating the same whole invocation. Previously committed storage-only
36-case receipt remains valid only for its own earlier source identities.

API owner granted narrow source handoff for coord action/schema, MCP coord task
routing and the HTTP agent-state/tasks budget_increase branch. Other audit
filters remain frozen under that owner; after transport handback they will
update the new action's inventory disposition. HubClient.coord already forwards
generic task action kwargs unchanged, so no client source edit is needed.

## Broker diagnostic follow-up

Isolated six new broker cases: 6 PASS, exit=0, stable source identities in
`state/validation/integration-cohort-36532d55ac6b.json`.
The full backend+broker+existing policy combination subsequently completed with
42 PASS in 6.72s, exit=0 and unchanged sources, with timed traceback diagnostics
enabled: `state/validation/integration-cohort-a2d75a4379cf.json`. The earlier
timeout is not reproduced and its root cause remains unproven; do not erase it.
Its before/after difference was only docs/agent-surface-audit.json, not budget
or broker code. No larger timeout or warning suppression was used.

API owner additionally requested completion be retained in MCP verification
protected keys; the single literal was added to _VERIFY_PROTECTED_KEYS. Their
new roundtrip regression must be included in the subsequent public-policy
validation. This source edit is separate from the tested broker increment.

## Public transport source draft

Added canonical task_budget_increase coord action, strict nested budget schema,
budget field scoped only to that action, MCP forwarding and HTTP tasks
budget_increase branch. HTTP reauthorizes admin/api_token then rebinds root,
loads the existing authorized task and invokes APP.commands (the broker).
Caller owner/actor/extra fields reject. Existing gaming/security controls remain.
Policy mutation now checks the requested response envelope before budget/audit
writes, retaining explicit bounded-accounting headroom rather than enlarging
the caller budget. No production request used this new action yet.

`state/validation/integration-cohort-199cbba9279d.json` records 34 dedicated cases
passing in 7.82s, exit=0, unchanged source identities. New cases cover response
budget rejection before mutation/audit, public field scoping and canonical SDK
forwarding. Actual HTTP owner-token/permission/root branches and MCP full-result
retention still need behavioral proof. Do not activate or claim transport ready
from schema/syntax or storage-only tests. Prompt sync and new action manifest
disposition remain pending under the API owner's handback coordination.

## Transport unit handback

Actual Handler._task_budget_increase is now an internal extracted handler called
by the unchanged /api/agent-state/tasks budget_increase dispatcher branch. Unit
tests exercise its real _authorized and root allowlist/task-scope checks against
temporary durable stores: valid owner admin, wrong token, missing admin,
supervisor, unauthenticated loopback fallback, caller owner, missing root and
unauthorized root. Only the project's coordination-ID resolver is isolated.
No socket server or production state was used. MCP roundtrip tests verify the
canonical forwarded payload and retention of budget, before and audit_event_id.

`state/validation/integration-cohort-f1e4bfe85e10.json`: 43 passed in 19.36s,
exit_code=0, watched source/test identities unchanged. This is transport unit
evidence, NOT fresh installed/runtime proof or actual production budget increase.
The HTTP/MCP/operation registry narrow scope is handed back to the audit owner
for explicit new-action disposition and prompt synchronization before the
combined validation/final source freeze. Existing gaming guards remain unchanged.
