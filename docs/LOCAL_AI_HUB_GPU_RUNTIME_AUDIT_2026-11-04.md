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

**Required closure:** define recoverable, generation-safe cleanup for partial deletion; test interruption/failure at each deletion boundary, subsequent status, claim, and consented recovery. Preserve fail-closed behavior for foreign or malformed records.

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

### A1 — partial cleanup recovery

**Status:** implemented in the current uncommitted worktree; source/release acceptance remains open.  
The recovery path now accepts only a metadata-only orphan with valid bounded metadata, matching generation, expired reservation, no digest path/symlink, and explicit operator consent. It appends a distinct `consented_release_recovery` audit event before deleting metadata. Corrupt metadata, a present or symlinked digest, a nonmatching generation, and an unexpired reservation remain fail-closed.

**Failure-first evidence:** the new recovery test failed before the fix at the second consented release. After the fix, `python -m pytest -q tests/test_external_gpu_reservation_lifecycle.py tests/test_opencode_gpu_reservation.py tests/unit/test_reranker_gpu_reservation.py tests/test_preprocess_status_scaling.py --tb=short` passed **85 tests** in 8.12 seconds. `git diff --check HEAD^ --` passed on the current candidate. No GPU runtime test ran; A1 is not a runtime acceptance receipt.

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
