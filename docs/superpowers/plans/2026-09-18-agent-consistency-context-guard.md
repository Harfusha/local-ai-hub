# Agent Consistency Context Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add default-on consistency guard and adaptive context packs that reduce duplicate discovery, scope drift, hallucinated repository facts, BE/FE contract mismatches, and unnecessary new abstractions.

**Architecture:** Keep the public MCP surface compact by extending `local_ai_repo(action="context")`. Add a focused `AgentConsistencyGuard` service that composes the existing task, memory, verification, lease, deterministic repository, code-index, preload, and local-model services. Deterministic evidence is authoritative; local models only rank, find gaps, and compose evidence-backed output. Existing unguarded context callers remain backward compatible.

**Tech Stack:** Python 3.11+, dataclasses, SQLite-backed Agent OS stores, existing `RepositoryTools`/`DeterministicEngine`/`CodeIndex`, existing local model generation path, FastMCP, pytest.

---

## Current integration points

- `src/local_ai_hub/mcp_server.py` already exposes `local_ai_repo` and already has `context`, `context_compile`, `verify`, and `verify_completion` actions.
- `src/local_ai_hub/http_server.py` already routes `/api/context/pack` and `/api/agent-state/context`.
- `src/local_ai_hub/repo_tools.py` already provides `git_snapshot`, `search`, `repo_map`, `verify_evidence`, `impact_analysis`, `context_pack_paths`, `file_slice`, and `context_pack`.
- `src/local_ai_hub/services.py` already implements deterministic-first fast context, hybrid lexical/semantic context, caching, single-flight, and bounded local model generation.
- `src/local_ai_hub/agent_context.py` already compiles task goals, checkpoints, receipts, memory, leases, incidents, blackboard state, and links within a token budget.
- `src/local_ai_hub/agent_memory.py` already supports provenance, evidence IDs, confidence, status, conflicts, supersession, scoped promotion, semantic find, and compaction.
- `src/local_ai_hub/agent_tasks.py` already supports non-goals, constraints, waiting status, checkpoints, and completion gates.
- `src/local_ai_hub/agent_verification.py` already stores repository revisions and fresh receipts.
- `src/local_ai_hub/app.py` owns all service construction and is the correct dependency-injection boundary.

Preserve unrelated existing changes in `src/local_ai_hub/dashboard.py`, `tests/test_dashboard_custom_modals.py`, `tools/hubctl.py`, `tools/monitor.py`, and `tools/telemetry_report.py`.

## Task 1: Extend memory vocabulary and revision-aware provenance

**Files:**
- Modify: `src/local_ai_hub/agent_memory.py:25-230`
- Modify: `src/local_ai_hub/agent_context.py:1-380`
- Test: `tests/test_agent_memory.py`
- Test: `tests/test_agent_context.py`
- Test: `tests/test_context_knapsack.py`

- [ ] **Step 1: Write failing memory tests.** Add tests named `test_consistency_memory_kinds_round_trip`, `test_repository_revision_is_preserved_in_provenance`, `test_stale_memory_is_excluded_from_authoritative_context`, and `test_stale_memory_remains_visible_as_diagnostic`. Construct `MemoryRecord` instances with `finding`, `reusable_candidate`, `contract_mapping`, `rejected_approach`, `unknown`, and `validation` kinds; assert serialization, deserialization, and context filtering behavior.

- [ ] **Step 2: Run the focused tests and verify failure.**

```powershell
python -m pytest -q tests/test_agent_memory.py tests/test_agent_context.py tests/test_context_knapsack.py -k "consistency_memory or repository_revision or stale_memory"
```

Expected: FAIL because the new memory kinds and stale-aware context selection do not exist.

- [ ] **Step 3: Add compatible memory kinds and stale status.** Extend `MemoryKind` with `FINDING`, `REUSABLE_CANDIDATE`, `CONTRACT_MAPPING`, `REJECTED_APPROACH`, `UNKNOWN`, and `VALIDATION`. Extend `MemoryStatus` with `STALE`. Keep existing serialized values unchanged. Do not add a database migration; store `repository_revision`, `path_refs`, `symbol_refs`, and `related_task` inside the existing `provenance` object.

- [ ] **Step 4: Add provenance helpers.** Add `MemoryRecord.repository_revision`, `MemoryRecord.path_refs`, and `MemoryRecord.symbol_refs` read-only helper properties that safely project values from `provenance`. Add `MemoryStore.mark_stale_for_revision(root, revision, changed_paths)` that only changes matching repository-scoped records whose provenance points at affected paths and a different revision. Emit the existing event format with `memory.staled` and preserve the original record as superseded metadata.

- [ ] **Step 5: Make context compilation authoritative-first.** In `ContextCompiler.compile`, exclude `STALE`, `QUARANTINED`, `REJECTED`, and `SUPERSEDED` records from normal high-value memory candidates. Add a bounded diagnostic element containing stale/conflict counts and record IDs when the request asks for diagnostics. Include memory provenance fields in non-compact output while keeping compact output bounded.

- [ ] **Step 6: Run focused tests and commit.**

```powershell
python -m pytest -q tests/test_agent_memory.py tests/test_agent_context.py tests/test_context_knapsack.py
git add src/local_ai_hub/agent_memory.py src/local_ai_hub/agent_context.py tests/test_agent_memory.py tests/test_agent_context.py tests/test_context_knapsack.py
git commit -m "feat: add evidence memory vocabulary and stale provenance"
```

## Task 2: Add consistency guard domain models and deterministic checks

**Files:**
- Create: `src/local_ai_hub/agent_consistency.py`
- Modify: `src/local_ai_hub/repo_tools.py:754-1515`
- Modify: `src/local_ai_hub/agent_tasks.py:20-180`
- Test: `tests/test_agent_consistency.py`
- Test: `tests/test_repo_tools.py`

- [ ] **Step 1: Write failing domain and reuse tests.** Create `tests/test_agent_consistency.py` with fixtures for a temporary repository containing one reusable backend service, one frontend client/type, one error model, and one test. Add tests named `test_contract_preserves_non_goals_constraints_and_scope`, `test_reuse_candidates_are_ranked_before_new_symbols`, `test_rejected_reuse_requires_reason`, `test_be_fe_contract_reports_response_and_error_mismatches`, `test_unknown_claim_has_no_authoritative_evidence`, and `test_soft_warning_has_required_fields`. Add `test_repository_tools_returns_revision_and_changed_paths_for_guard` to `tests/test_repo_tools.py`.

- [ ] **Step 2: Run the focused tests and verify failure.**

```powershell
python -m pytest -q tests/test_agent_consistency.py tests/test_repo_tools.py -k "contract or reuse or mismatch or unknown_claim or soft_warning or revision"
```

Expected: FAIL because `agent_consistency.py` and the guard-facing repository helpers do not exist.

- [ ] **Step 3: Define focused dataclasses in `agent_consistency.py`.** Implement `ConsistencyRequest`, `ReuseCandidate`, `ContractMapping`, `GuardWarning`, and `AdaptiveContextPack`. Each `to_dict()` must return bounded JSON-safe data. `ConsistencyRequest` fields: `root`, `task_id`, `query`, `phase`, `focus`, `workspace`, `preload_profile`, `token_budget`, `changed_paths`, `base`, `staged`, `tenant`, `override_reason`, and `approval`.

```python
@dataclass(frozen=True)
class GuardWarning:
    severity: str
    kind: str
    message: str
    evidence_ids: tuple[str, ...] = ()
    affected_paths: tuple[str, ...] = ()
    recommended_action: str = ""
    requires_approval: bool = False
```

- [ ] **Step 4: Implement deterministic guard helpers.** Add `AgentConsistencyGuard.build_contract(request)`, `find_reuse_candidates(request, contract)`, `build_contract_mappings(request, evidence)`, `check_claims(evidence, claims)`, and `check_drift(request, contract, changed_paths, diff)`. Use `RepositoryTools.search`, `search_paths`, `file_slice`, `git_snapshot`, `git_diff`, `verify_evidence`, and `impact_analysis`; use the existing task/memory/verification stores for durable state. Never treat local-model text as authoritative evidence.

- [ ] **Step 5: Implement reuse decision validation.** Accept a reuse decision only when its candidate ID is present in the deterministic result. Emit an ordinary warning when a candidate is rejected without a reason. Emit a boundary warning when a new public symbol is added despite a suitable candidate. Keep all warnings soft; `requires_approval=True` only for boundary/high-risk changes.

- [ ] **Step 6: Implement BE/FE contract extraction.** Parse bounded evidence for endpoint, request/response schema, error code/model, FE client, FE type, loading state, empty state, error state, and affected tests. Compare names, nullable markers, response fields, error identifiers, and client-layer usage. Emit `ContractMapping` rows and warnings with exact evidence IDs.

- [ ] **Step 7: Run focused tests and commit.**

```powershell
python -m pytest -q tests/test_agent_consistency.py tests/test_repo_tools.py
git add src/local_ai_hub/agent_consistency.py src/local_ai_hub/repo_tools.py src/local_ai_hub/agent_tasks.py tests/test_agent_consistency.py tests/test_repo_tools.py
git commit -m "feat: add deterministic consistency and reuse guard"
```

## Task 3: Extend context compiler with preloads, phase packs, and delta reuse

**Files:**
- Modify: `src/local_ai_hub/agent_context.py:18-380`
- Modify: `src/local_ai_hub/config.py` or the existing config defaults loader
- Modify: `defaults.toml`
- Test: `tests/test_agent_context.py`
- Test: `tests/test_context_delivery.py`
- Test: `tests/test_context_knapsack.py`

- [ ] **Step 1: Write failing context-pack tests.** Add tests named `test_context_request_accepts_phase_focus_and_preload_profile`, `test_preloads_are_bounded_and_deduplicated`, `test_phase_pack_prioritizes_reuse_for_edit`, `test_delta_pack_returns_unchanged_etag`, and `test_disabled_agent_state_returns_stateless_repo_context_warning`.

- [ ] **Step 2: Run the focused tests and verify failure.**

```powershell
python -m pytest -q tests/test_agent_context.py tests/test_context_delivery.py tests/test_context_knapsack.py -k "phase or preload or delta or stateless"
```

Expected: FAIL because `ContextRequest` has no phase/focus/preload fields and preloads are not compiled.

- [ ] **Step 3: Extend `ContextRequest` and `CompiledContext`.** Add `phase`, `focus`, `preload_profile`, `repo_revision`, `since_hash`, `include_diagnostics`, and `tenant` fields. Add `phase`, `repo_revision`, `stale`, `warnings`, and `delta_from` to `CompiledContext`. Preserve existing constructor defaults and existing `to_dict(compact=True)` fields.

- [ ] **Step 4: Add preload loading.** Implement a bounded preload loader that reads configured `[context.preloads]` files/patterns and memory kinds through existing snapshot and memory APIs. Deduplicate by normalized path/hash, attach evidence IDs, and omit missing files with a warning. Add defaults with no mandatory project files so existing repositories keep working.

- [ ] **Step 5: Add phase prioritization and delta behavior.** Pin task contract and unknowns for `plan`, reuse candidates and exact symbols for `edit`, drift and changed paths for `review`, receipts and affected tests for `test`, and decisions/checkpoints for `handoff`. If `since_hash` equals the compiled etag, return `unchanged=True`; otherwise return only changed high-value elements when a prior context hash is available.

- [ ] **Step 6: Run focused tests and commit.**

```powershell
python -m pytest -q tests/test_agent_context.py tests/test_context_delivery.py tests/test_context_knapsack.py
git add src/local_ai_hub/agent_context.py defaults.toml tests/test_agent_context.py tests/test_context_delivery.py tests/test_context_knapsack.py
git commit -m "feat: add phase-aware context preloads and deltas"
```

## Task 4: Add adaptive local-model planning and evidence-backed post-processing

**Files:**
- Modify: `src/local_ai_hub/services.py:350-900,2280-2470`
- Modify: `src/local_ai_hub/agent_consistency.py`
- Test: `tests/test_context_delivery.py`
- Test: `tests/test_agent_consistency.py`

- [ ] **Step 1: Write failing model-pipeline tests.** Add tests named `test_adaptive_context_is_deterministic_first`, `test_model_relevance_pass_receives_structured_evidence_only`, `test_postprocess_drops_unsupported_claims`, `test_model_failure_returns_deterministic_degraded_pack`, and `test_adaptive_context_cache_key_includes_revision_phase_and_memory_revision`. Use fake services and model responses; do not invoke Ollama in unit tests.

- [ ] **Step 2: Run the focused tests and verify failure.**

```powershell
python -m pytest -q tests/test_context_delivery.py tests/test_agent_consistency.py -k "adaptive_context or relevance_pass or unsupported_claims or degraded_pack or cache_key"
```

Expected: FAIL because the adaptive guarded pipeline does not exist.

- [ ] **Step 3: Add `LocalAIServices.adaptive_context_pack`.** The method must execute deterministic/indexed retrieval first, load the Agent OS context, invoke one bounded local relevance pass only when evidence is insufficient or the phase requires semantic ranking, fetch bounded follow-up evidence, then invoke a second bounded local composition pass. Call the existing `_generate` path with a structured JSON format and a system instruction that forbids unsupported claims and requires evidence IDs.

- [ ] **Step 4: Add post-processing validation.** Parse the model response, retain only claims whose evidence IDs are present in the supplied evidence set, move unsupported claims to `unknowns`, redact sensitive values using existing projectors/normalizers, enforce `token_budget`, and preserve raw detailed material in artifacts rather than the MCP response.

- [ ] **Step 5: Add cache/single-flight behavior.** Reuse the existing repository cache and single-flight path with a key containing root revision, task contract fingerprint, phase, focus, preload profile, memory revision, and model policy revision. Return `context_id`, `repo_revision`, `stale`, and `delta_from` metadata.

- [ ] **Step 6: Run focused tests and commit.**

```powershell
python -m pytest -q tests/test_context_delivery.py tests/test_agent_consistency.py
git add src/local_ai_hub/services.py src/local_ai_hub/agent_consistency.py tests/test_context_delivery.py tests/test_agent_consistency.py
git commit -m "feat: add adaptive evidence-backed context pipeline"
```

## Task 5: Wire guard state into the application and HTTP API

**Files:**
- Modify: `src/local_ai_hub/app.py:130-175`
- Modify: `src/local_ai_hub/http_server.py:2129-2160,2657-2675`
- Modify: `src/local_ai_hub/agent_tasks.py:384-548`
- Test: `tests/test_agent_state_operations.py`
- Test: `tests/test_context_delivery.py`

- [ ] **Step 1: Write failing HTTP integration tests.** Add tests named `test_guarded_context_pack_contains_contract_memory_reuse_and_warnings`, `test_context_pack_preserves_legacy_fast_mode`, `test_boundary_warning_moves_task_to_waiting`, and `test_guard_works_with_agent_state_disabled`. Use `LocalAIApp` with a temporary config and monkeypatch deterministic/model dependencies.

- [ ] **Step 2: Run the focused tests and verify failure.**

```powershell
python -m pytest -q tests/test_agent_state_operations.py tests/test_context_delivery.py -k "guarded_context or legacy_fast or boundary_warning or state_disabled"
```

Expected: FAIL because `LocalAIApp` has no consistency guard and `/api/context/pack` ignores guard fields.

- [ ] **Step 3: Instantiate the guard at the application boundary.** In `LocalAIApp`, construct `AgentConsistencyGuard` after repository, Agent OS, and service dependencies exist. Inject the guard into `LocalAIServices` or expose it as `app.consistency_guard`; do not create a second memory, task, or repository store.

- [ ] **Step 4: Add guarded context routing.** Extend `/api/context/pack` with additive fields `task_id`, `phase`, `focus`, `preload_profile`, `changed_paths`, `base`, `staged`, `guarded`, `since_hash`, and `approval`. When `guarded` is true or `task_id`/`phase` is provided, call the guard; when absent, retain current `fast`/`full` behavior exactly.

- [ ] **Step 5: Add soft-stop task transitions.** For boundary/high-risk warnings, transition an active task to `WAITING` with a checkpoint containing warning IDs and next action. Accept `approval` or an existing coordinator decision to resume. Ordinary warnings only require `override_reason` and persist a `decision` memory record. Never delete edits or rewrite Git history.

- [ ] **Step 6: Run focused tests and commit.**

```powershell
python -m pytest -q tests/test_agent_state_operations.py tests/test_context_delivery.py
git add src/local_ai_hub/app.py src/local_ai_hub/http_server.py src/local_ai_hub/agent_tasks.py tests/test_agent_state_operations.py tests/test_context_delivery.py
git commit -m "feat: wire consistency guard into guarded context API"
```

## Task 6: Extend MCP schema and generated agent guidance

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:202-285,400-430,1040-1100,1380-1425`
- Modify: `src/local_ai_hub/features.py:152-205`
- Modify: `src/local_ai_hub/generator.py` in the existing MCP schema and policy/reference generation functions
- Modify: `docs/MCP_AND_AGENTS.md`
- Modify: `docs/INSTALL_PROMPT.md`
- Modify: `README.md`
- Modify: `FEATURES.md`
- Test: `tests/test_mcp_compact_transport.py`
- Test: `tests/test_feature_surface_parity.py`
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write failing MCP tests.** Add tests named `test_repo_context_schema_exposes_phase_focus_and_guard_fields`, `test_repo_context_forwards_adaptive_fields`, `test_repo_context_response_stays_compact`, and `test_generated_guidance_requires_context_pack_before_nontrivial_edits`. Mock `HubClient.post` and assert the request sent to `/api/context/pack` includes task ID, phase, focus, preload profile, budget, and guarded mode.

- [ ] **Step 2: Run the focused tests and verify failure.**

```powershell
python -m pytest -q tests/test_mcp_compact_transport.py tests/test_feature_surface_parity.py tests/test_setup.py -k "context_schema or adaptive_fields or compact or context_pack"
```

Expected: FAIL because the public signature and generated guidance do not expose the new additive fields.

- [ ] **Step 3: Extend the existing `local_ai_repo` signature.** Add `phase: str = ""`, `focus: list[str] | None = None`, `preload_profile: str = ""`, `guarded: bool = False`, `changed_paths: list[str] | None = None`, `since_hash: str = ""`, `approval: str = ""`, and `override_reason: str = ""`. Forward these only for `action="context"`; retain all existing actions and defaults.

- [ ] **Step 4: Update action descriptions and generated references.** Describe `context` as the default adaptive pack for non-trivial repository work. Require agents to call it before planning/editing/reviewing, cite returned evidence IDs, reuse candidates before new abstractions, and record override reasons. State that deterministic evidence is authoritative and local models only compose bounded context.

- [ ] **Step 5: Preserve schema parity and compact output.** Update `FeatureSet.supported_repo_actions`, schema generation, and tests so the action enum remains identical to the runtime. Keep the new fields additive and ensure `_compact` removes raw model/debug payloads unless explicitly requested.

- [ ] **Step 6: Run focused tests and commit.**

```powershell
python -m pytest -q tests/test_mcp_compact_transport.py tests/test_feature_surface_parity.py tests/test_setup.py
git add src/local_ai_hub/mcp_server.py src/local_ai_hub/features.py src/local_ai_hub/generator.py docs/MCP_AND_AGENTS.md docs/INSTALL_PROMPT.md README.md FEATURES.md tests/test_mcp_compact_transport.py tests/test_feature_surface_parity.py tests/test_setup.py
git commit -m "feat: expose adaptive guarded context to all agents"
```

## Task 7: Automate evidence memory, completion audit, and telemetry-safe metrics

**Files:**
- Modify: `src/local_ai_hub/agent_consistency.py`
- Modify: `src/local_ai_hub/agent_verification.py:281-620`
- Modify: `src/local_ai_hub/agent_memory.py:330-430`
- Modify: `src/local_ai_hub/services.py` telemetry integration near adaptive context
- Test: `tests/test_agent_verification.py`
- Test: `tests/test_agent_memory.py`
- Test: `tests/test_agent_consistency.py`

- [ ] **Step 1: Write failing audit/memory tests.** Add tests named `test_guard_records_verified_finding_after_discovery`, `test_guard_records_reuse_decision_and_rejected_approach`, `test_soft_stop_override_records_decision`, `test_completion_audit_maps_criteria_to_evidence_and_receipts`, `test_completion_audit_reports_unresolved_contract_mismatch`, and `test_guard_metrics_store_categories_without_raw_prompt_or_source`.

- [ ] **Step 2: Run the focused tests and verify failure.**

```powershell
python -m pytest -q tests/test_agent_verification.py tests/test_agent_memory.py tests/test_agent_consistency.py -k "guard_records or soft_stop or completion_audit or metrics"
```

Expected: FAIL because automatic guard memory and consistency completion output do not exist.

- [ ] **Step 3: Add milestone memory recording.** Implement guard methods `record_finding`, `record_reuse_decision`, `record_decision`, `record_rejected_approach`, `record_unknown`, and `record_validation`. Each writes compact values with evidence IDs, repository revision, path/symbol refs, task relation, confidence, and bounded retention. Deduplicate by stable key plus revision.

- [ ] **Step 4: Extend completion output.** Add a consistency section to `VerificationStore.completion` or a guard-owned completion audit that reports criterion mappings, drift warnings, reuse decisions, contract mismatches, unsupported claims, stale records, and current-revision receipt coverage. Keep existing completion gate behavior unchanged for callers that do not request the consistency section.

- [ ] **Step 5: Add metadata-only metrics.** Record categorized counters for reuse candidates, reuse accepted/rejected, warnings by severity, unknown claims, contract mismatches, duplicate context reuse, and degraded local-model fallback. Do not record task text, source snippets, prompts, or model output.

- [ ] **Step 6: Run focused tests and commit.**

```powershell
python -m pytest -q tests/test_agent_verification.py tests/test_agent_memory.py tests/test_agent_consistency.py
git add src/local_ai_hub/agent_consistency.py src/local_ai_hub/agent_verification.py src/local_ai_hub/agent_memory.py src/local_ai_hub/services.py tests/test_agent_verification.py tests/test_agent_memory.py tests/test_agent_consistency.py
git commit -m "feat: persist consistency findings and completion audit"
```

## Task 8: Add release documentation, fallback coverage, and full verification

**Files:**
- Modify: `docs/CONFIGURATION.md`
- Modify: `docs/HTTP_API.md`
- Modify: `docs/TESTING.md` if the project test gate is documented there
- Modify: `AGENTS.md` only if generated policy text does not cover the new default flow
- Test: `tests/test_release_contract.py`
- Test: `tests/test_release_runtime.py`
- Test: `tests/test_async_coordination_reliability.py`
- Test: `tests/test_agent_state_reliability.py`

- [ ] **Step 1: Add documentation tests and fallback tests.** Cover missing preload files, unavailable code intelligence, local-model timeout, disabled Agent OS, unchanged delta packs, and legacy context callers. Assert every degraded result contains a concise machine-readable warning and remains useful.

- [ ] **Step 2: Update documentation.** Document `[context.preloads]`, `local_ai_repo(action="context")`, phase values, evidence IDs, soft-stop severity levels, memory promotion/stale behavior, and the rule that local-model composition cannot override deterministic evidence.

- [ ] **Step 3: Run targeted release tests.**

```powershell
python -m pytest -q tests/test_release_contract.py tests/test_release_runtime.py tests/test_async_coordination_reliability.py tests/test_agent_state_reliability.py
```

Expected: PASS with no changes to unrelated dashboard or telemetry work.

- [ ] **Step 4: Run repository validation through the command broker.** Use `local_ai_command(action="run")` for the required gates after the indexed impact/review pass:

```text
python tools/release_check.py
python -m compileall -q src tools tests
python -m pytest -q
python tools/selftest.py
```

- [ ] **Step 5: Run indexed impact and security review.** Run `local_ai_repo(action="review_diff")` and `local_ai_repo(action="security_audit")` for the feature diff. Resolve findings affecting evidence provenance, path traversal, redaction, model claims, state writes, or backward compatibility.

- [ ] **Step 6: Inspect the final diff and commit the integration.**

```powershell
git status --short
git diff --check
git diff --stat HEAD~8..HEAD
git commit -m "feat: complete agent consistency context guard"
```

## Spec coverage self-review

- Default-on enforcement: Tasks 5-6.
- Execution contract and non-goals: Tasks 2 and 5.
- Evidence memory vocabulary, provenance, confidence, revision, stale/conflict: Tasks 1 and 7.
- Reuse-first checks and rejection reasons: Task 2.
- Hallucination controls and `unknown`: Tasks 2 and 4.
- BE/FE contract matrix: Task 2.
- Soft-stop warning, waiting/approval, and durable decisions: Tasks 2, 5, and 7.
- Adaptive context command, deterministic-first pipeline, preload, local relevance, post-process, cache, delta: Tasks 3-4 and 6.
- Completion traceability and verification: Task 7.
- Fallbacks, compatibility, documentation, and tests: Task 8.

## Plan self-review

- No task relies on a new public MCP tool; the existing `local_ai_repo` action is extended additively.
- No task writes raw prompt/source/model output to memory or telemetry.
- Existing unguarded context behavior remains available when guard fields are absent.
- `MemoryStatus.STALE`, `ConsistencyRequest`, `GuardWarning`, and `AdaptiveContextPack` names are used consistently across tasks.
- Every implementation task starts with a failing test, runs a bounded focused command, implements one responsibility, verifies it, and commits.
