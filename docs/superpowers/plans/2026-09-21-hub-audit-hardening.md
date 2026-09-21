# Local AI Hub Audit Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Local AI Hub produce a short, trustworthy, fail-fast audit chain for repository work, while keeping deterministic tools authoritative and local models advisory.

**Architecture:** Extend existing routing, telemetry, async-job, command-broker, and Agent OS paths. Do not add public MCP tools. Each result carries bounded provenance and freshness metadata; semantic and queued paths have explicit quality/SLA gates; terminal Hub failures remain the only trigger for native fallback.

**Tech Stack:** Python 3.11+, existing MCP server, SQLite state/telemetry, `AsyncJobManager`, pytest/unittest, PowerShell-compatible command broker.

---

## Scope and evidence

Current evidence shows existing pieces in `services.py` (`review_diff`, diff chunking, command dispatch), `mcp_server.py` (reuse and tool routing), `http_server.py` (telemetry outcome classification), and tests for delivery policy, async jobs, review chunking, and Agent OS transport. The missing behavior is cross-cutting: stale or irrelevant results can still look usable, queued review has no practical caller SLA, and the audit chain does not consistently expose freshness, provenance, bypass reason, or receipt identity.

Preserve clean worktree state and public action literals. Do not introduce aliases, broad rewrites, persistent prompt/source/model payloads, or unbounded waits.

### Task 1: Define bounded evidence provenance and freshness

**Files:**
- Create: `src/local_ai_hub/evidence_contract.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/http_server.py`
- Test: `tests/test_evidence_contract.py`
- Modify: `tests/test_mcp_agent_routing.py`

- [ ] **Step 1: Write failing contract tests.**

```python
from local_ai_hub.evidence_contract import evidence_meta


def test_evidence_meta_is_bounded_and_does_not_store_payload():
    result = evidence_meta(
        source="repo.search", repository_revision="abc123", evidence_ids=["E1"],
        stale=False, status="success", payload={"text": "secret source"},
    )
    assert result == {
        "source": "repo.search", "repository_revision": "abc123",
        "evidence_ids": ["E1"], "stale": False, "status": "success",
    }


def test_stale_evidence_cannot_claim_verified():
    result = evidence_meta("repo.search", "abc123", ["E1"], True, "success")
    assert result["status"] == "stale"
    assert result["stale"] is True
```

- [ ] **Step 2: Run `python -m pytest -q tests/test_evidence_contract.py`; confirm missing module/failing assertions.**
- [ ] **Step 3: Implement `evidence_meta` with fixed keys, bounded strings, deduplicated evidence IDs, and no payload/source/model fields. Convert `status=success` to `stale` when freshness is false.**
- [ ] **Step 4: Attach metadata to repository search, artifact slices, command results, and review responses. Keep existing response fields intact.**
- [ ] **Step 5: Run focused routing, artifact, command, and review tests.**

### Task 2: Add semantic-result quality gate and one-shot bypass

**Files:**
- Create: `src/local_ai_hub/semantic_quality.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/services.py`
- Test: `tests/test_semantic_quality.py`
- Modify: `tests/test_mcp_agent_routing.py`
- Modify: `docs/INSTALL_PROMPT.md`
- Modify: `docs/UPDATE_PROMPT.md`

- [ ] **Step 1: Write failing tests for irrelevant model output.**

```python
from local_ai_hub.semantic_quality import assess_semantic_result


def test_unrelated_paths_are_rejected_as_advisory_only():
    result = assess_semantic_result(
        task="diagnose src/auth.py",
        evidence_paths=["src/auth.py"],
        output="Fix src/Calculator.java and src/UserManager.java",
    )
    assert result["usable"] is False
    assert result["reason"] == "unrelated_output"


def test_empty_or_queued_model_result_requests_bypass():
    result = assess_semantic_result("review diff", ["src/a.py"], "queued")
    assert result["usable"] is False
    assert result["reason"] in {"queued", "empty_output"}
```

- [ ] **Step 2: Run the focused test and confirm failure.**
- [ ] **Step 3: Implement a deterministic gate using bounded path overlap, status, output length, and explicit model error markers. Do not attempt semantic truth scoring.**
- [ ] **Step 4: Make `local_ai_task` and `solve` return `advisory_only=true` plus a bounded `bypass_reason` when the gate rejects output. Emit the required adoption bypass signal once; never retry identical semantic work.**
- [ ] **Step 5: Document: deterministic evidence wins; local model output cannot establish facts, test success, or completion.**

### Task 3: Enforce practical async-review SLA and queue state

**Files:**
- Modify: `src/local_ai_hub/async_jobs.py`
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/http_server.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/defaults.toml`
- Test: `tests/test_async_review_sla.py`
- Modify: `tests/test_delivery_policy.py`
- Modify: `tests/test_async_jobs.py`

- [ ] **Step 1: Write failing tests for queue age and bounded delivery.**

```python
def test_review_diff_auto_delivery_bypasses_queue_when_age_exceeds_budget(monkeypatch):
    result = dispatch_review_diff(delivery="auto", latency_budget_ms=5000,
                                  queue_age_ms=5001, job_id="job-1")
    assert result["delivery"]["mode"] == "bypass"
    assert result["delivery"]["reason"] == "queue_age_budget_exceeded"


def test_queued_review_exposes_pollable_state_without_fake_success():
    result = review_status("job-1", state="queued")
    assert result["success"] is False
    assert result["in_progress"] is True
    assert result["status"] == "queued"
```

- [ ] **Step 2: Run focused async/delivery tests and confirm failure.**
- [ ] **Step 3: Add configured `review.max_queue_age_ms` and classify queued, running, completed, failed, expired, and bypassed states. Preserve explicit `delivery=sync`.**
- [ ] **Step 4: Return a terminal, bounded response when queue age exceeds SLA; include job identity and next supported action, never a success-looking review.**
- [ ] **Step 5: Add tests for stale jobs, cancellation, and no duplicate submission under repeated `reuse_key`.**

### Task 4: Make command transport shell-safe and portable

**Files:**
- Modify: `src/local_ai_hub/commands.py`
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Test: `tests/test_command_transport.py`
- Modify: `tests/test_command_broker.py`
- Modify: `docs/INSTALL_PROMPT.md`
- Modify: `docs/UPDATE_PROMPT.md`

- [ ] **Step 1: Write failing Windows transport tests.**

```python
def test_command_arguments_are_passed_as_argv_not_nested_shell_text():
    invocation = build_invocation("python", ["-c", "print('a b')"], cwd="C:\\repo")
    assert invocation.argv == ["python", "-c", "print('a b')"]
    assert invocation.shell is False


def test_powershell_command_is_rejected_when_only_string_quoting_is_available():
    result = validate_invocation("powershell -Command Write-Host $HOME")
    assert result["safe"] is False
    assert result["reason"] == "unstructured_shell_text"
```

- [ ] **Step 2: Run focused transport tests and confirm failure.**
- [ ] **Step 3: Route structured commands through argv/list arguments, use project process helpers, and keep raw shell text only for explicitly classified bounded diagnostics.**
- [ ] **Step 4: Return `terminal=true, retryable=false` with a precise serialization error when a command cannot be represented safely.**
- [ ] **Step 5: Test nested repository roots, spaces, quotes, Unicode paths, timeout, cancellation, and PowerShell payloads.**

### Task 5: Close Agent OS lifecycle and receipt gaps

**Files:**
- Modify: `src/local_ai_hub/agent_state.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/http_server.py`
- Test: `tests/test_agent_state_lifecycle.py`
- Modify: `tests/test_agent_state_e2e.py`
- Modify: `tests/test_agent_state_transport.py`

- [ ] **Step 1: Write failing lifecycle tests for checkpoint, receipt, completion, and expired heartbeat.**

```python
def test_completion_requires_matching_validation_receipt(state):
    task_id = state.create_task("audit", acceptance_criteria=["pytest passes"])
    assert state.complete_task(task_id) == {"success": False, "error": "verification_required"}
    receipt = state.record_receipt(task_id, criterion="pytest passes", status="passed")
    assert state.complete_task(task_id, receipt_id=receipt["receipt_id"])["success"] is True


def test_expired_planned_task_is_marked_stale_not_completed(state):
    task_id = state.create_task("audit", heartbeat_expires_at=1)
    result = state.reap_expired(task_id, now=2)
    assert result["status"] == "stale"
```

- [ ] **Step 2: Run focused lifecycle tests and confirm failure.**
- [ ] **Step 3: Require receipt identity and criterion match for completion; make zombie/planned tasks visible as stale with bounded cleanup metadata.**
- [ ] **Step 4: Add checkpoint records for discover, inspect, act, verify, and review phases. Do not store prompts or source payloads.**
- [ ] **Step 5: Verify interrupted-task resume does not duplicate commands or semantic calls.**

### Task 6: Shape compact, useful telemetry and update agent prompts

**Files:**
- Modify: `src/local_ai_hub/telemetry.py`
- Modify: `src/local_ai_hub/http_server.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Test: `tests/test_telemetry_contract.py`
- Modify: `tests/test_delivery_policy.py`
- Modify: `docs/INSTALL_PROMPT.md`
- Modify: `docs/UPDATE_PROMPT.md`

- [ ] **Step 1: Write failing telemetry contract tests.**

```python
def test_telemetry_summary_has_decision_grade_fields_only(summary):
    assert set(summary) >= {"window", "counts", "routes", "errors", "queue"}
    assert "prompt" not in repr(summary).lower()
    assert "source_text" not in repr(summary).lower()


def test_truncated_backend_detail_reports_truncation_not_success(summary):
    assert summary["detail"]["truncated"] is True
    assert summary["detail"]["status"] == "incomplete"
```

- [ ] **Step 2: Run focused telemetry tests and confirm failure.**
- [ ] **Step 3: Add stable aggregate fields for route, cache hit, bypass reason, queue age, terminal/retryable outcome, and validation receipt count. Bound lists and mark truncation explicitly.**
- [ ] **Step 4: Preserve metadata-only privacy rules. Redact paths beyond repository-relative identifiers and never persist prompt/source/model output.**
- [ ] **Step 5: Sync routing, bypass, receipt, fallback, and telemetry rules into both canonical prompts.**

### Task 7: Measure and gate local-model quality

**Files:**
- Create: `src/local_ai_hub/model_quality.py`
- Create: `tests/fixtures/model_quality_cases.jsonl`
- Create: `tests/test_model_quality.py`
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/telemetry.py`
- Modify: `docs/INSTALL_PROMPT.md`
- Modify: `docs/UPDATE_PROMPT.md`

- [ ] **Step 1: Add synthetic, non-sensitive evaluation cases.** Include grounded diagnosis, valid phone/email classification, unrelated-path rejection, abstention when evidence is missing, structured JSON adherence, and review findings with known expected labels. Store expected labels and evidence paths, never production prompts or outputs.
- [ ] **Step 2: Write failing quality tests.**

```python
def test_model_case_records_grounding_and_schema_metrics():
    result = evaluate_case(
        task="classify input", evidence_paths=["fixtures/contact.txt"],
        output={"label": "phone", "reason": "matches phone pattern"},
        expected={"label": "phone"},
    )
    assert result["grounded"] is True
    assert result["schema_pass"] is True
    assert result["hallucinated_paths"] == []


def test_model_registry_rejects_candidate_below_quality_floor():
    result = promote_candidate({"grounded_rate": 0.70, "hallucinated_path_rate": 0.08})
    assert result["status"] == "rejected"
    assert result["reason"] == "quality_floor_not_met"
```

- [ ] **Step 3: Implement deterministic scoring:** grounded relevance, schema pass, abstention correctness, hallucinated-path rate, valid-input false-positive rate, p50/p95 latency, timeout rate, and token/context use. Model text remains advisory input, not truth.
- [ ] **Step 4: Add candidate registry states `candidate`, `champion`, `rejected`; require an evaluation receipt before promotion. Never auto-promote based on one response or model self-rating.**
- [ ] **Step 5: Add prompt/evaluation drift checks and a bounded champion-vs-candidate report. Include a hard bypass when model output is irrelevant, generic, queued, malformed, or below quality floor.**
- [ ] **Step 6: Add VRAM/context-pressure routing: reduce optional semantic calls, cap concurrency, and return explicit degraded status when resource pressure blocks reliable inference.**

### Task 8: Triage and harden security findings

**Files:**
- Modify: `src/local_ai_hub/commands.py`
- Modify: `src/local_ai_hub/process_utils.py`
- Modify: `src/local_ai_hub/http_server.py`
- Create: `tests/test_security_boundaries.py`
- Modify: `tests/test_auto_fix_repair_loop.py`
- Modify: `tests/test_feature_expansion.py`
- Modify: `tests/test_architectural_extensions.py`
- Modify: `tests/test_new_capabilities_and_hardening.py`

- [ ] **Step 1: Classify every security-audit finding as production issue, intentional test fixture, or scanner false positive. Do not suppress findings without a test proving the boundary.**
- [ ] **Step 2: Write failing boundary tests for shell metacharacters, path traversal, environment-secret leakage, subprocess timeout, process-tree termination, and unsafe auto-fix commands.**
- [ ] **Step 3: Keep test-only fake secrets obviously synthetic and add scanner-safe fixture conventions. Remove or isolate any value that can be mistaken for a live credential.**
- [ ] **Step 4: Enforce structured argv and command policy in production. Permit raw shell text only for explicitly classified, bounded diagnostics; reject `eval`, `exec`, shell expansion, and unapproved interpreters.**
- [ ] **Step 5: Run security audit again and require zero untriaged high findings before completion.**

### Task 9: Fix resource pressure, cache visibility, and backpressure

**Files:**
- Modify: `src/local_ai_hub/scheduler.py`
- Modify: `src/local_ai_hub/async_jobs.py`
- Modify: `src/local_ai_hub/telemetry.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/defaults.toml`
- Create: `tests/test_resource_backpressure.py`
- Modify: `tests/test_async_jobs.py`

- [ ] **Step 1: Write failing tests for bounded queue admission, high VRAM pressure, context budget factor below one, cache-stat truncation, and cancellation.**
- [ ] **Step 2: Add explicit scheduler admission decisions: `accepted`, `coalesced`, `degraded`, `rejected`, with reason, queue age, and retryability. Never report a queued job as completed.**
- [ ] **Step 3: Add cache counters and bounded eviction/expiry metadata. Ensure `cache`, `telemetry`, and `agent_state` summaries report truncation explicitly instead of silently returning incomplete detail.**
- [ ] **Step 4: Make context budget and review chunk limits adapt to measured resource pressure; preserve hard upper bounds and deterministic paths.**
- [ ] **Step 5: Test cancellation and process-tree cleanup under timeout.**

### Task 10: Reduce production complexity without broad rewrite

**Files:**
- Create: `tests/test_complexity_budget.py`
- Modify: production files identified by indexed complexity review only
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Re-run complexity analysis scoped to `src/` and rank production functions separately from tests.**
- [ ] **Step 2: Add characterization tests before changing any production hotspot.**
- [ ] **Step 3: Extract only one responsibility at a time from high-risk functions: validation, routing, persistence, or response shaping. Preserve public action literals and response compatibility.**
- [ ] **Step 4: Add a complexity budget for new production code and document exceptions with measured reason.**
- [ ] **Step 5: Run focused tests after every extraction; do not refactor test fixtures merely to improve scanner scores.**

### Task 11: Close operational, compatibility, and documentation gaps

**Files:**
- Modify: `tools/doctor.py`
- Modify: `tools/release_check.py`
- Modify: `src/local_ai_hub/defaults.toml`
- Modify: `config.toml.example`
- Create: `docs/MIGRATION_3_TO_4.md`
- Modify: `docs/INSTALL_PROMPT.md`
- Modify: `docs/UPDATE_PROMPT.md`
- Create: `tests/test_operational_contract.py`
- Modify: `tests/test_release_contract.py`

- [ ] **Step 1: Add contract tests for health/status timeout fallback, model inventory fallback, version/config parity, and state-directory isolation.**
- [ ] **Step 2: Verify every public action is represented consistently in MCP descriptions, generated prompts, config defaults, doctor output, and release checks.**
- [ ] **Step 3: Document native fallback exactly: only after `terminal=true` and `retryable=false`; preserve Hub result metadata and ownership.**
- [ ] **Step 4: Add upgrade/restart recovery checks for queued jobs, stale tasks, cache state, and schema compatibility.**
- [ ] **Step 5: Add a release gate for prompt synchronization, security audit, focused quality suite, and full validation.**
- [ ] **Step 6: Write `docs/MIGRATION_3_TO_4.md` with backup/rollback, state-directory handling, config changes, context-contract changes, telemetry schema changes, task receipt migration, model evaluation registry migration, command transport compatibility, staged rollout, and post-upgrade verification.**

### Task 12: Deduplicate context and create bounded handoff summaries

**Files:**
- Modify: `src/local_ai_hub/context_ledger.py`
- Modify: `src/local_ai_hub/agent_context.py`
- Modify: `src/local_ai_hub/response_budget.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Create: `tests/test_context_deduplication.py`
- Modify: `tests/test_agent_state_transport.py`

- [ ] **Step 1: Write failing tests for unchanged-context reuse and delta responses.**

```python
def test_same_revision_and_evidence_returns_pointer_not_full_context(ledger):
    first = ledger.compile("task-1", revision="r1", evidence_ids=["E1"], context="facts")
    second = ledger.compile("task-1", revision="r1", evidence_ids=["E1"], context="facts")
    assert first["status"] == "materialized"
    assert second["status"] == "unchanged"
    assert second["context"] is None
    assert second["reuse_key"] == first["reuse_key"]


def test_new_evidence_returns_only_delta(ledger):
    ledger.compile("task-1", "r1", ["E1"], "facts")
    result = ledger.compile("task-1", "r1", ["E1", "E2"], "facts plus new")
    assert result["status"] == "delta"
    assert result["added_evidence_ids"] == ["E2"]
```

- [ ] **Step 2: Implement digest-based context reuse keyed by repository revision, task, phase, evidence IDs, and schema version. Return pointer/delta metadata instead of repeated payload.**
- [ ] **Step 3: Add compact structured handoff summaries containing decisions, evidence IDs, changed paths, next action, and unresolved risks; never store raw prompt/source/model output.**
- [ ] **Step 4: Cap summary and delta sizes. Mark truncation explicitly and force refresh only when revision or evidence changes.**
- [ ] **Step 5: Verify no API response silently falls back to the full context when `response_profile=compact` or `delta` is requested.**

### Task 13: Add root-family budgets and fanout controls

**Files:**
- Modify: `src/local_ai_hub/budget.py`
- Modify: `src/local_ai_hub/scheduler.py`
- Modify: `src/local_ai_hub/agent_tasks.py`
- Modify: `src/local_ai_hub/agent_routing.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Create: `tests/test_root_family_budget.py`
- Modify: `tests/test_agent_tasks.py`
- Modify: `tests/test_agent_routing.py`

- [ ] **Step 1: Write failing tests for family budget exhaustion, duplicate scope, and micro-task fanout.**

```python
def test_root_family_budget_rejects_new_work_with_actionable_reason(budget):
    budget.reserve("woodbound", input_tokens=100, limit=100)
    result = budget.reserve("woodbound", input_tokens=1, limit=100)
    assert result["status"] == "rejected"
    assert result["reason"] == "root_family_budget_exceeded"


def test_duplicate_subagent_scope_is_coalesced_or_rejected(router):
    router.claim("task-1", "src/a.py", owner="agent-a")
    result = router.claim("task-1", "src/a.py", owner="agent-b")
    assert result["status"] in {"coalesced", "rejected"}
```

- [ ] **Step 2: Add per-task and root-family input/output budgets, fanout count, active-scope count, wait budget, and heartbeat expiry.**
- [ ] **Step 3: Default micro-tasks to one owner; require explicit bounded scope for additional agents. Prevent overlapping search/review scopes.**
- [ ] **Step 4: Return `accepted`, `coalesced`, `rejected`, or `expired` with remaining budget and retryability. Never hide budget denial as model failure.**
- [ ] **Step 5: Reap idle tasks and close stale coordination state; preserve audit records without retaining payloads.**

### Task 14: Instrument token efficiency and replay future savings

**Files:**
- Modify: `src/local_ai_hub/token_accounting.py`
- Modify: `src/local_ai_hub/telemetry.py`
- Modify: `src/local_ai_hub/trace_context.py`
- Modify: `src/local_ai_hub/response_budget.py`
- Create: `tests/fixtures/token_efficiency_cases.jsonl`
- Create: `tests/test_token_efficiency.py`
- Modify: `docs/INSTALL_PROMPT.md`
- Modify: `docs/UPDATE_PROMPT.md`

- [ ] **Step 1: Record future per-request metadata:** root family, task ID, parent task, phase, activity class, repository revision, context digest, estimated input, output size, cache/reuse state, queue wait, and bypass reason. Do not claim this reconstructs old Codex usage.
- [ ] **Step 2: Write replay tests for repeated full context, unchanged evidence, redundant review, fanout, and compact handoff.**
- [ ] **Step 3: Report raw input, reused input, generated output, and estimated avoided payload separately. Label cached tokens as raw usage, not automatically as billed cost.**
- [ ] **Step 4: Add budget alerts at task and root-family level. Alert only on meaningful threshold crossing, not every unchanged sample.**
- [ ] **Step 5: Set acceptance targets: zero duplicate full-context transmissions for unchanged ledger state; no semantic/test-quality regression; measurable reduction in payload bytes on replay corpus.**

### Task 15: Make task context complete and automatically consumable

**Files:**
- Modify: `src/local_ai_hub/agent_context.py`
- Modify: `src/local_ai_hub/agent_tasks.py`
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/http_server.py`
- Modify: `tests/test_agent_state_transport.py`
- Modify: `tests/test_mcp_agent_routing.py`
- Create: `tests/test_unified_task_context.py`
- Modify: `docs/INSTALL_PROMPT.md`
- Modify: `docs/UPDATE_PROMPT.md`

- [ ] **Step 1: Prove current split behavior with a failing integration test.** The test must create one task, record one checkpoint/memo/negative-knowledge item/lease, provide repository revision and evidence IDs, call `local_ai_coord(action="context_compile", task_id=...)`, then assert the response contains all expected layers and a stable `context_id`.
- [ ] **Step 2: Define one bounded response contract for compiled task context:** `task`, `acceptance_criteria`, latest checkpoint, relevant memories, negative knowledge, active leases, repository revision, changed paths, evidence IDs, receipts, freshness, omitted sections, `context_id`, `etag`, and `next_action`. No raw prompts, source files, model output, or absolute paths.
- [ ] **Step 3: Extend the existing `/api/agent-state/context` compile path to join Agent OS state with repository/index evidence for the requested task and revision. Preserve `since_hash`/etag unchanged responses and explicit truncation metadata.**
- [ ] **Step 4: Pass missing task-scoping fields through MCP and internal calls: phase, focus, preload profile, evidence IDs, repository revision, changed paths, and context etag. Reject mismatched task/root/revision combinations instead of silently returning partial context.**
- [ ] **Step 5: Make `local_ai_task` consume compiled context when `task_id` is supplied and explicit context is absent; make `local_ai_repo(action="context")` reuse the same compiled context instead of building a disconnected pack. Explicit caller context remains supported but must be labeled external and incomplete unless it carries the contract metadata.**
- [ ] **Step 6: Add end-to-end tests proving context propagation into semantic call, repo planning, command validation, resume, and verification. Test disabled Agent OS, missing task, stale revision, empty evidence, cross-task isolation, etag reuse, and compact truncation.**
- [ ] **Step 7: Update prompts so `context_compile` is mandatory before non-trivial resume/edit/review/test phases, not merely recommended documentation.**

### Task 16: Verification gate and completion evidence

**Files:**
- No source changes expected.

- [ ] **Step 1: Run focused suites through `local_ai_command`:** evidence contract, semantic quality, model quality, async SLA, command transport, security boundaries, resource backpressure, Agent OS lifecycle, operational contract, unified task context, context deduplication, root-family budget, token efficiency, delivery policy, review chunking, and telemetry.
- [ ] **Step 2: Run `python -m compileall -q src mcp tools tests`, `python tools/release_check.py`, `python -m pytest -q`, and `python tools/selftest.py` through the command broker.**
- [ ] **Step 3: Run indexed impact/review and security audit for changed paths. Treat queued or advisory results as non-evidence.**
- [ ] **Step 4: Attach passing command receipts to `task_ddbd70448d9b`; run `verify_completion`; only then transition the Agent OS task to complete.**
- [ ] **Step 5: Report remaining runtime-only, model-quality, or external-environment gaps separately.**

## Self-review

This plan covers deterministic provenance, complete task-context propagation, model quality, semantic bypass, queue behavior, command transport, security, resource pressure, production complexity, Agent OS lifecycle, operations, context deduplication, root-family budgets, token instrumentation, telemetry, prompt synchronization, and final receipt-gated verification. It distinguishes future Hub-side attribution from impossible retroactive Codex activity attribution. It adds no public MCP tool, no deprecated alias, no unbounded retry, and no completion claim based on model output alone.
