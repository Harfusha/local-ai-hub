# Agent Operating System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable, evidence-backed operating state for agents while preserving Local AI Hub's compact MCP surface and deterministic-first behavior.

**Architecture:** Add a selective event-sourced `agent_state.sqlite3` under `server.state_dir`. Focused stores project immutable events into tasks, scoped knowledge, incidents, verification, policy, and evaluation state. Existing cache, evidence, commands, async jobs, recovery journal, telemetry, leases, and workspace memos remain separate and are linked only by stable IDs.

**Tech Stack:** Python 3.11+, SQLite/WAL, existing `sqlite_support.py`, HTTP server, MCP server, dashboard, pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-agent-operating-system-design.md`

## Global Constraints

- Keep the seven-tool MCP surface compact; add bounded actions to existing tools instead of a new broad tool.
- Store all new runtime state beneath configured `server.state_dir`.
- Use `connect_sqlite`, `initialize_wal`, and bounded busy handling from `sqlite_support.py`.
- Store no secrets, raw prompts, source text, model responses, hidden reasoning, or full project paths in telemetry.
- Keep all waits, retries, cleanup, and subprocesses bounded.
- Use deterministic and indexed evidence before semantic retrieval or generation.
- Preserve loopback-first security, fail-soft optional backends, and existing cache/derived-state disposal semantics.
- Ship each delivery behind an explicit feature flag that defaults off until its focused tests pass.
- Make user approval mandatory for global-memory promotion and learned-policy promotion.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/local_ai_hub/agent_events.py` | Immutable event schema, idempotent append, snapshots, schema migrations, event export. |
| `src/local_ai_hub/agent_identity.py` | Repository-family identity, scope hierarchy, scope resolution, environment capsule sanitization. |
| `src/local_ai_hub/agent_tasks.py` | Goal contracts, task-state projection, checkpoint/resume, ownership, heartbeat and handoff. |
| `src/local_ai_hub/agent_memory.py` | Scoped records, decisions, assumptions, promotion, conflict/quarantine and retention. |
| `src/local_ai_hub/agent_incidents.py` | Error normalization, incident projection, negative knowledge and safe retry decisions. |
| `src/local_ai_hub/agent_verification.py` | Acceptance criteria, verification receipts, outcomes, change provenance and completion gate. |
| `src/local_ai_hub/agent_policy.py` | Capability metadata, risk classification, grants, budget/SLO admission and action receipts. |
| `src/local_ai_hub/agent_context.py` | Token-bounded context compilation, provenance and dependency-aware invalidation. |
| `src/local_ai_hub/agent_learning.py` | Candidate change lifecycle, replay/shadow/canary records, approval, monitoring and rollback. |
| `src/local_ai_hub/app.py` | Compose stores, start bounded maintenance, expose compact status and bundle hooks. |
| `src/local_ai_hub/services.py` | Connect repository/command/model outcomes to agent-state receipts and context. |
| `src/local_ai_hub/http_server.py` | Authenticated bounded API handlers for agent-state actions. |
| `src/local_ai_hub/mcp_server.py` | Add compact `local_ai_coord`, `local_ai_repo`, `local_ai_task`, and status action projections. |
| `src/local_ai_hub/dashboard.py` | Operator views for tasks, incidents, candidates, state health and retention. |
| `defaults.toml`, `docs/CONFIGURATION.md` | Feature flags, retention, quotas and SLO defaults. |
| `docs/MCP_AND_AGENTS.md`, `docs/OPERATIONS.md`, `FEATURES.md` | Agent contract, operator actions and supported capability documentation. |
| `tests/test_agent_*.py` | Focused deterministic unit, migration, restart, concurrency, privacy and transport tests. |

---

### Task 1: Event Core and State Database

**Files:**

- Create: `src/local_ai_hub/agent_events.py`
- Modify: `src/local_ai_hub/app.py`
- Modify: `defaults.toml`
- Create: `tests/test_agent_events.py`

**Interfaces:**

- Produces `AgentEvent`, `AppendResult`, `AgentStateStore`.
- `AgentStateStore.append(event: AgentEvent) -> AppendResult` is idempotent on `(stream_id, idempotency_key)`.
- `AgentStateStore.events(stream_id: str, after_seq: int = 0) -> list[AgentEvent]` returns sequence order.
- `AgentStateStore.snapshot(stream_id: str, state: dict[str, object]) -> int` writes a compacted projection checkpoint.

- [ ] **Step 1: Write failing idempotency and ordering tests.**

```python
def test_append_returns_existing_sequence_for_same_idempotency_key(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    event = AgentEvent.create("task-1", "task.created", {"title": "index"}, "key-1")
    assert store.append(event).seq == 1
    assert store.append(event).duplicate is True
    assert store.events("task-1") == [event.with_seq(1)]

def test_events_are_ordered_per_stream(tmp_path):
    store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store.append(AgentEvent.create("task-1", "task.created", {}, "one"))
    store.append(AgentEvent.create("task-1", "task.planned", {}, "two"))
    assert [event.seq for event in store.events("task-1")] == [1, 2]
```

- [ ] **Step 2: Run the focused test and verify the import fails.**

Run: `python -m pytest -q tests/test_agent_events.py`

Expected: FAIL because `local_ai_hub.agent_events` does not exist.

- [ ] **Step 3: Implement immutable event types and SQLite schema.**

```python
@dataclass(frozen=True)
class AgentEvent:
    event_id: str
    stream_id: str
    kind: str
    payload: Mapping[str, JSONValue]
    idempotency_key: str
    correlation_id: str
    actor: str
    schema_version: int
    created_at: float
    seq: int | None = None

class AgentStateStore:
    def append(self, event: AgentEvent) -> AppendResult:
        raise NotImplementedError

    def events(self, stream_id: str, after_seq: int = 0) -> list[AgentEvent]:
        raise NotImplementedError

    def snapshot(self, stream_id: str, state: Mapping[str, JSONValue]) -> int:
        raise NotImplementedError
```

Create `agent_events`, `agent_snapshots`, and `agent_schema_migrations` tables.
Use `BEGIN IMMEDIATE` only for append/snapshot transaction boundaries. Enforce
unique `(stream_id, idempotency_key)`, monotonic sequence per stream, bounded
payload size, JSON serialization, and schema-version migration records.

- [ ] **Step 4: Add feature-flag construction in `LocalAIApp`.**

```python
self.agent_state = AgentStateStore(
    self.config.server.state_dir / "agent_state.sqlite3",
    enabled=self.config.agent_state.enabled,
)
```

Keep construction inert when `agent_state.enabled = false`. Add default flag,
event retention days, maximum payload bytes, snapshot interval, and cleanup
batch size to `defaults.toml`.

- [ ] **Step 5: Run focused tests.**

Run: `python -m pytest -q tests/test_agent_events.py`

Expected: PASS.

- [ ] **Step 6: Commit the independently working event core.**

```bash
git add src/local_ai_hub/agent_events.py src/local_ai_hub/app.py defaults.toml tests/test_agent_events.py
git commit -m "feat: add durable agent event core"
```

### Task 2: Identity, Scope, and Sanitized Environment Capsules

**Files:**

- Create: `src/local_ai_hub/agent_identity.py`
- Modify: `src/local_ai_hub/agent_events.py`
- Create: `tests/test_agent_identity.py`

**Interfaces:**

- Consumes `AgentStateStore` from Task 1.
- Produces `AgentScope`, `RepositoryIdentity`, `ScopeResolver`.
- `ScopeResolver.resolve(records: Iterable[ScopedRecord], context: ScopeContext) -> list[ScopedRecord]` returns valid records by specificity, evidence, confidence and freshness.

- [ ] **Step 1: Write scope-precedence and path-redaction tests.**

```python
def test_more_specific_scope_wins_without_last_write_wins():
    resolver = ScopeResolver()
    chosen = resolver.resolve(records=[global_record(), branch_record()], context=branch_context())
    assert chosen[0].scope == AgentScope.BRANCH

def test_environment_capsule_drops_paths_and_secret_like_keys():
    capsule = EnvironmentCapsule.from_mapping({"PATH": "C:/secret", "TOKEN": "x", "python": "3.11"})
    assert capsule.values == {"python": "3.11"}
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `python -m pytest -q tests/test_agent_identity.py`

Expected: FAIL because identity types do not exist.

- [ ] **Step 3: Implement stable identities and resolver.**

Define scopes `GLOBAL`, `REPOSITORY`, `CLONE`, `WORKTREE`, `BRANCH`, `TASK`,
and `SESSION`. Derive repository-family identity from normalized remote identity
when available; otherwise create a local opaque ID held only in state storage.
Never persist an absolute workspace path in telemetry. Keep clone and
environment metadata local to their scope.

- [ ] **Step 4: Run focused tests.**

Run: `python -m pytest -q tests/test_agent_identity.py`

Expected: PASS.

- [ ] **Step 5: Commit identity support.**

```bash
git add src/local_ai_hub/agent_identity.py src/local_ai_hub/agent_events.py tests/test_agent_identity.py
git commit -m "feat: add scoped agent identities"
```

### Task 3: Goal Contracts, Work Journal, and Resume

**Files:**

- Create: `src/local_ai_hub/agent_tasks.py`
- Modify: `src/local_ai_hub/app.py`
- Modify: `src/local_ai_hub/http_server.py`
- Create: `tests/test_agent_tasks.py`

**Interfaces:**

- Consumes `AgentStateStore`, `RepositoryIdentity`, and `ScopeResolver`.
- Produces `GoalContract`, `TaskState`, `TaskStore`.
- `TaskStore.create(contract: GoalContract, context: ScopeContext) -> TaskState`.
- `TaskStore.transition(task_id: str, target: TaskStatus, *, reason: str, actor: str, idempotency_key: str) -> TaskState`.
- `TaskStore.checkpoint(task_id: str, checkpoint: TaskCheckpoint) -> TaskState`.

- [ ] **Step 1: Write failing lifecycle and heartbeat tests.**

```python
def test_completed_requires_all_criteria_to_have_fresh_receipts(store):
    task = store.create(contract_with_criteria("tests", "review"), task_context())
    store.transition(task.task_id, TaskStatus.VERIFYING, reason="ready", actor="agent", idempotency_key="v")
    with pytest.raises(CompletionGateError):
        store.transition(task.task_id, TaskStatus.COMPLETED, reason="claimed", actor="agent", idempotency_key="c")

def test_expired_active_task_becomes_abandoned_with_checkpoint(store):
    task = active_task_with_checkpoint(store)
    assert store.reap_expired_heartbeats(now=task.heartbeat_expires_at + 1) == [task.task_id]
    assert store.get(task.task_id).status is TaskStatus.ABANDONED
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `python -m pytest -q tests/test_agent_tasks.py`

Expected: FAIL because task store does not exist.

- [ ] **Step 3: Implement task projection and legal transitions.**

Implement statuses `draft`, `planned`, `active`, `verifying`, `completed`,
`waiting`, `blocked`, `failed`, `cancelled`, and `abandoned`. Persist goal,
scope, non-goals, constraints, acceptance criteria, SLO profile, owner, lease
reference, blockers, next owner, checkpoint, and evidence references as events
and projection rows. Reject invalid transitions with a structured non-retryable
error.

- [ ] **Step 4: Add bounded authenticated task endpoints.**

Add compact handlers below the existing HTTP agent-state namespace for create,
get, transition, checkpoint, resume, and list. Enforce request-size limits,
authorization, feature flag, task-scope validation, and idempotency key.

- [ ] **Step 5: Run focused tests.**

Run: `python -m pytest -q tests/test_agent_tasks.py`

Expected: PASS.

- [ ] **Step 6: Commit task lifecycle delivery.**

```bash
git add src/local_ai_hub/agent_tasks.py src/local_ai_hub/app.py src/local_ai_hub/http_server.py tests/test_agent_tasks.py
git commit -m "feat: add agent task journal and resume"
```

### Task 4: Scoped Memory, Decisions, Assumptions, and Promotion

**Files:**

- Create: `src/local_ai_hub/agent_memory.py`
- Modify: `src/local_ai_hub/agent_tasks.py`
- Modify: `src/local_ai_hub/http_server.py`
- Create: `tests/test_agent_memory.py`

**Interfaces:**

- Produces `MemoryRecord`, `MemoryKind`, `MemoryStore`, `PromotionRequest`.
- `MemoryStore.record(record: MemoryRecord, *, actor: str, idempotency_key: str) -> MemoryRecord`.
- `MemoryStore.promote(record_id: str, target_scope: AgentScope, *, approver: str) -> MemoryRecord`.
- `MemoryStore.quarantine(record_id: str, reason: str, *, actor: str) -> MemoryRecord`.

- [ ] **Step 1: Write failing automatic-write, approval, and conflict tests.**

```python
def test_model_conclusion_is_candidate_not_repository_memory(store):
    record = store.record(model_conclusion(scope=AgentScope.TASK), actor="agent", idempotency_key="m1")
    assert record.status is MemoryStatus.CANDIDATE

def test_global_promotion_requires_user_approval(store):
    record = confirmed_repository_record(store)
    with pytest.raises(ApprovalRequiredError):
        store.promote(record.record_id, AgentScope.GLOBAL, approver="agent")

def test_conflicting_high_confidence_records_are_quarantined(store):
    assert store.record(conflicting_record(), actor="user", idempotency_key="c").status is MemoryStatus.QUARANTINED
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `python -m pytest -q tests/test_agent_memory.py`

Expected: FAIL because memory store does not exist.

- [ ] **Step 3: Implement record projection and promotion policy.**

Support kinds `fact`, `decision`, `convention`, `gotcha`, `hypothesis`,
`assumption`, `playbook`, `capability_observation`, and `environment_capsule`.
Persist scope, provenance, confidence, freshness, sensitivity, retention,
supersession and contradiction links. Permit automatic task checkpoints,
structured redacted incidents, tool outcomes, and deterministic facts only.
Require explicit confirmation for repository decisions and user approval for
global promotion. Keep `WorkspaceMemoryStore` as TTL-only coordination memo
storage; do not repurpose it as hidden long-term memory.

- [ ] **Step 4: Run focused tests.**

Run: `python -m pytest -q tests/test_agent_memory.py`

Expected: PASS.

- [ ] **Step 5: Commit scoped knowledge delivery.**

```bash
git add src/local_ai_hub/agent_memory.py src/local_ai_hub/agent_tasks.py src/local_ai_hub/http_server.py tests/test_agent_memory.py
git commit -m "feat: add governed agent memory"
```

### Task 5: Incident Ledger, Negative Knowledge, and Retry Classification

**Files:**

- Create: `src/local_ai_hub/agent_incidents.py`
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/commands.py`
- Create: `tests/test_agent_incidents.py`

**Interfaces:**

- Produces `IncidentFingerprint`, `IncidentRecord`, `RetryDecision`, `IncidentStore`.
- `IncidentStore.capture(outcome: ToolOutcome) -> IncidentRecord | None` returns `None` for policy blocks and cancellations that are not operational incidents.
- `IncidentStore.retry_decision(fingerprint: IncidentFingerprint, state_revision: str) -> RetryDecision`.

- [ ] **Step 1: Write failing fingerprint and retry tests.**

```python
def test_same_error_signature_reuses_verified_fix_after_state_match(store):
    incident = store.capture(failed_command_outcome("locked database"))
    store.resolve(incident.incident_id, verified_fix="retry after busy backoff", confidence=0.95)
    assert store.retry_decision(incident.fingerprint, incident.state_revision).action == "apply_verified_fix"

def test_negative_knowledge_stops_repeat_until_state_changes(store):
    incident = store.capture(failed_command_outcome("invalid config"))
    assert store.retry_decision(incident.fingerprint, incident.state_revision).action == "stop"
    assert store.retry_decision(incident.fingerprint, "changed").action != "stop"
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `python -m pytest -q tests/test_agent_incidents.py`

Expected: FAIL because incident ledger does not exist.

- [ ] **Step 3: Implement normalized, redacted incident projection.**

Normalize error class, operation class, exit category, retryability, relevant
repository revision, and bounded redacted message fingerprint. Do not persist
raw command output. Record attempts, evidence IDs, root cause when confirmed,
verified fix, confidence, expiry and state revision. Integrate captures at
service and command outcome boundaries without changing existing command
single-flight semantics.

- [ ] **Step 4: Run focused tests.**

Run: `python -m pytest -q tests/test_agent_incidents.py`

Expected: PASS.

- [ ] **Step 5: Commit incident delivery.**

```bash
git add src/local_ai_hub/agent_incidents.py src/local_ai_hub/services.py src/local_ai_hub/commands.py tests/test_agent_incidents.py
git commit -m "feat: add agent incident ledger"
```

### Task 6: Verification, Outcomes, and Change Provenance

**Files:**

- Create: `src/local_ai_hub/agent_verification.py`
- Modify: `src/local_ai_hub/agent_tasks.py`
- Modify: `src/local_ai_hub/services.py`
- Create: `tests/test_agent_verification.py`

**Interfaces:**

- Produces `VerificationReceipt`, `ChangeIntent`, `OutcomeRecord`, `VerificationStore`.
- `VerificationStore.record(receipt: VerificationReceipt) -> VerificationReceipt`.
- `VerificationStore.completion(task_id: str, now: float) -> CompletionResult`.
- `VerificationStore.record_outcome(outcome: OutcomeRecord) -> OutcomeRecord`.

- [ ] **Step 1: Write failing freshness and feedback tests.**

```python
def test_stale_receipt_cannot_satisfy_completion(store):
    store.record(receipt_for("task-1", "tests", expires_at=10))
    assert store.completion("task-1", now=11).complete is False

def test_revert_is_explicit_negative_outcome(store):
    outcome = store.record_outcome(OutcomeRecord.reverted("change-1", actor="user"))
    assert outcome.kind == "reverted"
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `python -m pytest -q tests/test_agent_verification.py`

Expected: FAIL because verification store does not exist.

- [ ] **Step 3: Implement receipts and completion projection.**

Link each receipt to task, acceptance criterion, change intent, evidence ID,
command/job ID, repository revision, time observed, expiry, and result. Link
change intent to affected files or symbols, expected impact and rollback
description. Completion requires all declared criteria to have a passing,
fresh receipt at current task state. Record user acceptance, correction,
revert, regression and explicit rejection as outcomes; never infer success from
absence of feedback.

- [ ] **Step 4: Run focused tests.**

Run: `python -m pytest -q tests/test_agent_verification.py`

Expected: PASS.

- [ ] **Step 5: Commit verification delivery.**

```bash
git add src/local_ai_hub/agent_verification.py src/local_ai_hub/agent_tasks.py src/local_ai_hub/services.py tests/test_agent_verification.py
git commit -m "feat: add evidence-backed completion"
```

### Task 7: Capability Policy, Least-Privilege Grants, and Budgets

**Files:**

- Create: `src/local_ai_hub/agent_policy.py`
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/http_server.py`
- Modify: `defaults.toml`
- Create: `tests/test_agent_policy.py`

**Interfaces:**

- Produces `CapabilityDescriptor`, `RiskClass`, `CapabilityGrant`, `Budget`, `PolicyDecision`.
- `PolicyEngine.authorize(request: ActionRequest, task: TaskState) -> PolicyDecision`.
- `PolicyEngine.consume(task_id: str, cost: BudgetCost) -> Budget`.

- [ ] **Step 1: Write failing least-privilege tests.**

```python
def test_delegate_cannot_expand_parent_capabilities(engine):
    parent = grant(read_only_repository=True)
    child = engine.delegate(parent, requested={"network"})
    assert child.allowed == frozenset()

def test_write_request_requires_precise_grant(engine):
    decision = engine.authorize(write_action("src/app.py"), active_task())
    assert decision.requires_approval is True
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `python -m pytest -q tests/test_agent_policy.py`

Expected: FAIL because policy engine does not exist.

- [ ] **Step 3: Implement descriptors, grants, and receipts.**

Classify actions as read, write, network, Git mutation, secret access, system
configuration, or privilege change. Grants are explicit, task-scoped,
time-bounded and non-expandable. Attach time, token, compute and external-call
budgets to task SLO profiles. Emit redacted action receipts and structured
denials. Reuse existing command policy and sandbox controls rather than
creating a second command executor.

- [ ] **Step 4: Run focused tests.**

Run: `python -m pytest -q tests/test_agent_policy.py`

Expected: PASS.

- [ ] **Step 5: Commit policy delivery.**

```bash
git add src/local_ai_hub/agent_policy.py src/local_ai_hub/services.py src/local_ai_hub/http_server.py defaults.toml tests/test_agent_policy.py
git commit -m "feat: add agent capability policy"
```

### Task 8: Context Compiler and Dependency-Aware Knowledge Graph

**Files:**

- Create: `src/local_ai_hub/agent_context.py`
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/repo_state.py`
- Create: `tests/test_agent_context.py`

**Interfaces:**

- Produces `ContextRequest`, `ContextElement`, `CompiledContext`, `KnowledgeLink`.
- `ContextCompiler.compile(request: ContextRequest) -> CompiledContext`.
- `ContextCompiler.invalidate(changed_paths: Collection[str], revision: str) -> int`.

- [ ] **Step 1: Write failing token-budget and invalidation tests.**

```python
def test_compiler_prefers_fresh_task_evidence_within_budget(compiler):
    result = compiler.compile(ContextRequest(task_id="task-1", token_budget=80))
    assert result.estimated_tokens <= 80
    assert result.elements[0].source_kind == "verification_receipt"

def test_change_invalidates_only_linked_records(compiler):
    assert compiler.invalidate({"src/changed.py"}, "rev-2") == 1
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `python -m pytest -q tests/test_agent_context.py`

Expected: FAIL because context compiler does not exist.

- [ ] **Step 3: Implement bounded compilation and links.**

Rank scoped records by task relevance, specificity, evidence quality,
confidence and freshness. Add each element only when it fits the hard token
budget and record inclusion reason. Link tasks, files, symbols, tests,
dependencies, incidents, decisions and evidence by opaque IDs. Subscribe to
existing repository revision/dirty-path invalidation and invalidate linked
records without performing hidden broad scans.

- [ ] **Step 4: Run focused tests.**

Run: `python -m pytest -q tests/test_agent_context.py`

Expected: PASS.

- [ ] **Step 5: Commit context delivery.**

```bash
git add src/local_ai_hub/agent_context.py src/local_ai_hub/services.py src/local_ai_hub/repo_state.py tests/test_agent_context.py
git commit -m "feat: add bounded agent context compiler"
```

### Task 9: Tool Performance, Test Intelligence, and Cheapest-Sufficient Routing

**Files:**

- Create: `src/local_ai_hub/agent_routing.py`
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/telemetry.py`
- Create: `tests/test_agent_routing.py`

**Interfaces:**

- Produces `ToolObservation`, `RouteCandidate`, `RoutingDecision`, `TestSelection`.
- `RoutingEngine.select(request: RouteRequest) -> RoutingDecision`.
- `RoutingEngine.select_tests(change: ChangeIntent) -> TestSelection`.

- [ ] **Step 1: Write failing routing and flaky-test tests.**

```python
def test_router_uses_cached_evidence_before_model_candidate(engine):
    decision = engine.select(route_request(with_fresh_cache=True))
    assert decision.kind == "cache"

def test_known_flake_is_reported_but_not_converted_to_pass(engine):
    selection = engine.select_tests(change_with_flaky_test())
    assert selection.flaky_candidates == ("tests/test_network.py::test_retry",)
    assert selection.synthetic_passes == ()
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `python -m pytest -q tests/test_agent_routing.py`

Expected: FAIL because routing engine does not exist.

- [ ] **Step 3: Implement metadata-only observations and route selection.**

Record opaque task class, action class, cache/coalescing state, bounded latency,
cost counters, reliability outcome and revision. Enforce escalation order:
cache/deterministic, index/exact evidence, semantic/graph, bounded local
reasoning, then bounded peer work. Reuse existing scheduler and command broker.
Use current impact, test history and declared risk to select tests; mark flakes
as diagnostic information only.

- [ ] **Step 4: Run focused tests.**

Run: `python -m pytest -q tests/test_agent_routing.py`

Expected: PASS.

- [ ] **Step 5: Commit routing delivery.**

```bash
git add src/local_ai_hub/agent_routing.py src/local_ai_hub/services.py src/local_ai_hub/telemetry.py tests/test_agent_routing.py
git commit -m "feat: add evidence-aware agent routing"
```

### Task 10: Governed Learning, Replay, Canary, and Rollback

**Files:**

- Create: `src/local_ai_hub/agent_learning.py`
- Modify: `src/local_ai_hub/telemetry.py`
- Modify: `src/local_ai_hub/app.py`
- Create: `tests/test_agent_learning.py`

**Interfaces:**

- Produces `ImprovementCandidate`, `EvaluationRun`, `PromotionDecision`, `RollbackTrigger`.
- `LearningStore.create_candidate(candidate: ImprovementCandidate) -> ImprovementCandidate`.
- `LearningStore.promote(candidate_id: str, approver: str) -> PromotionDecision`.
- `LearningStore.observe(candidate_id: str, observation: SLOObservation) -> RollbackTrigger | None`.

- [ ] **Step 1: Write failing promotion and rollback tests.**

```python
def test_candidate_cannot_promote_without_approval(store):
    candidate = store.create_candidate(valid_candidate())
    with pytest.raises(ApprovalRequiredError):
        store.promote(candidate.candidate_id, approver="agent")

def test_declared_regression_rolls_back_to_last_known_good(store):
    candidate = promoted_candidate(store)
    trigger = store.observe(candidate.candidate_id, failing_slo_observation())
    assert trigger.action == "rollback"
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `python -m pytest -q tests/test_agent_learning.py`

Expected: FAIL because learning store does not exist.

- [ ] **Step 3: Implement governed candidate lifecycle.**

Store only opaque IDs, numeric metrics, booleans, baseline/candidate versions,
cohort metadata and approval references. Require ordered states `candidate`,
`replay_passed`, `shadow_passed`, `canary_passed`, `approved`, `promoted`,
`rolled_back`, and `rejected`. Promotion requires user approval. A promoted
version has predeclared quality, safety, reproducibility, latency and cost
thresholds. On threshold breach, restore last known-good version and emit an
auditable rollback event.

- [ ] **Step 4: Run focused tests.**

Run: `python -m pytest -q tests/test_agent_learning.py`

Expected: PASS.

- [ ] **Step 5: Commit governed learning delivery.**

```bash
git add src/local_ai_hub/agent_learning.py src/local_ai_hub/telemetry.py src/local_ai_hub/app.py tests/test_agent_learning.py
git commit -m "feat: add governed agent improvement loop"
```

### Task 11: Compact MCP and HTTP Projection

**Files:**

- Modify: `src/local_ai_hub/http_server.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/client.py`
- Create: `tests/test_agent_state_transport.py`

**Interfaces:**

- Consumes all prior stores through `LocalAIApp`.
- Adds compact existing-tool actions: `local_ai_coord` for task/checkpoint/memory/incident queries, `local_ai_repo` for context/verification projections, `local_ai_task` for governed evaluation records, and status detail for health summaries.
- Produces uniformly compact response fields: `success`, `state`, `event_id`, `task_id`, `evidence_ids`, `cache_hit`, `coalesced`, `retryable`, and bounded `next_action`.

- [ ] **Step 1: Write failing transport and privacy tests.**

```python
def test_coord_task_checkpoint_action_preserves_existing_memo_actions(client):
    response = client.coord(action="task_checkpoint", task_id="task-1", checkpoint={"next_action": "test"})
    assert response["success"] is True
    assert client.coord(action="memo_search", query="known") ["success"] is True

def test_agent_state_response_never_returns_raw_prompt_or_absolute_path(client):
    response = client.status(detail="agent_state")
    assert "prompt" not in repr(response).lower()
    assert "C:\\" not in repr(response)
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `python -m pytest -q tests/test_agent_state_transport.py`

Expected: FAIL because agent-state actions are absent.

- [ ] **Step 3: Implement handlers and projections.**

Add authenticated bounded HTTP handlers that validate feature flags, request
size, action schema, task scope and idempotency. Extend existing MCP action
literal types and client projections without changing tool count. Preserve all
existing action behavior and response compaction. Return a structured
non-retryable error for unknown action or unauthorized promotion.

- [ ] **Step 4: Run focused tests.**

Run: `python -m pytest -q tests/test_agent_state_transport.py`

Expected: PASS.

- [ ] **Step 5: Commit transport delivery.**

```bash
git add src/local_ai_hub/http_server.py src/local_ai_hub/mcp_server.py src/local_ai_hub/client.py tests/test_agent_state_transport.py
git commit -m "feat: expose compact agent state actions"
```

### Task 12: Operator Controls, Bundles, Retention, and Recovery

**Files:**

- Modify: `src/local_ai_hub/app.py`
- Modify: `src/local_ai_hub/dashboard.py`
- Modify: `src/local_ai_hub/http_server.py`
- Modify: `docs/CONFIGURATION.md`
- Modify: `docs/MCP_AND_AGENTS.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `FEATURES.md`
- Create: `tests/test_agent_state_operations.py`

**Interfaces:**

- `LocalAIApp.status()` includes bounded agent-state health, counts, retention and active candidate summaries.
- `LocalAIApp.export_bundle()` and `import_bundle()` include only selected signed agent-state records with validation.
- Operator actions support list, detail, approve, reject, quarantine, delete, cleanup, export and import.

- [ ] **Step 1: Write failing retention, restart, and export tests.**

```python
def test_cleanup_removes_expired_terminal_records_but_never_active_task(tmp_path):
    app = app_with_agent_state(tmp_path)
    active = app.agent_tasks.create(active_contract(), task_context())
    expired = create_expired_incident(app)
    assert app.agent_state_cleanup(now=expired.expires_at + 1) == 1
    assert app.agent_tasks.get(active.task_id).status is TaskStatus.ACTIVE

def test_selective_export_rejects_record_with_disallowed_scope(tmp_path):
    app = app_with_agent_state(tmp_path)
    with pytest.raises(BundleValidationError):
        app.export_bundle(agent_state_record_ids=[global_unapproved_record(app).record_id])
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `python -m pytest -q tests/test_agent_state_operations.py`

Expected: FAIL because agent-state operation hooks are absent.

- [ ] **Step 3: Implement bounded control-plane operations.**

Add dashboard sections for task state, incidents, memory candidates, policy
candidates, health and retention. Add authenticated control actions with audit
events. Extend existing bundle mechanism with selective signed records,
schema/version validation, size limits and no secret-bearing fields. Schedule
small cleanup batches from the existing bounded maintenance path. Reopen the
store on restart and validate migration/integrity before serving state.

- [ ] **Step 4: Document exact operator and agent contract.**

Document feature flags, retention, approvals, task states, allowed actions,
privacy boundary, export/import, rollback, and recovery procedures. Update
feature matrix without claiming default enablement until all validation passes.

- [ ] **Step 5: Run focused tests.**

Run: `python -m pytest -q tests/test_agent_state_operations.py`

Expected: PASS.

- [ ] **Step 6: Commit operations delivery.**

```bash
git add src/local_ai_hub/app.py src/local_ai_hub/dashboard.py src/local_ai_hub/http_server.py docs/CONFIGURATION.md docs/MCP_AND_AGENTS.md docs/OPERATIONS.md FEATURES.md tests/test_agent_state_operations.py
git commit -m "feat: add agent state operations"
```

### Task 13: End-to-End Reliability Matrix and Controlled Enablement

**Files:**

- Create: `tests/test_agent_state_e2e.py`
- Modify: `tests/test_v1_5_reliability.py`
- Modify: `tools/selftest.py`
- Modify: `docs/OPERATIONS.md`

**Interfaces:**

- Consumes completed feature-flagged system.
- Produces a release gate: all focused tests, restart recovery, concurrency, privacy, migration, cancellation, fault injection and current repository validation pass.

- [ ] **Step 1: Write end-to-end scenarios.**

```python
def test_interrupted_task_resumes_with_fresh_evidence_and_no_duplicate_command(app):
    task = create_task_with_checkpoint(app)
    restart_app(app)
    resumed = app.agent_tasks.resume(task.task_id, actor="agent", idempotency_key="resume-1")
    assert resumed.status is TaskStatus.ACTIVE
    assert command_invocations(app) == 0

def test_busy_database_returns_bounded_retryable_result_without_corrupting_event_stream(app):
    result = append_while_database_is_locked(app)
    assert result.retryable is True
    assert app.agent_state.events("task-1") == []
```

- [ ] **Step 2: Run end-to-end tests and verify failure before final integration fixes.**

Run: `python -m pytest -q tests/test_agent_state_e2e.py`

Expected: FAIL until all integration seams are complete.

- [ ] **Step 3: Fix only integration defects exposed by scenarios.**

Preserve prior public behavior, feature flags and bounded failure semantics.
Do not add broad compatibility aliases or unbounded retries.

- [ ] **Step 4: Run focused and project validation through Local AI Hub.**

Run:

```text
python -m pytest -q tests/test_agent_events.py tests/test_agent_identity.py tests/test_agent_tasks.py tests/test_agent_memory.py tests/test_agent_incidents.py tests/test_agent_verification.py tests/test_agent_policy.py tests/test_agent_context.py tests/test_agent_routing.py tests/test_agent_learning.py tests/test_agent_state_transport.py tests/test_agent_state_operations.py tests/test_agent_state_e2e.py
python -m compileall -q src mcp tools tests
python -m pytest -q
python tools/selftest.py
```

Expected: all commands PASS through `local_ai_command`; no duplicate in-progress command runs.

- [ ] **Step 5: Review staged diff and feature-flag defaults.**

Run: `git diff --check` and the existing indexed `review_diff`/`security_audit`
actions before enabling any delivery by default. Confirm no raw sensitive data,
new MCP tool, unbounded wait, or policy bypass appears.

- [ ] **Step 6: Commit release gate.**

```bash
git add tests/test_agent_state_e2e.py tests/test_v1_5_reliability.py tools/selftest.py docs/OPERATIONS.md
git commit -m "test: cover agent state reliability"
```

## Coverage Self-Review

- Event core, migrations, snapshots, retention, backup/export: Tasks 1 and 12.
- Identity, scope, worktree overlays and environment capsules: Task 2.
- Work journal, task graph basis, checkpoint/resume, heartbeat and handoff: Task 3.
- Memory, decisions, assumptions, promotion, conflict and quarantine: Task 4.
- Error logging, verified fixes and negative knowledge: Task 5.
- Evidence-backed completion, change provenance, outcomes and test intelligence: Tasks 6 and 9.
- Permission broker, capability grants, budget and SLOs: Task 7.
- Context compiler, knowledge graph and precise invalidation: Task 8.
- Cheapest-sufficient routing, performance history and flake handling: Task 9.
- Governed self-improvement, replay, canary, approval, monitoring and rollback: Task 10.
- Compact MCP/HTTP integration: Task 11.
- Operator controls, lifecycle operations and selective import/export: Task 12.
- Restart, contention, privacy, fault and full validation gates: Task 13.

No plan step creates a new public MCP tool, stores prohibited content, or permits autonomous policy promotion.
