# Local AI Hub GPU/runtime audit progress — 2026-11-05

Continuation of [the main audit](LOCAL_AI_HUB_GPU_RUNTIME_AUDIT_2026-11-04.md). This note records A6 work completed after that report's current snapshot.

## A6 — Demand-priority starvation measurement

Updated `tools/benchmark_preprocess_demand.py` to drain the full synthetic file-card queue after selecting the hot file. It now reports batches to hot-file selection, batches to queue completion, unique completed files, and unprocessed files. The test asserts both baseline and demand-priority runs finish all work.

Command: `python -c 'import json; from tools.benchmark_preprocess_demand import run; r=run(4096,64); keys=("batches_to_hot","batches_to_complete","completed_files","unprocessed_files","selection_median_ms"); print(json.dumps({k:{x:r[k][x] for x in keys} for k in ("baseline","demand")}, indent=2))'`

| Mode | Batches to hot file | Batches to completion | Completed | Unprocessed | Median selection |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 64 | 64 | 4096 | 0 | 2.216 ms |
| Demand priority | 1 | 64 | 4096 | 0 | 2.271 ms |

This synthetic queue-selection result shows earlier hot-file selection with no starvation in this fixture. It does not measure model inference, useful-context latency, work saved, or representative-repository behavior; A6 remains open for those measurements and an explicit decision about deeper analysis.

Validation: `python -m pytest -q tests/unit/test_preprocess_demand_priority.py --tb=short` — 4 passed. `git diff --check` — no whitespace errors; Git reported LF-to-CRLF conversion warnings for the two changed Python files.

Review status: `local_ai_repo:review_diff` request `req_19d7bfbc287f` queued under degraded resource admission. One `local_ai_work:wait` for returned job ID `4f1bab39f18047379072f0eee3d55478` returned `work order not found` (`req_053bae358484`). No semantic diff review result was obtained.

The main audit file was already modified by another editor. A lease claim for that path returned truncated output, so ownership could not be confirmed. This continuation stays separate until that lease is reconciled.

## A3/A4 — Current runtime readiness snapshot

`local_ai_status` request `req_c5cd98197882` returned Hub 5.1.3 online, hardware profile `high`, `active_model=null`, `vram_pressure=unknown`, and `context_budget_factor=0.25`. Provider readiness for semantic review was not checked. This is insufficient to start the GPU qualification runs safely or claim active CUDA embeddings/reranking. Recheck only after the runtime owner provides a measurable ready state.

Fresh status request `req_8e45d4736db3` now reports `active_model="qwen3.5:9b-nvfp4"` on the same high profile, while `vram_pressure` remains `unknown` and provider readiness is still `not_checked`. The active-model value changed from the preceding null observation; neither response reports reservation ownership or proves spare GPU capacity. Keep runtime qualification open.

Latest status request `req_e5736932db6c` has returned `active_model=null` again on profile `high`; `vram_pressure` remains `unknown` and provider readiness remains `not_checked`. Active-model identity is therefore inconsistent across nearby status samples. A bounded `local_ai_repo:code_index` query for `hardware profile VRAM detection 15 GiB CUDA selection low memory fallback` failed with an MCP transport send error to `127.0.0.1:11436/mcp`; the status health call succeeded, but supplied no repository fallback authorization. No native search or GPU work followed.

Source review of `src/local_ai_hub/hardware.py` (SHA-256 `e0d6c1a26fb8a4a724c63b8407c118b4e6a27db9bd0149d84d450a569066871a`, lines 89–130 and 267–319) confirms that `nvidia-smi` collects total VRAM only. Automatic profile selection uses total dedicated VRAM thresholds (6/12/20 GiB); an explicit requested profile is returned directly. Thus `hardware_profile=high` is a static route classification, not evidence of free VRAM or workload admission. A3 still needs live available/peak memory and concurrency evidence.

Source review of `src/local_ai_hub/embeddings.py` (SHA-256 `196b4f661fa5576ee46087e8e32dcd86660c66ffe77adc710830813dc8ce41d4`) and `src/local_ai_hub/reranker.py` (SHA-256 `76e09fd7ae1536d2465f8c62fb6432d17b40347cab0e747002bdfedbe54c47e`) shows configured backend/device state and fallback candidate handling. Source is not live-device evidence; A4 remains open for GPU/CPU batch latency, throughput, VRAM, quality, and fallback execution measurements.

The current plan records the latest bounded 4B attempt as `scheduler_state="pending"`, `wait_reason="gpu-reservation"`, `request_not_sent=true`, `operation_not_started=true`; inference did not start. Current status request `req_cd810a905f35` explicitly asked for `gpu_admission_state` and `wait_reason`, but returned neither. No current signal confirms that the reservation cleared. Do not retry the benchmark until an authoritative admission status or owner release appears.

## A4 — GPU reservation denial regression

Added `test_direct_rag_route_preserves_candidates_when_gpu_reservation_is_denied` in `tests/unit/test_rag_direct_cpu_bypass.py`. The test forces admission denial and verifies RAG still returns the baseline candidate paths without loading or predicting on a CPU reranker. It passed alone: `python -m pytest -q tests/unit/test_rag_direct_cpu_bypass.py::test_direct_rag_route_preserves_candidates_when_gpu_reservation_is_denied --tb=short` (`1 passed in 0.65s`).

This is mocked failure-path coverage only; it does not prove live CUDA/OpenVINO availability, GPU execution, latency, VRAM use, or quality. `local_ai_repo:review_diff` request `req_696063478c96` queued under degraded resource admission; the single `local_ai_work:wait` returned `work order not found` (`req_69664a7e476d`), so no independent semantic review result exists. The primary review checked the exact test and RAG/reranker source slices. Main audit ownership remains unresolved; this progress note stays separate.

Added `test_rag_embedding_gpu_reservation_denial_uses_lexical_candidates` to cover the other A4 denial path. It simulates `error_code="gpu_reserved"` from embeddings and verifies RAG uses BM25/FTS lexical fallback with the same candidate paths as the direct lexical baseline. Focused run `python -m pytest -q tests/unit/test_rag_direct_cpu_bypass.py::test_rag_embedding_gpu_reservation_denial_uses_lexical_candidates --tb=short` passed (`1 passed in 0.74s`). This remains mocked fallback coverage, not device or performance evidence.

After both regressions were added, the complete focused file `python -m pytest -q tests/unit/test_rag_direct_cpu_bypass.py --tb=short` passed (`10 passed in 7.89s`). Hub `local_ai_repo:diff` reports 46 additions and no removals in that file but returns hunk metadata only; source-slice review remains the primary review evidence.

## A2 — Selected active-guidance reference scan

After Hub search returned a terminal 413 despite reducing the page limit, one bounded native fallback searched the six active guidance surfaces named by A2: `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`, `docs/MODEL_CAPABILITIES.md`, `src/local_ai_hub/prompt_contracts.py`, `src/local_ai_hub/generator.py`, and `src/local_ai_hub/opencode_hardware.py`. The exact command was `rg -n -m 5 "qwen3\.5:4b-q4_K_M|gemma4:12b"` followed by those file paths; it found no matches. This supports removal from those selected active surfaces only; it is not a repository-wide absence claim, and current installed-tag inventory remains open.

## A7 — Capability readiness snapshot

Fresh `local_ai_status` request `req_f501a9337e06` reports profile `high`, active model `qwen3.5:9b-nvfp4`, and operator-enabled `code_generation`, `automation`, `vision`, and `search_summaries` capabilities. Their `provider_readiness` remains `not_checked`; `vram_pressure` is `unknown`. This is configuration/readiness state only, not tool-call quality, grounded task success, device performance, or promotion evidence. A7 remains open.

## A3 — Reconfirmed status and implementation gate

Current `local_ai_status` request `req_36ad67b56d98` again reports Hub/Ollama online, profile `high`, active model `qwen3.5:9b-nvfp4`, `vram_pressure=unknown`, and context factor `0.25`. The model identity differs from nearby `null` samples; no status response identifies a GPU reservation owner or available VRAM. Keep device qualification and any admission/profile-threshold change open.

Fresh source slices of `src/local_ai_hub/hardware.py` (SHA-256 `e0d6c1a26fb8a4a724c63b8407c118b4e6a27db9bd0149d84d450a569066871a`) reconfirm `_nvidia()` queries `memory.total` only and the hardware response reports those GPU objects. I made no hardware policy/source change in this step: the dynamic pressure/reservation evidence is absent, and the repository search endpoint currently returns `enriched_search` disabled. The symbol index returned stale, low-confidence candidates, so they are not sufficient test/source coverage evidence.

## A3 — Additive free-VRAM metric implemented

This follow-up supersedes the preceding “no hardware source change” note. `src/local_ai_hub/hardware.py` now queries `memory.free` and adds `vram_free_mb` while preserving `vram_mb` total and all profile thresholds. If the extended NVIDIA query fails, it retries the prior total/driver query and records free VRAM as `null`, so unsupported free-memory reporting does not hide a detected GPU. Current source SHA-256: `f0ec55b3d5004bc6f01afc5e564eb2d4a3ca272a1a8521b7af5d282cfa5212c0`.

Added two regression cases in `tests/test_features.py` for the normal total/free/driver column order and fallback when the free-memory query fails. The full module passed: `57 passed in 2.73s` (source SHA-256 `022360b1a89109772af677ad14fd3dcd1be58f8f76947c4725d21978a501007a`). The OpenCode hardware integration module passed: `8 passed in 0.35s` (source SHA-256 `417b6b2005dc2169ed3ed2afcc526688923dd76d9dd44ec5c2847168882cd7e7`). Scoped `git diff --check` exited 0 for both changed source/test pairs. No live hardware benchmark was run.

Current `local_ai_status` request `req_baefa6886686` now reports active model `qwen3.5:4b-nvfp4`, while `vram_pressure` remains unknown. Separately, the async `review_diff` admission sample (`req_9b14ced876e4`) reported `measurement_basis=dedicated_observed`, total 16,303 MB, available 7,471 MB, used 8,525 MB, pressure nominal. This is a scheduler resource snapshot, not an inference benchmark or proof of per-process residency. Its returned work ID was not found by the one allowed wait (`req_a8a44c69da8f`), so semantic review remains unavailable. The indexed hardware diff request returned retryable 503 (`req_d3d7249989d7`); source-slice review and focused tests remain available evidence.

## A2 — Future profile candidate source check

Current `src/local_ai_hub/opencode_hardware.py` (SHA-256 `42b5faf2dc3f9c8e33e803c153f89b96e513a7c32cce2d662929c0f2800761ef`) sets the 16 GB candidates to `qwen3.5:9b-nvfp4`, `qwen2.5-coder:7b`, and `qwen3.5:4b-nvfp4`; it has no retired Q4 Qwen, Gemma 12B, or Coder 14B entry. This file is clean in the current Git status. A2 remains open because canonical prompts and recommendation sources are concurrently edited, and a current installed-model inventory plus bounded active-reference scan is still needed.

Added an integration regression in `tests/test_opencode_hardware.py`: `inspect_opencode_hardware()` preserves `vram_free_mb` in its returned GPU object while keeping `admission="unverified"` and `runtime_verified=false`. The full file passed: `8 passed in 0.35s`; scoped `git diff --check` exited 0. This verifies metric propagation only, not runtime eligibility.

## A2 — Fresh focused contract validation

Current command `python -m pytest -q tests/test_prompt_contracts.py tests/test_opencode_hardware.py --tb=short` passed `17 passed in 0.56s`. This freshly verifies the capability registry and OpenCode candidate rules. It does not scan all active prompt surfaces or prove which model tags are currently installed.

## A3 — Free VRAM survives telemetry fallback

`src/local_ai_hub/gpu_monitor.py` now preserves validated `vram_free_mb` from `detect_hardware()` as `vram_available_mb`. Integrated GPUs or invalid/out-of-range measurements remain `null`. `get_dynamic_token_budget()` prefers an explicit valid available-memory measurement; when absent or invalid, it retains the previous total-minus-used fallback. This avoids treating the whole GPU as available when the live provider fails but the NVIDIA inventory has a free-memory measurement. Profile thresholds remain unchanged. Source SHA-256: `669fe4ca60716687bf3c95cf4f9fd10a3cd01c8752ebd7b731d6ef89106c18b5`.

Added two tests in `tests/test_gpu_monitor.py` for fallback propagation and budget selection. Failure-first run: `2 failed, 5 passed` before the implementation; after implementation, `python -m pytest -q tests/test_gpu_monitor.py --tb=short` passed `7 passed in 0.27s`. Combined `tests/test_gpu_monitor.py tests/test_features.py` passed `64 passed in 5.85s`. Scoped `git diff --check` exited 0. This is source/test evidence; no live GPU benchmark or residency claim.

## A5–A7 — Revalidated open acceptance gates

Current main-audit source (SHA-256 `19535b93477be83bca7cb8020e5691ad567bcc9226139cd483a6e311f4dd33d3`, lines 51–73) keeps A5, A6, and A7 open. A5 requires configured llama.cpp load → inference → unload → different-model load, plus inventory, GPU residency, cancellation, failure fallback, and scheduler reservation-release evidence. A6 requires representative-repository hot/cold time-to-useful-context and work-saved measurements, freshness/invalidation, and starvation coverage before deciding on deeper analysis. A7 requires labeled tool-use cases with measured model/provider identity, valid-call rate, grounded use, recovery, latency, and VRAM.

Fresh `local_ai_status` request `req_4b34eeaf958c` reports Hub/Ollama online, profile `high`, active model `qwen3.5:4b-nvfp4`, but `vram_pressure=unknown`; reservation ownership and provider readiness remain unreported. Therefore no live GPU or model-switching run was started. A bounded indexed search (`req_031748f04d58`) found concurrent service edits reading `vram_balancer.status().vram_available_mb`; result was partially verified and the GPU monitor candidate was stale, so this is only a handoff cue, not source-acceptance evidence. The status inventory shows `services.py`, benchmark/evaluation files, and the main audit are dirty alongside other work. I did not edit those paths. A5–A7 remain open pending owner completion and safe measured validation.

## A3 — Free-memory-only pressure regression

Added `test_free_vram_only_sample_derives_pressure_and_headroom` to `tests/unit/test_vram_balancer_telemetry_validity.py`. It supplies dedicated capacity of 8,192 MB and free memory of 6,144 MB, with used-memory fields absent; checks derived 25% pressure, 6,144 MB headroom, nominal context factor, and preserved raw unknown usage. Production code and thresholds unchanged. Focused file passed: `16 passed in 0.38s`. `git diff --check -- tests/unit/test_vram_balancer_telemetry_validity.py` exited 0. Diff SHA-256 at that checkpoint: `F17F96882343E84902649BA06C64FF1EBC7A91F33D440F22DEB711C56571E994`. Hub semantic review queued as job `24cd8c12baac4e8881e3389b58252d08`; its single wait returned `work order not found` (`req_64741c921ead`). Primary diff review confirmed test scope and expected calculation. This verifies the pressure consumer’s free-memory-only path, not live GPU telemetry or A3 hardware qualification.

Extended the same conservative-invalid telemetry matrix with four `vram_available_mb` cases: NaN, negative, boolean, and greater than `vram_total_mb`. Focused file now passes `20 passed in 0.36s`; `git diff --check` exits 0. Current test-file SHA-256: `8C3A50A3A630FB534A3180C135ABF4496809BAE90A10C7E46C5E055D71154D13`. No production threshold or behavior change. Fresh status `req_123935a2c485` still reports `vram_pressure=unknown`; hardware qualification remains open.

## A2 — Active model-reference scan

After bounded Hub source reads returned terminal 413, one native fallback ran `rg -n -m 5 "qwen3\.5:4b-q4_K_M|gemma4:12b|qwen2\.5-coder:14b"` on exactly six audit-named active surfaces: `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`, `docs/MODEL_CAPABILITIES.md`, `src/local_ai_hub/prompt_contracts.py`, `src/local_ai_hub/generator.py`, and `src/local_ai_hub/opencode_hardware.py`. It returned no matches. Git status shows both canonical prompts and `generator.py` concurrently modified; these files were read only. The other three scanned paths are clean. Hub lexical request `req_6ba330f895c8` also shows `tests/test_prompt_contracts.py` asserting the retired Q4 and Gemma names are absent from supported models. This is bounded evidence for named active surfaces, not a repository-wide absence claim. Current installed-tag inventory is still missing, so A2 remains open.

Fresh validation `python -m pytest -q tests/test_prompt_contracts.py --tb=short` passed: `9 passed in 0.24s`.

Fresh readiness request `req_bc6e85b3d374` returned `active_model=null`, `vram_pressure=unknown`, and context factor `0.25`; requesting `extra_fields=["installed_models"]` did not return an installed-tag inventory. This does not prove that no models are installed. A2's current inventory gate remains open. The same status reports a debug-trace probe timeout, which does not change this model-inventory conclusion.

## A5 — Managed model lifecycle serialization regression

Added `test_managed_model_load_and_unload_are_serialized` to `tests/test_llama_cpp_routing.py`. It blocks a managed `ensure_model` call, observes a concurrent `unload_model` attempting the generation lock, and asserts unload stays outside the critical section until load completes. The observer uses events around the actual lock acquisition; no sleep-based scheduling assumption. Focused test passed (`1 passed in 0.33s`); full routing file then passed (`35 passed, 20 subtests in 3.16s`); scoped `git diff --check` exited 0. Added `test_managed_inference_blocks_concurrent_model_unload` to cover the actual streaming-generation critical section. Its first run exposed an invalid Ollama-style NDJSON fixture; replaced it with the llama.cpp SSE `data:`/`choices[].delta` shape. The corrected focused test passed (`1 passed in 0.31s`), full routing file passed (`36 passed, 20 subtests in 3.12s`), and scoped `git diff --check` exited 0. Current test-file SHA-256: `81096528D15C1E43631518DD91C5FDEA3E048DC2D00CFB2B5EBA28103D77F13E`. Hub semantic review job `80a98807557f4437999c47c6e990d509` returned `work order not found` on its single wait (`req_c7786ef8fae4`); primary diff review verified the lock assertion and SSE fixture. Fresh review admission (`req_482eed81c75e`) observed dedicated VRAM 16,303 MB total / 11,441 MB available and accepted review work; this is scheduler admission telemetry, not a model benchmark or proof of llama.cpp residency. These are mocked source-level serialization tests, not live model switching, GPU residency, or reservation-release evidence. A5 remains open.

Added `test_managed_inference_cancellation_releases_slot_for_unload`; it uses the existing blocked response/socket fixture, confirms unload waits behind managed generation, cancels the stream, and verifies socket closure, `preempted` result, lock release, and successful unload. The first focused run passed (`1 passed in 1.09s`); full routing module passed (`37 passed, 20 subtests in 3.25s`); `git diff --check` exited 0. Current test-file SHA-256: `D0A36BFD5234D82DB9FAB39AAE785A34391CA7540A5A451D05FF7A140D8F31C3`. A direct `local_ai_task(action="review")` attempt was rejected because the response budget was too small (`req_f9f4f1c16f91`); no semantic review claim. Primary review inspected the complete test diff and bounded thread joins. Cancellation/serialization are now source-tested with mocks; live load/inference/unload across two real models and actual GPU reservation release remain open.

## A4 — Release own idle reservation when activation fails

Source inspection found CUDA reranker admission reserves an idle generation and then activates it with `renew(..., state="active")`. If activation fails, the reranker now attempts `release(digest, generation)` before returning the existing retryable `gpu_reserved` response. The store only releases an exact matching idle generation, so this cleans up its own unactivated reservation while failing closed if ownership/state changed.

Added regression `test_cuda_reranker_releases_its_idle_reservation_when_activation_fails`. Its failure-first run confirmed the reservation previously remained in the store. After the fix, `python -m pytest -q tests/unit/test_reranker_gpu_reservation.py --tb=short` passed `7 passed in 0.68s`; `python -m pytest -q tests/test_external_gpu_reservation_lifecycle.py --tb=short` passed `25 passed in 0.65s`; scoped `git diff --check` exited 0. Source SHA-256: `ABC9653511A082BB93A00739E7D1B7B975DE289D6917A988E25B14213D6D3883`; test SHA-256: `C2CE12A099A55D92619DDED422A806AB07D57AB2EA8608706FD540CAA1B906EF`.

The queued semantic `review_diff` job `9ee8ea9243ab4f6cb3bbf8efa8bb60ae` returned `work order not found` on its single wait (`req_1324fc2d2ab5`). Primary review confirmed the production change is limited to exact-generation cleanup and the test covers no inference after activation failure. This is mocked lifecycle coverage; actual cross-process contention and GPU runtime qualification remain open.

## A1 — Revalidated orphan recovery in current source

Fresh exact source slices confirm `release_with_consent` accepts a metadata-only orphan only when the digest fence is absent, metadata is regular/non-symlink, generation matches, and expiry or verified dead-owner conditions authorize release. Lifecycle regression `test_consent_release_recovers_metadata_orphan_after_partial_cleanup` injects the metadata-unlink failure after digest removal and proves consented recovery succeeds. Current source SHA-256: `d096dd2cbdfee3e43dc7ef9fa28ad4cc61753d9187bb70fe4480767cf1d6b64e`; test SHA-256: `8e647af03a8f7a46c7174bfc0ca17adab31877c7e5832d7814223901a44fa59b`; audit SHA-256: `19535b93477be83bca7cb8020e5691ad567bcc9226139cd483a6e311f4dd33d3`. Fresh `python -m pytest -q tests/test_external_gpu_reservation_lifecycle.py --tb=short` passed `25 passed in 0.77s`. The source recovery path is covered; installed MCP parity and live GPU behavior remain unverified.

## A3 — Revalidated free-VRAM telemetry path

Current source has advanced since the earlier telemetry checkpoint: `hardware._nvidia()` queries `memory.total,memory.free` and returns `vram_free_mb`, falling back to a total-only query when free memory is unavailable. Current `hardware.py` SHA-256 is `f0ec55b3d5004bc6f01afc5e564eb2d4a3ca272a1a8521b7af5d282cfa5212c0`; `gpu_monitor.py` remains `669fe4ca60716687bf3c95cf4f9fd10a3cd01c8752ebd7b731d6ef89106c18b5`. Fresh `python -m pytest -q tests/test_gpu_monitor.py tests/unit/test_vram_balancer_telemetry_validity.py --tb=short` passed `27 passed in 0.45s`; test-file SHA-256: `1872d0794cedb5f18f37911d896fd89d80d547b38e9908fd3ef462cfb35fd152`. This confirms mocked telemetry/fail-closed behavior only. Current Hub status `req_69adc83e5cd7` reports `vram_pressure=unknown`; 65k-context and concurrent-request GPU capacity remain unqualified.

## A2 — Current installed-model inventory

Read-only `ollama list` succeeded in the current checkout environment. It reports seven installed tags: `qwen3.5:9b-nvfp4`, `qwen3.5:4b-nvfp4`, `qwen3.5:9b`, `qwen2.5-coder:7b`, `qwen2.5-coder:3b`, `qwen2.5-coder:1.5b`, and `qwen3-embedding:0.6b`. The removed `qwen3.5:4b-q4_K_M`, `gemma4:12b`, and `qwen2.5-coder:14b` are absent from this installed inventory. This closes the current installed-tag snapshot; scoped active-reference coverage is recorded below, while dated evaluation evidence remains historical.

Fresh `python -m pytest -q tests/test_prompt_contracts.py tests/test_opencode_hardware.py --tb=short` passed `17 passed in 0.62s`. Bounded native fallback after exact artifact slices exceeded the Hub response cap found no retired model names in `src/local_ai_hub/generator.py`. These focused tests cover capability/OpenCode behavior; they do not alone establish prompt text coverage.

### A2 scoped active-surface scan complete

Fresh exact-source inspection covered the full `src/local_ai_hub/prompt_contracts.py` capability map (SHA-256 `f56f374fe2a051a0f90da23cb1ee548f478177aad5bd9dd2cf83cc0da407efd4`), all of `docs/MODEL_CAPABILITIES.md` (`a7bafe23423082597e7955a560b21ea251477220f590d09086c364080927142e`), and all of `src/local_ai_hub/opencode_hardware.py` (`42b5faf2dc3f9c8e33e803c153f89b96e513a7c32cce2d662929c0f2800761ef`). The targeted removed tags are absent from those sources. Bounded exact scans found no `qwen3.5:4b-q4_K_M`, `gemma4:12b`, or `qwen2.5-coder:14b` references in `src/local_ai_hub/generator.py`, `docs/INSTALL_PROMPT.md`, or `docs/UPDATE_PROMPT.md`; the latter two prompts have identical model-routing paragraphs at lines 265 and 263 respectively. Historical audit, evaluation and dated comparison records remain preserved. Together with the fresh seven-tag `ollama list` and 17 focused tests above, the specified A2 active-surface removal and prompt-sync check is complete; this is not a claim that every repository text occurrence is absent.
## A4 — Deterministic CPU bypass regression

Current `tests/unit/test_rag_direct_cpu_bypass.py` (SHA-256 `56115841ade1531c5746cfa70501e99ed047188d048346695a1c859409b1f309`) passed `10 passed in 4.27s`. This is CPU bypass/fallback source-test evidence only; no GPU execution, embedding/reranker benchmark, relevance or device parity is proven. Current Hub status `req_2519e32342bb` reports `vram_pressure=unknown`, so GPU performance acceptance remains open. Recorded in the main audit's 2026-11-05 continuation.

## A6 — Synthetic demand-priority measurement

Ran `python tools/benchmark_preprocess_demand.py --files 4096 --batch-size 64`: one synthetic temporary-SQLite queue-selection run, no model inference or checkout fixture. Demand priority put the hot file in batch 1 versus baseline batch 64. Both drained 4,096 files in 64 batches, with 0 unprocessed; the first demand batch retained 63 ordinary files. Median selection was 2.33 ms with demand priority versus 2.13 ms baseline (~9.3% overhead in this single run). `python -m pytest -q tests/unit/test_preprocess_demand_priority.py --tb=short` passed 4 tests in 1.12 s (test SHA-256 `773b53417b8b3b513e1049c2785a994ee48a8ce303cb826492199959926163fd`; benchmark SHA-256 `ea475e5f54714a0b043348920395510d86e975d3455bbc735ee675819099e42b`). This does not measure useful-context latency, work saved, freshness/invalidation or representative-repository behavior. A6 remains NOT VERIFIED pending those measurements and the plan's starvation/invalidation protocol.

Fresh `git_status` (`req_b2737283243b`) reports 11 modified paths: this audit and progress note plus nine shared paths (`docs/agent-evaluation/results.md`, `docs/superpowers/plans/2026-11-03-gpu-capability-tiers-and-local-ai.md`, `src/local_ai_hub/benchmark.py`, `src/local_ai_hub/code_index.py`, `src/local_ai_hub/preprocess.py`, `src/local_ai_hub/tiered_ollama.py`, `tests/test_benchmark_suite.py`, `tests/test_tiered_ollama_runtime.py`, `tests/unit/test_code_index_size_budget.py`). No shared implementation paths were edited for A6.

## A5 — Current-source lifecycle review

Fresh exact source slices of `src/local_ai_hub/llama_cpp.py` (SHA-256 `b9b68aa4773a411fa22ed0180906412835abd5c7320b369d17397ba70aa92e51`) confirm `ensure_model()` and `unload_model()` acquire `_managed_slot`; ensure forwards stop/deadline controls, while unload bounds the slot window and clears recovery/detail state only after successful unload. This is source evidence only. The indexed symbol candidate was stale/unknown for the path, so exact slices were used. No live load, inference, cancellation, model switch or GPU operation was started; those remain required for A5 runtime acceptance, which is NOT VERIFIED.

## A6 — Repository-sampled queue measurement

Added optional `--root`/`--query` support to `tools/benchmark_preprocess_demand.py`; synthetic mode remains intact. Repository sampling is bounded to 180 KB per file, 64 MiB total, and 50,000 filesystem entries, skips symlinks/junctions and common generated/vendor directories, and writes its SQLite fixture under a temporary directory outside the checkout. It measures scheduling and simulated completion, not generated/useful context. Tool SHA-256 `0956DEB24207B0D47BC9E4DBFDA7416C3779E2B910012A9E19AA66C10D1566C5`; test SHA-256 `1CB119A97B18C1A34788EB8F382B985580E261EF9CE39107D90809A4288B36AC`.

Test-first proof: new test failed on the missing `root` argument before implementation; focused module then passed **5 tests in 1.13 s**. Current-repository run (`ProjectPreprocessor`) sampled 4,096 files / 40,787,219 bytes after 5,867 filesystem entries; file cap reached. There were 712 query matches. First match was batch 1 in both baseline and demand modes; batch 1 contained 9 versus 24 query matches. Both drained all 4,096 sampled files in 64 batches, 0 unprocessed. Per-batch selector median/p95: 2.78/4.70 ms baseline, 3.52/5.09 ms demand, one run only. Repeated one-shot runs varied while shared files changed, so no performance claim. Query breadth is high and it is not proven to be a real learned query. `useful_context_verified=false`; A6 remains NOT VERIFIED for useful-context quality/latency, work saved, freshness/invalidation, and starvation.

Fresh Hub status `req_ca72349b3b0c` lists 19 modified paths: the two audit records and these benchmark/test files plus 15 other paths outside this work scope. Status does not identify their owners; no shared implementation path was edited. Hub status `req_26584f481876` showed active `qwen3.5:4b-nvfp4`, VRAM unknown. No GPU or model inference ran.

Review limitation: semantic `review_diff` job `173a825697114756932f14196b5c7ded` ended `outcome_unknown` on its single wait, with no usable review output. Indexed impact request `req_ca31ac26c5f4` reflected the broader 19-path checkout and omitted the benchmark tool/test from its changed-file list; it is not exact impact evidence. Primary agent reviewed the exact two-file Git diff. Focused module: 5 passed in 1.13 s; scoped `git diff --check`: exit 0.

## A6 — Narrow-query and cache-age checks

Four audit-derived queries were tested against separate bounded 4,096-file repository samples: `ensure_model` first-match batch 25→1 (26 matches); `external_gpu_reservation` 14→1 (33); `vram_free_mb` 36→1 (11); `hot_queries` 31→1 (9). Priority selected 16, 16, 11, and 9 matching files in batch 1. Each baseline and demand queue drained 4,096 sampled files in 64 batches, 0 remaining. These are audit-derived lexical queries, not verified user-learned queries; metric is first matching file selected, not useful context generated.

A new characterization test confirms the 15-second `_learned_priority_paths` cache: stale mapping persists at 14.999 seconds, refreshes at expiry. Current source SHA-256 `ccc3134ec5fa567ce418d5e7dc93809662cbb25c620ce21355beebb1b19887a5`. Focused module: **6 passed in 1.17 s**; scoped `git diff --check`: exit 0. Test SHA-256 `DE70C068D303E9FAB6A8C8E314B3308E7B78BA61630739D10F0970D51F2B62F4`.

This proves bounded cache age only; immediate invalidation and generated file-card freshness remain open. Both queue modes process the same work; work saved is unmeasured. A6 stays NOT VERIFIED pending real learned-query provenance, useful-context latency/quality, work saved, generation invalidation, and sustained fairness.

Current Hub `git_status` (`req_1ba4198177bf`) lists 23 modified paths; four are this audit, progress note, benchmark and focused test. Nineteen other changed paths are outside this task scope; the status does not assign owners. No shared runtime or preprocessing implementation was edited.

## Current revision check — 2026-11-06

Current `HEAD` is `616e84095b8b51ef503fc5e8144f59f4d217980f` on `master`. Fresh `git diff --check HEAD^ HEAD` exits 0. This clears the earlier EOF whitespace finding for `tests/test_external_gpu_reservation_lifecycle.py`; that report applied to audited revision `f08d7c9c919962216c719f8fb37c9d962aee9d61` only. Commit check does not validate the dirty worktree: Hub status `req_d7f011938b10` lists 19 modified paths. No shared paths changed here.

## A1 — Current-source focused regression revalidation

Fresh focused cohort `python -m pytest -q tests/test_external_gpu_reservation_lifecycle.py tests/test_opencode_gpu_reservation.py tests/unit/test_reranker_gpu_reservation.py tests/test_preprocess_status_scaling.py --tb=short`: **93 passed in 4.93 s**. Current `HEAD=e1c02efbd3660a8c66c491f0ac1f2cf94ebc6c92`; its commit diff does not change these source/test paths. Current SHA-256: `external_gpu_reservation.py` `d096dd2cbdfee3e43dc7ef9fa28ad4cc61753d9187bb70fe4480767cf1d6b64e`; lifecycle test `8e647af03a8f7a46c7174bfc0ca17adab31877c7e5832d7814223901a44fa59b`; OpenCode test `a371fc3b078827aba5d99b111494949a6124655611de361fa06a60dac2a3498a`; reranker test `c2ce12a099a55d92619dded422a806ab07d57ab2ea8608706fd540caa1b906ef`; status test `a8d054556a483866377417d65edc9e496a13193062fda02ba7ba252ba850d264`. `git diff --check HEAD^ HEAD` passes. Source-test coverage only; live cross-process/GPU behavior remains unverified. Hub status `req_1ab361702e9a` lists 19 modified paths; A1 paths are clean.

## A6 — Demand-priority cache invalidation

Updated `_learned_priority_paths()` so a cached path list is reused only while its 15-second TTL, current learned-query tuple, and file-card index signature still match. Signature uses available `file_refs` generation, update, size/access, and content metadata fields; this supports the repository's full schema and bounded test fixtures. Regression changes the learned query and then the indexed file generation before TTL expiry. `python -m pytest -q tests/unit/test_preprocess_demand_priority.py --tb=short`: **6 passed in 1.19 s**; scoped `git diff --check`: exit 0. SHA-256: `preprocess.py` `49D956F15BB7D16FA768F6B94F1C3157DD5395CC9A0C179126DABD6B63C643E9`; test at that revision `770756B05C6FBECC785191E1B8C8993B8952D258EF31FE19EB9213EE5F08754D`.

This is source-level cache invalidation and queue-selection coverage. It does not prove generated context freshness/usefulness, real user-query provenance, work saved, or sustained fairness. A6 remains **NOT VERIFIED** for those acceptance gates.

## A6 — Repeated-batch fairness regression

Added a sustained selection fixture with 8 persistent hot-query matches and 12 ordinary files. Across four consecutive 4-file batches, each batch selects one hot file and three ordinary files; all 12 ordinary files advance. Full focused module `python -m pytest -q tests/unit/test_preprocess_demand_priority.py --tb=short`: **7 passed in 1.22 s**; scoped `git diff --check`: exit 0. Test SHA-256: `B78332D88468C10B46EA3C6CDBCA70918E6BC4F3869928821C6F254E40D531B9`.

This proves repeated queue-selection fairness in a bounded SQLite fixture. It does not prove sustained fairness under real preprocessing load, time-to-useful-context, or generated-context quality; A6 remains **NOT VERIFIED** for those gates.

## A3/A5 — One hardware smoke and retained uncertainty

One `local_ai_task(action="hardware_benchmark")` smoke on installed `qwen3.5:4b-nvfp4` (`model_digest_status=verified_installed`, digest `56d8c805bbeb679be81d064cbda81aa3f91eb32492a4547c0ebaa50690980506`, request `req_733fab95b850`) succeeded on NVIDIA GeForce RTX 5070 Ti. Prompt requested `ready`, maximum 4 tokens; backend generated 2. TTFT 110.71 ms, generation 49.17 ms, 40.68 tokens/s, queue wait 39.86 ms, call latency 159.88 ms. Sampled device VRAM: 16,303 MB total, 8,731 MB used, 7,265 MB available; device-wide sampled peak `9,155,117,056` bytes. `loaded_model_vram_status=unavailable`; peak scope is device-wide. `ollama ps` was empty immediately before and after. One tiny sample; no cold/warm, residency, quality or capacity claim.

A different 128-token attempt was admitted but ended with `model output repetition loop detected` (`req_8cd44dec35f8`), so it yielded no performance result. The following distinct request was refused with `gpu_outcome_unknown`, `outcome_unknown=true`, reservation retained (`req_ec451fd7b5f2`). Fresh status `req_56a8fddc3b78`: `gpu_admission_state=outcome_unknown`, telemetry `sample_pending`/stale, pressure `unknown`. No further inference or restart attempted. Do not clear or bypass the fence without explicit scheduler/operator reconciliation. A3/A5 remain **NOT VERIFIED** for long-context/concurrency and managed llama.cpp lifecycle; A4/A7 remain open for device and task-quality evidence.

## A6 — CPU cache timing attempt outcome

A later CPU/SQLite-only cache-hit timing invocation did not yield an inspectable command result; the orchestration response reported output truncation. Execution and measurement outcome are **unknown**. No timing claim is recorded, and this attempt is not validation evidence. The invocation did not request model inference; the separate GPU `outcome_unknown` fence remains unchanged. Do not repeat this identical measurement without first establishing whether the original process completed.

## A1 — Focused recheck and embedding fixture diagnosis

Focused cohort `python -m pytest -q tests/test_external_gpu_reservation_lifecycle.py tests/test_opencode_gpu_reservation.py tests/unit/test_reranker_gpu_reservation.py tests/test_preprocess_status_scaling.py --tb=short`: **88 passed, 5 failed in 4.54 s**. The first failing OpenCode embedding case also failed alone (**1 failed in 0.35 s**), so failure is not caused only by suite ordering.

Source diagnosis for that case: the test constructs `EmbeddingModel` with `__new__`, sets `_gpu_reservation_path`, but omits `_gpu_reservation_store`. Production initialization creates `ExternalGpuReservationStore`; `_claim_embedding_gpu()` returns `False` when a path exists without a store, so `encode()` rejects before the mocked inference callback. This explains the isolated case as a fixture setup defect; the other four failing fixtures still need individual confirmation before applying a shared repair. No real model inference was requested.

During this recheck, `local_ai_status` changed from `gpu_admission_state=outcome_unknown` (`req_fd586aa16af3`) to `external_reservation` (`req_ab8a06c4c555`); VRAM telemetry remains stale/unknown. Preserve the active reservation. Test-fixture repair waits until the required bounded solve/review can run without submitting work against the reserved GPU.

## A1 — Shared cause confirmed across failed fixtures

Bounded source review of all five failed cases in `tests/test_opencode_gpu_reservation.py` confirms each bypasses `EmbeddingModel.__init__` with `__new__`, sets `_gpu_reservation_path`, and omits `_gpu_reservation_store`. The process-exit child does the same before `_encode_ollama()`. Production initialization creates a store for that path, and the reservation claim explicitly fails closed when a path is configured without its store. This explains the five fixture failures; it does not indicate a production reservation defect. Repair should create an independent `ExternalGpuReservationStore` for each model at the same temp path used by its scheduler, including the child fixture, so the tests exercise file-backed cross-instance exclusion. Patch remains pending while `gpu_admission_state=external_reservation` prevents the required bounded semantic solve/review.

## A1 — Embedding reservation fixture repair

Updated only `tests/test_opencode_gpu_reservation.py`: four in-process fixtures and the process-exit child now create their own `ExternalGpuReservationStore` at the same temporary reservation path as the scheduler. Product code unchanged. Focused module `python -m pytest -q tests/test_opencode_gpu_reservation.py --tb=short`: **58 passed in 4.56 s**. Targeted `git diff --check -- tests/test_opencode_gpu_reservation.py`: exit 0.

The semantic review response (`req_64bdc3bfe105`) was unusable (`invalid_citation`, `usable=false`); the broader `review_diff` job failed because the shared workspace diff exceeded its 12,000-token limit. No semantic review claim is made. Manual review confirms each model gets a separate store instance sharing the scheduler's temp file path. The full A1 cohort remains pending because its reservation source and lifecycle test are currently modified by another editor.

## A1 — Current-source regression cohort

Fresh direct `local_ai_coord(action="gpu_reservation_status")` reported `state=free`, `reservation_present=false` before validation. Full focused cohort against current dirty checkout: `python -m pytest -q tests/test_external_gpu_reservation_lifecycle.py tests/test_opencode_gpu_reservation.py tests/unit/test_reranker_gpu_reservation.py tests/test_preprocess_status_scaling.py --tb=short` — **98 passed in 5.82 s**. This includes 58 OpenCode reservation tests and 40 reservation lifecycle, reranker, and preprocessing-status tests. The five previous failures were test fixtures created with `EmbeddingModel.__new__` that omitted `_gpu_reservation_store`; adding an independent `ExternalGpuReservationStore` at each fixture's shared temporary path resolved them. Product code unchanged by this fixture repair. Bounded A1 source regression cohort passes; live cross-process/GPU and installed-process behavior remain unverified. `local_ai_task(action="review")` (`req_64bdc3bfe105`) returned `usable=false` with `invalid_citation`; it is not semantic review evidence. The broad repo `review_diff` job failed because the workspace diff exceeded 12,000 tokens. Primary review was limited to the exact test diff.

## A6 — Fresh current-source test

`python -m pytest -q tests/unit/test_preprocess_demand_priority.py --tb=short`: **7 passed in 1.99 s** against current dirty checkout. Current `_learned_priority_paths()` source SHA-256 `6ebc2a10495b027b179d94f5359b9984272f66846c2f8627c3ba87c41961e0b3`; cache key checks the current hot-query tuple, aggregate `file_refs` signature and 15-second TTL. Focused tests cover query/index-generation invalidation and four-batch fairness. This remains bounded source/SQLite evidence only. Real learned-query provenance, generated-context quality/latency, work saved and sustained fairness under actual preprocessing load remain **NOT VERIFIED**. Current Hub status (`req_ff2d97ad4e7c`) reported `gpu_admission_state=preparing_model`; no model-backed review or inference was started after that status.

## Review gate — bounded local review unavailable

A second, fixture-only `local_ai_task(action="review")` request included the exact changed helper, fixture call sites and file citations (`req_0cb4d73b887c`) but terminated with `local model output reached its token limit`. It produced no usable review. The earlier response (`req_64bdc3bfe105`) had `invalid_citation` and `usable=false`. Neither is accepted as semantic review; retain primary code review plus passing tests, and do not claim model approval.

## A4 — Current deterministic CPU bypass cohort

Fresh `python -m pytest -q tests/unit/test_rag_direct_cpu_bypass.py --tb=short`: **10 passed in 2.98 s** against the current checkout. This validates the deterministic direct CPU bypass regression only; no CUDA, model inference, retrieval quality, or CPU/GPU parity is measured.

## Readiness discrepancy — 2026-11-06

At the start of this continuation, `local_ai_coord(action="gpu_reservation_status")` returned `reservation_present=false`, `state=free`; in the same check set, `local_ai_status` (`req_dbf28b27de28`) returned `gpu_admission_state=external_reservation`, `ollama_online=null`, and degraded dependency probes (`runtime.online` and `ollama_profile`, each `probe_timeout`). VRAM telemetry was stale/unknown. Treat runtime admission as unavailable; no inference or model-backed review was started. The reservation/status disagreement needs scheduler/operator reconciliation before GPU qualification.

## A5 — Fresh mocked lifecycle cohort

Four focused `llama.cpp` routing/runtime regressions passed against current checkout: managed load/unload serialization; unload exclusion during inference; cancellation releases the slot; partial CUDA output is not replayed through fallback. Command result: **4 passed in 0.82 s**. No live model or GPU was exercised. Runtime load/inference/unload, real cancellation, VRAM release and admission remain **NOT VERIFIED**. The first pytest invocation used an incorrect class nodeid and collected no tests; corrected class-qualified nodeids then passed.

## A2 — Future profile retired-tag regression guard

`src/local_ai_hub/opencode_hardware.py` currently lists only `qwen3.5:9b-nvfp4`, `qwen2.5-coder:7b`, and `qwen3.5:4b-nvfp4` for the future 16 GB profile. Added `test_retired_model_tags_are_absent_from_future_profile_candidates` to `tests/test_opencode_future_stage.py`, covering retired `qwen3.5:4b-q4_K_M`, `gemma4:12b`, and `qwen2.5-coder:14b`. Targeted validation passed: **2 passed in 0.29 s**; scoped `git diff --check` exited 0. Git reported the file's LF-to-CRLF normalization warning. This supplements the completed scoped A2 scan above by independently guarding the future 16 GB candidate list; the prior scan and installed-tag snapshot cover the named active/advisory surfaces, while historical evaluation records intentionally retain tested tags.

The fresh readiness sample (`req_a10a195e21ef`) reports Ollama online but scheduler `probe_timeout`, `gpu_admission_state=unknown`, and stale `sample_pending` VRAM telemetry; reservation status (`req_3823c1b3d8c9`) is free. No model inference or GPU benchmark was run. The diff-review job (`e4b4c95a12d644efa163406fcf96db21`) failed terminally because the broker included a shared diff fragment exceeding its 512-token review budget; no semantic approval is claimed.

## A4 — Current-checkout CPU bypass revalidation

After the shared checkout's embedding changes, `python -m pytest -q tests/unit/test_rag_direct_cpu_bypass.py --tb=short` passed **10 passed in 1.71 s**. The unchanged focused test file SHA-256 is `56115841ade1531c5746cfa70501e99ed047188d048346695a1c859409b1f309`; current Git status (`req_23e5ff79887a`) lists `src/local_ai_hub/embeddings.py` as modified. This confirms deterministic CPU bypass behavior in the current checkout's synthetic fixture only. GPU execution, CPU/GPU parity, retrieval quality and performance remain unverified; no broker verification receipt was recorded.

## A2 — Capability-registry retired-tag regression guard

Expanded `test_retired_model_tags_are_not_in_the_prompt_capability_registry` to reject `qwen2.5-coder:14b` alongside the retired Qwen Q4 and Gemma tags. The focused test passed (**1 passed in 0.34 s**); `git diff --check -- tests/test_prompt_contracts.py` exited 0. Updated test-file SHA-256: `05fb16e2eac8fce5a462f9d3f357ebd8e87b4d65a79a15c69da4e83e84955023`. This adds a regression guard for the capability registry; prompt-surface and installed-tag evidence remains as recorded in the completed scoped A2 scan above.

## Readiness discrepancy — current continuation

Fresh `local_ai_status` request `req_e988eb661160` returned degraded status: Ollama online, active model empty, `gpu_admission_state=unknown`, scheduler `probe_timeout`, and stale `sample_pending` VRAM telemetry. The paired `gpu_reservation_status` response reports `reservation_present=true`, `state=unknown`, and `manual_intervention_required=true`. No inference, GPU test, or reservation release was attempted. Owner, generation, expiry, and confirmed liveness were not available in the returned status fields; the fail-closed release rule therefore prohibits mutation. GPU runtime acceptance remains blocked pending authoritative reservation reconciliation and fresh telemetry.

## Readiness update — reservation free, VRAM telemetry pending

On the next fresh check, `gpu_reservation_status` returned `reservation_present=false`, `state=free`, `manual_intervention_required=false`; `local_ai_status` request `req_70330e579184` returned Ollama online, active `qwen3.5:9b-nvfp4`, and `gpu_admission_state=available`. VRAM telemetry remains `sample_pending`/stale with pressure `unknown`. This current snapshot clears the previous unknown-reservation condition but does not establish how it cleared or provide a safe measured VRAM baseline. No GPU inference or benchmark was started; runtime acceptance remains open.

## A1 — Current clean-path reservation cohort revalidation

Fresh `git_status` (`req_399aef0d734d`) showed the A1 source and cohort test paths clean. Current checkout cohort `python -m pytest -q tests/test_external_gpu_reservation_lifecycle.py tests/test_opencode_gpu_reservation.py tests/unit/test_reranker_gpu_reservation.py tests/test_preprocess_status_scaling.py --tb=short` passed **98 passed in 6.69 s**. Post-run status (`req_75fe1d47ba6c`) still shows those paths clean; six unrelated prompt/HTTP/MCP paths are modified. This revalidates file-backed lifecycle, scheduler and fixture regressions in the current checkout; installed-process and physical GPU behavior remain unverified.

## Readiness discrepancy — MCP status mismatch

In the same fresh check set, `local_ai_status` request `req_b0019731c91d` reported `gpu_admission_state=external_reservation`, while `gpu_reservation_status` returned `reservation_present=false`, `state=free`, `manual_intervention_required=false`. VRAM telemetry remained `sample_pending`/stale with pressure `unknown`. No inference, service restart, or GPU benchmark was attempted. Treat runtime admission as unavailable until both APIs agree and telemetry is fresh.

## A6 — Current clean-path demand-priority regression revalidation

Fresh `git_status` before and after execution (`req_399aef0d734d`, `req_75fe1d47ba6c`) showed `src/local_ai_hub/preprocess.py`, `tests/unit/test_preprocess_demand_priority.py`, and `tools/benchmark_preprocess_demand.py` clean. Current focused test `python -m pytest -q tests/unit/test_preprocess_demand_priority.py --tb=short` passed **7 passed in 1.78 s**. This revalidates query/index invalidation and bounded queue fairness in SQLite fixtures. It does not establish real learned-query provenance, generated useful-context latency/quality, work saved, or sustained fairness under live preprocessing; A6 remains open for those gates. No model inference or GPU operation was used; no broker verification receipt was recorded.

## A6 — Actual learned-query provenance gap

`UsageLearner.hot_queries(root, limit)` reads query labels for the resolved repository root from `learning.sqlite3` under `server.state_dir`, ordered by hit count and recency (`learning.py` SHA-256 `110204afa645ae9cdf90b51f62e1f78b1e005da7f68ac160ea40d5b693c17a9f`). The current repository benchmark accepts an explicit `--query` and includes that raw query in output (`tools/benchmark_preprocess_demand.py` SHA-256 `0956deb24207b0d47bc9e4dbfda7416c3779e2b910012a9e19aa66c10d1566c5`). Existing A6 runs used audit-derived queries, not verified learned-query provenance. Next bounded implementation should read the top query for the exact repository root through read-only SQLite and report only a query digest/length plus aggregate selection metrics; never print query text. No user learning database or query value was read in this turn. This can establish real hot-query provenance and queue selection only; useful generated-context quality/latency, work saved, invalidation and live fairness remain open.

## A6 — learned-query provenance correction

The prior provenance note was not present in the current audit log; the file ended at line 279 with the fixture-test revalidation. Source inspection established that `UsageLearner.hot_queries(root, limit)` selects queries from the resolved root's `learning.sqlite3` under `server.state_dir`, ordered by hits and recency (`src/local_ai_hub/learning.py`, SHA-256 `110204afa645ae9cdf90b51f62e1f78b1e005da7f68ac160ea40d5b693c17a9f`). `tools/benchmark_preprocess_demand.py` instead accepts explicit `--query` and emits it verbatim (SHA-256 `0956deb24207b0d47bc9e4dbfda7416c3779e2b910012a9e19aa66c10d1566c5`). Existing A6 runs used audit-derived queries, so learned-query provenance remains unverified. No user learning database or query value was read. Next safe implementation: read-only selection for the exact authorized root and report only a digest/length plus aggregate selection metrics; test with a synthetic isolated database. This proves provenance and selection only, not generated useful-context quality/latency, work saved, live invalidation, or fairness. Code edits deferred: current GPU telemetry is stale/unknown, so required semantic pre-edit review cannot be trusted. No model inference/GPU action or broker receipt.

## A5 — mocked llama.cpp lifecycle regression cohort

Fresh `local_ai_repo:git_status` (`req_2283d72c1db9`) showed `tests/test_llama_cpp_routing.py` clean. Source evidence (`src/test` file SHA-256 `d0a36bfd5234d82db9fab39aae785a34391ca7540a5a451d05ff7a140d8f31c3`) includes cancellation/unload coordination tests with fake sockets and managed-runtime doubles. Bounded native command `python -m pytest -q tests/test_llama_cpp_routing.py --tb=short` passed **37 passed, 20 subtests in 3.25 s**. This validates mocked routing and lifecycle behavior only; it does not prove a real llama.cpp load/inference/unload/switch, GPU residency, measured VRAM release, real cancellation or scheduler reservation behavior. A5 remains open. No model inference/GPU action; no broker receipt (`receipt_status=not_recorded`).

## A2 — current status cannot establish installed-tag snapshot

Fresh compact `local_ai_status` (`req_b72d390a96c1`) reports Hub/Ollama online, `active_model=null`, GPU admission `available`, and VRAM telemetry unavailable with `sample_pending`/stale state. This response contains no installed-model tag inventory, so it cannot close A2's required current installed-tag snapshot. No model list was inferred from configuration or historical inventory. GPU-bound A3-A5/A7 measurements remain deferred until telemetry is fresh; no inference or GPU operation was attempted.

## A2 — current regression revalidation

Fresh `local_ai_repo:git_status` (`req_fb0f8ecb56d5`) showed both A2 test files clean while other agents had edits in `docs/agent-evaluation/results.md` and `docs/superpowers/plans/2026-11-03-gpu-capability-tiers-and-local-ai.md`; those files were left untouched. Bounded native command `python -m pytest -q tests/test_opencode_future_stage.py tests/test_prompt_contracts.py --tb=short` passed **14 passed in 0.64 s**. The regression tests protect retired model names from active/future candidate lists; they do not establish current installed tags. A2's runtime inventory snapshot remains open. No inference/GPU operation; no broker receipt (`receipt_status=not_recorded`).

## A4 — current deterministic CPU bypass cohort

Fresh `local_ai_repo:git_status` (`req_00f82505da99`) showed `tests/unit/test_rag_direct_cpu_bypass.py` clean while `tests/unit/test_search_mode_fusion.py` was modified by another editor; the latter was not touched. Bounded native command `python -m pytest -q tests/unit/test_rag_direct_cpu_bypass.py --tb=short` passed **10 passed in 4.59 s**. This revalidates synthetic CPU bypass behavior only; no GPU embedding/reranking, relevance, throughput, or VRAM evidence. No model/GPU action and no broker receipt (`receipt_status=not_recorded`).

## A2 — installed-tag inventory surface check

Current `local_ai_status` (`req_02f5c2c5dc28`) reports `active_model=qwen3.5:4b-nvfp4`, admission free (`local_ai_coord:gpu_reservation_status`), but VRAM sampling remains stale/pending and no installed-tag list is returned. Requesting `installed_models`/`model_inventory` as status extra fields (`req_1e0eae931c97`) did not add inventory. Read-only source inspection of the current `src/local_ai_hub/services.py` snapshot (SHA-256 `f4b4c0161c66faa4f13167db6b8c404a11a204d0800a4faf62313c735b293ac2`, lines 9281–9294) shows that this health-check detail exposes only `len(runtime.installed_models())`, not tag names. This limits the compact status/health-check surfaces; it does not prove no other authorized inventory API exists. `services.py` is modified by another editor and was not changed. A2 current installed-tag inventory remains open; no model inference/pull or GPU operation.

## Shared diff review — terminal unknown outcome

A bounded `local_ai_repo:review_diff` request (`req_604e9cd0e52e`, job `885e8b76bd3d42d9a1893bd4e4d36415`, trace `0f8ea6d4258a4d939dc27c5dfa74e61e`) was durably queued, then one `local_ai_task:wait` returned terminal `outcome_unknown`: `Review segment 1/21 failed` (`req_ed2f467d3318`, `retryable=false`). The prescribed single `local_ai_task:result` inspection (`req_8428d9ea59c7`) returned the same unknown state and no artifact. This is not a review receipt and no findings are accepted. Do not retry or replay this job; independent source/test evidence remains authoritative. No source edits or GPU action occurred.

## A1 — current external reservation lifecycle cohort

Fresh `local_ai_repo:git_status` (`req_d1c1b0f004d9`) showed `tests/test_external_gpu_reservation_lifecycle.py` clean; concurrent edits remained confined to `src/local_ai_hub/services.py`, `tests/unit/test_search_mode_fusion.py`, and the plan/evaluation documents. Bounded native command `python -m pytest -q tests/test_external_gpu_reservation_lifecycle.py --tb=short` passed **30 passed in 0.83 s**. This covers file-backed reservation lifecycle fixtures only. It does not establish installed MCP action parity, simultaneous live-process admission, or physical GPU behavior. No GPU action; no broker receipt (`receipt_status=not_recorded`).

## A1 — live MCP status action

A current call to `local_ai_coord:gpu_reservation_status` succeeded and returned `reservation_present=false`, `state=free`, `manual_intervention_required=false`. This verifies the installed MCP status action and its free-state response only. No claim/release mutation was attempted, so installed mutation-action parity, cross-process admission and physical GPU behavior remain unverified. Concurrent `src/local_ai_hub/services.py` and `src/local_ai_hub/mcp_server.py` edits were preserved.

## A2 — readiness instability and repo transport

In this turn, `local_ai_status` first reported `active_model=qwen3.5:4b-nvfp4` (`req_9d922bfc36ce`) and after one Hub repo transport error reported `active_model=null` (`req_f59b2f310876`); both showed VRAM telemetry `sample_pending`/stale. A subsequent bounded `local_ai_repo:search` failed with HTTP transport error (no request ID returned); the single health check succeeded, so no native fallback was authorized. This confirms the active route is not a stable installed-model inventory or readiness receipt. No inference, GPU operation, or code edit.

## A2 — overlapping capability-aware status work in progress

Current `git_status` (`req_ef614ca4b412`) shows another editor changing `src/local_ai_hub/mcp_server.py`, `src/local_ai_hub/services.py`, `tests/test_mcp_agent_routing.py`, and the GPU capability plan/evaluation files. Read-only indexed/source inspection of the dirty MCP routing test (`tests/test_mcp_agent_routing.py`, SHA-256 `4ced52b287d7ff759da5ae3341e954e3c4413e79c8f4a3e0fc2aa9506ac525da`) found new draft cases for status capability reasons without inference and suppressing local routing descriptions when models are unavailable. This overlaps A2/A7 capability discoverability; it remains unvalidated draft evidence because those files are actively modified. They were not edited or tested in this turn.

## Goal resume — GPU admission regressed to outcome_unknown

After Local AI MCP tools returned, fresh `git_status` (`req_fc462ea50bab`) showed 18 modified paths and one untracked test; concurrent work now includes prompts, runtime/MCP services, search code and tests. Fresh `local_ai_status` (`req_28ef5fb016ba`) reports `active_model=null`, `gpu_admission_state=outcome_unknown`, and stale `sample_pending` VRAM. No GPU/model call or reservation mutation is safe. `plan_list` (`req_9c7a6c137525`) exposes no GPU-audit-specific Agent OS plan; the existing task contract was resumed and checkpointed as `task_c04ba331704e`. Relevant memory lookup returned only an unrelated orphan-intent record, explicitly excluded. Next: preserve the shared dirty paths, continue source/test work only when it does not require model inference, and resume semantic pre-edit review after readiness is known and admission is resolved. No verification receipt.

## A1 — live reservation state requires manual intervention

Read-only `local_ai_coord:gpu_reservation_status` after the resumed status reported `reservation_present=true`, `state=unknown`, `manual_intervention_required=true`. This is a current fail-closed reservation, not a free GPU. No release/claim was attempted; repo policy requires verified owner death or expiry and valid generation/consent for release, and unknown owner liveness remains fail-closed. Do not run model inference or GPU benchmarks until operator reconciliation and fresh VRAM telemetry. This supersedes earlier `state=free` snapshots for current readiness; historical results remain unchanged.

## A1 — reservation diagnostics projection gap

A read-only `gpu_reservation_status` request with `extra_fields=[owner,generation,state,expires_at,manual_intervention_required]` still returned only `reservation_present=true`, `state=unknown`, and `manual_intervention_required=true`; owner, generation and expiry were omitted. No release action was attempted. The current MCP projection therefore cannot supply the exact generation/expiry needed for consented recovery; operator-side authoritative inspection is required. This is an observed response-contract gap, not proof that reservation metadata itself is malformed or expired.

## A1 — classify `unknown` from current source

Bounded source inspection after lexical search exceeded Hub response budget found the current read path. In dirty `src/local_ai_hub/mcp_server.py` SHA-256 `69a7896f5cd5f70dabcede416797ddb15ed899e49de65841f1c3f5231bba29f1` lines 5170–5178, status calls `store.reap_expired()`, then `store.read()`; `record is None` plus existing reservation path maps to `state=unknown`, `manual_intervention_required=true`. `src/local_ai_hub/external_gpu_reservation.py` lines 266–309 returns `None` for symlink, missing/invalid metadata, unreadable digest, digest mismatch, or invalid schema/fields. Therefore the live result is not merely a response-projection omission: runtime cannot authenticate a valid reservation record. Exact failure cause remains unknown without operator-side artifact inspection. Do not release, delete, recreate, or infer owner/expiry. The MCP source is actively modified by another editor and was not changed.

### A1/A2/A7 — fresh reservation and focused routing evidence (2026-11-05)

- The bounded status request `req_b84f4b2092eb` reported `gpu_admission_state=outcome_unknown`, `vram_pressure=unknown`, VRAM sampling pending/stale, and `active_model=null`.
- The subsequent read-only `gpu_reservation_status` returned a valid active reservation: owner `embedding:22628:41680`, generation `4d5d35dceb7a46bd9ddbd87a74b73ec9`, expiry `1793904759.0376031`, `expired=false`. This is the latest reservation record; it does not explain the differing aggregate admission status. Treat it as owned and fail closed. No release, inference, or benchmark was run.
- Focused mocked routing tests: `python -m pytest -q tests/test_mcp_agent_routing.py -k "test_status_exposes_profile_capability_reasons_without_model_inference or test_disabled_descriptions_omit_local_routing_without_models" --tb=short` → **5 passed, 113 deselected**. This checks profile capability reporting and omission of local routes when models are unavailable; it is not GPU/runtime acceptance.
- Evidence IDs: status `req_b84f4b2092eb`; checkout status `req_7e9af55fed46`. The checkout had only this progress audit modified before this append. GPU/runtime acceptance remains **NOT VERIFIED**.

### A2 — exact-reference verification remains open (2026-11-05)

- Bounded repository search `req_deaac685d246` for the retired tags returned a degraded lexical fallback, 276 lexical matches and only four unrelated code slices. A path-guided follow-up `req_7c7b785df706` was also degraded/partial (2 of 10 candidates, unknown index coverage, no exact count) and returned unrelated tests.
- These results cannot establish whether retired tags remain in the six active/advisory files named in A2. Search returned successfully with degraded optional backends, so native broad search is not authorized by the fallback contract. No files were changed for A2. Keep its required closure open until bounded exact-source/index evidence is available.
- Latest `git_status` `req_34add697fb06` reports this progress audit plus `src/local_ai_hub/llama_cpp_runtime.py` modified and `tests/unit/test_llama_cpp_runtime_startup_diagnostics.py` untracked. The latter two paths are concurrent work; they remain untouched.

### A3 — classify scheduler uncertainty separately from external reservation (2026-11-05)

- Current Hub status `req_ac1301bccc8a` reports `gpu_admission_state=outcome_unknown`, `active_model=null`, and `vram_pressure=nominal`; the separate reservation status still reports the unexpired active embedding lease recorded above.
- Source confirms these are distinct layers. `AffinityScheduler.status()` reports `outcome_unknown` first when `_internal_gpu_uncertain` is true, before checking `_external_gpu_reserved()` (`src/local_ai_hub/scheduler.py`, lines 1970–1981; SHA-256 `cc3d0d8c456b8237577d8da947fd38e55519e2651bf2cfc1092f35b747d74cc5`). MCP status projects that scheduler field (`src/local_ai_hub/mcp_server.py`, lines 2677–2688; SHA-256 `69a7896f5cd5f70dabcede416797ddb15ed899e49de65841f1c3f5231bba29f1`).
- Source sets `_internal_gpu_uncertain=True` when `_perform_switch()` raises after the operation may have started (`scheduler.py`, lines 1488–1494); an `operation_not_started` exception does not set it. This explains why a valid external lease can coexist with scheduler `outcome_unknown`; it does not identify the live triggering exception or establish that GPU use is safe.
- Keep GPU admission fail-closed. No lease release, scheduler reset, model inference, or benchmark. The runtime cause and safe recovery remain open; collect an authentic runtime diagnostic or wait for owner-authorized recovery.

### Ownership and reservation refresh (2026-11-05)

- Fresh `git_status` `req_3a7b5c3137e5` shows concurrent edits in `src/local_ai_hub/llama_cpp_runtime.py`, `src/local_ai_hub/repo_tools.py`, `tests/unit/test_hybrid_expanded_lexical_candidates.py`, and untracked `tests/unit/test_llama_cpp_runtime_startup_diagnostics.py`, plus this audit. These paths remain untouched. The repo-search implementation is now also concurrently changing, so defer A2 indexed search follow-up until its owner finishes.
- Fresh `gpu_reservation_status` still reports generation `4d5d35dceb7a46bd9ddbd87a74b73ec9`, owner `embedding:22628:41680`, `state=active`, `expired=false`. Keep it intact.
