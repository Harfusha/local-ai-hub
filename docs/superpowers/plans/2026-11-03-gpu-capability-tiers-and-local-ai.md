# GPU Capability Tiers and Local AI Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. The main agent owns implementation and integration; delegate only when explicitly authorized. Checkboxes track deliverables, not evidence of completion.

**Goal:** Expose, recommend and execute local-model capabilities according to hardware profile, actual backend readiness and measured task quality, while making useful deterministic results optionally AI-assisted.

**Architecture:** A single capability registry and resolver supplies MCP discovery, generated instructions, runtime admission and dashboard explanations. Deterministic evidence remains authoritative; model enrichments are bounded, clearly identified and optional. Local autonomous work remains explicitly authorized, scoped and independently reviewed.

**Tech stack:** Existing Python 3.11+ Local AI Hub, MCP and HTTP surfaces, current model providers, pytest and the existing evaluation and telemetry infrastructure.

**Spec:** This document is the self-contained design and execution plan. Profile assignments and thresholds below are proposed defaults, not current behavior or measured guarantees.

## Context and constraints

- The user wants weaker profiles to omit unsuitable actions from MCP and generated agent instructions, not merely route them to smaller models. Runtime enforcement must agree.
- Current evidence: `FeatureSet` derives flags from configuration; `operation_actions` filters registry actions by feature requirements; `generator.py` emits work guidance when the work orchestrator is enabled. That condition does not itself test the GPU profile. `hardware.py` and `model_policy.py` already implement profile/model routing; reuse them.
- `local_ai_repo` adaptive context can rank/compress grounded evidence; `solve` supports a bounded semantic pass. `local_ai_task` offers separate compression, analysis, review, vision and evaluation; `local_ai_work` offers constrained bounded changes. `enriched_search` adds source content, not necessarily model summaries.
- These observations do not establish complete HTTP coverage, runtime behavior, installed models, measured quality or 5070 Ti utilization. Inventory and verify first. Reuse existing plans and implementation; do not duplicate them.
- Existing single-owner, authorization, path confinement, writer lease, broker receipt, cancellation, token-budget and evidence contracts remain authoritative. Never fabricate test results, receipts, savings, GPU use or model quality. Do not change the preprocessing provider silently.
- Security decisions and final verification remain with the primary agent. No unrestricted autonomous edits. Explicit operator permissions and task-specific quality evidence remain mandatory regardless of tier.
- Sync user-facing tool/policy/schema/default changes into both `docs/INSTALL_PROMPT.md` and `docs/UPDATE_PROMPT.md` and applicable project instructions. Preserve root, session and task identity.

## Proposed capability policy

Profiles are ceilings, not proof of readiness. Resolve effective profile from existing hardware policy and explicit user overrides; a missing or unknown profile takes the conservative path. Do not infer actual GPU execution from configured names. A capability is usable only when its tier, feature flag, permissions, provider/model capability, health and required evaluation are satisfied. Make unavailable reasons observable without leaking private state.

- **`cpu`, `integrated`, `low`:** deterministic search, code indexes, source and existing safe utilities. Optional bounded extraction/compression only when a suitable model and backend are available. No autonomous editing capability or work recommendation.
- **`balanced`:** additionally allow evaluated evidence-grounded summaries, reranking, diff explanation and limited analysis. No autonomous editing recommendation or bounded edit admission by default.
- **`high`:** additionally allow evaluated cross-file analysis and design, supported vision, and explicitly authorized bounded local implementation, subject to model-specific quality gates and existing work limits.
- **`max`:** same capability classes as `high`, with separately measured model/context/concurrency limits. More VRAM alone does not grant a new authority.
- Embeddings, rerankers, vision, transcription and generation have distinct provider/device checks; do not pretend Whisper CPU transcription uses GPU. Capabilities may remain unavailable even at `max`.
- Management and recovery actions for already submitted work (`status`, `wait`, `get`, `cancel`, and any necessary safe recovery) must remain accessible after a downgrade or outage, with existing authorization. Never hide or strand an active job.
- Define any deliberate manual override explicitly, with authorized scope, audit reason and a clear distinction between hardware suitability and permissions. An override must not manufacture evaluation evidence, bypass path fences or enable unsafe work.

## Workstream 1 — Inventory and baseline

**Likely owners:** `src/local_ai_hub/operation_contracts.py`, `features.py`, `hardware.py`, `model_policy.py`, `mcp_server.py`, `generator.py`, HTTP routes and existing tests. Confirm actual owners before editing.

- [x] Inspect current Git state and existing plans; preserve concurrent and unrelated changes. Record revision, relevant existing tasks and plan links in `docs/LOCAL_MODEL_CAPABILITY_INVENTORY.md` (baseline HEAD `5939aba3d8a4fc04eec3831da6ee2312bfc0a0d2`, existing dirty changes preserved; Agent OS task `task_524dd92de739`).
- [x] Inventory every exposed MCP action and relevant HTTP model route: deterministic, embedding/reranker, optional LLM enhancement, direct inference, mutation, or job management. Record gates, profile behavior, instructions, authorization, evidence provenance and tests. Distinguish implementation, configuration and live availability. RAG reranking is now explicitly classified and gated in the inventory.
- [x] Trace automatic model calls versus opt-in calls, especially `search`, `context`, `solve`, `review_diff`, test/log diagnostics and RAG. Identify whether long-output summaries already exist before designing another path. Existing long-search summary is opt-in; RAG retrieval stays separate from synthesis, and RAG reranking has an independent default-off gate.
- [x] Capture baseline exposure and generated guidance for each profile with deterministic fixtures. Inventory actual work admission and recovery behavior across profile changes. Do not assume an MCP action name is an HTTP path. Baseline suites and MCP/HTTP recovery mapping are linked from the inventory; no inference or GPU use is implied.
- [x] Deliver a checked-in capability inventory or update the existing authoritative inventory, linking current code and explicitly marking unknowns.

**Acceptance:** Each proposed capability maps to an existing implementation, a documented gap or an explicit decision not to add it. Baseline tests establish current behavior; no inference run or GPU usage is implied by static inventory.

## Workstream 2 — Shared capability registry and policy

**Likely owners:** operation contracts and feature detection, hardware/model policy; add a narrowly scoped capability module only if current ownership cannot express the policy cleanly.

- [x] Define stable capability IDs, minimum tier, operation/action/mode mapping, optional backend requirements, authority class, quality-gate requirement and failure reason. Keep execution permissions independent from hardware selection.
- [x] Build one resolver from effective profile, explicit configuration, provider/model capability, readiness and applicable evaluation. Record whether a result is ready, disabled, unsupported, unknown or blocked by quality; distinguish static discovery from transient runtime health. Do not perform model inference during schema generation.
- [x] Write parameterized tests across all profiles, overrides, feature flags, missing/malformed providers, unavailable/unevaluated models and profile changes. Prove `high` and `max` do not bypass permissions or quality gates.
- [x] Implement the smallest shared policy needed to pass tests; preserve existing project overrides and existing model routing. No tenant fields or parallel compatibility contract.
- [x] Test safe discovery defaults and manage/cancel/recovery access after downgrade and provider failure.

**Acceptance:** One resolved policy produces reproducible capability decisions and explicit reasons. Existing safe deterministic actions and active-job recovery remain available.

## Workstream 3 — MCP, HTTP and instruction parity

**Likely owners:** `operation_contracts.py`, `mcp_server.py`, `generator.py`, HTTP dispatch and prompt documents; use the current transport ownership discovered in workstream 1.

- [x] Add tests asserting exact action/mode exposure and generated instructions for every profile. On lower tiers omit unsupported creation/edit operations and their promotional text; keep safe job management available. If a shared action has both safe and restricted modes, enforce mode admission even when schema cannot express dynamic distinctions.
- [x] Consume the shared resolver in MCP discovery and instructions; retain compact public tools and avoid inventing separate endpoints merely for tiers. Define schema refresh/reconnect behavior when configuration changes.
- [x] Enforce the same restrictions server-side for MCP and HTTP, including direct calls that bypass discovery. Return stable, actionable reasons; preserve security and existing request contracts. Test dynamic changes between discovery and execution.
- [x] Expose effective profile, capability state and reason in existing dashboard/status surfaces without expensive inference or sensitive trace disclosure. Sync both canonical prompts and relevant generated guidance.
- [x] Keep RAG reranking hidden below `balanced` and until the default-off `features.local_reranking` release gate is enabled; enforce parity for MCP and direct HTTP calls while leaving retrieval available. Targeted operation/MCP/HTTP modules: 91 passed.

**Acceptance:** Discovery, agent instructions and runtime agree for a fixed policy snapshot; direct HTTP/MCP calls cannot bypass admission. Downgrade, reconnect and existing-job behavior are tested.

## Workstream 4 — AI-assisted deterministic operations

**Likely owners:** repository search/context/review, task compression, response projection/artifacts and existing test suites. Confirm from inventory.

- [x] Define an explicit opt-in or configured policy for bounded enhancement: input and output budgets, fast-model route, timeout, cancellation, cost/latency ceiling, root/session/evidence identity and fallback. Avoid turning every exact lookup into inference.
- [x] Start with long `search` results: keep exact matches and pagination authoritative; optionally return a separate cited summary over bounded retrieved evidence. Clearly mark incomplete coverage, model/provider, failure and truncation; never present generated statements as raw matches. Long output alone must not force inference when disabled or unavailable.
- [x] Map follow-ups independently in `docs/LOCAL_MODEL_CAPABILITY_INVENTORY.md`: reuse the existing gated model review for `review_diff`; keep impact/dependency authoritative and offer explicit high-profile `solve` separately; compress only caller-supplied test/log text; keep RAG retrieval distinct from optional `solve` synthesis. No duplicate enrichment layer is added where an existing model route already covers the need or deterministic authority is preferable.
- [x] Test short/long input, threshold boundaries, missing or malicious source, invented citations, conflicting evidence, unsupported provider, timeout, cancellation, truncation and budget overflow. `tests/test_mcp_agent_routing.py -k search_ai_summary`: 12 passed, including new cancellation and two-sided conflicting-match cases. Exact rows remain available when compression is cancelled or rejected. Stale-artifact rejection is not applicable to this synchronous summary path: it creates no persisted summary artifact; each response is bound to the current search rows/evidence IDs and root fingerprint.
- [ ] Compare fast local model with deterministic baseline on representative tasks: factuality/citation precision, omissions, latency, token and VRAM use. Record cases and regressions; never claim savings without current baseline evidence.

**Acceptance:** Each enabled enhancement supplies useful, bounded, traceable advice without silently altering or losing authoritative results. A disabled or failed model falls back visibly to deterministic output.

## Workstream 5 — Analysis and bounded autonomous work

**Likely owners:** `local_ai_task`, `local_ai_work`, existing bounded executor, broker and evaluation tests. Extend existing work rather than adding an unscoped agent.

- [x] Define read-only cross-file analysis/design through `local_ai_repo: solve`: authorized repository root, deterministic/context evidence, confidence, bounded tool loop and output, cancellation, `high` profile plus default-off semantic-analysis flag, and advisory output. Documented in `docs/LOCAL_MODEL_CAPABILITY_INVENTORY.md`; verification: `tests/unit/test_single_owner_tool_agent.py` and `tests/unit/test_tool_agent_and_trace_context_edge_cases.py` (11 passed). Role-specific quality remains unqualified until evaluation passes.
- [x] Audit current work executor: planning, tool calls, file/command limits, write authorization, leases, patch/rollback, receipts, deadline, cancellation, handoff and primary review. Verified limits: caller scope is 1–8 exact paths and 1–8 approved commands; effective plan limit is at most 16 steps; LLM-step config defaults to 24 and caps at 32; deadline accepts 30–7,200 seconds (config default 3,600); validation-command config defaults to 5 and caps at 8; patch files default to 64 and cap at 128; patch bytes default to 2 MiB and cap at 4 MiB; retries default to 2 and cap at 4. Executor revalidates persisted permissions and bounded scope, requires read permission and test+build permissions for execute/bounded, applies patch path/create/delete checks, claims a work-id writer lease and attempt fence, persists exact verification receipts, rejects stale mutation generations, and prevents completion after cancellation. Rollback/recovery, ambiguous outcomes, handoff and ownership/barrier behavior are covered by the focused executor suites above; primary-agent review remains the final acceptance owner.
- [x] Define benchmark tasks for small fixes/tests (`I1`), related files and runtime behavior (`I2`), cross-file analysis (`A1`) and design (`A2`) in `docs/agent-evaluation/local-model-gpu-cases.md`, with scoring in `local-model-gpu-scoring.md`. Fixture tests verify A1/A2 structure; target-model evaluation remains NOT_RUN until hardware admission and model identity are available. Require task-specific evaluation before bounded editing; preserve current executor fences.
- [x] Test executor scope, path/command rejection, rollback/recovery, receipts, ambiguous outcomes and ownership/barrier handling. Focused run: 293 passed, 1 skipped across `test_work_orchestrator.py`, `test_bounded_work_scope.py`, `test_bounded_work_recovery_phase.py` and `test_bounded_broker_receipts.py`; symlink case skipped because creation is unavailable. A handoff or model assertion never establishes completion. Further per-model qualification remains separate.
- [x] Keep security-sensitive decisions, unbounded changes, production actions and final integration with the primary agent. Existing explicit delegation and review requirements remain in force; local output remains advisory, and no model/handoff bypasses primary review.

**Acceptance:** Qualified `high`/`max` profiles can perform explicitly authorized, bounded work with independently inspectable evidence; lower profiles cannot initiate restricted work but can safely manage prior jobs.

## Workstream 6 — RTX 5070 Ti and hardware evaluation

- [ ] Inspect active effective profile, installed model tags, device/backend selection and memory availability through approved status and benchmark interfaces. Record observed revision, driver/backend versions, context, quantization and model identity. Do not pull models or change providers without explicit authorization.
- [ ] Benchmark representative available models and capability workloads on RTX 5070 Ti; collect real GPU residency/offload, peak VRAM, prompt and generation throughput, latency, concurrency, context length and errors. Measure warm and cold cases separately and preserve artifacts.
- [ ] Evaluate quality against task-specific labeled cases and baseline: grounded search summary, cross-file analysis, review, vision where supported and bounded edits. Report passes, failures and sample limitations; benchmark-runner success alone is not quality success.
- [ ] Use measurements to propose `high` model routes and context/concurrency limits. Define promotion thresholds and regression checks before claiming readiness. Candidate models, missing weights and unmeasured hardware remain explicitly unqualified.
- [ ] Test low-memory and provider failure behavior without synthetic success. Do not claim full 5070 Ti utilization from model size or theoretical GPU specifications.

**Acceptance:** Reproducible evidence supports each recommended route and capability; unknowns remain visible. GPU evaluation does not authorize deployment, model downloads or edits beyond the task scope.

## Order, verification and release gates

1. Inventory and baseline; identify overlap with existing plans.
2. Shared policy, then discovery/instruction/runtime parity and recovery.
3. Search enhancement first; expand only after quality and latency measurements.
4. Qualify analysis and bounded work using task-specific evaluations.
5. Benchmark the 5070 Ti and tune profile settings from observed results.

- [ ] Each independently reviewable unit gets focused failure-first tests, implementation, targeted tests and review. Keep existing tests authoritative; do not weaken acceptance to pass.
- [ ] Run relevant unit/integration suites for registry, profiles, MCP schemas, HTTP admission, generation, provenance, work authorization, cancellation and fallback. Validate documentation/prompt synchronization.
- [ ] Before release, run applicable project release checks and broader suites from `AGENTS.md`; distinguish actual command results from broker receipts and from live GPU evidence.
- [ ] Produce a final capability matrix: profile, action/mode, visibility, admission prerequisites, evidence links, model availability and measured quality. Explicitly identify unimplemented or unevaluated capabilities.
- [ ] Roll out additions behind existing explicit feature controls where appropriate. Rollback must preserve deterministic access, active job management and authorization fences. No data migration or deletion is implied by this plan.

## Implementation progress — 2026-11-03

### Checkpoint — 2026-11-03, implementation and integrated gate

- The shared registry now gates semantic analysis, repo solve/review/delegation, search summaries, vision, code generation, browser automation and bounded local work by profile and separate default-off operator flags. Unknown actions fail closed; lower profiles do not advertise restricted actions. Direct MCP and mapped HTTP inference admission share these gates. Existing-job controls remain available after downgrade.
- `local_ai_status`, live status, dashboard capability states, generated instructions, repo/task schema descriptions, inventory and both canonical prompts now expose the effective policy and explain that provider readiness and quality are not inferred from configuration. The inventory also records the async `speculative_lint` route.
- Added bounded opt-in search summaries over deterministic search evidence; the exact matches and pagination remain authoritative and the summary is separate, cited and advisory.
- Latest integrated targeted suite: **543 passed, 1 skipped** across features, instruction generation, MCP/HTTP routing, operation schemas, feature parity, async admission, work authorization/orchestration, dashboard and live status. The skip is `tests/test_bounded_work_scope.py:223` because symlink creation is unavailable. `python -m compileall -q src/local_ai_hub` passed.
- Read-only device check observed **NVIDIA GeForce RTX 5070 Ti**, driver 621.01, 16,303 MiB VRAM, 1,123 MiB in use and 0% GPU utilization at observation time. `ollama list` observed installed tags including `qwen3.5:9b-nvfp4` (5.3 GB), `qwen3.5:9b` (6.6 GB), `qwen2.5-coder:14b` (9.0 GB), `gemma4:12b` (8.0 GB), `qwen2.5vl:7b` (6.0 GB), plus smaller coding, vision and embedding models. These are inventory facts, not quality or speed evidence.
- `hubctl status` reports Hub v5.1.3 online, managed Ollama + llama.cpp backend online, 12 installed models and RTX 5070 Ti (15 GB). `local_ai_status` reports Ollama online, `active_model=null`, `vram_pressure=unknown`; the effective server profile and selected inference device remain unreported.
- One explicit 40-token `qwen3.5:9b-nvfp4` hardware-benchmark request was accepted by the Hub, but its serialized response was truncated and exposed no measurements. Do not infer throughput, VRAM residency or quality from it. The generic benchmark action also returned terminal argument-validation failure (`audio_path` unexpected), so it was not retried.
- A separate short benchmark request for installed `qwen3.5:4b-nvfp4` failed safely with `CUDA endpoint state is not safely reserved; Ollama fallback blocked`. No fallback or repeated request was attempted; runtime lease/device state must be repaired through the owning Hub path before benchmarking.
- The project-local model profile is `balanced`; global hardware configuration says `auto`. The observed GPU does not establish the server's effective profile, selected backend, GPU offload, or model quality.
- `python -m compileall -q src tools tests`, `python tools/selftest.py` and `python tools/doctor.py` passed. Doctor reports the live Hub and model providers online, but Serena's optional MCP backend is degraded. `python tools/release_check.py` failed on local checkout/runtime contents: forbidden `.merge-checks`, `.serena`, `.superpowers`, `.venv`, `.worktrees`, `.egg-info`, `state`, `tool-envs`, local `config.toml`, generated runtime files and timestamped `AGENTS.md` backup payloads. These pre-existing/local artifacts were preserved.
- Full `python -m pytest -q` was stopped at about 3% because of runtime. Its first failure was an old second-opinion test fixture that omitted the new profile/feature gates; the fixture now sets `balanced` and `features.local_semantic_analysis=true`, and that focused test passes. A fail-fast full-suite pass then cleared the first ~3% without another failure before it was stopped. Final focused integration rerun including that fixture: **553 passed, 1 skipped** in 234.48s; the skip is unavailable symlink creation.
- The requested Local AI Hub `review_diff` call did not return before its execution cell was stopped; it produced no review findings or durable receipt. It was not repeated.

### Checkpoint — 2026-11-03, safe hardware benchmark routing

- Traced the CUDA fallback rejection to `HardwareBenchmarkRunner.run`: unlike T12 runs, the regular benchmark called runtime generation directly and skipped the injected `AffinityScheduler`. Managed llama.cpp/Ollama fallback correctly refused the unreserved endpoint.
- Changed regular hardware benchmarks to execute through the scheduler when present, preserve admission and timeout outcomes, record queue wait, and fail closed when managed mixed mode has no scheduler. Non-managed standalone test runtimes retain their direct path.
- Added unit coverage for scheduler use, admission refusal without inference, and missing-scheduler fail-closed behavior. Extended mixed-backend integration cases to run the actual benchmark through scheduler preparation and verify admitted/rejected VRAM paths.
- Validation: `tests/test_benchmark_suite.py` + `tests/test_mixed_scheduler_integration.py` + benchmark timeout, T12 and surface suites: **149 passed**. The deployed Hub process was not restarted, so no post-change physical-GPU benchmark is claimed.
- Follow-up audit found `eval_suite` also called `runtime.request` directly. It now submits each case through the model scheduler and fails closed for managed mixed mode without a scheduler. The same mixed-backend integration fixture exercises eval-suite success and VRAM rejection.
- Evaluation case results now preserve scheduler timeout identity: pending requests are marked not sent/not started, while dispatched timeouts are marked outcome-unknown and non-retryable.
- Extended hardware benchmark records with sampled device-wide peak VRAM during inference; absent or malformed samples remain absent. Queue wait is recorded separately from TTFT.
- Latest focused regression set across model-quality evaluation, benchmarks, mixed-scheduler integration and canonical MCP task inputs: **143 passed**. Compile and `git diff --check` passed.
- A broader benchmark/surface run yielded **217 passed, 1 failed**: a surface benchmark triggered recursive formatting while pytest handled multiple unraisable exceptions. The exact affected surface cases passed in isolated runs; a whole-file run later failed a different scratch-cleanup case the same way. This sequence-dependent surface-suite issue remains unclassified and is not suppressed.
- Restarted the repository-managed Hub so it loaded the updated benchmark/evaluation paths; status returned online with 12 installed models and the RTX 5070 Ti. A new 40-token `qwen3.5:4b-nvfp4` benchmark then timed out in scheduler state `pending`, with `request_not_sent=true` and `operation_not_started=true`. Scheduler status after timeout showed no queued/inflight job and no active model; no inference occurred. Do not retry until dispatch readiness is understood.
- Added safe `gpu_admission_state` status (`outcome_unknown`, `external_reservation`, `background_lease`, `preparing_model`, `inference_active`, `available`) without exposing reservation owner/token. Scheduler pending timeouts now preserve a safe `wait_reason`; benchmark, T12 and `eval_suite` return that reason with timeout identity.
- Dashboard live queue summary now displays `GPU admission: <state>` (unknown when absent). Test-first assertion failed before the UI change and passed in the final focused run.
- Final focused regression set after these edits: **202 passed** across capability/hardening, benchmark, mixed scheduler, timeout identity, T12, dashboard operational surfaces and canonical task-input suites. The broader surface-suite unraisable-exception issue above remains separate and unresolved.
- Physical benchmark remains unmeasured: the only post-fix run never left `pending`; no request reached inference. The new status/wait-reason observability narrows the next diagnosis without authorizing a duplicate request.
- Restarted the repo-managed Hub after loading the wait-reason/status changes. A single bounded `qwen3.5:4b-nvfp4` run returned `scheduler_state="pending"`, `wait_reason="gpu-reservation"`, `request_not_sent=true`, `operation_not_started=true`, and `outcome_unknown=false`. This identifies an active external GPU reservation as the admission blocker; no inference was sent. Do not retry until the reservation owner clears or explains that lease.

Implemented in the current checkout:

- Added `CAPABILITY_REGISTRY` with stable capability IDs, operation/action mapping, minimum profile, backend class, authority, quality-gate label and unavailable reason. `FeatureSet` prefers the effective profile already resolved by `load_config` in `_hardware`; missing or unknown values fail closed to `low`.
- MCP action schemas, direct MCP validation, generated instructions and mapped direct HTTP semantic routes consume the shared profile policy. `local_ai_status` reports the effective configured profile plus capability availability and reasons. Deterministic `investigate` and `diagnose` remain available at all tiers.
- `local_ai_work(action="submit")` is limited to `high`/`max` and `mode="bounded"`; status, wait, get and cancel remain available below those profiles. Existing explicit scopes and work-order authorization remain in force.
- Added `features.search_summaries` as a default-off operator opt-in. At `balanced` or higher, `summarize_results=true` sends at most 8 bounded search matches / 12,000 characters to `/api/compress`; exact search rows remain authoritative and summary output is separate and advisory.
- Search summaries now require every bracketed `[path:start-end]` citation to match a retrieved source path and line range. Missing, invented or out-of-range citations reject only the generated summary; deterministic rows remain available. Input is bounded as valid JSON (max 8 matches / 12,000 characters), absolute root is withheld in favor of a fingerprint, HTTP timeout is capped at 15s, and truncated generation is rejected.
- Added `docs/LOCAL_MODEL_CAPABILITY_INVENTORY.md` and synchronized the capability policy into both canonical prompt files and `docs/MODEL_CAPABILITIES.md`.
- Focused integration validation: 489 passed, 1 skipped across feature, generator, MCP routing, bounded work, work-order and HTTP route suites.

Still open before this plan can be accepted:

- Installed-model inventory is now observed with `ollama list`, but active backend selection, effective server profile and GPU offload still need runtime evidence. The read-only evaluation report had 0 matched tasks and verdict `insufficient_evidence`. The focused hardware benchmark produced a truncated response with no usable measurements; the generic benchmark action returned terminal argument-validation error (`audio_path` unexpectedly supplied). No model was pulled. RTX 5070 Ti performance and task-quality evidence remain unproven.
- This change does not create measured task-quality evidence or claim that a model is qualified. The registry documents required quality gates, but role-specific qualification and runtime promotion evidence still need to be completed before claiming model quality or production readiness.
- Workstream 4 still needs cancellation, conflicting-evidence and real quality/latency cases. Search tests now cover citation membership/ranges, missing/unbracketed citations, malicious source instructions, valid JSON input bounds and truncated output. `review_diff` already has a model-backed review route, caller-supplied test/log text can use `compress`, and RAG-backed `context`/`solve` already exist; whether impact/dependency synthesis merits a separate opt-in remains unassessed.
- Workstream 1 inventory remains bounded to verified MCP/model-adjacent routes; other RAG, embedding/reranker and HTTP routes need source-level classification and evidence before they are promoted as local-model inference.

### Checkpoint — 2026-11-03, source-bound search summaries

- Added fail-closed citation validation for the optional search summary. Every `[path:start-end]` citation must match a path and line range returned by deterministic search. Missing, invented-path and out-of-range citations suppress only the summary and return a compact rejection reason; deterministic search rows are unchanged.
- Updated the model instruction to require the validated citation form. The summary remains advisory; source-range matching does not certify factual correctness.
- Replaced raw JSON character slicing with a structured, valid-JSON budgeter; it sends no more than 8 matches and 12,000 characters, with a root fingerprint rather than an absolute path. Compression has a 15-second hard timeout. Truncated output is rejected without exposing partial generated text as usable.
- Test-first evidence: the citation, JSON-budget, hard-timeout and truncation tests failed before implementation. The summary-specific suite passed **10/10**; the broader MCP agent-routing, feature, generator and operation-contract suites passed **279/279**.
- Remaining: complete adversarial/timeout/truncation/quality cases, assess impact synthesis, finish route inventory, and obtain real local-model/GPU measurements. Current reservation blocker remains `gpu-reservation`; no inference or quality claim is established.


### Checkpoint — 2026-11-03, test regression resolution and release validation

- Resolved all 15 previous test failures across `test_llama_cpp_runtime.py`, `test_surface_audit_policy.py`, `test_review_diff_path_scope.py`, `test_brief_status_authority.py`, `test_mcp_rag_work_action_contract.py`, `test_t19_sdk_scenarios.py`, and `test_task_context_task_integration.py`.
- Preserved `hub_online` and `degraded` authoritative fields in `_mcp_bounded_error` within `mcp_server.py`.
- Synchronized `output_schema_fields` in `docs/agent-surface-audit.json` for `MCP local_ai_status.brief` to include `capabilities` and `hardware_profile`.
- Replaced brittle port 0 patch in `test_llama_cpp_runtime.py` with dynamic allocation of free port upon port 12438 collision.
- Fixed capability and feature gate test fixtures across review_diff, work submit, delegate conversation, and task reason suites.
- Full targeted validation cohort (7 suites, 161 tests): **161 passed, 36 subtests passed, 0 failed**.
- System validation passes: `compileall` (0 errors), `git diff --check` (clean), `release_check.py --allow-installed` (OK), `selftest.py` (6/6 OK), `audit_agent_surface.py` (0 errors), `security_audit` (0 blocking production findings).
- GPU reservation status: `state/external-gpu-reservation` fence active with hash `fe80438e54e6d1e808a9e72dbc0f5a909073cb48155fdcf2c72c0188e09886fb`. Pre-image token unexposed; file not deleted and token not fabricated per rules. Physical benchmark remains blocked by `gpu-reservation`.
- Agent OS checkpoints updated for `task_524dd92de739` and `task_a14aebc48690`.
