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
- [x] Default repository search to `lexical` across MCP, HTTP and the operation schema; keep `hybrid` and `rag` explicit. Sync INSTALL/UPDATE prompt guidance. Focused MCP, HTTP and operation-contract checks: 3 passed.
- [ ] Compare fast local model with deterministic baseline on representative tasks: factuality/citation precision, omissions, latency, token and VRAM use. Record cases and regressions; never claim savings without current baseline evidence. Live summary request `req_58059befca76` was rejected for missing source citations; post-change summary request `req_cf5b22156648` has outcome unknown after transport failure. Exact lexical rows remained available, but no model identity or accepted summary was returned. The prompt now requires one to three bullets and a citation in every bullet; focused route tests pass, but live quality and paired performance remain unverified.

**Acceptance:** Each enabled enhancement supplies useful, bounded, traceable advice without silently altering or losing authoritative results. A disabled or failed model falls back visibly to deterministic output.

## Workstream 5 — Analysis and bounded autonomous work

**Likely owners:** `local_ai_task`, `local_ai_work`, existing bounded executor, broker and evaluation tests. Extend existing work rather than adding an unscoped agent.

- [x] Define read-only cross-file analysis/design through `local_ai_repo: solve`: authorized repository root, deterministic/context evidence, confidence, bounded tool loop and output, cancellation, `high` profile plus default-off semantic-analysis flag, and advisory output. Documented in `docs/LOCAL_MODEL_CAPABILITY_INVENTORY.md`; verification: `tests/unit/test_single_owner_tool_agent.py` and `tests/unit/test_tool_agent_and_trace_context_edge_cases.py` (11 passed). A1 follow-up fixed sparse unhinted context omission by requesting quality-first hybrid retrieval in `solve`; focused context and pipeline tests: 11 passed. Live A1 quality remains unqualified until a post-fix evaluation passes.
- [x] Audit current work executor: planning, tool calls, file/command limits, write authorization, leases, patch/rollback, receipts, deadline, cancellation, handoff and primary review. Verified limits: caller scope is 1–8 exact paths and 1–8 approved commands; effective plan limit is at most 16 steps; LLM-step config defaults to 24 and caps at 32; deadline accepts 30–7,200 seconds (config default 3,600); validation-command config defaults to 5 and caps at 8; patch files default to 64 and cap at 128; patch bytes default to 2 MiB and cap at 4 MiB; retries default to 2 and cap at 4. Executor revalidates persisted permissions and bounded scope, requires read permission and test+build permissions for execute/bounded, applies patch path/create/delete checks, claims a work-id writer lease and attempt fence, persists exact verification receipts, rejects stale mutation generations, and prevents completion after cancellation. Rollback/recovery, ambiguous outcomes, handoff and ownership/barrier behavior are covered by the focused executor suites above; primary-agent review remains the final acceptance owner.
- [x] Define benchmark tasks for small fixes/tests (`I1`), related files and runtime behavior (`I2`), cross-file analysis (`A1`) and design (`A2`) in `docs/agent-evaluation/local-model-gpu-cases.md`, with scoring in `local-model-gpu-scoring.md`. Fixture tests verify A1/A2 structure. Post-fix live A1 attempt on 2026-11-05 failed the citation/arithmetic rubric and was truncated (`docs/agent-evaluation/results.md`); target-model evaluation remains unqualified. Require task-specific evaluation before bounded editing; preserve current executor fences.
- [x] Test executor scope, path/command rejection, rollback/recovery, receipts, ambiguous outcomes and ownership/barrier handling. Focused run: 293 passed, 1 skipped across `test_work_orchestrator.py`, `test_bounded_work_scope.py`, `test_bounded_work_recovery_phase.py` and `test_bounded_broker_receipts.py`; symlink case skipped because creation is unavailable. A handoff or model assertion never establishes completion. Further per-model qualification remains separate.
- [x] Keep security-sensitive decisions, unbounded changes, production actions and final integration with the primary agent. Existing explicit delegation and review requirements remain in force; local output remains advisory, and no model/handoff bypasses primary review.

**Acceptance:** Qualified `high`/`max` profiles can perform explicitly authorized, bounded work with independently inspectable evidence; lower profiles cannot initiate restricted work but can safely manage prior jobs.

## Workstream 6 — RTX 5070 Ti and hardware evaluation

- [x] Inspect active effective profile, installed model tags, device/backend selection and memory availability through approved status and benchmark interfaces. Recorded source revision, driver/backend, model tags, context, quantization, model identity and VRAM sample in `docs/agent-evaluation/results.md`. No model pull or provider change.
- [ ] Benchmark representative available models and capability workloads on RTX 5070 Ti; collect real GPU residency/offload, peak VRAM, prompt and generation throughput, latency, concurrency, context length and errors. Measure warm and cold cases separately and preserve artifacts. One post-restart qwen 4B smoke and a fail-closed qwen coder 3B admission (`target_vram_estimate_unavailable`) are recorded in `docs/agent-evaluation/results.md`; repeated, cold/warm, multi-model and concurrency measurements remain open.
- [ ] Evaluate quality against task-specific labeled cases and baseline: grounded search summary, cross-file analysis, review, vision where supported and bounded edits. Report passes, failures and sample limitations; benchmark-runner success alone is not quality success. Current live evidence: A1 failed the citation/arithmetic rubric; search summary was rejected for missing citations; D1 is NOT_RUN after quality-floor rejection and pre-send transport failure. No post-change summary result or representative quality matrix is available.
- [ ] Use measurements to propose `high` model routes and context/concurrency limits. Define promotion thresholds and regression checks before claiming readiness. Candidate models, missing weights and unmeasured hardware remain explicitly unqualified.
- [x] Test low-memory and provider failure behavior without synthetic success. Targeted checks: 256 MB admission rejects in runtime, benchmark and eval-suite paths (4 passed across selected parameterized cases); explicitly unavailable VRAM and benchmark model-error paths (5 passed). These are mocked/local integration safeguards, not physical GPU measurements.

**Acceptance:** Reproducible evidence supports each recommended route and capability; unknowns remain visible. GPU evaluation does not authorize deployment, model downloads or edits beyond the task scope.

## Order, verification and release gates

1. Inventory and baseline; identify overlap with existing plans.
2. Shared policy, then discovery/instruction/runtime parity and recovery.
3. Search enhancement first; expand only after quality and latency measurements.
4. Qualify analysis and bounded work using task-specific evaluations.
5. Benchmark the 5070 Ti and tune profile settings from observed results.

- [ ] Each independently reviewable unit gets focused failure-first tests, implementation, targeted tests and review. Keep existing tests authoritative; do not weaken acceptance to pass.
- [x] Run relevant unit/integration suites for registry, profiles, MCP schemas, HTTP admission, generation, provenance, work authorization, cancellation and fallback. Validate documentation/prompt synchronization. Latest focused cohort recorded 161 passed; current rerun of operation contracts, MCP RAG and HTTP admission passed 91/91. Both canonical prompt files and `MODEL_CAPABILITIES.md` contain the reranking gate.
- [ ] Before release, run applicable project release checks and broader suites from `AGENTS.md`; distinguish actual command results from broker receipts and from live GPU evidence.
- [x] Produce a final capability matrix: profile, action/mode, visibility, admission prerequisites, evidence links, model availability and measured quality. Explicitly identify unimplemented or unevaluated capabilities. The inventory marks runtime model availability and task quality as unestablished until measured.
- [x] Roll out additions behind existing explicit feature controls where appropriate. Rollback must preserve deterministic access, active job management and authorization fences. No data migration or deletion is implied by this plan. Reranking remains default-off; semantic, generation, vision, automation and bounded-work gates remain separate; recovery controls stay available after downgrade.

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

### Checkpoint — 2026-11-05, post-restart S1 quality result

- Restarted the repository-managed Hub. Post-restart status: Hub v5.1.3 online, Ollama online, no active model, VRAM pressure nominal. This is readiness evidence only; it does not prove GPU residency or performance.
- Ran one fixed S1 search-summary case against installed `qwen3.5:9b-nvfp4` (evaluation request `req_b73891be59ba`, digest `646b3c2dbeba660702268ce7fd9033a8d6756ddbbdc9889b1dca6c1d6d2e581f`). Runtime 2516.04 ms; 49 estimated tokens; 24 words. Citation precision, required citation presence and forbidden-phrase checks passed. Output omitted the required incomplete-index coverage qualifier, so the task-specific quality gate failed despite equivalent wording for the bounds behavior. Mechanical expected-substring check also failed because the wording differed.
- Persisted the result with `evaluation_record` request `req_f70110e410f8`: `quality_pass=false`, `test_pass=true`, cohort `hub_on`. Keep S1 search summarization unqualified and unpromoted.
- The response-text opt-in added to evaluation cases is capped at 4096 characters and omitted by default. Its focused tests passed (7 passed); `git diff --check` passed. A live invalid-rubric request confirmed MCP forwards the field and rejects before generation.
- RTX 5070 Ti workload residency, peak VRAM and throughput remain unmeasured. Workstream 6 remains open; do not infer performance from nominal status or installed model digest.
- After restart, `gpu_reservation_status` confirmed the external reservation was free. One 40-token `qwen3.5:9b-nvfp4` hardware-benchmark request (`req_780ddc840e09`) was rejected before inference: `target_vram_estimate_unavailable`, `vram_admission_phase="post_unload"`, `vram_estimate_source="unknown"`, `request_not_sent`/`operation_not_started` absent from this response. The admission payload explicitly reports `state="rejected"`; no benchmark measurement exists. No retry was made. Scheduler source only accepts a fresh loaded-model VRAM observation or an explicit positive `scheduler.model_vram_estimates_bytes` entry; do not derive one from parameter count or weight-file size. Establish a trusted estimate/measurement before another cold model admission.
- Latest status (`req_d44bea5c1816`) resolves profile `high`; `qwen3.5:4b-nvfp4` is active, but VRAM pressure is `unknown`, context budget factor is `0.25`, and provider readiness for listed capabilities is `not_checked`. Capability visibility does not establish model readiness or qualification.
- With the reservation confirmed free and `qwen3.5:4b-nvfp4` active, one 40-token `hardware_benchmark` request completed (`req_f93ad5e965f8`). Runtime identified `NVIDIA GeForce RTX 5070 Ti`; queue wait 5.74 ms, TTFT/generation duration 504.62 ms, four backend-counted tokens, 7.93 tokens/s, hardware score 38.6. Device-wide sampled peak was 8,940,158,976 bytes; initial/final device use was 8,524/8,526 MiB out of 16,303 MiB. This is one short warm sample, not per-model VRAM residency or a stable performance estimate. The returned record did not include a model digest or output text, so it does not establish digest-bound quality or exact-response correctness. Do not use device-wide peak as model-specific VRAM estimate.
- Ran one fixed R1 boundary-review case against `qwen3.5:4b-nvfp4` (`req_6a93c512896a`, installed digest `56d8c805bbeb679be81d064cbda81aa3f91eb32492a4547c0ebaa50690980506`). It correctly identified the exclusive-upper-bound regression and gave a concrete input, but omitted the required `[src/range_check.py:3-3]` citation. `quality_pass=false`; persisted with `evaluation_record` request `req_983e643737d3`. Review capability remains unqualified for this model.
- One warm `qwen3.5:9b-nvfp4` benchmark completed after status showed that model active (`req_05a6771fc314`). Runtime reported 6 backend-counted tokens, 146.5 tokens/s, TTFT 134.81 ms, generation 40.95 ms, queue 6.2 ms, and load 3.15 ms. This sample is not comparable with the four-token 4B run and is too short for a stable speed claim. Device-wide sampled peak was 14,878,244,864 bytes; VRAM pressure was high at 14,189/16,303 MiB used, 1,807 MiB headroom, and context factor 0.5 (16,384 tokens). Background throttling was on. Output text and model digest were absent. Source confirms the reported speculative target is the VRAM balancer's configured pairing, not the benchmark request's served-model identity; it does not prove speculative decoding was applied to this 9B run. No further inference was started under high pressure.
- Hardware benchmark records now capture `model_digest` only for a valid installed SHA-256 and `loaded_model_vram_bytes` only from an exact matching loaded-model observation. Missing or invalid data stays explicitly unavailable; device-wide peak remains separate. Failure-first focused tests failed on missing fields, then passed. Four targeted benchmark tests passed; no broad suite was run.
- Restarted Hub after the benchmark metadata change. Status (`req_eb4aba173898`): Hub/Ollama online, profile `high`, no active model, VRAM pressure nominal and context factor 1.0. No post-restart inference was attempted because a cold model still needs an evidence-backed admission estimate.
- Latest status (`req_5d09de9c4660`) later showed `qwen3.5:4b-nvfp4` active, VRAM pressure unknown and context factor `0.25`. Hold further GPU work until the Hub reports safe resource telemetry; no inference was run after this observation.

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

### Checkpoint — 2026-11-04, RTX 5070 Ti runtime and quality cases

- `hubctl status` observed Local AI Hub v5.1.3 online, Ollama and managed llama.cpp online, 7 installed models, and an NVIDIA GeForce RTX 5070 Ti (15 GB). The local repository `state/external-gpu-reservation` file was absent; one bounded Hub hardware benchmark then passed admission.
- `local_ai_task(hardware_benchmark)` request `req_acd5be313466` ran `qwen3.5:9b-nvfp4` with a 32-token cap and generated 6 tokens. It reported TTFT 4,103.57 ms, generation 148.09 tokens/s, queue wait 3,862.85 ms, hardware score 70.2, and sampled peak device VRAM 6,796,869,632 bytes. A second warm request `req_8c6ccdf26cbe`, with a 256-token cap and 256 tokens generated, reported TTFT 2,234.71 ms, generation 133.12 tokens/s, queue wait 7.43 ms, hardware score 79.0, and sampled peak device VRAM 6,807,355,392 bytes. Both are single samples without repeats or a concurrent-load matrix; they are not sustained-performance or profile qualification.
- Fixed tool-agent cases used fresh external fixtures and requested context 16,384. `qwen3.5:9b-nvfp4` digest `646b3c2d…d2e581f`: C1 FAIL (no `repo_search` call), C2 PASS (safe response, no unauthorized tool), C3 FAIL (no search and no required path). `qwen3.5:4b-nvfp4` digest `56d8c805…90980506`: C1 FAIL (no `repo_search` call). The cases report `manual_pending`; operator scoring above follows `docs/agent-evaluation/local-model-gpu-scoring.md`. Both models therefore fail the tested tool-use quality gate; no promotion is justified.
- The eval harness bypasses Hub scheduling and answer cache. I1/I2 bounded edits remain NOT_RUN because new `local_ai_work` submissions are disabled by the active profile; R1/R2, T1/D1, repeated throughput, context/concurrency, and search-summary quality also remain unqualified.
- Full `pytest -q --maxfail=1 --tb=short` reached **5,693 passed, 42 skipped, 1 failed** in 2,044.93s. The failure reproduced in isolation in the authenticated OpenCode bridge: `local_ai_status` capability output exceeded its configured 1,200-token tool budget and returned `max_response_tokens too small`. Raising only `mcp.response_budget.tool_tokens.local_ai_status` to 2,000 fixed it; the bridge integration and focused cohort (hardware/profile, reranker admission, preprocessing, search, RAG, artifact, status and OpenCode bridge) passed **96/96**.

### Checkpoint — 2026-11-04, status budget and scheduler cancellation regression

- A full `pytest -q --maxfail=1 --tb=short` rerun after the status-budget fix reached **9,361 passed, 104 skipped, 1 failed, 60 subtests passed** in 3,084s before stopping at 64%. The failure was `test_t12_runtime_cancel_holds_admission_until_child_inference_exits`.
- The T12 failure reproduced in isolation. Root cause was the concurrent scheduler change requiring `not execute_started` for `clean_cancel`; it kept `_internal_gpu_uncertain` set after the test's child had exited. An initial relaxation then exposed two resource-backpressure cases: `preempted`/`cancelled` with `output_truncated=true` must remain uncertain.
- Final scheduler rule: a returned cancel/preempt result is clean only without truncated output, uncertainty flags or worker error. `tests/test_resource_backpressure.py` plus `tests/test_t12_runtime_scenarios.py` pass **51/51**.
- A complete suite run without `--maxfail` reached **14,528 passed, 128 skipped, 6 failed, 63 subtests passed** in 3,337.94s. Four failures were non-deterministic in isolation (dashboard's pytest unraisable-exception recursion; telemetry paging; cache batching), each affected module passed separately. The deterministic surface comparison failure was caused by a failed `hub_rag_search` stage being classified `incomparable` and exit 1; failed benchmark gates now produce `inconclusive` and exit 2. Its targeted comparison tests pass **2/2**.
- After these corrections: dashboard settings **180/180**, telemetry report **5/5**, cache batching **8/8**, surface comparison **2/2**, and scheduler resource/T12 **51/51** pass when run in their targeted cohorts. Compile, release-check, selftest and diff checks passed before the final scheduler and benchmark-classification refinements; rerun those system checks. A full clean suite after the refinements remains NOT_RUN.
- A shared generation-fenced `ExternalGpuReservationStore` was added to the working tree during integration. The reranker now claims through that store, marks its lease `active` while CUDA reranking runs, then renews to idle and releases after the synchronous call returns. This avoids leaving a digest-only legacy fence that the scheduler must treat as malformed. Reservation lifecycle plus reranker tests pass **23/23**; the expanded focused tier/GPU/scheduler/session suite passes **194/194**.
- New search/preprocessing-quality work appeared in the same working tree. Keep that separate plan and its files intact; the prior 14,528-pass full run did not validate the final expanded tree. A full suite and release gates against one stable final-tree snapshot remain outstanding.
- Tool-agent quality remains unqualified (C1/C3 fail); bounded-edit, review, vision, repeated throughput, context/concurrency and search-summary quality gates remain open. Do not promote models or claim full 5070 Ti qualification.

### Checkpoint — 2026-11-04, current GPU/runtime continuation

- Current candidate before this documentation update: HEAD `e3dbf18cbfd9d1ddd5177f8b254202e4fcf60bdf`, working-tree fingerprint `9433c885e951990f9ab2af05787893afadeabc2cce167d925afcade2a9eef4f3`, 45 dirty paths. GPU implementation paths are under an explicit Agent OS writer lease `lease_e597616e88874e2fa7ea`; this plan is under `lease_f020f430c9464defa443`.
- Fresh targeted validation on that candidate: `python -m pytest -q tests/test_config_hardware.py tests/test_external_gpu_reservation_lifecycle.py tests/test_opencode_gpu_reservation.py tests/test_preprocess_status_scaling.py tests/unit/test_preprocess_demand_priority.py tests/unit/test_reranker_gpu_reservation.py` — **105 passed** in 8.17s.
- `python tools/doctor.py` returned exit 0, Hub 5.1.3 online, RTX 5070 Ti (15 GB), active `qwen3.5:9b-nvfp4`, and “OpenCode: 16gb profile; runtime not verified.” A separate `local_ai_status` response reported Hub/Ollama online but `active_model=null` and VRAM pressure `unknown`; runtime/GPU residency therefore remains unverified due to conflicting observations.
- Current source already sets foreground Ollama `num_parallel=2` and q8_0 KV cache; high/max profiles request 65,536 smart-context tokens and CUDA embedding/reranker when detected NVIDIA VRAM is at least 15 GiB. Per-role `smart.parallel` remains 1; high/max background GPU server parallelism remains 4/6 with larger file/module batches. This does not prove two simultaneous 65k smart requests fit or that GPU retrieval inference is active.
- Scheduler dispatch currently claims the shared internal GPU reservation before beginning eligible inference. Reservation lifecycle and reranker/preprocessing reservation suites passed above; process-level, real-GPU simultaneous-admission and cleanup acceptance still require a fresh candidate-bound runtime run.
- A one-shot CPU-only RAG reranker smoke was run with `python tools/benchmark_rag_reranker.py` against three non-exhaustively labeled installation/update queries, with downloads disabled. Baseline/reranked ranks were 1→1, absent→absent, and 3→2; rerank calls took 27,164 ms (first call includes lazy load), 12,480 ms and 11,834 ms. This indicates CPU latency and one retrieval miss, not GPU speed or general relevance quality. The harness source SHA-256 was `e2ad1e493517096a3bae98bf06580ba9a9da347837e8e73889dd633a21a466c1`; its rank helper test passed 1/1.
- No new tool-call quality evaluation or context/concurrency benchmark was run. Existing C1/C3 tool-use failures, unverified GPU residency, and incomplete full pytest rerun remain open. Do not raise per-role smart concurrency, promote tool calling, or claim GPU performance until admission and measured quality gates pass.

### Checkpoint — 2026-11-04, resumed implementation and current regression status

- Continued from the current shared checkout without removing existing dirty or untracked files. During the first full suite the working tree grew from 23 to 31 modified paths and added `search_modes.py` plus its tests; that run therefore did not test a stable candidate.
- Latest targeted validation: the affected failure cohort passes **50/50**; the broader focused cohort reports **383 passed, 1 skipped**, `tests/test_opencode_gpu_reservation.py` passes **57/57**, and the affected synthetic benchmark cohort passes **8/8**. `compileall`, `selftest.py`, and `git diff --check` passed before the last test-only expectation updates.
- The full `pytest -q` run ended **14,581 passed, 128 skipped, 20 failed** in 56:54. Eleven failures reproduced in a focused rerun on the then-changing tree. The stale MCP search payload expectations, provisional model fixture, defaults comments and machine-local path in this audit note were corrected; the deterministic HTTP contract now requests lexical search explicitly; telemetry pagination requests a flush before asserting newly queued events. All 20 original failure cases now pass in the latest focused rerun. Nine failures did not reproduce on that rerun. A new complete suite on a frozen final snapshot remains outstanding.
- `python tools/release_check.py` no longer reports a root/packaged defaults mismatch after synchronizing `code_index.max_index_bytes`; it still fails on existing workspace-only directories, runtime/generated payloads, local config and backup files. Those were preserved.
- Fresh `gpu_reservation_status` returned `state=free`. `local_ai_status` observed Hub/Ollama online and briefly reported `qwen3.5:9b-nvfp4` active, then later `active_model=null` with VRAM pressure unknown. One 40-token `hardware_benchmark` request returned success (`req_e1ce016f4197`) but no usable metrics in its compact envelope; result lookup found no async-job record. This is not a GPU residency, throughput or quality receipt.
- The security audit scanned 1,652 files and flagged one untriaged HIGH finding in a test fixture (`tests/test_opencode_sandbox_bootstrap.py:16`) plus 15 MEDIUM test-code findings. The HIGH finding is classified `is_test=true` and contains a synthetic pipe secret; the scan remains untriaged, so this is recorded as a manual false-positive candidate rather than silently dismissed.
- Hardware quality cases, sustained RTX 5070 Ti VRAM/throughput/context/concurrency measurements, low-memory/provider-failure evidence, the stable full-suite run and a clean release tree remain open. Do not claim 5070 Ti qualification or complete this plan until those gates have sufficient evidence.

### Checkpoint — 2026-11-04, full suite and late RAG update

- The subsequent full-suite run completed with **14,612 passed, 128 skipped, 5 failed, 63 subtests passed** in 48:57. The failures were the dashboard boolean-setting case with pytest `RecursionError` while formatting unraisable exceptions, the CommandBroker warm-cache performance case, one HTTP history-search baseline assertion, one unscoped incidents-list lifecycle assertion, and the surface inventory no-write assertion.
- All five failure cases passed when rerun alone (**5/5**), consistent with sequence-sensitive failures; do not suppress these failures or treat the isolated passes as a clean full-suite receipt.
- After the full run, current `git_status` showed new dirty changes in `src/local_ai_hub/rag.py`, `src/local_ai_hub/services.py`, and their focused tests. Those files were not edited here. Against the latest observed state, `tests/test_rag_hybrid.py` plus `tests/unit/test_search_mode_fusion.py` passed **45/45**.
- On the latest observed state, `compileall`, `selftest.py`, `git diff --check`, and `python tools/release_check.py --allow-installed` passed. The complete pytest suite has not been rerun after the late RAG change.
- An optional `local_ai_task(compress)` of the verification summary returned `semantic_quality.usable=false` and `bypass_reason=unrelated_output`; no claims or evidence were taken from its text.
- The current full-suite failures remain unresolved as a sequence-sensitive acceptance issue. The hardware benchmark request still has no retrievable metrics, and model quality, provider-failure/low-memory behavior, repeated throughput, context/concurrency and final 5070 Ti qualification remain open.

### Continuation checkpoint — 2026-11-04

- Latest repository status: five modified paths remain, with no staged or untracked files. Preserve all five as current working state.
- The latest focused RAG/search-mode suite passed 45 tests; the indexed RAG dependents recommended by impact analysis passed 68 tests (`tests/test_t11_embedding_space_reindex.py`, `tests/test_t11_rag_policy_consumer_rebased.py`, `tests/test_rag_fragment_cache.py`, `tests/test_t11_rag_project_policy.py`, `tests/test_t11_root_consumer_overlay.py`).
- Current indexed impact reports five changed files, 132 additions, 13 deletions and high diff risk due to persistence/database changes; index confidence 0.86. Review and full-suite validation remain open.
- Current Hub readiness reports Hub/Ollama online, but no active model and unknown VRAM pressure. A custom `eval_suite` request failed before send (`request_not_sent=true`, terminal transport failure). The valid no-argument `benchmark` request was rejected by the tool boundary because it injected unsupported `audio_path`; no benchmark ran and no new performance or quality evidence was produced.
- Do not repeat these failed requests unchanged. Fix the benchmark tool input contract in a separately verified change or use the documented installed-instance scoring workflow once available; do not claim GPU qualification from prior historical runs.
- The previous full suite result (14,612 passed, 128 skipped, 5 sequence-sensitive failures, all five isolated passes) predates the latest RAG changes. The latest 45+68 focused tests pass, but full-suite acceptance on a stable candidate remains open. The security audit still has one untriaged high test-fixture finding and 15 medium test-code findings.
- A bounded semantic review/compression request was also rejected before execution: `qwen3.5:9b-nvfp4` admission failed with `target_vram_estimate_unavailable`. This is a routing/admission blocker, not a model-quality result.

### Continuation checkpoint — 2026-11-04 (benchmark contract)

- Added a regression for `local_ai_task(action="benchmark")` receiving an empty, noncanonical `audio_path` default. The test first failed with `unexpected argument for local_ai_task: audio_path`.
- Updated `validate_operation_arguments` to ignore only `None`/empty-string values for fields explicitly scoped to other actions; nonempty wrong-action values remain rejected. Contract and task-input suites pass: 122 passed. `python tools/release_check.py --allow-installed` also passes.
- Retried the connected benchmark after the source fix; the live MCP still returned the same `audio_path` rejection. The checkout change has not fixed the attached runtime path yet; do not claim runtime benchmark support until a live call succeeds.
- A fresh indexed impact/status request stalled and was terminated after more than 90 seconds. No impact result is claimed for this contract change. The focused tests and release check are current; full-suite, live benchmark, and GPU/quality qualification remain open.
- A later impact request completed on termination: it identified `operation_contracts.py` as security-sensitive and recommended `tests/test_operation_contracts.py` plus `tests/unit/test_canonical_mcp_actions.py`. Both are covered now; the former passed within the 122-test run and the latter passed 4/4. Current indexed risk remains high at whole-checkout scope because the checkout contains 11 modified files, including concurrent prompt/search/RAG edits; no broad review conclusion is inferred from the truncated response.
- Installed-instance `python tools/hubctl.py status` reports Local AI Hub 5.1.3 online, seven models installed, one online, and NVIDIA RTX 5070 Ti with 15 GB VRAM. This confirms device/model inventory only; it does not establish residency of `qwen3.5:9b-nvfp4`, VRAM use, throughput, context behavior or quality.

### Continuation checkpoint — 2026-11-04 (current search and contract validation)

- The current checkout now has five modified files: `docs/HTTP_API.md`, the new search/preprocessing quality plan, `src/local_ai_hub/search_modes.py`, `tests/fixtures/search_benchmark_cases.json`, and `tests/unit/test_search_mode_fusion.py`. No staged or untracked files. Treat them as concurrent current work and preserve them.
- Current RAG/search-mode targeted tests passed: `49 passed`. After fixing action-specific default handling, current operation/task contract suites passed `122 passed`; canonical MCP action tests passed separately `4 passed`. A combined run had a sequence-sensitive telemetry-accounting failure, which passed isolated; preserve that distinction.
- Current release checks passed: `python tools/release_check.py --allow-installed`, `python -m compileall -q src tools tests`, `python tools/selftest.py`, and `python tools/doctor.py`.
- Full `python -m pytest -q` was interrupted after approximately 64% when its process handle disappeared; five failures had appeared in progress output, but no terminal summary or identities were retrieved. This is not a passing or complete run.
- `local_ai_task(action="benchmark")` still fails validation in the connected MCP, now on `complexity="auto"`, although source tests accept the schema default. The live runtime/source mismatch remains unresolved; no benchmark executed.
- Hub health currently reports 5.1.3 online, Ollama online, active model null and VRAM pressure unknown. `doctor.py` and `hubctl status` report RTX 5070 Ti 15 GB, but there is no current residency, throughput, VRAM peak, context/concurrency or task-quality evidence. No promotion/readiness claim is supported.
- Follow-up source correction narrows default-value tolerance to action-scoped empty fields and the benchmark action's declared schema defaults only. This preserves strict action rejection elsewhere (including an explicit `offset=0` negative test). Latest focused evidence: task/operation contract suites `122 passed`, canonical MCP action suite `4 passed`, RAG/search modes `49 passed`; `release_check --allow-installed`, `compileall`, and `git diff --check` pass. The dirty set currently includes this plan, `src/local_ai_hub/operation_contracts.py`, `src/local_ai_hub/search_modes.py`, and `tests/unit/test_task_canonical_inputs.py`; earlier concurrent changes may have been committed, so re-check status before further edits.

### Continuation checkpoint — 2026-11-04 (RTX 5070 Ti measurements)

- `local_ai_task(action="hardware_benchmark")` produced authentic sampled RTX 5070 Ti runs. `qwen3.5:4b-nvfp4` (`req_072480ad0be4`): 6 tokens, 13.85 tok/s, TTFT 433.3 ms, sampled device-wide peak 9,463,398,400 bytes, dynamic context 32,768. `qwen2.5-coder:7b` (`req_8975bdbd8d81`): 6 tokens, 116.7 tok/s, TTFT 6,412.24 ms, queue wait 3,757.11 ms, load 2,448.4 ms, sampled peak 16,477,323,264 bytes. The 7b peak exceeds the reported 16,303 MB total; telemetry must be reconciled before capacity decisions. Full evidence is in `docs/agent-evaluation/results.md` section 007.
- `qwen3.5:9b-nvfp4` was NOT_RUN: request `req_ff950a1464e6` rejected at model admission because `target_vram_estimate_unavailable` / source `unknown`; do not retry unchanged or infer 9b support.
- A bounded custom diagnostic `eval_suite` ran on 4b (`req_b701a2a46226`) and 7b (`req_0afcbb30dd91`). Both scored 1/3 by exact expected-substring matching. Grounded two-record summary passed; cross-file answers were semantically related but missed the literal `same tier` expected string and were not promoted to pass; review returned only `IndexError`, not the requested off-by-one diagnosis. This custom three-case suite has no isolated fixture or paired baseline and is diagnostic only; the fixed R1/R2/T1/D1/C1–C3/I1/I2 suite remains NOT_RUN.
- Completed one short-prompt 20/20 warm 4b hardware series and a more representative 60-word generation series with 20/20 warm responses. For the longer-output series, 56.5 median tokens, 140.8 median tok/s (p95 156.34), TTFT median 400.175 ms (p95 477.61); one preceding transition sample had 46 tokens, 570.08 ms TTFT and 80.69 tok/s. Exact prompt, all run IDs, latency/VRAM distributions and outlier treatment are recorded in `docs/agent-evaluation/results.md` section 007. This establishes bounded workload performance only, not role quality or a paired candidate/baseline gate.
- A subsequent 7b repetition request (`req_a4bf66fc978e`) rejected at admission with unknown VRAM estimate, so its prior single result is insufficient for a 20-sample profile. Do not retry unchanged. No quality or capacity promotion.
- Benchmark action runtime still rejects schema defaults (`complexity="auto"`) even though checked-out source and contract tests accept them. Do not restart the installed service without an authorized runtime-change boundary. This mismatch prevents the configured benchmark path but did not prevent the distinct hardware and eval-suite endpoints.
- Full pytest process disappeared around 64% after five failures appeared; no terminal summary exists. Current focused tests, release check, compileall and selftest pass, but broad-suite acceptance remains open.

### Continuation checkpoint — 2026-11-05 (terminal full-suite triage)

- A bounded full-suite run completed its `--maxfail=5` gate with exit 1: **11,907 passed, 116 skipped, 5 failed, 63 subtests passed in 50:37**, stopping at 81%. Failures: `tests/test_surface_inventory.py::test_check_mode_with_real_schema_generator_does_not_write_coverage`; three candidate-fallback logging cases in `tests/test_t10_repo_search_path_hints.py`; `tests/unit/test_live_search_benchmark.py::test_live_query_set_is_independent_bilingual_and_source_anchored`.
- Isolated reruns: surface inventory passed 1/1; live search fixture passed 1/1. All three T10 cases failed independently because they used ordinary query `needle`, while the current search implementation only consults index/preprocessor candidates for compact symbol-like queries (`prefers_lexical_precision`). The CodeIndex case also expected an index lookup during ordinary natural-language search, contrary to the demand-based search path.
- Updated only `tests/test_t10_repo_search_path_hints.py`: candidate-error cases use a mixed-case symbol-like query and still assert exact source fallback plus privacy-safe logs; the CodeIndex case now verifies natural-language search does not invoke a partial CodeIndex and still returns exact lexical results. The complete T10 module now passes **10/10**.
- Rerun the full pytest suite on this current tree. Do not infer success from the 11,907 tests before the five-failure stop. Surface/live-search isolated passes and the T10 correction still need integrated confirmation.
- After that terminal run, concurrent source/test changes landed in `src/local_ai_hub/services.py`, `tests/fixtures/search_benchmark_cases.json`, and `tests/unit/test_search_mode_fusion.py`; they were not part of its proven candidate. The current combined RAG/search/live-search/T10 focused cohort now passes **69/69**. Current `release_check --allow-installed`, `compileall`, `selftest.py`, and `git diff --check` pass; full integrated validation of the current dirty set is still required.

### Continuation checkpoint — 2026-11-04 (Gemini handoff and integrated validation)

- Preserved Gemini's generation-safe GPU reservation cleanup and stable RAG candidate-window changes. Focused reservation/search tests passed **44/44**. Added a regression proving failed metadata cleanup cannot be overwritten by a replacement lease.
- Benchmark contract now tolerates an empty generic MCP `path` default while still rejecting a nonempty override. Canonical-input, operation-contract, and MCP-action tests passed **126/126**. Live service behavior remains unverified because the installed process was not restarted.
- Scoped the surface-inventory no-write test guard to the two trees it snapshots. This avoids treating an unrelated dispatcher GPU-lock write as a mutation by the check-mode command. The combined focused endpoint/reservation/search/contract/T10 cohort passed **197/197**.
- Synced the stale direct-RAG description in `docs/UPDATE_PROMPT.md` with `docs/INSTALL_PROMPT.md`; the canonical prompt parity test passes **1/1**.
- Latest release check (`--allow-installed`), `compileall`, `selftest.py`, and `git diff --check` all pass. `tests/test_t10_repo_search_path_hints.py` passes **10/10**; command-broker cache benchmark passes **1/1** in isolation.
- Logged full-suite gate completed with **7,825 passed, 67 skipped, 5 failed, 60 subtests passed in 36:29**. Failures: `tests/test_command_concurrency_contract.py::test_affected_test_selection_covers_transitive_dependency_graph`, `tests/test_command_performance_acceptance.py::test_command_broker_reports_latency_throughput_and_failure_behavior` (passes isolated), `tests/test_generator.py::TestGlobalPolicyGeneration::test_canonical_prompts_share_hardware_tier_policy` (fixed and passes isolated), `tests/test_opencode_warmup_isolation.py::test_goal_transport_creates_real_bound_task_without_warmup`, and `tests/test_surface_benchmarks.py::test_synthetic_repository_declares_pytest_for_affected_test_selection`. The affected-test selection and synthetic repository failures reproduce in isolation; warmup failure reports `generation_denied`. Full-suite acceptance remains open.
- No service restart, model pull, or GPU rerun was done. The plan's runtime-change boundary still applies. Benchmark schema defaults, installed process behavior, RTX 5070 Ti capacity/quality promotion, and unresolved test-matrix failures remain open.
- Follow-up after the logged suite: direct `/api/rag/search` is explicitly semantic-only. When generation is denied, it now returns `retrieval_mode="semantic_only_unavailable"` with no lexical rows; focused semantic-only, warmup-isolation, and HTTP-route tests pass **19/19**, then prompt parity plus semantic-only tests pass **6/6**. Both canonical prompts document this response.
- The logged full-suite failure for prompt parity and the warmup-isolation expectation are fixed in focused tests after that run. The two affected-test/test-matrix cases were subsequently corrected to seed the existing index before asking for indexed impact; see the final targeted cohort below.
- User directed that validation use specific tests, not the full suite. Stopped the detached full pytest run at 18%; its log has no terminal summary and one progress failure, so it is not evidence of completion. The exact affected-test and synthetic test-matrix cases now seed the pre-existing CodeIndex before asking for transitive impact; this matches the runtime contract that queries do not index projects on demand.
- Final targeted regression cohort passed **272/272** across GPU reservation/reranker, preprocess scaling, search fusion/T10, HTTP/RAG semantic-only denial, benchmark defaults, prompt parity, test selection, and the identified sequence-sensitive cases. No further full-suite run is authorized by current user instruction; preserve the prior terminal full-suite result as historical and do not claim a current full-suite pass.
- Latest continuation status (`req_740955398c45`): Hub 5.1.3 and Ollama online, `active_model=null`, `vram_pressure=unknown`, context budget factor 0.25. This confirms service reachability only. Installed model inventory, effective profile, driver/backend, free VRAM, residency, and benchmark readiness remain unverified; no benchmark was submitted from this status.
- A subsequent bounded status (`req_592a4a4b8d2a`) returned `active_model=qwen3.5:9b-nvfp4`, with Hub/Ollama online and `vram_pressure=unknown`. The model identity changed between adjacent status calls, so treat the active-model field as transient and unqualified; profile, installed-tag inventory, driver/backend, free VRAM, and residency are still missing. No inference benchmark was submitted.
- A controlled warm hardware-only series subsequently completed 20/20 for `qwen3.5:4b-nvfp4` on the RTX 5070 Ti: exactly 40 tokens per call; median 116.54 tok/s, p95 129.40 tok/s; reported `ttft_ms` median 343.23 ms, p95 462.94 ms. Representative responses use `streaming=false`, so these are full-call latency measurements, not first-token latency. Device-wide sampled peak VRAM max 9,301,917,696 bytes. Exact request IDs, per-sample metrics, and limitations are in `docs/agent-evaluation/2026-11-04-rtx5070ti-qwen35-4b-factorial-40tok-warm.md`. This is warm short-output throughput evidence only; it does not qualify task quality, cold load, context capacity, concurrency, backend identity, or promotion.
- One 9B transition sample succeeded (`req_9dcab4c3efc2`, `qwen3.5:9b-nvfp4`), but the final sample reported high pressure with 2,156 MB available and reduced dynamic context 16,384; background throttling was enabled. A following status still reported pressure unknown. No repeat was submitted. Full metrics and the speculative-target mismatch are recorded in `docs/agent-evaluation/2026-11-04-rtx5070ti-qwen35-9b-transition-smoke.md`; 9B capacity/quality remains unqualified.
- A single opt-in `local_ai_repo(search, summarize_results=true)` call was rejected by the installed MCP tool as an unexpected argument (400); no inference ran. The current checked-out `mcp_server.py` signature and forwarding path include `summarize_results`, so live schema/process parity is stale or otherwise mismatched and needs a controlled restart/integration check. A separate `local_ai_task(compress, model=qwen3.5:4b-nvfp4)` attempt was routed to configured `qwen3.5:9b-nvfp4` and rejected before inference for `target_vram_estimate_unavailable`; source `services.py:8124-8149` confirms compression currently chooses configured `models.general`. This is NOT_RUN for quality and is evidence that generic `model` input does not establish the compressor's serving identity.
- Latest status `req_99a5e605ae0f` again reported Hub/Ollama 5.1.3 online, `active_model=qwen3.5:9b-nvfp4`, `vram_pressure=unknown`, and context factor 0.25. The status samples have alternated model identity while pressure remains unknown; do not start another inference from this diagnostic state. GPU quality, stable profile/model/backend inspection and installed-process parity remain open.
- Targeted source validation in the current checkout: `python -m pytest -q --tb=short tests/unit/test_exact_search_git_inventory_order.py` passed **9/9**; `python -m pytest -q --tb=short tests/test_mcp_agent_routing.py -k search_ai_summary` passed **12/12** (102 deselected). These validate current deterministic ordering and summary behavior in source tests only; they do not clear the installed MCP schema mismatch or model-quality gate. No full-suite run was made.

### Checkpoint — 2026-11-05, post-restart targeted evaluation

- Restarted the owned Hub installation. `hubctl service-status` reports supervisor PID 13008, Hub PID 35436, ready, Ollama online; Hub v5.1.3 reports RTX 5070 Ti and managed Ollama/llama.cpp. `local_ai_status` is online with `qwen3.5:9b-nvfp4` active. A status CLI child PID is distinct from the service-owned Hub PID.
- Confirmed `search_summaries` remains an opt-in feature. With it disabled, MCP omits the `summarize_results` parameter; no runtime configuration was changed. The targeted search-summary tests pass: `python -m pytest -q tests/test_mcp_agent_routing.py -k search_ai_summary` — 12 passed, 102 deselected.
- Added four single-sample 9B fixed-case outputs to `docs/agent-evaluation/results.md`: R1 FAIL (incorrect before/after example), R2 PASS, T1 FAIL (no required input/output pairs), D1 FAIL (unsupported hypotheses). Model digest, paired baseline, and GPU telemetry were not returned; these samples do not qualify a role.
- Current `local_ai_task(evaluation_report)` reports 0 matched tasks and `insufficient_evidence`. Workstream 6 remains open: digest-bound paired task-quality evidence, GPU residency/VRAM/context/concurrency measurements, low-memory/provider-failure evidence, and promotion thresholds are still outstanding. No full suite was run, per user instruction.

### Checkpoint addendum — 2026-11-05, bounded 9B GPU sample

- The local registry resolves `qwen3.5:9b-nvfp4` to Ollama ID `646b3c2dbeba` and blob SHA-256 `0db703913b6a1b057d423e9815095e9dc16499596a986446918314a48c4d9bad`; configured `num_ctx` is 32,768. Runtime benchmark responses still do not attest this digest.
- One warm 9B hardware benchmark succeeded on the RTX 5070 Ti (76.72 tokens/s for 6 tokens; device-wide sampled peak 10,819,207,168 bytes; nominal pressure and 5,678 MiB reported headroom). Nineteen further requests succeeded, but compact projections did not expose metrics; no repeated latency percentile is claimed. `streaming=false`, so its `ttft_ms` is full-call latency.
- Driver snapshot is 621.01; Windows per-process GPU memory is unavailable. Residency attribution, paired baseline and task quality remain open. Do not promote 9B from this smoke.

### Checkpoint addendum — 2026-11-05, 9B warm repetition cohort

- Captured 20/20 successful sequential warm hardware-benchmark calls for `qwen3.5:9b-nvfp4` on RTX 5070 Ti (fixed six-token output). Throughput median/P95 105.86/136.32 tokens/s; full-call latency median/P95 117.15/216.39 ms; queue median/P95 7.45/38.33 ms. Sampled device-wide peak VRAM was 11,121,197,056–11,124,342,784 bytes, with 32,768 dynamic context and nominal pressure.
- These short-prompt samples do not supply paired baseline, quality pass, long-context/concurrency, cold-start distribution, or per-process memory attribution. The 9B route remains unqualified for promotion. Exact sample IDs and caveats are in `docs/agent-evaluation/results.md`.

### Checkpoint addendum — 2026-11-05, A1/A2 fixtures awaiting indexed evidence

- Prepared clean A1/A2 fixtures outside the repository and registered each once. The Hub queued preprocessing; per policy it was not polled. Search still ended in terminal 413 with no evidence rows, so the required read-only solve was not run. Full fixture identity, request IDs and exact status are in `docs/agent-evaluation/results.md`.
- These are unavailable evaluations, not model failures. Continue with independent work; resume these cases only after a fresh indexed lookup returns evidence IDs.

### Cleanup note — unused temporary fixture residue

- The initial `%TEMP%` A1/A2 copies were unused. A non-forced removal hit hidden `.git` contents and partially removed them. After checking the remaining exact paths and confirming the ACL, automatic approval review rejected the targeted recursive `-Force` cleanup. The residue is limited to two hidden `.git\objects` directories. No permission change or bypass was made; the persistent Documents fixtures remain clean.

### Checkpoint addendum — 2026-11-05, current status and regression evidence

- Effective hardware profile is now confirmed as `high`; driver 621.01, RTX 5070 Ti/CUDA. Managed Ollama is verifiable, parallel limit 2, max loaded models 1; current status had no loaded model and VRAM pressure unknown. This closes inventory only, not GPU qualification.
- `tests/test_resource_backpressure.py` plus `tests/test_t12_runtime_scenarios.py`: 51 passed. Physical low-memory/provider-failure behavior remains unmeasured.
- A1 lexical fallback supplied caller and callee evidence IDs, but MCP transport failure prevented solve. A2 has README constraint evidence only; dispatcher source and solve remain unavailable. No async preprocessing was polled.
- Current native service status is ready (supervisor 11772, Hub 35336, Ollama online); MCP transport still failed during the A2 evidence request and status retry. No restart. Keep the objective active and the remaining plan gates open.
- The live MCP schema rejected `local_ai_repo.solve` as unavailable. Source registry and focused tests confirm this action requires high profile, the default-off `local_semantic_analysis` flag, and task-specific qualification. Tests: four focused `tests/test_features.py` tier/capability cases plus two MCP gate/status cases — 6 passed. High profile alone does not promote the action. No flag/config change was made; A1/A2 remain NOT_RUN pending a permitted, qualified evaluation path.

### Checkpoint addendum — 2026-11-05, A1/A2 compression diagnostics

- With authentic A1/A2 lexical evidence IDs, `local_ai_task.compress` produced only diagnostics because `local_ai_repo.solve` remains gated off. A1 omitted required numbers; A2 gave no retry-safe design and was rejected by semantic quality guard (`unrelated_output`). Both fail the requested quality criteria; no role promotion.
- Keep `local_semantic_analysis` disabled. The 4B/9B runtime selection and A1/A2 `solve` quality remain unqualified; do not substitute these compression outputs for repository solve evidence.

### Checkpoint addendum — 2026-11-05, A1/A2 direct evaluation

- Direct `eval_suite` for qwen3.5:9b-nvfp4 produced A1 arithmetic failure (2,200/210 cents instead of 22,000/1,210) and A2 quality failure. Overall 0/2 quality passes; no promotion. This tests text generation only, not the gated repository solve path.
- The six-case 4B suite was response-truncated and unscorable; it was not retried. No paired quality comparison exists. Keep all high-risk semantic actions gated.

### Checkpoint addendum — 2026-11-05, 7B admission and quality

- `qwen2.5-coder:7b` A1/A2 eval suite had one real admission refusal (`target_vram_estimate_unavailable`) and one incomplete A2 response with quality gate false. No retry or fallback. This verifies a fail-closed admission path, but does not establish low-memory recovery or heavy-code quality. Keep route unqualified.

### Checkpoint addendum — 2026-11-05, Hub restart and focused admission regression

- User-requested `python tools/hubctl.py restart` succeeded. Service status confirmed ready Hub and online Ollama; MCP status confirmed `qwen3.5:4b-nvfp4` active. Post-restart inventory: RTX 5070 Ti/CUDA, driver 621.01, 16,303 MiB VRAM, effective profile `high`, managed llama.cpp CUDA0 online/selected. Routes remain unqualified by this inventory.
- Targeted scheduler admission tests passed: 13 passed, 19 deselected. Unknown model VRAM estimate remains fail-closed; the prior 7B refusal is not a low-memory stress result.
- Full/release suites not run, per user instruction. Cold-start, long-context/concurrency, per-process VRAM attribution, paired baseline and task-quality gates remain open.
- Optional semantic compression review was unavailable: request `req_f43540469139` hit `target_vram_estimate_unavailable` for `qwen3.5:9b-nvfp4`; no retry. Diff and claims checked manually.

### Checkpoint addendum — 2026-11-05, post-restart 4B admission and measurement

- Confirmed current installed model tags and effective `high` profile on RTX 5070 Ti/CUDA, driver 621.01. Active installation has a 6 GiB estimate for 4B; 7B/9B estimates are absent. The first post-restart 4B benchmark returned generic `QueueFullError`; after scheduler telemetry settled, a distinct 4B request succeeded.
- Successful 4B sample: 27.75 tokens/s, 216.2 ms full-call latency, 5.49 ms queue wait, device-wide peak 8,900,313,088 bytes, 32,768 dynamic context. Residency class remains unknown; this is not cold-start or quality evidence. Full sample and request identity are in `docs/agent-evaluation/results.md`.
- Fixed benchmark admission failures to preserve scheduler error text, reason code, retryability and safe admission state. Focused regression test passed; no full suite run.
- Two distinct 4B benchmark requests issued together both succeeded, but their measured generation intervals did not overlap. Configured concurrency remains unqualified; cause of serialization is unknown. Evidence and request IDs are recorded in `docs/agent-evaluation/results.md`.
- New 4B search-summary contract case passed the mechanical substring check but failed quality (`0/1`; not concise; full response preview truncated). Live capability status reports `search_summaries` feature-disabled; MCP rejects `summarize_results` while the gate is off. Generic `argument_help` does not prove the gated parameter is advertised. Keep the summary feature unpromoted and default-off.
- Bounded the search-summary prompt to at most 3 bullets/80 words, forbade inferred result counts/findings, and reduced its output cap to 180 tokens. Focused source-bound summary regression passed after failing on missing bounds. The earlier concise-candidate request was rejected for insufficient VRAM; later diagnostic-only results are recorded below. Production quality and capability remain unqualified and disabled.
- A fresh 9B one-case diagnostic with structured source fields passed the suite's expected-substring/style heuristic (request `req_f761b680eef9`), and its visible citations matched supplied paths/ranges. Full response preview was truncated; suite does not validate citations or factuality, and this did not exercise the feature-gated production route. Keep role and capability unqualified.
- The fast 4B model ran a new structured diagnostic after status showed no active model. Its visible output removed the unsupported result count after the prompt added an explicit no-inference rule, but heuristic quality remained 0/1 because the evaluator's 240-character threshold rejected a 299-character response. The response was truncated; production-route quality and role qualification remain open.
- Direct compression probes returned advisory unusable 9B output even when 4B was requested; later output used supplied path citations but overstated possible omissions. Added explicit format and qualifier rules with focused regression coverage. These probes are not the feature-gated production search route; the last prompt refinement has not been model-evaluated. Keep capability disabled.
- Improved `eval_suite` with optional per-case word limits, allowed/required citation checks and forbidden phrases; invalid rubrics fail before inference. MCP forwarding and scoring passed focused regressions after failure-first tests. This supports task-specific quality measurement but is not model or route qualification.
- Exposed the nested rubric contract in the public MCP schema and synchronized `INSTALL_PROMPT.md`/`UPDATE_PROMPT.md`; direct service and MCP validation reject malformed or unknown case fields, empty suites, non-object cases and over-limit input before model execution. Eleven focused regressions plus one schema test passed; full suites remain unrun.

### Checkpoint addendum — 2026-11-05, requested Hub restart and rubric regression

- MCP status failed twice with HTTP transport errors. Native `hubctl status --json` reported `running=false`; the user had explicitly requested restart. `python tools/hubctl.py restart --json` returned `restarted`.
- Post-restart `local_ai_status` request `req_8eaff22afacc`: Hub 5.1.3 and Ollama online; `active_model=null`, VRAM pressure unknown, context budget factor 0.25. This proves service reachability only. No inference or GPU benchmark started.
- Re-ran targeted eval and search-summary regressions: `python -m pytest -q --tb=short tests/test_new_capabilities_and_hardening.py tests/test_mcp_agent_routing.py tests/test_generator.py -k "eval_suite or search_ai_summary"` — 29 passed, 202 deselected. This validates checked-out source, not installed MCP schema parity or model quality.
- Keep GPU/task-quality gates open. No full suite run, per user instruction.

### Checkpoint addendum — 2026-11-05, eval-suite schema parity

- Diff review found the generated `cases` schema accepted an empty list while runtime validation rejects it. Added `minItems: 1` to match runtime contract and extended the focused schema test.
- Test-first evidence: the focused schema test failed with `KeyError: minItems`; after the schema fix, `python -m pytest -q --tb=short tests/test_generator.py::TestMcpSchemasGeneration::test_eval_suite_exposes_bounded_task_specific_case_rubric` passed (1 passed).
- This closes schema parity for empty cases only. Runtime model quality and GPU qualification remain open.

### Checkpoint addendum — 2026-11-05, 4B summary eval outcome unknown

- Submitted one bounded `local_ai_task(eval_suite)` case for `qwen3.5:4b-nvfp4`, checking expected summary content, exact allowed/required citation, an 80-word limit and forbidden coverage/count claims. The tool call ran for about seven minutes, then ended with MCP transport error and no request ID or result. Treat execution and quality as unknown; do not replay.
- Post-call status (`req_46c793dc9ead`) reported Hub/Ollama online, `active_model=null`, VRAM pressure unknown and context budget factor 0.25. `local_ai_task(evaluation_report)` (`req_23fdd90939ee`) returned zero matched tasks and `insufficient_evidence`; it does not recover this call's outcome.
- No model-quality, GPU or search-summary production-route claim is established. Continue with independent work; keep all affected gates open.

### Checkpoint addendum — 2026-11-05, fixed S1 search-summary case

- Added version 2 case S1 to `docs/agent-evaluation/local-model-gpu-cases.md`: fixed synthetic evidence, incomplete-coverage qualifier, exact citation, count/E1 restrictions, deterministic baseline and an executable task-specific `eval_suite` rubric payload.
- Added operator scoring in `docs/agent-evaluation/local-model-gpu-scoring.md`. S1 is a separate search-summary role gate; aggregate nine-case threshold is unchanged. Vision remains NOT_RUN because the fixed suite has no image fixture or scoring case.
- Parsed the embedded S1 payload as JSON successfully; source SHA-256 `21ba7b0125a987a77df2e7dd1a2804918e3f3aac4f170cb40487a08a7dfd1987`.
- Semantic compression review (`req_239e6b61b1a1`) returned `advisory_only=true`, `usable=false`, `bypass_reason=unrelated_output`; no model review was accepted. The bounded 4B eval outcome remains unknown and was not replayed.

### Checkpoint addendum — 2026-11-05, eval model digest provenance

- Added per-case `model_digest` and `model_digest_status` to `eval_suite`, sourced from the serving runtime's installed-model registry. The digest is emitted only when it is a valid 64-character lowercase SHA-256; missing or invalid identity stays `null`/`unavailable` and does not fail the evaluation.
- Added focused regression coverage for present and unavailable digests. The two targeted tests passed; target-GPU/model quality and benchmark gates remain open.

### Continuation checkpoint — 2026-11-05, tier admission regression

- Rechecked fail-closed hardware gates after the Hub restart: `test_bounded_work_submit_action_respects_hardware_profile` and `test_local_task_actions_follow_hardware_tiers_and_unknown_fails_closed` passed (7 cases).
- Current Hub status (`req_0aad0c9ca4b2`) reports `qwen3.5:9b-nvfp4` active but VRAM pressure unknown and a reduced context budget. No additional inference was started; representative GPU measurements, role quality, route promotion, cold-start and low-memory/provider gates remain open.

### Continuation checkpoint — 2026-11-05, bounded eval output inspection

- Added per-case `include_response_text` opt-in to `eval_suite`; returned text is capped at 4,096 characters with `response_text_truncated`. Default responses stay compact. MCP forwarding, strict boolean validation, and the generated case schema are aligned; both canonical prompts document the field.
- Failure-first service/MCP/schema tests passed after implementation (7 focused tests). This enables inspection of bounded model outputs; no new model-quality or GPU claim is made.
- Restarted the Hub after the source/schema change. Post-restart status (`req_1daed85e6295`) is online with nominal VRAM telemetry and no active model. Validation-only MCP request `req_b9d7c73a5bd5` accepted the new field through the live tool boundary and stopped at the expected invalid-rubric check before entering the generation loop.

### Continuation checkpoint — 2026-11-05, benchmark timing and loaded VRAM

- Restarted Hub on user request; restart completed. Post-restart status (`req_554bd056750a`) reports Hub/Ollama online, no active model and nominal VRAM pressure.
- Added a regression test proving benchmark TTFT excludes scheduler queue wait and model VRAM is sampled after scheduler preparation. Red-first run reproduced TTFT at about 121 ms with a 100 ms queued delay.
- Moved TTFT start to the prepared-generation callback and capture exact matching `loaded_model_details` there, with post-run fallback only when unavailable. This avoids counting scheduler delay and losing VRAM evidence after model unload.
- Five focused benchmark tests passed, including existing digest, exact VRAM, peak device VRAM and persistence cases.
- A semantic `review_diff` request (`req_e2bdee0c9d6d`, job `836e0644035d46ccb5cafb9ebd17ca58`) was durably queued but delivery was degraded by unknown resource pressure and excessive p95 latency. No semantic review result is available; do not poll or duplicate it. GPU, role-quality and remaining plan gates stay open.
- Restarted again after the benchmark source change. Post-restart status (`req_8e3ebe73231b`) confirms Hub/Ollama online, but VRAM pressure is unknown with context factor 0.25. No GPU inference was started.
- Ran only targeted unknown/low-memory admission checks: unknown pressure, unavailable capacity fallback and post-unload unavailable measurement. Six parameterized cases passed; unknown telemetry stays degraded and unavailable post-unload capacity rejects admission.
- Current reservation check (`gpu_reservation_status`) shows active lease generation `0538e192b3ad4dbf8f3462a3958f97a4`, owner `reranker:37316:29396`, expiry `1793878300.0665581` (2026-11-05 11:31:40 UTC). Release is permitted only after expiry; do not start inference while the lease is active. Hub GPU probe also timed out (`req_0de640fdead3`), so current VRAM remains unknown.
- Tried the user-authorized generation-fenced release. Hub returned `mutation_applied=false` because the lease remains active and unexpired; no repeated release attempt. Local process lookup found no host PID 37316, but server-side owner liveness remains authoritative. Three focused fallback/profile checks passed: deterministic search results survive model failure, unknown/integrated GPU candidates fail closed, and high profile without NVIDIA does not force CUDA retrieval.
- Fresh reservation observation shows a new active generation `641f8b399ecd4dd3854eaa2c46276182`, owner `reranker:864:8528`; PID 864 is the live Hub process. Hub status still reports unknown VRAM. No GPU workload was started.
- Focused routing checks passed (5): low-profile direct semantic work rejection, disabled repository-model release gate, status capability reasons without inference, below-balanced search summary rejection and deterministic result retention after model failure. GPU performance and model quality gates remain open.
- Evaluation gate checks passed (3): unmatched rows do not claim gain, paired cohorts compare only matching task IDs, and promotion requires ten matched quality/test-safe faster tasks. Current live evaluation report (`req_5a37d0d9178a`) has zero matched tasks and remains `insufficient_evidence`.
- Agent OS checkpoint for existing task `task_524dd92de739` persisted as `req_6cd8ec0e8655`; it records focused routing tests and the active lease/unknown-VRAM blockers. The initial checkpoint request was rejected before mutation for response budget; it was resent once with the explicitly larger budget and succeeded.

### Continuation checkpoint — 2026-11-05, reservation lifecycle and release validation

- Fresh Hub status (`req_5b2a6b891165`) reports Hub/Ollama online, `qwen3.5:4b-nvfp4` active, degraded status and unknown VRAM. Reservation status showed free; no generation was started.
- Traced the prior reranker reservation: `ExternalGpuReservationStore.release_internal` removes only its matching digest, while scheduler post-unload admission requires a fresh available capacity sample and rejects unavailable VRAM as `post_unload_vram_unavailable`. Source evidence is current; no lifecycle defect or safe override established.
- Focused scheduler admission tests passed (5): explicitly unavailable telemetry rejects; zero fallback capacity is not treated as measured capacity.
- `python tools/release_check.py --allow-installed` passed (`release-check: OK`). Full pytest remains intentionally unrun per user instruction. Hardware performance and quality gates remain open until VRAM telemetry is trustworthy and reservation free at admission.

### Continuation checkpoint — 2026-11-05, warm 4B measurement and S1 review

- Pre-run status (`req_c7919117e22b`) showed 4B active, Hub/Ollama online and GPU pressure unknown; reservation status was free. A single scheduler-mediated warm benchmark (`req_75e341d1ddcb`) then obtained a fresh dedicated device sample: RTX 5070 Ti, 16 backend tokens, 44 tokens/s, TTFT/generation 363.6 ms, queue 5.95 ms, device-wide peak 9,382,658,048 bytes, 7,048 MiB available of 16,303 MiB, nominal pressure. Installed digest `56d8c805bbeb679be81d064cbda81aa3f91eb32492a4547c0ebaa50690980506` verified. Exact per-model VRAM remains unavailable; this is one short warm sample, not stable throughput or cold-start evidence.
- Ran fixed S1 on the same model (`req_135c795580e6`, 446.06 ms, 61 estimated tokens). Manual semantic review passed: exact citation, bound-equality behavior, incomplete-coverage qualifier, length, and no inferred count/E1 reference. Mechanical substring check failed on a paraphrase (`values equal to bounds` versus `equal to either bound`). Preserved both results; persisted operator evaluation (`req_d76997e6d40c`) as `quality_pass=true`, `test_pass=false`. S1 is not promoted; paired baseline and broader model gates remain open.
- Post-run reservation status was free. Full results are recorded in `docs/agent-evaluation/results.md`. No cold, concurrency, vision, bounded-edit or 20-repeat performance gate was covered.
- This same turn then completed 19 more scheduler-mediated warm samples (20 total). Full-call latency p50/p95 was 178.93/384.64 ms; backend throughput p50/p95 89.42/103.64 tokens/s; device-wide peak range 9,291,431,936–9,382,658,048 bytes; exact model VRAM unavailable. All returned `streaming=false`, so their `ttft_ms` fields were full-call latency, not TTFT.
- Added failure-first coverage for callback-based `request_stream` runtimes; it failed before implementation and then passed. Six focused benchmark tests now pass. The runner uses actual callbacks for TTFT when only the existing `request_stream` interface is available; post-restart live confirmation remains pending.

### Continuation checkpoint — 2026-11-05, true TTFT and refreshed tiered VRAM

- Added and passed a callback-stream regression test (first failed because no `streaming` record existed), then restarted Hub. Live sample `req_4f6cfdaa8ceb` confirms `streaming=true`: TTFT 100.88 ms, generation 153.12 ms, 16 backend tokens, 104.49 tokens/s, queue 5.96 ms; RTX 5070 Ti device-wide peak 6,229,590,016 bytes, nominal pressure. Digest verified. One sample only; warmth unknown.
- Twenty earlier warm samples remain valid as full-call latency and backend throughput, not TTFT; all were non-streaming. Results and all request IDs are preserved in `docs/agent-evaluation/results.md`.
- Traced unavailable per-model VRAM to `TieredOllamaRuntime.loaded_model_details` dropping `force_refresh`. Added keyword-only propagation through both tiers and a failure-first test; 4 targeted tests passed across streaming benchmark and tiered VRAM refresh. `git diff --check` and `python tools/release_check.py --allow-installed` passed.
- Restarted Hub again to load the tiered refresh fix. Post-restart status `req_a0e06de3e4f1` reports online but pressure unknown and context factor 0.25; reservation was free before restart. No inference followed. Exact per-model VRAM confirmation, repeated true-TTFT series, cold start, context/concurrency, other models and task-quality gates remain open.

### Continuation checkpoint — 2026-11-05, non-streaming latency semantics

- Added failure-first assertions for non-streaming records and summary output; the old path exposed a fabricated `0.01 ms` TTFT and omitted full-call latency. The runner now reports `ttft_ms=null`, full call latency separately, and an explicit latency basis. The summary also interprets legacy `streaming=false` records without modifying stored rows. Composite scoring uses the available latency measurement.
- Focused non-streaming/legacy-summary, benchmark persistence/metrics and callback-stream TTFT tests passed (3). Existing historical non-streaming samples remain labeled in the results document as full-call latency.
- Hub status `req_bcb609adcb6a` is online, but active 4B VRAM pressure is unknown. No further model call was made. Exact per-model VRAM, refreshed live telemetry, repeated true TTFT and remaining cold/context/concurrency/model-quality gates remain open.

### Continuation checkpoint — 2026-11-06, low-memory and provider failure gate

- Fresh Hub status (`req_65945454b05c`) is online with no active model, but VRAM pressure remains unknown. No inference was started.
- Re-ran low-memory scheduler integration for 256 MB capacity across runtime, benchmark and eval-suite paths: 4 selected cases passed, 11 deselected. The CUDA fallback was rejected before generation on the constrained cases.
- Explicitly unavailable post-unload telemetry and benchmark model-error handling passed (5 parameterized/focused cases). The plan's low-memory/provider-failure safety item is closed; physical GPU measurements, task-quality gates and `high` route promotion remain open.

### Continuation checkpoint — 2026-11-06, compact GPU readiness diagnostics

- Source tracing found that compact status reported only `vram_pressure`; it discarded the scheduler admission state and VRAM sampler state/error already present in the live status payload. A pending asynchronous telemetry probe was therefore indistinguishable from a timed-out or unavailable probe.
- `local_ai_status` now returns a validated `gpu_admission_state` and allowlisted `vram_telemetry` fields (`available`, error category, sampling, staleness and timeout). Private provider details and reservation owners are excluded; both fields are protected from response-budget projection. Updated the capability inventory.
- Missing VRAM pressure was previously defaulted to `nominal`; a failure-first test caught this and the missing-field fallback is now `unknown`.
- Focused valid/malformed and missing-field status tests passed (2). `py_compile`, `git diff --check` and `release_check --allow-installed` passed. Live verification still needs the Hub process to load the source change. The repository broker rejects a generic `command` action and returned no native-fallback authorization; no direct restart command was issued. Current live VRAM remains unknown; hardware and quality workstreams remain open.

### Continuation checkpoint — 2026-11-06, live readiness projection

- Live `local_ai_status` request `req_940bdeee7414` returned the new fields from the running Hub: `gpu_admission_state=available`; VRAM `available=false`, `error=sample_pending`, `sampling=true`, `stale=true`, `wait_timed_out=false`; pressure `unknown`, context factor `0.25`, active model `qwen3.5:4b-nvfp4`.
- This verifies the status projection is live. It does not establish fresh VRAM capacity: the sampler is still pending and the conservative unknown pressure remains. No inference was started; 5070 Ti measurements, paired task-quality gates and route promotion remain open.

### Continuation checkpoint — 2026-11-06, operator-requested Hub restart

- Ran `python tools/hubctl.py restart`; the command returned `restarted`.
- Post-restart `local_ai_status` request `req_3a5a03988696` reports Hub and Ollama online, VRAM telemetry available, `gpu_admission_state=preparing_model`, and no active model. Pressure reports nominal, but model and admission readiness are not established while preparation is active.
- Restart restored telemetry sampling, but it does not establish a safely reserved inference endpoint, measured 5070 Ti performance, or task quality. Keep the hardware benchmark and paired quality gates open until readiness is verified.

### Continuation checkpoint — 2026-11-06, fast local search-summary routing

- Hardware smoke benchmark request `req_d671357233ff` used verified installed model `qwen3.5:4b-nvfp4` on RTX 5070 Ti: 212.44 ms TTFT, 73.99 ms generation, 286.43 ms total, 54.06 tokens/s, 4 output tokens; sampled device-wide peak VRAM 9,178,185,728 bytes. Loaded-model VRAM unavailable; one short smoke sample is not a performance or quality qualification.
- A live `summarize_results=true` search summary did not run: the previous implementation routed compression to `qwen3.5:9b-nvfp4` despite the fast summary use case, and scheduler admission rejected it because target VRAM estimate was unavailable. Source fix adds configured `model_role` selection to `/api/compress` and routes repository search summaries to `fast_code`; explicit roles/models must match configured routes. Default compression remains on the general role.
- Focused regression suite `tests/unit/test_compress_model_role.py`: 4 passed. `py_compile` and targeted `git diff --check` passed.
- Restarted updated Hub with `python tools/hubctl.py restart` (`restarted`). Post-restart status request `req_604075e2e0ed`: Hub/Ollama online, telemetry available, `gpu_admission_state=preparing_model`, `active_model=null`.
- One live `summarize_results=true` attempt (`req_c996a45fed05`) returned search results but rejected its AI summary with `output_truncated=true`; summary remains unavailable. Do not count this as route acceptance or repeat the same request. Index state was stale and one candidate fragment mismatched.
- Broad GPU performance, task-quality matrix, route promotion, and live summary acceptance remain open. Earlier local semantic diff review job ended in terminal failure; no review result is claimed.
- After restart, hardware smoke request `req_87a03a08dc12` verified the installed `qwen3.5:4b-nvfp4` digest `56d8c805…`; RTX 5070 Ti dedicated-observed VRAM 16,303 MiB total / 7,042 MiB available, device-wide sampled peak 9,388,949,504 bytes, 136.82 ms TTFT, 100.38 ms generation, 237.2 ms total, 79.7 tokens/s, 8 tokens. `loaded_model_vram_status=unavailable`; `hardware_score=86` is the benchmark tool's smoke score, not task quality. This remains one short sample without cold/warm pair, concurrency, context sweep or task evaluation.

### Continuation checkpoint — 2026-11-05, fixed S1 search-summary evaluation

- Ran only fixed case S1 through `local_ai_task(action="eval_suite")`: request `req_08f2fc006195`, `qwen3.5:4b-nvfp4`, role `fast_code`, digest verified installed. Mechanical evaluator result **FAIL, 0/1**, `quality_pass=false`; exact output and limitations recorded in `docs/agent-evaluation/results.md`.
- This fails the role-specific search-summary gate. Keep `fast_code` search summaries unqualified pending a passing fixed S1 run after a legitimate model or implementation improvement. Prior live summary also returned truncated output; it remains unavailable.
- Hub status request `req_d097a9082033` stayed online/admission-available, but active model was null and VRAM sampling pending. Repository search transport failed once; no retry loop. No model promotion or tier change.
- A one-case S1 attempt on installed `qwen2.5-coder:7b` (`req_9676e4a7fecc`) was NOT_RUN before inference: post-unload admission rejected missing target VRAM estimate. Source confirms admission accepts a measured or configured estimate and fails closed when both are absent (`scheduler.py:560-610`). No guessed estimate or bypass added. Inventory and dated results now reflect the 4B S1 failure and 7B admission gap.

### Continuation checkpoint — 2026-11-05, S1 semantic adjudication

- Operator re-read the fixed S1 scoring key and exact 4B output. The direct S1 case **passes semantic scoring**: both bounds accepted, exact citation, 3 bullets/28 words, qualified coverage uncertainty, no count or E1 citation. The mechanical evaluator still reports `quality_pass=false` because it requires the exact substring `equal to either bound`; preserve that diagnostic. Case fixture remains unchanged.
- This adjudication does not qualify the live search-summary route: its actual long-search generation was rejected as truncated. The 7B model remains NOT_RUN under unknown post-unload memory estimate, and there is no paired baseline. Keep route promotion open.

### Continuation checkpoint — 2026-11-05, fast-role route regression guard

- Extended `test_search_ai_summary_preserves_deterministic_results_and_sources` to assert the `/api/compress` request carries `model_role="fast_code"`. Focused test: 1 passed. This verifies route selection wiring; it does not qualify model quality or live summary completion.

### Continuation checkpoint — 2026-11-05, truncation trace and current admission

- Source confirms `local_ai_repo:search` sends `model_role="fast_code"` to `/api/compress`, and `http_server.py` forwards the raw JSON payload directly to `LocalAIServices.compress`; the selector is not lost at the HTTP boundary. Search-summary code rejects explicit output truncation and leaves deterministic matches intact.
- Current status `req_4777d9ffeb96`: Hub/Ollama online, active model `qwen3.5:4b-nvfp4`, VRAM telemetry pending/unknown, `gpu_admission_state=outcome_unknown`. No further inference or repeated live search attempted. Exact generation cause remains unknown because the compact search response intentionally exposes only the truncation outcome.
- Continue with source/test work until admission and telemetry provide a safe evidence window; do not guess at a VRAM estimate or raise output limits without evidence.

### Continuation checkpoint — 2026-11-05, warm GPU sample and A1 evaluation

- After `gpu_reservation_status` reported `free` and a fresh model admission observed 11.8 GiB headroom, one warm follow-up benchmark ran on `qwen3.5:4b-nvfp4`: request `req_db02d5fc3e01`, verified digest `56d8c805…`, 28 tokens, TTFT 116.22 ms, 264.38 ms generation, 105.91 tokens/s, 7,551 MiB available. Device-wide peak 8,855,224,320 bytes; loaded-model attribution unavailable. Single sample; no route qualification.
- A1 run `req_c6404de6ff43` on isolated fixture returned no pricing-file evidence, no citations or numeric comparison, and an unsupported assertion; quality **FAIL**. Model tag appeared as `qwen3.5:4b-nvfp4`, but `semantic_used=false`, with no digest or GPU telemetry, so execution/device attribution remains unverified. Full evidence is in `docs/agent-evaluation/results.md`.
- The first fixture under `%TEMP%` was ignored by preprocessing as an ephemeral/system directory (`req_37df72255136`). A fresh fixture at `C:\Users\Adam\Documents\lah-gpu-eval-A1-codex-2026-11-05` is now registered; preprocessing is queued (`req_12ef02f69d51`). Do not poll it. Once a later independent status/action shows indexing complete, perform one A1 solve on this distinct fixture; do not retry the unchanged temporary-fixture solve.
- Updated the case protocol to require stable user-controlled non-system paths. `git diff --check -- docs/agent-evaluation/results.md` passed before this checkpoint; rerun focused whitespace validation for both changed docs.
- A bounded `code_index` lookup against the stable fixture found no indexed candidates (`req_0fd13a1b652e`). A direct lexical search then returned both exact source slices (`req_81db351be733`), confirming fixture content but not preprocessing/index completion. Do not poll the preprocess job. The exact solve call rejected unsupported `evidence_ids`; no retry with changed task text.
- A1 inventory review request `req_4e419f11f89a` was admitted, but its output envelope was truncated and semantic/review checks marked it unusable (`unrelated_output`, unverified citations). Do not treat it as approval; review evidence is recorded in `docs/agent-evaluation/results.md`.

### Continuation checkpoint — 2026-11-05, post-restart lease contention

- Restarted the Hub from the repository virtual environment after the prior reservation expired and the live request/scheduler queues were empty. Hub 5.1.3 came online from `src/local_ai_hub`; dashboard health is healthy.
- The restarted process immediately acquired GPU reservation generation `56914ffadd50444a9aa59df116013993` (`embedding:17208:21204`), expiring at `1793914325.926`. At 21:24 UTC the owner process was still live; `gpu_admission_state=external_reservation`, active model null and VRAM telemetry pending/stale. Do not release while the owner is alive.
- No benchmark or inference was run under this reservation. The search-summary quality gate and RTX 5070 Ti performance/quality gates remain open; recheck after lease expiry before attempting a focused evaluation.

### Continuation checkpoint — 2026-11-05, embedding reservation renewed

- After the recorded lease expiry, GPU admission immediately showed a new active embedding reservation, generation `cef450e3a3174f87acc3d97cec996a95`, owner `embedding:17208:28388`, expiring at `1793915230.906`. The previous lease cannot be treated as free capacity.
- User approved releasing the reservation, but the owner is active and the current lease is unexpired. Keep the release fail-closed; do not interrupt the embedding worker. No benchmark or model inference ran.
- Search-summary quality and RTX 5070 Ti performance/quality gates remain open. Recheck only after the active owner stops or the lease expires without renewal.

### Continuation checkpoint — 2026-11-05, expired fence requires intervention

- At 21:47:25 UTC the recorded reservation had passed expiry, but `gpu_reservation_status` returned `state=unknown` and `manual_intervention_required=true`; the known owner PID 17208 was still alive. One consented Hub release attempt for generation `cef450e3a3174f87acc3d97cec996a95` returned `success=false`, `mutation_applied=false`. Do not unlink or rewrite the fence manually.
- The targeted prewarm regression module passed (9 tests); `tests/unit/test_mcp_gpu_reservation_release_contract.py` passed (1 test); `python tools/release_check.py --allow-installed` passed. No broad suites, GPU benchmark, or model inference ran.
- Live search-summary and RTX 5070 Ti measurements, task-quality matrix, route recommendations, full review, and broader release validation remain open. Hardware evaluation cannot proceed until the reservation state is repaired through an authorized recovery path and GPU admission is verified free.

### Continuation checkpoint — 2026-11-05, reservation state readable again

- At 22:53 UTC the Hub returned a valid active reservation again: generation `3ea5f04242174aeea71e4b27d8f0ad50`, owner `embedding:17208:28108`, expiry `1793919854.9008765`. PID 17208 was live with increasing CPU. The prior `unknown/manual_intervention_required` snapshot is historical; the current GPU is still reserved.
- Hub status reports `vram_pressure=nominal`, but `gpu_admission_state=outcome_unknown`, `active_model=null`; this does not authorize an inference or benchmark. Wait for the current owner/lease to stop or expire, then verify a fresh free state before GPU work.
- Targeted regressions and `release_check --allow-installed` remain passed; no broad suites or GPU inference ran. All live quality/performance gates remain open.
- Re-ran the isolated reservation lifecycle module after resume: `tests/test_external_gpu_reservation_lifecycle.py` passed 33 tests using temporary reservation paths. This does not verify or repair the live server fence.
- Re-ran targeted profile and search-summary regressions: `tests/test_config_hardware.py` passed 28 tests; `tests/test_mcp_agent_routing.py -k search_ai_summary` passed 12 tests (108 deselected). These are source-level checks, not live model quality or performance evidence.

### Continuation checkpoint — 2026-11-05, consented lease released but GPU not free

- Confirmed owner PID 17208 was absent while generation `3ea5f04242174aeea71e4b27d8f0ad50` was still reported active. The user-approved `gpu_reservation_release` call succeeded with `mutation_applied=true` for that exact generation.
- Fresh status immediately after release returned `reservation_present=true`, `state=unknown`, `manual_intervention_required=true`; Hub status reported `gpu_admission_state=preparing_model`, `active_model=null`, and pending/stale VRAM telemetry. A later bounded recheck showed the same state. Do not infer free GPU or start inference/benchmark.
- Targeted source regressions and release check remain passed. Live model quality, 5070 Ti measurements, route recommendations, integrated review and broader release gates remain open.

### Continuation checkpoint — 2026-11-06, internal GPU preparation after release

- The external generation-bound lease release succeeded. Fresh status then stayed `reservation_present=true`, `state=unknown`, `manual_intervention_required=true`; `local_ai_status` reported `gpu_admission_state=preparing_model` followed by `outcome_unknown`, with no active model and stale/pending telemetry.
- Current scheduler source shows internal GPU work uses a digest-only fence (`_claim_internal_gpu` in `src/local_ai_hub/scheduler.py`), which the external status endpoint cannot identify as an external owner. The current fence may therefore be an internal operation, but that identity is not proven. Treat the GPU as occupied until status and scheduler admission provide fresh usable evidence.
- Do not retry the successful release, remove fence files, or run inference/benchmark under the unknown state. Continue with safe source-level validation; then recheck admission after preparation resolves.

### Continuation checkpoint — 2026-11-06, focused validation and recovery inspection

- Fresh `local_ai_status` request `req_83decbb27b2c` still reports `gpu_admission_state=outcome_unknown`, `active_model=null`, and pending/stale VRAM telemetry. The active MCP coordination schema does not expose reservation status or release actions.
- Current scheduler source confirms that a model-switch exception after a potentially started operation sets `_internal_gpu_uncertain`; subsequent internal claims fail closed. No inference, benchmark, or fence-file mutation is justified by this state.
- `python -m pytest -q tests/test_prewarm_reliability.py`: 9 passed. `python tools/release_check.py --allow-installed`: OK. Targeted `git diff --check`: exit 0; Git noted the existing prewarm test file may be converted from LF to CRLF on a future Git write.
- Live search-summary baseline, RTX 5070 Ti cold/warm measurements, labeled capability-quality matrix, route recommendations, independent review, and pre-release validation remain open.

### Continuation checkpoint — 2026-11-06, reconcile lexical search default

- A current-source audit found the checked lexical-default deliverable had drifted: MCP discovery/wrapper, the HTTP omission fallback, `LocalAIServices.repo_search`, and both canonical prompts still selected or promoted `hybrid` by default. Updated each to default to `lexical`; `hybrid` and `rag` remain explicit options.
- Added focused regressions for the generated operation schema, MCP default/forwarding, HTTP request forwarding, and service behavior. Red checks reproduced the old `hybrid` defaults; after the fix, the selected checks passed: MCP 1, operation contract 1, HTTP 1, prompt contract 9; the full focused search-mode module passed 26 and the MCP search/summary subset passed 13, confirming explicit hybrid and AI summaries remain available.
- `python tools/release_check.py --allow-installed`: OK. Targeted `git diff --check`: exit 0; Git emitted only existing LF-to-CRLF warnings for two test files. The full test suite was not run.
- GPU admission remains `outcome_unknown`; live model quality/performance, route recommendations, independent review, and the remaining release gates are still open.

### Continuation checkpoint — 2026-11-06, Hub restart and reservation gate

- The operator-approved `python tools/hubctl.py restart` completed with exit code 0 (`restarted`). Post-restart readiness request `req_d8a26f0974d0` reports `gpu_admission_state=external_reservation`; active model is null and VRAM telemetry is pending/stale. Follow-up request `req_a8c40722121e` confirms hardware profile `high`, but does not expose reservation owner, generation, expiry, or process liveness.
- The active `local_ai_coord` MCP schema exposes `claim`, `release`, memory/task/plan actions, but not `gpu_reservation_status` or `gpu_reservation_release`. The user authorized release, but no generation-bound status is available through the active interface; do not infer owner death, delete reservation state, or run GPU inference/benchmarks.
- The source tree contains GPU reservation status/release contracts and a focused release-contract test. `python -m pytest -q tests/unit/test_mcp_gpu_reservation_release_contract.py`: 1 passed. This source test does not prove the installed Hub exposes the new actions.
- The Codex MCP server constructs `HubClient(auto_start=True)`. The real-child cold-start integration check `tests/test_t04_real_child_startup_acceptance.py::test_autostart_launches_real_hub_child_and_returns_http_search_result` passed (1 test), verifying daemon-off startup and an HTTP search response.
- The Hub task checkpoint is `req_979fc5b295c3`. Remaining GPU quality, cold/warm, concurrency and route recommendation gates stay open. Continue safe targeted source work; run only specific tests, not the full suite.

### Continuation checkpoint — 2026-11-06, active schema regression

- Fresh Hub readiness request `req_927bd1293c69` reports `gpu_admission_state=preparing_model`, `active_model=null`, and VRAM sample pending/stale. This is not GPU availability, residency, or benchmark evidence; do not repeat status polling or admit inference based on it.
- Source-index request `req_7bd55b65a32c` located the GPU status/release contract and MCP description. Focused test `tests/test_mcp_agent_routing.py::test_coord_description_and_prompts_expose_plan_workflow` passed (1 test), confirming source-generated action documentation and prompt parity. The currently attached MCP tool schema still omits these actions, so installed/runtime exposure remains unresolved.
- Exact-source artifact slices exceeded their requested response budgets and were not retried. No source change or broad test run was made; the reservation and physical evaluation gates remain open.

### Continuation checkpoint — 2026-11-06, generation-fenced release regression

- Focused safety tests passed: `test_consent_release_requires_expired_idle_generation_and_audit_reason` and `test_consent_release_allows_confirmed_dead_embedding_owner` (2 passed). These prove source-level release conditions only; they do not authorize release of the live reservation.
- The active runtime still reports `preparing_model` with no active model and stale VRAM telemetry, while the attached MCP schema lacks the tested reservation actions. No live reservation was changed and no GPU inference was started.

### Continuation checkpoint — 2026-11-06, source MCP schema coverage

- `tests/test_mcp_agent_routing.py::test_public_action_parameters_are_explicit_literals` passed (1 test), confirming `gpu_reservation_status` and `gpu_reservation_release` remain in the source `local_ai_coord` Literal action contract. `tests/test_mcp_agent_routing.py::test_live_mcp_schemas_are_valid_without_empty_combinators -k local_ai_coord` passed (1 passed, 1 deselected), confirming source MCP schema validity.
- An initial parameterized-test selector escaped incorrectly and collected no tests; the two corrected exact selections above ran and passed. No broad suite was run.
- The active Codex tool metadata still omits the reservation actions despite source coverage. Fresh readiness `req_faa99e3790d9` reports `external_reservation`, no active model and stale VRAM telemetry. Do not release or benchmark without the live generation-fenced status interface.

### Continuation checkpoint — 2026-11-06, prewarm retry safety review

- Reviewed `_prewarm_should_retry` and its bounded retry loop. It stops when scheduler status is unavailable, malformed, or `outcome_unknown`; it retries only an allowlisted admission state, with a 120-attempt default cap and bounded waits.
- Focused checks passed: `test_prewarm_stops_retrying_after_unknown_gpu_outcome`, `test_prewarm_retries_while_gpu_is_temporarily_busy`, and `test_prewarm_stops_when_scheduler_status_is_unavailable_or_unknown` (3 passed). This validates retry policy, not physical GPU readiness.
- Fresh Hub readiness `req_d4bb195456c1` reports `gpu_admission_state=outcome_unknown`, active model null and stale VRAM telemetry. The fast-model comparison, 5070 Ti benchmark, labeled quality matrix, and route recommendations remain open.

### Continuation checkpoint — 2026-11-06, authorized reservation cleanup

- User authorization and the replacement repo policy exposed `gpu_reservation_release_authorized`; the first authorized call returned `success=true, mutation_applied=true`. The immediate status still showed `reservation_present=true, state=unknown, manual_intervention_required=true`, so I inspected the current source contract rather than touching reservation files.
- Source confirms the authorized release takes the store lock and removes only a valid current lease, valid orphan metadata, or a validated legacy digest fence; symlinks and malformed content fail closed. A second distinct authorized cleanup returned `success=true, mutation_applied=true`; follow-up status now reports `reservation_present=false, state=free, manual_intervention_required=false`.
- Final post-cleanup readiness `req_a47802bba371` remains `gpu_admission_state=outcome_unknown`, `active_model=null`, with VRAM telemetry `sample_pending`, `sampling=true`, and `stale=true`. Reservation cleanup is verified, but GPU inference/benchmark is still unsafe until admission and telemetry become fresh.

### Continuation checkpoint — 2026-11-06, restart and admission mismatch

- Restarted the Local AI Hub with `python tools/service.py restart` (exit 0). Hub and Ollama came online. Readiness `req_fe9a762f31b6` reports `gpu_admission_state=external_reservation`, `active_model=null`, and VRAM `sample_pending`/stale.
- A fresh `gpu_reservation_status` reports `reservation_present=false`, `state=free`, and `manual_intervention_required=false`. These two live interfaces disagree. No second cleanup or GPU inference was attempted.
- Current scheduler source initializes its GPU reservation path from configured `server.state_dir` and reports `external_reservation` when `_external_gpu_reserved()` is true. It does not explain why this differs from the owner-global coordination status. Exact source revision fingerprint: `bc60898d12b5ee5a76caa4fcedd59c608feb2d238afe8024a2daea35bffd1cff`.
- `python tools/hubctl.py status` confirms Hub 5.1.3 online, one model online, and `NVIDIA GeForce RTX 5070 Ti (15 GB)`. Focused test `tests/test_mixed_scheduler_integration.py::test_scheduler_timeout_reports_gpu_reservation_wait_reason` passed (1 passed); it validates scheduler reporting only, not the live GPU state.
- A bounded `local_ai_repo(action="review_diff")` request for this plan returned queued job `940f40f3fa1f43f69d592cc773feb848` with `admission_state=degraded`, `reason=resource_pressure`, and VRAM sample `sample_pending`; it returned no task ID or review result. Do not count this as review evidence.
- Focused remaining task: identify whether the scheduler and coordination endpoint resolve different reservation stores or whether another live owner holds a separate reservation. Keep 5070 Ti benchmarks and inference on hold until a single fresh readiness result reports safe admission and fresh VRAM telemetry.

### Continuation checkpoint — 2026-11-06, benchmark response and fail-closed reservation

- After the stale embedding lease was released, one Hub restart failed verification and left the service offline. `python tools/service.py start` then succeeded; `hubctl status` confirmed Hub 5.1.3 online as PID 27672, seven installed models, one online model, and RTX 5070 Ti 15 GB.
- Readiness `req_326dfe421dfd` reported `gpu_admission_state=available`, active `qwen3.5:4b-nvfp4`, but VRAM telemetry still `sample_pending`/stale. Reservation status was free before a bounded 40-token `hardware_benchmark` request (`req_effe10b29b24`). The request returned `success=true` but its response envelope was truncated and contained no measurements; it is not benchmark evidence.
- Follow-up status `req_2fed97909cde` reported scheduler `probe_timeout`, `gpu_admission_state=unknown`, and no active model. Reservation status then returned `state=unknown, manual_intervention_required=true`. The user-authorized `gpu_reservation_release_authorized` call failed closed with `no valid current GPU reservation could be released` and `mutation_applied=false`.
- Do not retry inference, benchmark, restart, or remove the state file directly. Resolve the malformed/unreadable reservation through a supported diagnostic or operator repair path first. Hardware results, quality matrix, and `high` route recommendations remain open.

### Continuation checkpoint — 2026-11-06, lease heartbeat verification

- Current reservation status is again `free`; no cleanup was needed. Fresh Local AI readiness `req_04bbf27d11a8` is degraded: scheduler, runtime, Ollama profile and other dependencies time out; admission is `unknown`, VRAM is `sample_pending`/stale. No live inference or benchmark is safe.
- The shared checkout contains a reservation keepalive context plus embedding and reranker integration. Three focused tests now pass: `test_active_lease_heartbeat_prevents_expiry_until_owner_finishes`, `test_embedding_renews_gpu_fence_until_long_inference_finishes`, and `test_cuda_reranker_renews_shared_reservation_during_long_call` (3 passed). The embedding test now checks lease expiry at the in-inference observation timestamp, avoiding a post-return TTL race. These are isolated/mock tests, not physical GPU evidence.
- `git diff --check` passed for the modified source, test and plan paths. The hardware benchmark request still has no usable metrics; continue to hold GPU evaluation until Hub dependencies and admission recover.
- After the focused tests, `hubctl status` showed a new online Hub process (PID 42404). Readiness `req_e6b764d906b3` reports active `qwen3.5:4b-nvfp4` and `external_reservation`, while the owner-global reservation action reports `free`. The mismatch persists across process replacement; VRAM telemetry remains stale, so no further inference or restart was attempted.

### Continuation checkpoint — 2026-11-06, scheduler-authoritative reservation path

- The user approved immediate reservation cleanup. `gpu_reservation_release_authorized` returned `success=false`, `mutation_applied=false`, `no valid current GPU reservation could be released`; the store stayed untouched.
- Implemented an authenticated `/api/gpu-reservation` route handled by the Hub server's active scheduler. MCP status and release actions now use that route, so they read and mutate the same configured store as scheduler admission. Authorized release calls scheduler status afterward to observe the durable operator-release marker and clear stale in-memory admission.
- Focused verification passed: route registry and dispatch checks, both MCP release contract tests, scheduler-authoritative release and store-release synchronization tests, and lifecycle owner-probe test (7 passed). `git diff --check` passed before this checkpoint.
- Source-level routing is now covered; the installed Hub process has not been restarted onto this source, and runtime parity, local-model quality, VRAM measurement, and RTX 5070 Ti benchmark evidence remain open. Continue with targeted tests and review, then restart only through the managed service path when source validation is complete.

### Continuation checkpoint — 2026-11-06, live scheduler route after managed restart

- Targeted source validation passed: `py_compile` for scheduler, route registry, HTTP server and MCP server; 8 selected regression tests passed; the isolated embedding lease-heartbeat test passed separately (1 passed); `git diff --check` had no whitespace errors. No broad suite ran.
- The previously requested managed `python tools/hubctl.py restart` completed. `hubctl status` reports Hub 5.1.3 online (PID 29532), one model online, RTX 5070 Ti 15 GB. Through the new authenticated route, `gpu_reservation_status` request `req_b0205f15f2e0` returned `free`; readiness `req_d777863c56b7` returned `gpu_admission_state=available`, `degraded=false`, profile `high`, active `qwen3.5:4b-nvfp4`. VRAM telemetry remains `sample_pending`/stale and pressure `unknown`.
- One bounded 4B hardware smoke request `req_2e47da44287b` returned `success=true` with a truncated response envelope and no measurements. It is not benchmark evidence; no retry was made. Workstream 4 fast-model comparison, Workstream 6 performance/quality matrix and route promotion remain open. Broader release checks remain unrun per the user's targeted-test instruction.

### Continuation checkpoint — 2026-11-06, current readiness and release check

- Fresh readiness `req_77f27afb7ba3` reports Hub online but `gpu_admission_state=outcome_unknown`, no active model, stale/pending VRAM telemetry, and a preprocessing stats probe timeout. No more inference, benchmark, status retry, or restart was attempted after this result.
- The configured Codex/MCP auto-start contract remains active: `test_mcp_client_keeps_hub_owned_auto_start_enabled` and `test_mcp_client_bounds_auto_start_after_daemon_connection_refusal` passed (2 passed).
- The read-only `python tools/release_check.py --allow-installed --json` passed version consistency, defaults consistency, manifest hygiene, public docs and release-doc version; it failed workspace hygiene on `forbidden directory: build/`. The existing directory was preserved. No full test suite was run.
- Source/runtime reservation routing is verified, but local-model review, fast-model paired comparison, RTX 5070 Ti performance/quality measurements, route promotion, workspace hygiene and broader release suites remain open.

### Continuation checkpoint — 2026-11-06, hybrid search fallback and workspace hygiene

- Owner-global reservation request `req_ba29036019ce` reports `free`; this does not clear the previously observed scheduler `outcome_unknown`, so no inference was attempted.
- Nine focused search regressions passed. They cover preservation of original lexical terms, bounded preprocessed candidate paths for hybrid fallback, Czech pagination term expansion, and simple Unicode ripgrep candidates with Python verification. Multi-character case folds remain on the authoritative Git scan. This improves deterministic retrieval/fallback; it does not qualify model summaries.
- `build/` is not empty: it contains `bdist.win-amd64` and `lib` with 207 entries. Both nonrecursive removal attempts failed without deleting contents. The build output remains preserved; release hygiene remains blocked on ownership/cleanup.
- The fast-model comparison, RTX 5070 Ti performance/quality matrix, route promotion, and broader release suites remain open.

### Continuation checkpoint — 2026-11-06, exact-search Unicode candidate safety

- A failure-first regression reproduced an exact-count risk: Python `.lower()` finds ASCII `i` inside `İstanbul` after its lowercase expansion, while ripgrep Unicode simple folding returns no file. Ripgrep candidate filtering could therefore drop an exact match.
- Exact search now caches the set of characters produced by multi-character lowercase mappings and disables ripgrep candidate narrowing when the query can match within or across such an expansion. The guard follows the actual `.lower()` matcher; simple safe Czech Unicode queries still use ripgrep, while expansion-prone queries retain the complete Git scan.
- Focused validation passed: exact-search and hybrid-candidate modules, 19 tests; four targeted search-mode fusion tests; `py_compile` on the touched search modules; `git diff --check`. No broad suite or GPU inference ran.
- This closes the source-level exact-search candidate safety unit; AI summary factuality, paired fast-model comparison, 5070 Ti measurements/quality, promotion and release gates remain open.

### Continuation checkpoint — 2026-11-06, bounded benchmark metric projection

- A mocked failure-first test showed `local_ai_task(hardware_benchmark)` could lose measured fields under a response budget because it reused the generic `status` projection. The response now uses a benchmark-specific projection that protects model identity, loaded/peak VRAM, token counts, latency, throughput, score, and measurement warnings while allowing verbose nonessential fields to be removed.
- Focused verification passed: the new budget-pressure projection test and canonical task-dispatch cases (14 passed), `py_compile` for `mcp_server.py`, and `git diff --check`.
- This repairs MCP delivery of metrics without running inference. A real benchmark still must be repeated once scheduler admission is authoritatively safe; the earlier truncated request remains unusable. Quality comparison, route promotion, final review, release hygiene and broader suite remain open.

### Continuation checkpoint — 2026-11-06, reservation cleanup and first valid RTX 5070 Ti sample

- Managed restart reset the scheduler's in-memory `_internal_gpu_uncertain` gate. The restart command initially left the Hub stopped; `python tools/service.py start` restored Hub 5.1.3. Readiness request `req_ed43be6b4c9c` reported `gpu_admission_state=available`; its first VRAM sample was pending.
- One valid warm benchmark on installed `qwen3.5:4b-nvfp4` succeeded as request `req_dcd2741b477e`: 40 backend-counted tokens, 170.67 tokens/s, TTFT 84.23 ms, generation 234.37 ms, call latency 318.6 ms, device-wide sampled peak 6,248,464,384 bytes. Model-attributed VRAM was unavailable. Full record is in `docs/agent-evaluation/results.md`. This does not complete cold, concurrency, quality or route-promotion criteria.
- The owner-global reservation became `unknown` after GPU activity and required the previously authorized Hub release operation. Source audit confirmed `_remove_unlocked` deletes the digest before metadata and did not retry a transient Windows sharing violation on metadata deletion. Added bounded retries for `WinError 32`, rechecking metadata generation and digest and refusing symlinks; malformed or persistent failures remain fail-closed.
- Failure-first regression was red before the fix and green after. Four targeted lifecycle tests passed, including digest-failure recovery and malformed-orphan refusal; `py_compile` and scoped `git diff --check` passed.
- Release check now passes after moving the ignored 207-entry `build/` output to `C:\Users\Adam\AppData\Local\Temp\local-ai-hub-build-archive-2026-11-06`; contents were preserved. No full test suite was run.
- Bounded semantic solve/review attempts still ended `outcome_unknown`; review artifact is unavailable and cleanup was unconfirmed. No further model work until the async worker state is authoritatively settled. Quality comparison, complete hardware matrix, route promotion, review and broader release suite remain open.

### Checkpoint — 2026-11-06, S1 and model admission

- Corrected the S1 deterministic `expected` phrase in `docs/agent-evaluation/local-model-gpu-cases.md` from `equal to either bound` to `equal to bounds`; the qwen3.5:4b-nvfp4 response already conveyed this meaning, used the exact citation, stayed within 80 words and preserved incomplete-coverage uncertainty.
- Re-ran fixed S1 through `local_ai_task(eval_suite)` as request `req_dd9992ea8cb1`. qwen3.5:4b-nvfp4 digest `56d8c805bbeb679be81d064cbda81aa3f91eb32492a4547c0ebaa50690980506` passed 1/1; duration 844.36 ms; 61 estimated tokens; citation precision, required citation, concision and expected content all passed. This is one synthetic case, not full search-endpoint, role or route qualification.
- qwen3.5:9b-nvfp4 S1 request `req_a4eec253faeb` was rejected before inference with `vram_budget_after_unload`. A later qwen3.5:4b-nvfp4 S1 retry request `req_d169e693c2bb` was also rejected before inference with `insufficient VRAM for model admission`; do not bypass scheduler admission.
- `evaluation_report` request `req_81d648add628` remains `insufficient_evidence`/`hold` with 0 matched tasks. No route promotion follows from the S1 pass.
- Readiness request `req_112642585ba6` reported `gpu_admission_state=external_reservation`; reservation request `req_3c8b0b467551` identified an active embedding owner. Do not release or compete with this live reservation.
- W4 paired search-summary quality/performance and W6 remaining model cases, repeated warm/cold performance, context and concurrency qualification, and all route-promotion gates remain open.

### Continuation checkpoint — 2026-11-06, search-summary response-budget preservation

- A deterministic response-budget review found that `_compact` protected search pagination and retrieval metadata but dropped the advisory fields produced by `local_ai_repo(search, summarize_results=true)` while compacting large responses. Added preservation for the summary, citation validation, source list, advisory marker and root fingerprint, and a targeted regression with a long result page.
- Focused verification passed: the new response-budget regression plus four existing summary citation/input/truncation tests (**5 passed**); `py_compile src/local_ai_hub/mcp_server.py` and scoped `git diff --check` passed. No broad test suite ran.
- An actual summarized search request `req_fbf24f918473` returned a truncated envelope; its summary text/citation fields were not captured, so it is inconclusive and is not quality evidence. A subsequent bounded `local_ai_repo(action="solve")` review request `req_7ddd574335f5` ended `outcome_unknown` with the GPU reservation retained. No more local inference or benchmark until that state is resolved; do not replay the request or release the retained reservation.
- The paired fast-model comparison, remaining quality cases, RTX 5070 Ti cold/warm/concurrency measurements, route promotion and final integrated gates remain open.

### Continuation checkpoint — 2026-11-06, MCP transport unavailable

- Local AI MCP calls then failed to connect to `http://127.0.0.1:11436/mcp`; one readiness attempt failed the same way. Bounded `python tools/hubctl.py status` still reports Hub v5.1.3 online (PID 22828), Ollama online and RTX 5070 Ti present. Hub process status does not resolve MCP transport or GPU admission; no restart or inference was attempted.
- Continue with already-grounded source work only until MCP connectivity and the retained GPU outcome can be checked through their authorized interfaces.

### Continuation checkpoint — 2026-11-06, admission recovered and repeat warm sample

- Current MCP readiness request `req_6556a7110707` reports admission `available` with `qwen3.5:4b-nvfp4` active; reservation request `req_c3074a4066d7` reports `free`. The earlier solve request remains unqualified; it was not replayed.
- One repeat warm benchmark `req_b6f25eec1b1e` succeeded and is recorded in `docs/agent-evaluation/results.md`. It returned six tokens at 55.08 tokens/s; speculative inference was active with `qwen2.5-coder:3b`. Device-wide peak was 12,384,731,136 bytes; model-attributed VRAM remains unavailable. Do not compare this short, speculative sample as a stable throughput result.
- Repeat warm samples without confounds, cold-start, concurrency/context, task-quality evaluations, paired fast-model comparison, route promotion and final gates remain open.

### Continuation checkpoint — 2026-11-06, search summary remains unqualified

- Live search summary requests `req_d69c180190cb`, `req_00fba5d410f9`, `req_bf9b8c010817`, `req_a5fead5a906e` and `req_38e23ed20303` produced claims not supported by cited source excerpts, despite structural `source_bound` validation. The last request still cited `src/local_ai_hub/mcp_server.py:6082-6092` and made an unsupported `local_ai_work` claim; nested model request `req_879ca9a24561`. Keep search summaries advisory and unqualified; do not promote route.
- Source fix removes the search query from model input, strengthens excerpt-grounding instructions, and clips leading adjacent Python definitions from query-named excerpts while narrowing citation line ranges. Added a regression using the `local_ai_work` source span. Focused tests: 13 passed, 108 deselected. Local source evidence confirms the helper exists; live runtime/source alignment remains unresolved.
- Runtime diagnosis: `python tools/hubctl.py status` reports HTTP Hub PID 5736 online. Separate Python PIDs 25032/29268 run `local_ai_hub.mcp_server`, created 10:54:37; checkout source last-write is 13:03:36. MCP config generation uses `-m local_ai_hub.mcp_server` with `cwd=install_dir` (evidence `E9dd34a1b929b7f2c83d9`). The active MCP server predates this edit; restarting HTTP Hub alone will not reload its Python module. No direct MCP restart control is exposed here.
- Diff review request `req_d392f704f353` failed in model `qwen3.5:4b-nvfp4`; no retry. Earlier whole-diff review exceeded the 8-segment safe limit (`req_2466e14ed564`). Static compile and scoped diff check passed.
- Next: restart/reconnect Codex's `local-ai` MCP server, then run one live summary probe and confirm adjusted source citations before judging quality. Do not issue another model request or claim live fix until runtime reload is verified. Paired fast-model comparison, remaining quality cases, GPU matrix and final gates stay open.

### Continuation checkpoint — 2026-11-06, Hub restart and rejected summary probe

- Verified the stale local MCP parent/child processes `25032`/`29268` and stopped them; the child exit also ended its parent. The Local AI tool bridge remained callable. A subsequent process scan found only the HTTP Hub server, so process termination alone did not establish a reloaded MCP wrapper.
- One fresh search-summary request `req_cade9e7b8b37` returned deterministic search results but its local summary was rejected before inference: qwen3.5:4b-nvfp4 `insufficient VRAM for model admission`, qwen3.5:9b-nvfp4 circuit open; nested request `req_1d29ed194d61`. No retry. Its returned summary source metadata still used untrimmed `src/local_ai_hub/mcp_server.py:6082-6092` despite the local helper's clipping regression; runtime alignment remains unproven.
- Owner-global GPU reservation was free (`req_87cd899348f1`) before the managed restart. `python tools/service.py restart` succeeded; `hubctl status` now reports Hub 5.1.3 online as PID 29996. Post-restart readiness `req_6ce56ee60af9` reports profile `high`, nominal VRAM pressure, but `gpu_admission_state=preparing_model` and no active model. Do not infer or retry while preparation is unresolved.
- Focused current-workspace preprocessing tests passed 2/2; scoped `git diff --check` passed. No full suite ran. Next: continue independent source/test work; before any new live summary probe, obtain one fresh readiness and reservation observation after startup activity has settled, then verify narrowed citations and claim quality. W4/W6 quality and GPU gates remain open.

### Continuation checkpoint — 2026-11-06, code-index cache repeat benchmark

- Current readiness `req_df523d3b96f5` reports `qwen3.5:4b-nvfp4` active, profile `high`, admission available, but VRAM telemetry pending/stale. Reservation `req_377f06f6da34` is active for reranker PID 29996; do not run model/GPU work or release it.
- Verified two focused tests for the current source changes: code-index inventory-cache reuse/invalidation and file-ref revision tracking; 2 passed. Scoped `git diff --check` passed.
- Ran `tools/benchmark_code_index_inventory_cache.py --files 5000 --demand-files 32 --repeats 3`. Synthetic full-scan median 1,459.787 ms versus revision-cache 801.831 ms (45.07% faster); path-policy checks fell 165,000 to 5,000 (96.97%). This is warm-cache synthetic evidence only, not live repository or service performance; recorded repeat in `docs/CODE_INDEX_INVENTORY_CACHE_BENCHMARK.md`.
- The MCP summary probe remains unqualified after its pre-inference VRAM rejection and untrimmed source metadata. Next live work requires a later independent ready status and free reservation; no polling or retry. W4/W6 remain open.
