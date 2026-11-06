# Local AI Hub GPU/runtime audit

**Audit date:** 2026-11-04  
**Audited checkout:** repository root (machine-local path omitted)  
**Revision:** `f08d7c9c919962216c719f8fb37c9d962aee9d61` (`master`, clean, one commit ahead of `origin/master`)  
**Scope:** user requests and open gates in `docs/superpowers/plans/2026-11-03-gpu-capability-tiers-and-local-ai.md`.  
**Disposition:** source changes are partial; GPU/runtime acceptance is **NOT VERIFIED**. This report records findings and evidence limits. It is not a release approval.

## Findings

### A1 — Reservation cleanup can strand an orphan record

**Severity:** high; recovery/correctness risk.  
`ExternalGpuReservationStore._remove_unlocked()` deletes the digest fence first and the metadata second. If the process stops or the second unlink fails between those operations, metadata remains without a digest. `_read_unlocked()` requires both files, so consented release cannot recover the generation and later claims fail closed. Existing lifecycle tests cover consent, expiry, malformed state, and shared claims, but no failure injection between the two deletions.

**Evidence:** `src/local_ai_hub/external_gpu_reservation.py` (`_remove_unlocked`, `_read_unlocked`, `release_with_consent`); `tests/test_external_gpu_reservation_lifecycle.py`.

**Closure update (2026-11-04):** the owner may recover the exact valid metadata-only orphan only with explicit consent for the matching generation and after expiry. All valid leases, including `active`, now expire after 900 seconds without renewal; reaping, replacement reservation and internal GPU claims apply the same expiry. The owning scheduler also retains the lease deadline in memory and releases its fail-closed reservation state at expiry if the files disappeared. Malformed metadata remains fail-closed. Twelve focused lifecycle/scheduler tests pass, covering expiry, renewal, both unlink-failure boundaries, consented recovery, malformed metadata, in-memory expiry, and cross-scheduler exclusion. Live Hub status now reports GPU admission `available`; the current process started after the earlier `external_reservation` observation, so this demonstrates recovery after a service start, not the cause of the prior runtime state. Installed MCP action parity remains unverified.

### A2 — Removed model names remain in prompts and advisory metadata

**Severity:** medium; stale recommendations/configuration.  
The removed `qwen3.5:4b-q4_K_M` and `gemma4:12b` remain in both canonical agent prompts, `docs/MODEL_CAPABILITIES.md`, `src/local_ai_hub/prompt_contracts.py`, and generated guidance in `src/local_ai_hub/generator.py`. `gemma4:12b` and `qwen2.5-coder:14b` also remain in the future `16gb` candidate list in `src/local_ai_hub/opencode_hardware.py`. The latter is explicitly a future candidate list, not proof of a live inference route. Current high/max hardware defaults inspected in `src/local_ai_hub/hardware.py` route to Qwen Coder 3B/7B and Qwen 3.5 9B.

**Progress:** the working tree now replaces the retired Qwen Q4 capability entry with the user's `qwen3.5:4b-nvfp4` candidate, removes Gemma and Coder 14B from prompt/capability recommendations, updates the 16 GB future-candidate list to the installed NVFP4/Coder choices, and synchronizes both canonical prompts. Historical inventory and audit evidence retain old names where needed to preserve what was tested. The same-day inventory records successful benchmark requests on Qwen 9B NVFP4 and Qwen 4B NVFP4, proving those tags were installed at measurement time; a new installed-tag snapshot is still needed before a current runtime claim.

**Required closure:** verify that no stale active/advisory/future-candidate reference remains outside historical evidence, confirm current installed tags, and keep both canonical prompts synchronized.

### A3 — Context and concurrency settings are not hardware-qualified

**Severity:** medium; OOM/latency and capacity risk.  
High/max defaults set Ollama `num_parallel=2` and `q8_0` KV cache. Smart context is configured for 65,536 tokens, while smart-role parallelism remains 1. High/max background GPU parallelism is 4/6, with larger file/module batches. The profile selects CUDA retrieval devices when detected NVIDIA VRAM is at least 15 GiB. These are configuration values; they do not prove available memory, GPU residency, two-request capacity, throughput, or stable latency.

**Evidence:** `src/local_ai_hub/hardware.py`; the dated observations in `docs/LOCAL_MODEL_CAPABILITY_INVENTORY.md` (2026-11-04) report Hub/Ollama/managed llama.cpp online, seven installed models, and an RTX 5070 Ti with 15 GB reported VRAM. That status does not report the effective profile or simultaneous request capacity.

**Partial benchmark evidence:** the same inventory records two single-sample `qwen3.5:9b-nvfp4` hardware benchmarks: a six-token smoke at 148.09 tokens/s and 4.10 s TTFT, and a warm 256-token run at 133.12 tokens/s and 2.23 s TTFT; sampled device-wide peak VRAM was about 6.80 GB in both. These do not establish sustained performance or quality.

**Required closure:** capture driver/backend, effective profile, model identity, context, KV quantization, free/peak VRAM, residency/offload, repeated cold/warm latency, throughput, and concurrency/error results. Test 65k contexts and two concurrent requests together; reduce configured limits if measurements fail.

### A4 — GPU embeddings and reranking are configured, not proven active

**Severity:** medium; performance/readiness unknown.  
The high/max profile requests CUDA for embeddings and reranking. Both implementations use shared GPU admission when CUDA is selected. This source path does not prove the current Python/Torch backend loaded CUDA or that these requests execute on the GPU. A previously recorded reranker smoke was CPU-only and too small to establish relevance or performance.

**Evidence:** `src/local_ai_hub/embeddings.py`, `src/local_ai_hub/reranker.py`, `src/local_ai_hub/hardware.py`; the dated inventory contains no GPU benchmark for embeddings or reranking. Its earlier reranker smoke was CPU-only.

**Required closure:** benchmark representative embedding and reranker batches on GPU and CPU, record device, warm/cold latency, throughput, peak VRAM, result quality, and fallback behavior. Preserve deterministic retrieval when GPU admission/backend is unavailable.

### A5 — Llama.cpp model switching exists in source; runtime acceptance is open

**Severity:** acceptance gap.  
`llama_cpp.py` exposes `ensure_model()` and `unload_model()`. `ollama.py` calls these during model preparation and can unload competing models. This establishes source-level lifecycle support, not successful live loading/unloading, cancellation safety, model switching under concurrency, or measured VRAM release on the configured backend.

**Required closure:** exercise load → inference → unload → different model load on the configured llama.cpp backend; verify inventory, actual GPU residency, cancellation, failure fallback, and scheduler reservation release. Do not infer this from the Ollama path or source methods alone.

### A6 — Demand-based preprocessing is partial, not a global on-demand guarantee

**Severity:** design/quality gap.  
`UsageLearner.hot_queries()` orders learned queries by hit count and recency. Preprocessing maps up to four hot queries to matching source paths and gives a bounded preference to those paths in semantic file-card batches; ordinary structural priorities remain. This affects batch selection. It does not establish that all preprocessing is demand-triggered or that frequently used files receive deeper/higher-quality analysis.

**Evidence:** `src/local_ai_hub/learning.py`; `src/local_ai_hub/preprocess.py` (`_learned_priority_paths`, `_find_next_files`); `tests/unit/test_preprocess_demand_priority.py`.

**Required closure:** measure time-to-useful-context and work saved for hot versus cold files on representative repositories; confirm freshness/invalidation and ensure hot-file priority cannot starve the rest of the index. Decide explicitly whether additional quality/depth is intended.

### A7 — Tool-calling quality is unqualified

**Severity:** capability remains unavailable for promotion.  
The dated inventory records fixed C1–C3 cases at requested context 16,384: `qwen3.5:9b-nvfp4` failed C1 (zero tools attempted) and C3 (required source path missing, no tool attempted), while passing C2; `qwen3.5:4b-nvfp4` failed C1 (zero tools attempted). The harness bypasses Hub scheduling/cache and is smoke evidence, not broad quality qualification. OpenAI-compatible API/tool schema support alone does not prove useful tool calling.

**Required closure:** run the plan's task-specific labeled tool-use cases with measured model/provider identity, valid-call rate, grounded result use, failure recovery, latency, and VRAM. Keep permissions and final verification independent of model capability.

## Validation evidence and limits

- `git diff --check HEAD^ HEAD` fails on this audited revision: `tests/test_external_gpu_reservation_lifecycle.py:168` has a new blank line at EOF.
- Earlier focused GPU/search evidence was not bound to this clean revision: one combined run recorded 173 passed, 1 failed, 1 skipped; the cancellation failure passed in isolation, so timing sensitivity remains unresolved.
- Earlier full-suite evidence was from a changing candidate. After later refinements, a clean full pytest/release-check run was recorded as **NOT RUN**. Do not treat prior targeted passes as current full acceptance.
- Prior security scanning was incomplete (visited-file cap) and untriaged; it is not evidence that the current full repository is clean.
- During the save attempt, `local_ai_repo:search` returned `terminal=true`, `retryable=false`, `request_not_sent=true` (`req_c7dba910f3da`), permitting bounded native Git inspection. The same-day inventory supplies an earlier status/benchmark snapshot, but no live status call completed during report creation.
- The initial audit-document save made no runtime/provider changes. The later A1 progress entry records source and test changes. No model pulls, provider switches, or deployment changes were made.

## Open plan gates

The following plan acceptance items remain open: deterministic-vs-model quality comparison; live profile/model/device/memory inspection; RTX 5070 Ti throughput, VRAM, context, and concurrency benchmarks; labeled quality evaluation; evidence-based route/promotion thresholds; low-memory/provider-failure tests; focused failure-first testing/review; and full release checks plus broader suites.

## Suggested processing order

1. Fix and failure-test reservation partial-cleanup recovery.
2. Remove stale model recommendations from canonical prompts, model catalogs, generated guidance, and future-profile candidates.
3. Run focused source tests and `git diff --check` on a stable candidate.
4. Measure real GPU admission, embeddings, reranking, llama.cpp switching, context, and concurrency on the target device.
5. Evaluate tool calling and demand-priority behavior against labeled tasks and deterministic baselines.
6. Run full tests and release checks on one stable final revision; keep deployment/runtime claims separate from source-test evidence.

## Progress log

### A1 — generation-safe reservation cleanup

**Status:** source fix and focused regression coverage pass on the current worktree; GPU/runtime acceptance remains separate.
Consented recovery accepts only a valid, expired metadata-only orphan with the matching generation and no digest path/symlink, writes a distinct `consented_release_recovery` audit event, then removes the metadata. `reserve()` now aborts when cleanup of an expired generation fails, preventing a replacement lease from overwriting the orphan without consent. Malformed state and incomplete cleanup remain fail-closed.

**Failure-first evidence:** before the `reserve()` guard, the new metadata-unlink regression failed because `reserve()` returned a replacement generation. Tests cover both deletion boundaries: digest unlink failure retains the original readable expired generation; metadata unlink failure leaves the metadata orphan. For both, replacement/internal claims fail and explicit consented cleanup permits a later reservation. The current cohort `python -m pytest -q tests/test_external_gpu_reservation_lifecycle.py tests/test_opencode_gpu_reservation.py tests/unit/test_reranker_gpu_reservation.py tests/test_preprocess_status_scaling.py --tb=short` passed **87 tests** in 6.19 seconds. Scoped `git diff --check -- src/local_ai_hub/external_gpu_reservation.py tests/test_external_gpu_reservation_lifecycle.py` exited 0; Git reported only LF-to-CRLF working-copy warnings. No live GPU/runtime test ran; A1 is not GPU/runtime acceptance.

### A2 — stale model recommendations

**Status:** prompt/catalog cleanup implemented in the current uncommitted worktree. The 16 GB future-candidate test now expects `qwen3.5:9b-nvfp4`, `qwen2.5-coder:7b`, and `qwen3.5:4b-nvfp4`. The prompt capability registry recognizes the NVFP4 4B tag and drops the retired Q4/Gemma entries. A vision-prompt test now uses the retained `qwen3-vl:4b` contract.

**Validation:** tests were changed first and failed on the old candidate list and old model registry. After implementation, `python -m pytest -q tests/test_opencode_hardware.py tests/test_prompt_contracts.py tests/test_mcp_agent_routing.py --tb=short` passed **130 tests** in 5.94 seconds. The MCP routing cohort also exposed an outdated literal-action test that omitted the already-exposed `gpu_reservation_status` and `gpu_reservation_release`; its expected set now matches the public API. Historical inventory/audit references are intentionally retained and are not recommendations.

### A3 — profile, context, and concurrency qualification

**Status:** not qualified; no setting was changed. A single `local_ai_task(action="hardware_benchmark")` request selected `qwen3.5:4b-nvfp4` but returned `SchedulerTimeoutError`, `wait_reason="gpu-reservation"`, `scheduler_state="pending"`, `request_not_sent=true`, and `operation_not_started=true` (`req_acb028ebc48d`). This is an admission result only: no benchmark ran and it supplies no performance or capacity evidence. I did not retry or wait on the identical request. The shared checkout also contains uncommitted changes in runtime/configuration paths whose owner is not established, so those paths remain untouched.

Fresh Hub status (`req_26549f9f546b`) reports profile `high`, Hub/Ollama online, `active_model=null`, `vram_pressure=unknown`, and `context_budget_factor=0.25`. Reranking is `enabled_by_operator`, but provider readiness is `not_checked`. The response did not include `gpu_admission_state`; it does not establish that the earlier reservation has cleared or identify its owner.

**New live dashboard snapshot (2026-11-04, 14:36–14:37 Europe/Prague):** Overview reported GPU utilization 0%, system VRAM 9,698/16,303 MiB, and scheduler 0 queued / 0 running. After `Refresh resident inventory`, Models & search showed **no models currently resident**. Its configured execution rows show `qwen3.5:4b-nvfp4` fast context/max 65,536 with parallel 2; `qwen3.5:9b-nvfp4` smart context 32,768/max 65,536 with parallel 1; and `qwen2.5-coder:7b` smart context/max 32,768 with parallel 1. This conflicts with the later `local_ai_status` response (`req_b2302e456287`) reporting `active_model="qwen3.5:9b-nvfp4"`. Treat route identity, residency, and free memory as unresolved. The Coordination dashboard lists only the two `wishflix-shared-*` semaphores at 0/1; it exposes no GPU reservation owner/state.

**Next evidence needed:** reconcile the conflicting active-model/residency observations and establish the external GPU reservation owner through its owning Hub path. Then capture selected backend/device, installed model identity, available memory, and repeated cold/warm, context, and concurrent-request measurements. Until then, keep the 65k context, `num_parallel=2`, and background parallelism values classified as unqualified configuration.

### A4 — retrieval GPU evidence and safe CPU baseline

**Status:** GPU path remains unmeasured. The checked-in CPU reranker harness (`tools/benchmark_rag_reranker.py`, SHA-256 `e2ad1e493517096a3bae98bf06580ba9a9da347837e8e73889dd633a21a466c1`) disables model downloads and forces the reranker to Torch CPU, but obtains candidates through the live Hub `/api/rag/search` endpoint. It therefore isolates the reranker device, not the full retrieval/embedding path; running it cannot be assumed independent of GPU admission. I did not run it while the GPU reservation remained unresolved.

The plan still requires paired representative CPU/GPU embedding and reranker measurements with device, warm/cold latency, throughput, peak VRAM, relevance and fallback evidence. Existing CPU smoke results are small, one-shot, and insufficient for promotion. No A4 performance or quality claim is made.

### A5 — managed llama.cpp lifecycle: source tests only

**Status:** live acceptance remains open. The current `tests/test_llama_cpp_runtime.py` suite passed **51 tests and 36 subtests** in 0.70 seconds. Its lifecycle/startup cases use fake processes and temporary state, so this confirms mocked control-flow coverage only. The current Hub status reports `active_model=null` and `vram_pressure=unknown`; no live load → inference → unload → second-model load, cancellation, fallback, or VRAM-release sequence was run.

**Next evidence needed:** after the GPU reservation is cleared by its owner, run the managed backend sequence on the target device and record model/backend identity, actual residency, cancellation/fallback outcomes, and reservation release. Keep A5 unaccepted until that evidence is fresh and candidate-bound.

## Chat continuation evidence — 2026-11-04 21:46 UTC

This section consolidates additional evidence surfaced after the initial audit. It preserves historical runs as historical; none of these entries promotes a model or closes runtime acceptance.

### Current checkout and ownership boundary

The latest Hub `git_status` (`req_ae3ee3b183df`) reported branch `master`, 13 modified files, zero staged files, and zero untracked files. Modified paths were `docs/INSTALL_PROMPT.md`, this audit, `docs/UPDATE_PROMPT.md`, `docs/superpowers/plans/2026-11-03-gpu-capability-tiers-and-local-ai.md`, `src/local_ai_hub/external_gpu_reservation.py`, `src/local_ai_hub/operation_contracts.py`, `src/local_ai_hub/rag.py`, and tests `test_command_concurrency_contract.py`, `test_external_gpu_reservation_lifecycle.py`, `test_opencode_warmup_isolation.py`, `test_surface_benchmarks.py`, `test_surface_inventory.py`, and `unit/test_task_canonical_inputs.py`. The user confirmed another editor is still working. This inventory is a point-in-time workspace snapshot, not ownership attribution; preserve those changes and keep implementation/runtime tests separate until the editor releases the checkout.

### A1 and A2 latest evidence

- A1 source currently guards `reserve()` on a false `_remove_unlocked()` result. The focused reservation/OpenCode/reranker/preprocess cohort previously passed 87 tests in 6.19 seconds; both unlink failure boundaries and consented recovery are covered. This remains source/test evidence, not GPU acceptance.
- A2's current focused cohort passed 130 tests in 10.02 seconds. The earlier recorded run passed the same 130 tests in 5.94 seconds; retain both as separate run records. A repository search for the retired Q4 model returned 256 lexical matches with unrelated top results, while `code_index` reported stale results. Neither proves repository-wide absence of stale active recommendations.
- The dated inventory's seven-installed-model snapshot is historical. No current installed-tag inventory was obtained. Current status may identify a selected model but does not by itself prove installation, residency, or GPU execution.
- A paginated lexical search for `gemma4:12b` returned 11 candidates, including this audit, `AGENTS.md`, dated adoption/Blackwell/GPU plans and `tests/test_prompt_contracts.py`; the search used its fallback instead of path hints. Direct source slices show the 2026-11-01 spec labels Q4/Gemma assignments as initial advisory scopes and explicitly says they do not prove quality, installation, image support or tool support. The 2026-11-02 Blackwell plan treats Q4/Gemma as comparison or pending-evaluation candidates. Preserve those dated evaluation references as historical context; this lexical result is not a complete active-reference scan.
- `tests/test_prompt_contracts.py` currently asserts `qwen3.5:4b-nvfp4` is supported and the retired Q4/Gemma tags are absent from the capability registry. This is source evidence only; no test was run in this continuation.

### A3 current observations and benchmark limits

- Latest status request `req_a20e3c96554c`: Hub 5.1.3 and Ollama online, `active_model=null`, `vram_pressure=unknown`, `context_budget_factor=0.25`. Across separate chat status requests, `active_model` varied among null, `qwen3.5:4b-nvfp4`, and `qwen3.5:9b-nvfp4`; VRAM pressure stayed unknown. Dashboard resident inventory was shown as unknown/stale. Route identity, residency, free VRAM, and reservation ownership therefore remain unresolved.
- The plan working copy records a six-token `qwen3.5:4b-nvfp4` sample at 13.85 tokens/s, 433.3 ms TTFT, 9.46 GB sampled device-wide peak, and dynamic context 32,768. A single `qwen2.5-coder:7b` sample measured 116.7 tokens/s, 6.41 s TTFT, 3.76 s queue wait, 2.45 s load, and 16.48 GB sampled peak against a separately reported 16.30 GB total. Reconcile telemetry; neither sample qualifies capacity.
- A `qwen3.5:9b-nvfp4` request was rejected before inference because `target_vram_estimate_unavailable` (`req_ff950a1464e6`); do not replay it unchanged. Two earlier single-sample 9B runs measured 148.09 tokens/s for a six-token smoke and 133.12 tokens/s for a 256-token warm run, with about 6.80 GB sampled peak. They are not sustained or concurrent-load evidence.
- Two 20/20 warm 4B performance series are recorded in the plan. A longer 60-word generation series reports 56.5 median output tokens, 140.8 median tokens/s (p95 156.34), and 400.175 ms median TTFT (p95 477.61). This qualifies only those bounded workload measurements; it does not establish role quality, paired candidate/baseline acceptance, or broad context/concurrency capacity. A subsequent 7B repetition request was rejected for unknown VRAM estimate.
- Existing high/max settings (including 65,536-token context, `num_parallel=2`, q8_0 KV cache, and background GPU parallelism 4/6) remain configuration values, not measured guarantees. The plan also records a runtime/schema mismatch: benchmark runtime rejects `complexity="auto"` although checked-out source and contract tests accept it. Do not restart the installed service without an authorized runtime-change window.

### A4–A7 quality and runtime gates

- GPU embeddings and reranking remain unmeasured. The available CPU reranker harness uses the live Hub RAG search endpoint, so it is not independent of GPU admission. Paired representative CPU/GPU batches still need device, cold/warm latency, throughput, VRAM, relevance, and fallback evidence.
- Llama.cpp lifecycle tests use fake processes and temporary state. No live load/infer/unload/switch, cancellation, fallback, or measured VRAM release is recorded.
- Demand-based preprocessing only gives bounded priority to up to four learned hot queries. Time-to-useful-context, work saved, freshness, and starvation behavior lack representative measurements.
- Tool evaluation remains below promotion. Recorded fixed cases: `qwen3.5:9b-nvfp4` failed C1 and C3, passed C2; `qwen3.5:4b-nvfp4` failed C1. A separate custom three-case suite scored 1/3 on both 4B and 7B and is diagnostic only. Fixed R1/R2/T1/D1/C1–C3/I1/I2 runs remain incomplete or NOT_RUN.
- The fixed evaluation protocol requires a fresh isolated fixture outside every Git checkout for each run, paired baseline/candidate inputs and budgets, at least 20 comparable warm repetitions per measured scenario, median/p95, actual residency and VRAM, and separate 16k/32k/64k context plus concurrency-one/two and background-contention checks. Promotion requires all applicable nine cases, zero critical failures, at least eight passes, and no paired regression. Do not prepare fixtures or execute write cases in the shared checkout.

### Integrated validation still open

The plan's continuation records a bounded full-suite run stopping at 81% with 11,907 passed, 116 skipped, and five failures. Isolated reruns passed two cases; three T10 assumptions were corrected, after which the focused RAG/search/live-search/T10 cohort passed 69/69 and release-check, compileall, selftest, and diff-check were reported passing. The same plan says full integrated validation of the then-current dirty set remains required. These are plan-recorded historical results, not a fresh run for this checkout. The plan copy also contains a continuation heading dated 2026-11-05, later than the client date for this audit; reconcile chronology before treating those entries as current.

No tests, builds, fixture preparation, model pulls, provider switches, or service restarts were performed while the editor-owned checkout remained active. The latest live runtime sample above is status-only; GPU/runtime acceptance remains **NOT VERIFIED**.

## Chat continuation evidence — 2026-11-05

### Current checkout and validation

The fresh Hub `git_status` (`req_20e50d1e8aca`) reports branch `master`, four modified paths, zero staged paths and zero untracked paths: `docs/agent-evaluation/results.md`, `docs/superpowers/plans/2026-11-03-gpu-capability-tiers-and-local-ai.md`, `src/local_ai_hub/mcp_server.py`, and `tests/test_mcp_agent_routing.py`. This is a point-in-time dirty-path snapshot, not ownership attribution. Those paths remain untouched here.

A later `git_status` (`req_c63f0dae1f61`) reports seven modified paths: this audit, `docs/agent-evaluation/results.md`, the GPU plan, `src/local_ai_hub/external_gpu_reservation.py`, `src/local_ai_hub/mcp_server.py`, `tests/test_external_gpu_reservation_lifecycle.py`, and `tests/test_mcp_agent_routing.py`. This newer snapshot supersedes the four-path list above. It still does not identify owners; those source/test paths remain untouched here.

The Hub readiness sample (`req_bf5b801e0df4`) reports version 5.1.3, Hub/Ollama online, `active_model=qwen3.5:9b-nvfp4`, `vram_pressure=unknown`, and `context_budget_factor=0.25`. It does not report installed tags, GPU residency, free VRAM, or reservation owner. No additional GPU workload was started from this status.

Focused current-source validation ran `python -m pytest -q tests/test_prompt_contracts.py tests/test_opencode_hardware.py --tb=short`: **16 passed in 0.60 seconds**. The model capability registry contains the `qwen3.5:4b-nvfp4` advisory entry and no Q4/Gemma registry entry; the OpenCode 16 GB staging candidates are `qwen3.5:9b-nvfp4`, `qwen2.5-coder:7b`, and `qwen3.5:4b-nvfp4`. This does not establish a complete repository-wide stale-reference scan or current installed-model inventory.

### Remaining work and gates

- A1 source fix and focused failure tests are already recorded above; live GPU acceptance remains open.
- A2 prompt/catalog source checks pass, but full active-reference coverage and a current installed-tag snapshot remain open.
- A3–A5 require coordinated target-device evidence for context/concurrency, GPU embeddings/reranking, and live llama.cpp switching. Current VRAM pressure is unknown and the running model is 9B NVFP4; do not infer admission, residency, or a free device from Hub online status.
- A6 demand-priority measurements and A7 labeled tool-calling evaluation remain open. Preserve their baseline/fixture and scoring protocols from the GPU plan.
- The release/full-suite gate still needs one stable, integrated candidate after all working changes are reconciled.

No source edits, model pulls, service restarts, or GPU benchmarks were performed in this continuation. These observations update the audit only; GPU/runtime acceptance remains **NOT VERIFIED**.

### Follow-up while checkout changes continue

The latest Hub `git_status` (`req_19db4f0a564c`) now reports ten modified paths: this audit, `docs/agent-evaluation/results.md`, the GPU plan, `src/local_ai_hub/external_gpu_reservation.py`, `src/local_ai_hub/mcp_server.py`, `src/local_ai_hub/process_utils.py`, `src/local_ai_hub/services.py`, `tests/test_external_gpu_reservation_lifecycle.py`, `tests/test_mcp_agent_routing.py`, and `tests/test_new_capabilities_and_hardening.py`. This supersedes earlier dirty-path snapshots. The A1 source and lifecycle-test paths are now dirty, so the previously recorded 87-test run is historical until those changes stabilize and the cohort reruns. No ownership is inferred from status alone.

The semantic compression request (`req_bb2e78a881de`) was rejected before inference with `target_vram_estimate_unavailable`. It produced no review output and is not a benchmark or model-quality result.

## Chat continuation evidence — 2026-11-05, A2 active guidance

The live `AGENTS.md` instruction that named `qwen3.5:4b-q4_K_M` and `gemma4:12b` as advisory prompt candidates was stale. It now names the current `qwen3.5:4b-nvfp4` and `qwen3-vl:4b` prompt scopes and retains the advisory-only warning. Exact source slice SHA-256 after the edit: `6fb6b772ec6ce7a607099cc5e95cf16ac7e12b90dc9ca11fb0ad63c968461cfc`. `git diff --check -- AGENTS.md` exited 0 with only the working-copy LF-to-CRLF warning.

The paginated model-name search located remaining Q4/Gemma references in the dated 2026-11-01 adoption evaluation spec and plan, the 2026-11-02 Blackwell comparison plan, this audit, `AGENTS.md` before the correction, and tests that assert retired tags are absent or constrain candidate authority. The adoption spec calls the candidate config inactive; the plans keep measurements and promotion pending. Preserve these evaluation history and test fixtures. The Q4 search still has noisy lexical matches, so repository-wide absence is not claimed. Current installed-tag inventory is still missing.

The latest Hub `git_status` (`req_2cdaeaf0adc3`) now reports 17 modified paths and two untracked tests. It includes this audit, `AGENTS.md`, both canonical prompts, the GPU plan, evaluation results, A1 reservation files, MCP/runtime files and related tests. This supersedes earlier snapshots; status does not attribute owners. No path outside this audit and the one AGENTS line was edited here.

The fresh readiness request (`req_81b8c945cbaf`) still reports Hub/Ollama online, active `qwen3.5:9b-nvfp4`, `vram_pressure=unknown`, and context factor 0.25; optional debug-trace probe is degraded by `probe_timeout`. A3–A7 runtime and quality gates remain open. GPU/runtime acceptance remains **NOT VERIFIED**.

## Chat continuation evidence — 2026-11-05, A4 deterministic CPU fallback

The current checkout status (`req_39aa6bcb998d`) reports six modified paths: this progress log, `docs/agent-evaluation/results.md`, the GPU plan, `src/local_ai_hub/tiered_ollama.py`, `tests/test_benchmark_suite.py`, and `tests/test_tiered_ollama_runtime.py`. Those runtime/benchmark paths remain untouched here. The audit itself was clean in that snapshot.

Fresh `python -m pytest -q tests/unit/test_rag_direct_cpu_bypass.py --tb=short` passed **10 tests in 4.27 seconds** (test-file SHA-256 `56115841ade1531c5746cfa70501e99ed047188d048346695a1c859409b1f309`). This verifies the bounded deterministic CPU bypass regression cohort only; it does not measure CUDA execution, embedding/reranker throughput, relevance, or GPU/CPU parity. Current Hub status (`req_2519e32342bb`) reports Ollama online, active model `qwen3.5:4b-nvfp4`, and `vram_pressure=unknown`; no GPU workload was started. A4 GPU performance/readiness remains **NOT VERIFIED**.

## Chat continuation evidence — 2026-11-05, A6 synthetic demand-priority measurement

Current `git_status` (`req_d988d96ae6b0`) lists nine modified paths: this audit and progress log, `docs/agent-evaluation/results.md`, `docs/superpowers/plans/2026-11-03-gpu-capability-tiers-and-local-ai.md`, `src/local_ai_hub/benchmark.py`, `src/local_ai_hub/tiered_ollama.py`, `tests/test_benchmark_suite.py`, `tests/test_tiered_ollama_runtime.py`, and `tests/unit/test_code_index_size_budget.py`. The benchmark/runtime and index-size paths were left untouched.

`python tools/benchmark_preprocess_demand.py --files 4096 --batch-size 64` ran one synthetic, temporary-SQLite queue-selection series, with no model inference and no fixture in the checkout. Demand priority put the hot file in batch 1 versus baseline batch 64; both drained all 4,096 files in 64 simulated batches, with 0 unprocessed. First demand batch contained 63 regular files, showing the hot item did not replace the whole batch. Median selection time was 2.33 ms with demand priority versus 2.13 ms baseline (about 9.3% overhead in this single run). Existing `tests/unit/test_preprocess_demand_priority.py` passed **4 tests in 1.12 seconds** (source SHA-256 `773b53417b8b3b513e1049c2785a994ee48a8ce303cb826492199959926163fd`; benchmark tool SHA-256 `ea475e5f54714a0b043348920395510d86e975d3455bbc735ee675819099e42b`). This does not measure useful-context latency, work saved, freshness/invalidation, or representative-repository behavior. A6 remains **NOT VERIFIED** pending those measurements and the plan's starvation/invalidation protocol.

## Chat continuation evidence — 2026-11-05, A6 status refresh

A fresh `git_status` request (`req_b2737283243b`) now reports 11 modified paths, including this audit and progress note plus nine paths being edited elsewhere: `docs/agent-evaluation/results.md`, `docs/superpowers/plans/2026-11-03-gpu-capability-tiers-and-local-ai.md`, `src/local_ai_hub/benchmark.py`, `src/local_ai_hub/code_index.py`, `src/local_ai_hub/preprocess.py`, `src/local_ai_hub/tiered_ollama.py`, `tests/test_benchmark_suite.py`, `tests/test_tiered_ollama_runtime.py`, and `tests/unit/test_code_index_size_budget.py`. This supersedes the earlier nine-path snapshot; it does not attribute ownership. No shared implementation paths were edited for A6.

## Chat continuation evidence — 2026-11-05, A5 current-source lifecycle review

Fresh exact source slices from `src/local_ai_hub/llama_cpp.py` (SHA-256 `b9b68aa4773a411fa22ed0180906412835abd5c7320b369d17397ba70aa92e51`) show `LlamaCppRouter.ensure_model()` and `unload_model()` both acquire `_managed_slot`; ensure forwards stop/deadline controls, and unload bounds its slot window and clears recovery/detail state only after a successful unload. This confirms current source-level lifecycle controls, not actual process switching, inference, cancellation, GPU residency or reservation release. The indexed symbol candidate was marked stale/unknown for this path, so the exact source slices, not the index, are the evidence. No live model operation was started. A5 runtime acceptance remains **NOT VERIFIED**.

## Chat continuation evidence — 2026-11-05, A6 repository-sampled queue measurement

Added an opt-in `--root`/`--query` mode to `tools/benchmark_preprocess_demand.py`; the synthetic mode remains unchanged. Repository mode reads only bounded text files (per-file 180 KB, aggregate 64 MiB, up to 50,000 filesystem entries), skips symlinks/junctions and common generated/vendor directories, and builds its temporary SQLite fixture outside the checkout. It measures file-card queue selection and simulated completion only; it does not generate or assess useful context. Tool SHA-256: `0956DEB24207B0D47BC9E4DBFDA7416C3779E2B910012A9E19AA66C10D1566C5`; test SHA-256: `1CB119A97B18C1A34788EB8F382B985580E261EF9CE39107D90809A4288B36AC`.

The new regression first failed as expected because `run()` lacked repository mode, then passed. The full focused module passed **5 tests in 1.13 seconds**. A bounded run on the current repository used query `ProjectPreprocessor`, a 4,096-file sample of 40,787,219 bytes, and 5,867 examined filesystem entries; the file cap was reached. Of 712 matching files, the first query match appeared in batch 1 with both baseline and demand priority. Query matches in batch 1 rose from 9 to 24. Both modes completed all 4,096 sampled files in 64 batches with 0 unprocessed. Per-batch selection median/p95 were 2.78/4.70 ms baseline and 3.52/5.09 ms demand in this run. Several one-shot runs showed timing variation while the shared checkout changed, so these timings do not establish a performance regression or gain. The query is broad and is not verified as a learned user query. `useful_context_verified=false`; A6 remains **NOT VERIFIED** pending task-grounded hot/cold context quality and latency, work saved, freshness/invalidation, and starvation evidence.

The latest Hub `git_status` (`req_ca72349b3b0c`) reports 19 modified paths. Four are this audit, this progress note, the bounded benchmark tool, and its focused test; 15 other modified paths remain outside this work scope, and status does not attribute their owners. No shared implementation path was changed. Hub status (`req_26584f481876`) had active `qwen3.5:4b-nvfp4` and `vram_pressure=unknown`; this benchmark ran no inference or GPU workload.

The asynchronous semantic `review_diff` job (`173a825697114756932f14196b5c7ded`) ended `outcome_unknown` after its sole wait; no review text was accepted. The indexed `impact` response (`req_ca31ac26c5f4`) summarized the broader 19-path checkout and omitted the benchmark tool/test from its changed-file list, so it is not accepted as exact impact evidence. Primary review used the exact two-file Git diff; focused tests and scoped `git diff --check` passed.

## Chat continuation evidence — 2026-11-05, A6 narrow-query and cache-age checks

Four audit-derived narrow queries were run against separate bounded 4,096-file repository samples (file cap reached in each; no inference). Queue-level batches to first matching file were: `ensure_model` 25 baseline → 1 demand (26 matching files); `external_gpu_reservation` 14 → 1 (33); `vram_free_mb` 36 → 1 (11); `hot_queries` 31 → 1 (9). Demand selected 16, 16, 11, and 9 matching files in batch 1 respectively. Each baseline and demand drain processed 4,096 sampled files in 64 batches with 0 remaining. These are audit-derived lexical queries, not observed user-learned queries, and they measure first matching file selection rather than generated/useful context.

A new characterization test confirms `_learned_priority_paths` caches the mapping for 15 seconds: after changing the FTS fixture/query, the old path remains at 14.999 seconds and the new path is selected at expiry. Current `preprocess.py` slice SHA-256: `ccc3134ec5fa567ce418d5e7dc93809662cbb25c620ce21355beebb1b19887a5`. Focused `tests/unit/test_preprocess_demand_priority.py`: **6 passed in 1.17 seconds**; scoped `git diff --check`: exit 0. Test SHA-256: `DE70C068D303E9FAB6A8C8E314B3308E7B78BA61630739D10F0970D51F2B62F4`.

This confirms bounded cache age, not immediate invalidation or file-card freshness across content generations. No work is skipped in either queue run; no work-saved result exists. A6 remains **NOT VERIFIED** pending observed learned-query provenance, useful-context generation/quality and latency, actual work saved, cross-generation invalidation, and sustained fairness.

Latest Hub `git_status` (`req_1ba4198177bf`) lists 23 modified paths, including these audit documents, benchmark tool and test; the other 19 paths remain outside this scope. The status does not establish ownership. No shared runtime/preprocessing implementation path was changed.

## Chat continuation evidence — 2026-11-06, current commit whitespace check

The current checkout advanced to `HEAD=616e84095b8b51ef503fc5e8144f59f4d217980f` on `master`. Fresh `git diff --check HEAD^ HEAD` now exits 0, including for `tests/test_external_gpu_reservation_lifecycle.py`. The earlier line-168 EOF warning describes the audited `f08d7c9c919962216c719f8fb37c9d962aee9d61` revision and is historical; it does not describe this commit. This commit-level check does not cover the dirty working tree, which the latest Hub `git_status` (`req_d7f011938b10`) reports as 19 modified paths. No shared paths were changed for this correction.

## Chat continuation evidence — 2026-11-06, A1 current-source regression cohort

Fresh `python -m pytest -q tests/test_external_gpu_reservation_lifecycle.py tests/test_opencode_gpu_reservation.py tests/unit/test_reranker_gpu_reservation.py tests/test_preprocess_status_scaling.py --tb=short` passed **93 tests in 4.93 seconds**. Current `HEAD` is `e1c02efbd3660a8c66c491f0ac1f2cf94ebc6c92`; its parent-to-commit diff contains none of these five A1 source/test paths. Current SHA-256: reservation source `d096dd2cbdfee3e43dc7ef9fa28ad4cc61753d9187bb70fe4480767cf1d6b64e`, lifecycle test `8e647af03a8f7a46c7174bfc0ca17adab31877c7e5832d7814223901a44fa59b`, OpenCode reservation test `a371fc3b078827aba5d99b111494949a6124655611de361fa06a60dac2a3498a`, reranker reservation test `c2ce12a099a55d92619dded422a806ab07d57ab2ea8608706fd540caa1b906ef`, and preprocessing status test `a8d054556a483866377417d65edc9e496a13193062fda02ba7ba252ba850d264`. `git diff --check HEAD^ HEAD` also passes. This revalidates mocked reservation cleanup, MCP consent contract, reranker admission, and preprocessing status on current unchanged A1 paths; it does not prove live cross-process/GPU behavior. Latest Hub status `req_1ab361702e9a` reports 19 modified paths; none of these A1 paths is dirty.

## Chat continuation evidence — 2026-11-05, A2 inventory and A6 freshness/fairness

Read-only `ollama list` reports seven installed tags: `qwen3.5:9b-nvfp4`, `qwen3.5:4b-nvfp4`, `qwen3.5:9b`, `qwen2.5-coder:7b`, `qwen2.5-coder:3b`, `qwen2.5-coder:1.5b`, and `qwen3-embedding:0.6b`. The removed `qwen3.5:4b-q4_K_M`, `gemma4:12b`, and `qwen2.5-coder:14b` are absent. A bounded exact scan of the six active surfaces named by A2 (`INSTALL_PROMPT.md`, `UPDATE_PROMPT.md`, `MODEL_CAPABILITIES.md`, `prompt_contracts.py`, `generator.py`, `opencode_hardware.py`) found no references to those three tags. The canonical install/update prompts retain identical model-routing paragraphs. This closes the specified active-surface, installed-inventory and prompt-parity checks; it does not claim repository-wide absence of historical/test references.

Updated `_learned_priority_paths()` to reuse cached priorities only while the learned-query set, file-card index signature and 15-second TTL match. A regression changes both learned queries and indexed generation before TTL expiry. A second regression runs four consecutive 4-file batches with 8 priority matches and 12 ordinary files; each batch selects one priority and three ordinary files, advancing all ordinary files. Focused `tests/unit/test_preprocess_demand_priority.py`: **7 passed in 1.22 seconds**; scoped `git diff --check`: exit 0. Source SHA-256 `49D956F15BB7D16FA768F6B94F1C3157DD5395CC9A0C179126DABD6B63C643E9`; test SHA-256 `B78332D88468C10B46EA3C6CDBCA70918E6BC4F3869928821C6F254E40D531B9`.

These are source-level inventory and queue-selection results. A6 remains **NOT VERIFIED** for actual work saved, real learned-query provenance, generated-context quality/latency and sustained repository-load fairness. Current live `local_ai_status` (`req_e080c405c638`) reports active model `qwen3.5:4b-nvfp4`, but VRAM telemetry is unavailable (`sample_pending`, stale) and pressure is `unknown`; no inference or GPU benchmark was started. A3–A5 and A7 physical/runtime/quality gates remain open.

## Chat continuation evidence — 2026-11-05, short 4B hardware smoke and uncertainty fence

One `local_ai_task(action="hardware_benchmark")` smoke on installed `qwen3.5:4b-nvfp4` (`model_digest_status=verified_installed`, digest `56d8c805bbeb679be81d064cbda81aa3f91eb32492a4547c0ebaa50690980506`, request `req_733fab95b850`) succeeded on NVIDIA GeForce RTX 5070 Ti. Prompt requested `ready`, maximum 4 tokens; backend generated 2. TTFT 110.71 ms, generation 49.17 ms, 40.68 tokens/s, queue wait 39.86 ms, call latency 159.88 ms. Sampled device VRAM: 16,303 MB total, 8,731 MB used, 7,265 MB available; device-wide sampled peak `9,155,117,056` bytes. `loaded_model_vram_status=unavailable`; peak scope is device-wide. `ollama ps` was empty immediately before and after. This is one very short smoke, not warm/cold performance, residency or capacity qualification.

A separate 128-token attempt was admitted but ended with `model output repetition loop detected` (`req_8cd44dec35f8`); it produced no performance result. The following distinct request was refused with `gpu_outcome_unknown`, `outcome_unknown=true`, and “reservation retained” (`req_ec451fd7b5f2`). Fresh `local_ai_status` (`req_56a8fddc3b78`) now reports `gpu_admission_state=outcome_unknown`, VRAM telemetry `sample_pending`/stale, and pressure `unknown`. No further inference or restart was attempted. Treat the retained fence as authoritative; do not clear or bypass it without explicit scheduler/operator reconciliation. A3–A5 and A7 remain open; the smoke does not qualify model quality, concurrency, long context, embedding/reranking, or managed llama.cpp switching.

## A1 — Current-source regression closure

After initializing each mocked `EmbeddingModel` fixture with its own `ExternalGpuReservationStore` over the scheduler's shared temporary reservation path, the full focused cohort passed against the current source tree: `python -m pytest -q tests/test_external_gpu_reservation_lifecycle.py tests/test_opencode_gpu_reservation.py tests/unit/test_reranker_gpu_reservation.py tests/test_preprocess_status_scaling.py --tb=short` — **98 passed in 5.82 s**. The prior five failures were test-fixture setup errors; production reservation behavior was unchanged. This closes the bounded source regression cohort for A1. It does not establish live cross-process atomic admission, target-GPU exclusion, or installed-runtime behavior. The audit progress log records the exact fixture repair and the unusable semantic review response (`invalid_citation`); no model-review approval is claimed.

## A6 — Current-source focused regression

Fresh `python -m pytest -q tests/unit/test_preprocess_demand_priority.py --tb=short`: **7 passed in 1.99 s**. Current `_learned_priority_paths()` source (`preprocess.py`, SHA-256 `6ebc2a10495b027b179d94f5359b9984272f66846c2f8627c3ba87c41961e0b3`) keys the 15-second cache on the current hot-query tuple and aggregate `file_refs` signature; the tests cover query and index-generation invalidation plus repeated-batch fairness. This remains bounded SQLite/source-test evidence. It does not establish real user-query provenance, generated-context quality or latency, work saved, or sustained fairness under repository preprocessing load. A6 remains **NOT VERIFIED** for those acceptance gates.

## Chat continuation evidence — 2026-11-06, A4 CPU bypass and readiness discrepancy

Current `python -m pytest -q tests/unit/test_rag_direct_cpu_bypass.py --tb=short`: **10 passed in 2.98 s**. This confirms only deterministic direct CPU bypass behavior; GPU execution, retrieval quality, and CPU/GPU parity remain unverified.

Readiness APIs disagreed in the same check set: `local_ai_coord(action="gpu_reservation_status")` returned `reservation_present=false`, `state=free`, while `local_ai_status` (`req_dbf28b27de28`) returned `gpu_admission_state=external_reservation`, `ollama_online=null`, dependency probe timeouts, and stale/unknown VRAM telemetry. No inference or model-backed review was started. Preserve fail-closed runtime status pending reconciliation.

## A5 — Mocked managed-lifecycle regressions revalidated

Fresh focused cohort against the current checkout: `python -m pytest -q tests/test_llama_cpp_routing.py::LlamaCppRoutingTests::test_managed_model_load_and_unload_are_serialized tests/test_llama_cpp_routing.py::LlamaCppRoutingTests::test_managed_inference_blocks_concurrent_model_unload tests/test_llama_cpp_routing.py::LlamaCppRoutingTests::test_managed_inference_cancellation_releases_slot_for_unload tests/test_llama_cpp_runtime.py::LlamaCppRuntimeTests::test_mixed_fallback_never_replays_partial_cuda_output --tb=short` — **4 passed in 0.82 s**. These tests exercise mocked source-level serialization, cancellation, and partial-output fallback. They do not exercise a live llama.cpp server, physical model load/unload, cancellation under real inference, measured VRAM release, or GPU reservation reconciliation. A5 remains **NOT VERIFIED** for its runtime acceptance gate.

## Chat continuation evidence — 2026-11-06, GPU reservation readiness reconciliation

Fresh `local_ai_status` (`req_7fee0e117b1a`) reported `gpu_admission_state=external_reservation`, `hub_online=true`, `ollama_online=true`, `active_model=null`, and VRAM telemetry pending/stale. The immediately following `local_ai_coord(action="gpu_reservation_status")` returned `reservation_present=true`, `state="unknown"`, and `manual_intervention_required=true`. These current observations are consistent with fail-closed external-reservation admission; the earlier same-check-set `state="free"` observation is stale and is not evidence that admission is clear. The status response did not provide verified owner liveness/generation/expiry, so no release or GPU inference was attempted. Resolve only through the authorized owner/liveness reconciliation path; physical residency and safe reservation release remain **NOT VERIFIED**.
