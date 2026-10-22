# Existing Task Budget Increase Implementation Plan

> **For agentic workers:** Use this plan in the existing `audit-remediation-20261020` task; do not create a replacement task or reset counters.

**Goal:** Add a public, owner-authorized action to increase limits on an existing task while preserving usage counters and recording an auditable change.

**Architecture:** `PolicyEngine` performs an atomic persisted limit-only update and writes an audit row in the same transaction. The coordination action resolves the existing task, verifies its recorded owner and repository scope, then invokes the policy operation; missing task or identity fails closed.

**Tech Stack:** Python 3.11+, SQLite, Local AI MCP coordination contract, pytest.

**Spec:** User request in the active `audit-remediation-20261020` task and current `AGENTS.md` single-owner/task-scope rules.

## Global Constraints

- Update only existing task budgets; only increase limits.
- Preserve all `used_*` counters exactly.
- Require task owner, nonempty reason, and an audit row containing before/after limits, preserved usage, actor, and timestamp.
- Use public Hub action; never modify SQLite directly or bypass the broker.
- Preserve current dirty files, data, configuration, and release/security gates.
- No deployment or restart without a fresh candidate-bound reason and authorization.

## Review Focus

- Missing task or owner identity rejects before mutation.
- Non-owner and mismatched repository scope reject before mutation.
- Equal/decreased limits reject; omitted limits remain unchanged.
- Malformed values, NaN, infinity, booleans, or empty reason reject.
- Audit failure rolls back the budget update; usage counters remain unchanged on success.

---

### Task 1: Persisted budget update and authorization

**Files:** `src/local_ai_hub/agent_policy.py`, `src/local_ai_hub/commands.py`, `tests/test_agent_task_budget_increase.py`.

**Interfaces:** Add an increase-only `PolicyEngine` operation with explicit `actor`, `reason`, and proposed limits. `CommandBroker` checks the existing task's recorded owner and root before calling it.

- [ ] Add failing tests for preserved counters, strict increase-only validation, owner mismatch, and atomic audit persistence.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement transactional audit plus task-owner enforcement.
- [ ] Run focused tests and confirm pass.

### Task 2: Public coordination action

**Files:** `src/local_ai_hub/operation_contracts.py`, `src/local_ai_hub/mcp_server.py`, task API dispatch in `src/local_ai_hub/http_server.py` or its registered service, prompt files.

**Interfaces:** Add canonical `task_budget_increase` carrying `task_id`, explicit owner, reason, and proposed limits; route only through the registered server service and existing broker.

- [ ] Add failing contract and dispatch tests.
- [ ] Wait for the active API-surface audit owner to release overlapping files.
- [ ] Add action schema, strict argument validation, server dispatch, and prompt guidance.
- [ ] Verify missing owner/task, malformed limits, and successful limit increase behavior.

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
