# Agent Operating System design

## Status

Approved architectural direction. This document defines the target system and
implementation constraints. It does not authorize implementation by itself.

## Objective

Make Local AI Hub a reliable, efficient operating layer for coding agents.
The system must preserve useful work across interruptions, prevent repeated
failures and duplicate work, produce evidence-backed completion, and improve
routing only through measured, governed promotion.

Priority order is:

1. Correctness.
2. Safety.
3. User intent.
4. Reproducibility.
5. Latency.
6. Cost.

## Architecture boundary

Add a dedicated durable `agent_state.sqlite3` under configured
`server.state_dir`. It uses selective event sourcing for agent operating state
only. Existing caches, indexes, telemetry, artifacts, evidence, async jobs,
recovery journal, leases, and `WorkspaceMemoryStore` remain separate stores
with their current ownership and disposal rules.

The public MCP surface remains seven tools. New capabilities are exposed as
bounded actions on the existing `local_ai_coord`, `local_ai_repo`,
`local_ai_task`, and status projections where that saves schema and context.
No new broad orchestration tool is introduced.

```text
agent lifecycle events
        |
        v
immutable agent event journal -----> audit / export / replay
        |
        +---- transactionally maintained projections
                    |
                    +-- tasks and checkpoints
                    +-- memory and decisions
                    +-- incidents and negative knowledge
                    +-- verification and outcomes
                    +-- capability, budget, and policy state
```

## Core invariants

- Every durable event has a schema version, immutable ID, correlation ID,
  actor, timestamp, scope, idempotency key, and provenance links.
- A repeated request is idempotent. Concurrent writers use optimistic
  concurrency and explicit conflict results.
- Completion is impossible without fresh evidence for all acceptance criteria.
- A stale, contradictory, low-confidence, or unsafe record is quarantined or
  rejected, never silently promoted.
- No durable state stores secrets, raw prompts, source text, model responses,
  or hidden reasoning.
- Self-improvement can propose and evaluate a change. It never promotes an
  unverified change autonomously.
- All waits, retries, background work, and cleanup have bounded lifetime.

## Identity and scope

Scopes inherit in this order:

```text
global -> repository family -> clone/environment -> worktree/branch -> task -> session
```

The most specific valid record wins. Conflicts resolve by explicit override,
evidence quality, calibrated confidence, and freshness; they never resolve by
last-write-wins alone. A record may be promoted only through its configured
approval gate.

Repository-family identity is stable across path moves and avoids writing to a
user repository. No-remote repositories receive a local stable identity.
Clone and environment facts remain isolated from shared repository facts.

## Task lifecycle

Task states are `draft`, `planned`, `active`, `verifying`, `completed`,
`waiting`, `blocked`, `failed`, `cancelled`, and `abandoned`.

Every transition is an immutable event with reason and actor. `active` work
holds owner and lease data. `waiting` and `blocked` retain a resumable
checkpoint, dependency, and next owner. An expired heartbeat creates
`abandoned` plus a resumable checkpoint; it never deletes work.

Every task starts with a goal contract: goal, scope, non-goals, constraints,
risk profile, SLO profile, and acceptance criteria. `completed` requires a
fresh verification projection that proves every criterion.

## Durable projections

### Work journal

Records goal, plan, current phase, owner, lease, checkpoints, blockers, next
action, affected paths, evidence IDs, and command/job references. It enables
resume and structured handoff without rediscovery.

### Memory and decision ledger

Record kinds include fact, decision, convention, gotcha, hypothesis,
assumption, playbook, capability observation, and environment capsule. Every
record includes scope, provenance, confidence, freshness, sensitivity,
retention, and links to contradictions or superseding records.

Automatic writes are limited to task checkpoints, structured redacted incident
and tool outcomes, and deterministic verified facts within allowed scope.
Model conclusions are candidates. Repository conventions and decisions require
explicit agent or user confirmation. Global records always require user
approval.

### Incident and negative-knowledge ledger

An incident stores normalized error signature, operation class, redacted
environment and revision context, attempts, evidence, root cause when known,
verified resolution, confidence, and expiry. Negative knowledge suppresses a
repeated attempt until relevant state changes. Failure classification decides
whether a policy-limited retry is safe, a verified fix applies, or work stops.

### Verification and outcome ledger

Links acceptance criteria, change intent, affected files or symbols, impact,
validation selection, fresh evidence, result, and outcome. User feedback,
reverts, later corrections, and regressions are explicit outcome signals;
silence is not success evidence.

## Context, knowledge, and routing

The context compiler builds the smallest current context from task profile,
scoped memory, decisions, assumptions, evidence, repository state, and changed
paths. It has a hard token budget, deduplicates content, and records why each
context element was included.

The knowledge graph relates task, file, symbol, test, dependency, incident,
decision, and evidence. Repository changes invalidate only dependent records.

The capability registry declares preconditions, side effects, permission class,
latency, cost, reliability, and verification requirements. The router uses
task SLOs, risk, budget, and observed performance. It follows cheapest
sufficient escalation:

```text
cache/deterministic -> index/exact evidence -> semantic/graph ->
bounded local reasoning -> bounded peer work
```

It reuses cached and coalesced work, never fans out overlapping retrieval, and
stops once evidence and calibrated confidence meet the task profile. Existing
scheduler and command broker retain ownership of admission, cancellation, and
bounded execution.

## Verification, tests, and changes

Every change set links its goal, decision, evidence, expected impact, and
rollback procedure. Test intelligence selects validation from current impact,
test history, cost, and flake history. It can classify a flaky failure but
cannot manufacture a passing result. A validation receipt is evidence for the
completion gate, not merely a log line.

## Security and permissions

Every requested action declares target and side effects before execution.
Capability grants are explicit, task-scoped, least-privilege, and time-bounded.
Delegated agents receive only a strict subset and cannot self-escalate.

Read-only checks may use narrow policy grants. Writes, network activity, Git
mutation, secrets, system configuration, and privilege changes require precise
approval under existing policy. Actions stay sandboxed and bounded. A redacted
receipt captures outcome and evidence references.

## Governed self-improvement

Learning input consists only of redacted metadata and explicit outcomes.
Candidate routes, rules, and playbooks are versioned and isolated. Promotion
pipeline:

```text
candidate -> offline replay -> shadow -> bounded canary -> human approval ->
promoted version -> SLO monitoring -> automatic rollback on declared regression
```

Replay, shadow, and canary results must compare quality, safety,
reproducibility, latency, and cost against a known baseline. Promotion and
rollback retain audit evidence. The system does not alter policy based only on
aggregate telemetry.

## Operator controls and data lifecycle

Provide an operator control plane to inspect, edit, approve, reject,
quarantine, export, delete, and explain durable state. It exposes task status,
incidents, candidate improvements, retained data, and current policy version.

Durable agent state has backups, restore, schema migrations, integrity checks,
bounded compaction, quotas, retention, selective signed import/export, and
orphan cleanup. Retention is type- and scope-specific. Existing derived cache
data keeps its disposable behavior.

## Integration constraints

- Preserve compact seven-tool MCP surface.
- Reuse evidence IDs, artifact slices, command receipts, async job IDs,
  recovery journal IDs, and lease IDs rather than copying payloads.
- Preserve metadata-only telemetry rules.
- Keep loopback-first security and fail-soft optional backends.
- Do not store full project paths in observability telemetry.
- Do not turn ephemeral coordination memos into hidden long-term memory.
- Route repository facts through deterministic and indexed layers before any
  semantic or model operation.

## Delivery order

1. Event core, identities, migrations, retention, and operator primitives.
2. Task journal, goal contracts, checkpoint/resume, leases, and handoff.
3. Verification/outcome ledger, incident ledger, negative knowledge, and
   test intelligence.
4. Scoped memory, decisions, assumptions, promotion, and quality controls.
5. Context compiler, knowledge graph, capability registry, and budget router.
6. Replay, shadow, canary, governed promotion, and rollback.
7. Operator UI, import/export, backup/restore, and resilience testing.

Every phase ships behind a feature flag with schema migration tests, restart
recovery tests, idempotency/concurrency tests, privacy tests, and fault
injection. No phase depends on unbounded model inference.

## Explicit non-goals

- Hidden conversation logging or secret retention.
- Autonomous permission escalation.
- Autonomous promotion of learned behavior.
- Replacing existing repository caches, evidence stores, scheduler, command
  broker, or recovery journal.
- Embedding every external service into Hub instead of brokering capabilities.
