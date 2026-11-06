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

## A6 — exact source-identity revision for learned-priority cache (2026-11-05)

- Added derived `file_refs_revision` state with SQLite insert/delete triggers and an update trigger on `root`, `path`, and `content_hash`. `_init_db()` installs the table/triggers. `_learned_priority_paths()` uses the per-root revision as an O(1) cache signature; card status changes such as `card_key` do not invalidate learned-query-to-path mappings. Minimal legacy/test schemas without startup tracking keep the prior aggregate fallback.
- Regression test first failed: after renaming the matching `file_refs`/FTS path while preserving the old aggregate signature, `_learned_priority_paths()` returned stale `old.py` instead of `new.py`. Added trigger coverage proving source identity changes increment revisions, card-state updates do not, and root moves update both roots.
- Updated the bounded synthetic benchmark to install revision tracking and report `cache_revision_tracking=true`, so selection measurements exercise the production cache path.
- Focused suite: `python -m pytest -q tests/unit/test_preprocess_demand_priority.py --tb=short` — **8 passed**. `git diff --check` — no whitespace errors; Git emitted LF-to-CRLF warnings for the test and benchmark files.
- Same 4,096-file/64-batch synthetic queue run: baseline reached the hot file in 64 batches; demand reached it in 1. Both completed 4,096 files with 0 unprocessed. Selection median/p95: baseline **2.28/3.14 ms**, demand **2.68/3.45 ms**. This is queue-selection evidence only; `useful_context_verified=false`, with no model inference or GPU work.
- An intermediate per-row Python hash signature measured **15.35/16.85 ms** demand selection median/p95 in the untracked benchmark schema. Replaced it with the trigger-maintained revision to avoid the repeated row serialization cost.
- Semantic review unavailable: `local_ai_repo:review_diff` job `651b386458a043ac845ff3775ee9c181` could not be retrieved (`req_80ce165fc0e7`, work order not found); `local_ai_task:review` `req_9e1d78409d50` was terminally rejected by scheduler `gpu_outcome_unknown`. `local_ai_repo:impact` `req_ef6e35f2d339` used heuristic scan fallback and is not accepted as exact impact evidence. Primary review inspected the bounded diff and source slices.
- GPU status remains fail-closed (`req_b73909ff22ad`: scheduler `outcome_unknown`, VRAM sample pending/stale); active embedding lease remains unexpired. No inference, reservation release, or scheduler reset.
- Source snapshot IDs: `preprocess.py` SHA-256 `b4747b41ab1db92dd6a14facf6a393558972457424711e7154ca159aeadd1a9c`; focused test SHA-256 `ab583e92d0108fec9c36190ada2ce65980272b84c768d8c17d02cf39f6761565`; benchmark SHA-256 `d550585759f4d0aacd10b4d4161cd76dec7fea8fa044c62d3002306a98e184fe`.

### Fresh GPU/ownership snapshot after A6 validation (2026-11-05)

- `local_ai_status` `req_927e6a6f2594` still reports scheduler `gpu_admission_state=outcome_unknown`, `vram_pressure=unknown`, and stale/pending VRAM sampling.
- Fresh `gpu_reservation_status` now reports generation `1a169eeeff194f2f85ac8936a1c69e62`, owner `embedding:22628:44996`, `state=active`, expiry `1793905793.3707826`, `expired=false`. This differs from the earlier generation/owner; do not infer continuity or release either record.
- Fresh `git_status` `req_2ba76ae13626` shows concurrent edits to both canonical prompts (`docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`). They remain untouched. Current A6 paths are the only other code/test changes besides this progress log.

### A5 — managed startup diagnostics evidence (2026-11-05)

- Current `tests/unit/test_llama_cpp_runtime_startup_diagnostics.py` (SHA-256 `255c23f4bea5e7d98844e311cbc72428457de9a93a4ca89a813a417e6629e7ed`) covers a managed port conflict and missing `llama-server` binary, asserting actionable `_last_error` text and the expected provisioning call behavior.
- `python -m pytest -q tests/unit/test_llama_cpp_runtime_startup_diagnostics.py --tb=short` — **2 passed**. This is mocked startup-diagnostic coverage only; no model was loaded and A5 live load/infer/unload, cancellation, residency, and scheduler-reservation acceptance remain open.
- Fresh checkout status `req_97ebd08abe21` no longer lists the runtime file or diagnostic test as dirty/untracked. Treat these tests as current checkout evidence; do not infer ownership or live-runtime qualification from that status.

### Resume snapshot — bounded follow-up (2026-11-05)

- Fresh `local_ai_repo:git_status` `req_067d7c937663`: modified paths are `.local-ai-hub/plans/plan_lah_5_1_0_release_finalization.plan.json`, both canonical prompts, this progress report, `src/local_ai_hub/external_gpu_reservation.py`, `src/local_ai_hub/preprocess.py`, `tests/test_external_gpu_reservation_lifecycle.py`, and `tests/unit/test_preprocess_demand_priority.py`; no staged or untracked files. Keep prompt and reservation work within their current owners. A6 source/test and this report remain the current task's paths.
- Fresh `local_ai_status` `req_c6dd864ad06a`: Hub 5.1.3 online; `active_model=null`, `gpu_admission_state=external_reservation`, `vram_pressure=unknown`; VRAM telemetry unavailable, sampling, and stale. A live GPU measurement is not authorized by this evidence.
- A6 fairness source review: `_find_next_files()` reserves at least one regular slot when demand paths exist (`quota = min(limit - 1, max(1, limit // 4))`), then fills remaining slots from the ordinary ordered queue. The current focused tests assert regular work remains in the first hot batch and both demand/baseline queues complete with zero unprocessed files. The 2026-11-05 recorded focused run was 8 passed. The representative temporary-repository benchmark measures queue selection only and explicitly reports `useful_context_verified=false`; time-to-useful-context and deeper analysis quality remain unverified. No A6 fairness code change was justified by current source/tests; no test was rerun in this continuation.
- `local_ai_repo:solve` `req_8abee5fed446` terminated with `gpu_outcome_unknown` and `reservation retained`; no retry. A2 exact searches did not return usable candidate locations for the generated guidance, and canonical prompt files remain modified by another editor. A2 current installed-tag confirmation and cross-file closure remain open.
- Next safe work: resume A2 once prompt ownership releases and exact source candidates are available; keep A3/A4/A5/A7 live hardware/model acceptance `NOT VERIFIED` while GPU admission or required labeled runs remain unavailable.

## A2 — remove a retired tag from safety-test fixture (2026-11-05)

- Current source evidence: `src/local_ai_hub/prompt_contracts.py` registry includes `qwen3.5:4b-nvfp4` and has no registry entries for `qwen3.5:4b-q4_K_M`, `gemma4:12b`, or `qwen2.5-coder:14b`. `src/local_ai_hub/opencode_hardware.py` future candidates are Qwen 9B NVFP4, Coder 7B, and Qwen 4B NVFP4 for 16 GB. `docs/MODEL_CAPABILITIES.md` names Qwen 4B NVFP4 and omits the three retired recommendations in the inspected section.
- `generator._model_capability_guidance()` derives guidance from configured `cfg["models"]` and `capability_for()`; it contains no hard-coded model candidate list. Current configured model values and exact canonical prompt content still need a fresh cross-file check before A2 closure.
- Changed `tests/test_prompt_contracts.py`: replaced the removed `qwen2.5-coder:14b` input in the conservative unknown-heavy-model safety test with `unregistered-coder:14b`, and renamed the test to describe the exercised behavior. Negative assertions that retired tags are absent remain.
- Focused validation: `python -m pytest -q tests/test_prompt_contracts.py tests/test_opencode_future_stage.py --tb=short` — **14 passed**. Exact native diff review confirmed only the fixture name and test name changed. The Hub indexed current source at `req_b17a76aa490b` (`Ec3a6cca36ae8c2a49d7d`).
- `local_ai_repo:review_diff` `req_208170d33603` could not split a concurrent diff fragment above its 512-token review cap; scoped native review and the focused tests cover this small fixture-only edit. No production behavior changed.
- Fresh `git_status` `req_bf4b2a15be0f`: prompt documents are no longer modified; other agents still have reservation/MCP changes and the untracked reservation contract test. Preserve those paths. Fresh `local_ai_status` `req_16a4974ec5a6`: admission remains `external_reservation`; `active_model=null`, VRAM unknown/stale. GPU/runtime acceptance remains open.

### A2 — current configured-route evidence (2026-11-05)

- Current `src/local_ai_hub/hardware.py` high/max profile slices (SHA-256 `f0ec55b3d5004bc6f01afc5e564eb2d4a3ca272a1a8521b7af5d282cfa5212c0`, lines 506–575) route background/fast to `qwen2.5-coder:3b`, heavy/reasoning/general/vision to `qwen3.5:9b` in high; max routes background/fast to Coder 3B and heavy/reasoning/general/vision to Qwen 9B. No removed A2 tags appear in these profiles. This is source configuration, not installed-model or live-route evidence.
- Current canonical prompt files are no longer in `git_status` modified paths (`req_da00b506c97d`). Exact inspected initial slices are current hashes INSTALL `431476997f2c8be22956f7d2c5fa7bfbf28cf386c5a5d3fe09786d301432fb78` and UPDATE `c1e3ed56f476c7552979f1c64972b3d29675674f092cb6c81b1eb2603a04461d`; those slices contain contracts and caution against assuming runtime model availability. The complete model-guidance sections were not exhaustively fetched, so this does not close prompt synchronization.
- No current installed-tag inventory was retrieved. `local_ai_status` `req_0de194955102` reports only `active_model=null`, `gpu_admission_state=external_reservation`, and VRAM telemetry `sample_pending`/stale/unknown. Keep current installed-tag and GPU/runtime acceptance open; do not infer absence or residency from `active_model=null`.
- Remaining A2 closure: inspect complete model-guidance sections and obtain a current installed-tag snapshot through a read-only supported inventory path. Do not run inference while reservation is held by another process.

### A2 — current retired-tag reference audit (2026-11-05)

- Replaced the remaining positive-name fixture `qwen2.5-coder:14b` in `tests/test_opencode_model_names.py` with `unregistered-coder:14b`; arbitrary local model-name coverage remains. Focused tests `python -m pytest -q tests/test_opencode_model_names.py tests/test_prompt_contracts.py tests/test_opencode_future_stage.py --tb=short` — **23 passed**. Current source SHA-256: `2bfb81535b72c698a0109e72e90be1c36328e672a60f2e3dd28e770075438646`.
- Exact indexed reference set for `qwen2.5-coder:14b` now totals 14 current-source hits and paginated to `has_more=false` (`req_fa18b622b51a` plus offsets 1–13). Hits are in the audit/progress/historical plan/spec records and negative retirement/future-candidate assertions; there is no remaining positive model candidate in the source hits. The prior positive arbitrary-name test is gone.
- Exact indexed reference set for `gemma4:12b` totals 16 hits and paginated through offset 15; results were historical audit/progress/plan/spec records and negative assertions, not active registry, hardware candidate, or prompt recommendation. Historical records remain intact.
- Fresh source slices confirm the prompt capability registry (`prompt_contracts.py`, SHA-256 `f56f374fe2a051a0f90da23cb1ee548f478177aad5bd9dd2cf83cc0da407efd4`), 16 GB future candidate list (`opencode_hardware.py`, SHA-256 `42b5faf2dc3f9c8e33e803c153f89b96e513a7c32cce2d662929c0f2800761ef`), and full model capability matrix (`MODEL_CAPABILITIES.md`, SHA-256 `a7bafe23423082597e7955a560b21ea251477220f590d09086c364080927142e`) use Qwen 4B NVFP4 instead of the retired Q4 candidate. `generator.py` emits model guidance from active `cfg["models"]` and `capability_for()`; it does not keep a static candidate registry.
- `qwen3.5:4b-q4_K_M` search has low precision (272 lexical matches and unrelated top results); this did not prove a complete current-reference set. The canonical prompt full model sections and a current installed-tag snapshot also remain unverified. A2 therefore remains **partially verified**, not closed. No inference or pulls were run; Hub still reports external GPU reservation and unknown/stale VRAM.

### Resumed after MCP transport outage — A2 prompt section checked (2026-11-05)

- Fresh `local_ai_status` `req_24cc888d8e63` succeeds: Hub 5.1.3, `hub_online=true`, `gpu_admission_state=outcome_unknown`, `active_model=null`, VRAM pressure `unknown`, telemetry sample pending/stale. Transport availability returned; cause of the previous MCP transport outage is not established and no restart was performed.
- Current ownership snapshot `local_ai_repo:git_status` `req_ec71cd8287da` shows both canonical prompts dirty again alongside multiple editor-owned source/tests and audit progress. All prompt/source edits deferred to their current owners.
- Exact current hardware-tiered model-policy slices were read with SHA-bound artifact pages: `docs/INSTALL_PROMPT.md` SHA-256 `10d43a0a3d666352956dc21f455daa370d7614c10ced94195138a055de9b1133`, lines 795–827; `docs/UPDATE_PROMPT.md` SHA-256 `9b4a9c8faf06070da6e72ed45a57665c77c5c2eaa8739631cd7684ebae8b465e`, lines 767–819. Both sections describe profile/feature ceilings, independent provider-readiness, and GPU acceptance limits; neither lists stale model candidates. The policy says two-request high/max configuration is not capacity proof.
- Exact retired-tag lexical search for `qwen3.5:4b-q4_K_M` still yields 272 fragments including unrelated files; it cannot establish whole-repo absence. The inspected prompt policy sections and complete `MODEL_CAPABILITIES.md` do not contain the retired recommendation. Keep broad reference closure and installed-model inventory unverified.
- Current action: continue only on unowned files. No service restart, model inference, model pull, or prompt edit.

### Fresh status after resumed work (2026-11-05)

- `local_ai_status` `req_d5fe42bdab68`: Hub online, version 5.1.3, `degraded=false`; GPU admission `outcome_unknown`, active model null, VRAM pressure unknown, and VRAM telemetry pending/stale. Optional `agent_state` probe is degraded with `probe_timeout` at 250 ms. This is a separate status signal; no evidence ties it to the earlier MCP transport outage.
- `local_ai_repo:git_status` `req_3e9b2f308db6`: 12 modified paths and one untracked test; INSTALL/UPDATE prompts, reservation/MCP/preprocess source and tests remain editor-owned/dirty. No staged files. This task changed only the progress audit in this continuation.
- No live model or GPU operation attempted. Keep runtime acceptance open; continue source-only on unowned work.

### A6 — useful-context benchmark extension (2026-11-05)

- Extended `tools/benchmark_preprocess_demand.py` and `tests/unit/test_preprocess_demand_priority.py` so repository mode measures deterministic `RepositoryTools.context_pack_paths` output for each strategy's first selected batch. It requires `success=true`, nonempty evidence, and nonempty context; synthetic mode remains explicitly unverified. No model, inference, GPU, or runtime behavior is involved.
- Focused validation: `python -m pytest -q tests/unit/test_preprocess_demand_priority.py --tb=short` — **8 passed**.
- Bounded repository run: `python tools/benchmark_preprocess_demand.py --root . --files 64 --batch-size 16 --query ProjectPreprocessor` — 64 sampled files, 12 lexical matches, deterministic useful context confirmed for both strategies at batch 1 / 16 files; each returned 5 evidence items and 2,320 context characters. Work saved: **0 batches / 0 files** for this query. Both strategies completed all 64 files.
- The benchmark emits elapsed selection/context measurements for observation only. This single sequential baseline-then-demand run is cache/order sensitive; do not interpret its timing difference as a speedup or quality result. No paired repeated performance study was run.
- A separate bounded `file_refs_revision` query found no matching file in its sample and exited before measurement; this is a query/sample mismatch, not a benchmark defect. Representative-query selection remains open.
- A6 remains partial: useful context is now measured for repository mode, but demand-priority savings are query-dependent and this case demonstrated no savings. GPU/runtime acceptance remains **NOT VERIFIED**.

### A6 — benchmark sample correction and demand-work measurement (2026-11-05)

- The earlier 64-file `ProjectPreprocessor` run above is superseded as a representative-repository measurement: inspection showed the sampler had admitted `.local-ai-hub/local/intents`, installed `.local-ai-hub-superpowers`, and `.merge-checks/pytest` artifacts before repository source. The fixture now skips these three tool/runtime directories; the regression test includes matching generated files and confirms they are excluded.
- Failure-first regression: `python -m pytest -q tests/unit/test_preprocess_demand_priority.py::test_repository_benchmark_measures_real_hot_files_against_cold_queue --tb=short` failed because 4 files were sampled instead of the 3 source files; after the sampler exclusion fix, the full focused module passed **8 tests**.
- Corrected bounded measurement: `python tools/benchmark_preprocess_demand.py --root . --files 512 --batch-size 64 --query get_dynamic_token_budget` — 512 files / 3,880,289 bytes sampled, one query match; baseline reached useful context after 8 batches / 512 files, demand after 1 batch / 64 files. Both returned one evidence item and 1,608 context characters. Deterministic work-count difference: **7 batches / 448 files**. Both completed the full sample.
- This result is preliminary, not a performance or quality claim: timing is cache/order sensitive, and the bounded sample still includes `.superpowers` workflow material. A6 remains open until source-oriented representative queries and repeatable measurements are established. No model inference or GPU operation ran; GPU/runtime acceptance remains **NOT VERIFIED**.

### A4 — deterministic retrieval fallback verified; hardware gate remains open (2026-11-05)

- Current `src/local_ai_hub/reranker.py` SHA-256 `abc9653511a082bb93a00739e7d1b7b975de289d6917a988e25b14213d6d3883`: when CUDA admission is denied, the standalone reranker fails closed with `gpu_reserved` and no fabricated scores. The direct RAG route disables CPU rerank fallback and preserves baseline retrieval results if reranking cannot run.
- Existing regression cases in `tests/unit/test_rag_direct_cpu_bypass.py` SHA-256 `56115841ade1531c5746cfa70501e99ed047188d048346695a1c859409b1f309` cover GPU load and prediction failure; both assert no CPU rerank attempt in direct RAG and unchanged baseline result paths. `python -m pytest -q tests/unit/test_rag_direct_cpu_bypass.py --tb=short` passed **10 tests**.
- This verifies deterministic retrieval/fail-closed behavior under mocked failures only. It does not prove CUDA backend activation, GPU residency, GPU/CPU latency or quality, or runtime fallback on the installed hardware. A4 remains open for paired GPU/CPU benchmark evidence; no GPU inference was run.

### A6 — source-sample refinement and second measurement (2026-11-05)

- The benchmark exclusion set now also skips `.superpowers` and `.t03-sync-checks`, observed local workflow/validation trees that displaced source in the prior bounded sample. The existing regression fixture now contains all five generated directories; it confirms only the three intended source files enter its four-file cap.
- Focused test module: `python -m pytest -q tests/unit/test_preprocess_demand_priority.py --tb=short` — **8 passed**.
- New bounded run: `python tools/benchmark_preprocess_demand.py --root . --files 512 --batch-size 64 --query get_dynamic_token_budget` — 512 files / 8,152,460 bytes, two query-matching files. Baseline first useful context: 7 batches / 448 files, one evidence item / 710 chars. Demand: 1 batch / 64 files, three evidence items / 4,561 chars. Both completed all 512 files. Deterministic work-count difference: **6 batches / 384 files**.
- This supersedes the earlier 512-file measurement, which included `.superpowers` material. Evidence counts and context lengths differ between batches, so work saved is not a relevance or quality score. Single sequential timings remain cache/order sensitive; no repeated performance study or GPU/model run was performed. A6 remains open for broader representative repositories and paired quality evaluation; GPU/runtime acceptance remains **NOT VERIFIED**.

### A6 — source-only subtree measurement and malformed pack guard (2026-11-05)

- The checkout-root benchmark can include documentation that mentions its own query. A source-only run therefore used `--root src`, avoiding audit and local workflow files while retaining all 196 source files in that subtree.
- `python tools/benchmark_preprocess_demand.py --root src --files 512 --batch-size 16 --query get_dynamic_token_budget` — 196 files / 4,698,484 bytes; one matching source file. Baseline reached useful context after 8 batches / 128 files; demand after 1 batch / 16 files. Both returned one evidence item and 706 context characters. Work-count difference: **7 batches / 112 files**. Both completed all 196 files. Timing remains advisory and order/cache sensitive.
- Added a malformed `context_pack_paths` regression: a non-dict result must stay unverified and must not crash or claim work saved. The failure-first run reproduced `AttributeError`; after a type guard, `python -m pytest -q tests/unit/test_preprocess_demand_priority.py --tb=short` passed **9 tests**.
- This source-subtree measurement is stronger for the named code path but does not represent every repository workload or establish relevance/quality gains. A6 remains open for additional representative query cases and quality/depth policy. No GPU/model inference ran; GPU/runtime acceptance remains **NOT VERIFIED**.

### A6 — three-query source-subtree comparison (2026-11-05)

- Three bounded runs used the same complete `src` subtree (196 files, batch size 16), deterministic context packing, and no model/GPU. Results show demand benefit depends on query placement/popularity:
  - `get_dynamic_token_budget` (1 matching file): baseline useful context at 8 batches / 128 files; demand at 1 / 16; **112 files / 7 batches saved**. Both produced one evidence item and 706 context chars.
  - `hot_queries` (2 matching files): baseline at 5 / 80; demand at 1 / 16; **64 files / 4 batches saved**. Baseline returned one item / 508 chars; demand returned four / 2,122. Different payload sizes are not a quality score.
  - `ExternalGpuReservationStore` (69 lexical matches): both reached useful context at batch 1 / 16; **0 work saved**. Evidence counts were 3 vs. 10, so content size is not directly comparable.
- All successful cases completed the full 196-file sample. Two exploratory terms did not occur in that sample and produced no measurement; they are excluded from the comparison.
- The focused suite remains **9 passed**. A6 confirms freshness/invalidation and starvation tests exist in that suite, while broader repositories and paired quality/depth evaluation remain open. The operator confirmed scheduling-only; no deeper-analysis behavior was added. GPU/runtime acceptance remains **NOT VERIFIED**.

### A6 — explicit analysis-depth decision and current runtime gate (2026-11-05)

- Decision: this A6 work remains scheduling-only. Frequently used paths should reach useful deterministic context sooner; they do not receive deeper analysis or extra model work. The audit and current accepted behavior define no depth metric, quality rubric, or resource budget for such work. Any future depth expansion needs a separate requirement and paired quality/resource evaluation.
- Current `local_ai_status` `req_eb5e5cd89035`: Hub/Ollama online, active model null, `gpu_admission_state=outcome_unknown`, VRAM unknown with sampling pending/stale. No live GPU qualification is authorized by this status; A3/A4/A5/A7 runtime gates remain open.

### A2 — current OpenCode future-candidate metadata rechecked (2026-11-05)

- Clean `src/local_ai_hub/opencode_hardware.py` SHA-256 `42b5faf2dc3f9c8e33e803c153f89b96e513a7c32cce2d662929c0f2800761ef` lists only Qwen 3.5 9B / Qwen Coder 7B for 12 GB, and Qwen 3.5 9B NVFP4 / Qwen Coder 7B / Qwen 3.5 4B NVFP4 for 16 GB. Its contract explicitly says capacity labels do not establish inference admission or benchmark results.
- `python -m pytest -q tests/test_opencode_hardware.py --tb=short` passed **8 tests**. This verifies advisory candidate logic only.
- Fresh status `req_eb5e5cd89035` has `active_model=null`, `gpu_admission_state=outcome_unknown`, and unknown/stale VRAM; it returned no installed-model inventory. Do not infer installed-model absence from null active model. Canonical INSTALL/UPDATE prompts and several related tests remain dirty under concurrent editors (`req_46df7a408caa`); they were left untouched. A2 remains open for current installed-tag evidence and prompt-section synchronization.

### A2 — canonical prompt route parity rechecked (2026-11-05)

- Fresh exact source slices show the route maps match: `docs/INSTALL_PROMPT.md` line 265 (file SHA-256 `10d43a0a3d666352956dc21f455daa370d7614c10ced94195138a055de9b1133`) and `docs/UPDATE_PROMPT.md` line 263 (SHA-256 `9b4a9c8faf06070da6e72ed45a57665c77c5c2eaa8739631cd7684ebae8b465e`). Both list the same role/profile mapping and state routes are not proof of installed models.
- A bounded exact-tag scan over both whole canonical prompt files found no `qwen3.5:4b-q4_K_M`, `gemma4:12b`, or `qwen2.5-coder:14b` references. This is scoped to those two files; it does not establish repository-wide absence or cover every advisory surface.
- Both prompt files remain dirty under concurrent editing (`req_6e1b84a69fe7`) and were read only. Installed-tag inventory is still unavailable (`active_model=null` is not an inventory). A2 remains partial pending installed-model evidence and final owner synchronization.

### Fresh runtime gate after resumed audit (2026-11-05)

- Current `local_ai_status` `req_35867bb5676e` reports Hub/Ollama online, `active_model=null`, `gpu_admission_state=outcome_unknown`, and VRAM telemetry unavailable with `sample_pending`/stale state. The response envelope was truncated, but these status fields were present. This is not installed-model inventory or runtime qualification.
- Do not infer GPU readiness or model absence, trigger inference, or release/reset reservation from this status. A3/A4/A5/A7 runtime acceptance remains **NOT VERIFIED** pending owner-authorized recovery and fresh live evidence.
- Later fresh status `req_208f89953e15` changed admission to `external_reservation`; Hub/Ollama remain online, `active_model=null`, VRAM telemetry remains `sample_pending`/stale. This supersedes the prior `outcome_unknown` snapshot as the current status, but does not identify reservation owner or prove runtime readiness. Preserve the reservation; A3/A4/A5/A7 remain **NOT VERIFIED**.

### A5 — fresh startup-diagnostics regression validation (2026-11-06)

- Current `src/local_ai_hub/llama_cpp_runtime.py` SHA-256 `78aa9dcafd38bb6246aaa93c0a738247540fb7f61eec7e0641bd00bf39ed6322`; current `tests/unit/test_llama_cpp_runtime_startup_diagnostics.py` SHA-256 `255c23f4bea5e7d98844e311cbc72428457de9a93a4ca89a813a417e6629e7ed`.
- `python -m pytest -q tests/unit/test_llama_cpp_runtime_startup_diagnostics.py --tb=short` — **2 passed in 0.47 s**. Mocked startup diagnostics only: no model load, inference, unload, CUDA residency, cancellation, or scheduler-release behavior was exercised. A5 runtime acceptance remains **NOT VERIFIED**.

### Fresh GPU admission status (2026-11-06)

- Subsequent `local_ai_status` `req_73a46c151212` reports `gpu_admission_state=outcome_unknown`, `active_model=null`, and VRAM telemetry `sample_pending`/stale. This conflicts with the immediately preceding `external_reservation` status `req_208f89953e15`; neither response identifies reservation owner or generation. A `gpu_reservation` extra-field request returned no reservation detail.
- Treat admission as **unknown** and fail closed. No GPU action, reservation release, or runtime acceptance claim. A3/A4/A5/A7 remain **NOT VERIFIED**.

### A2 — fresh exact-source catalog review (2026-11-06)

- `docs/MODEL_CAPABILITIES.md` SHA-256 `a7bafe23423082597e7955a560b21ea251477220f590d09086c364080927142e`, lines 28–48: the advisory table now lists `qwen3.5:4b-nvfp4`; the retired Q4 4B, Gemma 12B and Coder 14B tags are absent from this table. Its profile routing table keeps Qwen Coder 3B/7B and Qwen 3.5 9B.
- `src/local_ai_hub/prompt_contracts.py` SHA-256 `f56f374fe2a051a0f90da23cb1ee548f478177aad5bd9dd2cf83cc0da407efd4`, lines 26–62: the complete capability registry lists `qwen3.5:4b-nvfp4` and does not contain those retired tags.
- `src/local_ai_hub/opencode_hardware.py` SHA-256 `42b5faf2dc3f9c8e33e803c153f89b96e513a7c32cce2d662929c0f2800761ef`, lines 17–18: 12 GB/16 GB future candidates use the current 9B, Coder 7B and NVFP4 4B choices; the source labels these as candidates, not inference admission.
- After Hub adaptive context `req_e2f1be780535` failed terminally with stale source evidence, bounded native fallback `rg -n -F -e 'qwen3.5:4b-q4_K_M' -e 'gemma4:12b' -e 'qwen2.5-coder:14b' src/local_ai_hub/generator.py` exited **1** (no matches). Current file SHA-256 `8557102D14CA9F4A4BA37433AF2FADBCFB5D20C1A1CB78FE3062956FE2D63F`; file is clean. This verifies only the three exact strings in this one file, not generated artifacts or repository-wide absence. Canonical prompt owner synchronization and a fresh installed-tag inventory remain unverified; A2 remains partial.

### A4 — fresh deterministic retrieval fallback revalidation (2026-11-06)

- Current `src/local_ai_hub/reranker.py` SHA-256 `abc9653511a082bb93a00739e7d1b7b975de289d6917a988e25b14213d6d3883`; current `tests/unit/test_rag_direct_cpu_bypass.py` SHA-256 `56115841ade1531c5746cfa70501e99ed047188d048346695a1c859409b1f309`.
- `python -m pytest -q tests/unit/test_rag_direct_cpu_bypass.py --tb=short` — **10 passed in 1.64 s**. Mocked failure-path evidence confirms deterministic retrieval fallback only; no GPU backend, CUDA residency, quality or latency measurement. A4 remains open for paired GPU/CPU evaluation.

### A6 — fresh useful-context scheduling comparison (2026-11-06)

- Current benchmark SHA-256 `6e1bfec2f2627a6f59569d83dab43192849276dff8e09d9763ab4d3813ab85fd`, focused test SHA-256 `5dbd437a2c133bc241bb4059007db86c7a6328a4c48c59154be742c9d2fc9d07`, and shared preprocessor source SHA-256 `b4747b41ab1db92dd6a14facf6a393558972457424711e7154ca159aeadd1a9c`.
- Fresh run `python tools/benchmark_preprocess_demand.py --root src --files 512 --batch-size 16 --query get_dynamic_token_budget`: 196 source files / 4,699,348 bytes; one seeded learned-query match. Deterministic `context_pack_paths` returned one evidence item and 706 context characters in both modes; `useful_context_verified=true`.
- Baseline reached useful context at batch 8 / 128 processed files / 341.55 ms elapsed; demand priority at batch 1 / 16 files / 30.32 ms. Seeded workload difference: **7 batches / 112 files**. Both modes completed all 196 sampled files with zero unprocessed.
- This measures scheduling with a seeded query and nonempty deterministic context, not real user-history learning or semantic quality. One sequential run is cache/order sensitive; selection p95 was 0.67 ms baseline vs 2.23 ms demand. No model/GPU workload. Focused module `python -m pytest -q tests/unit/test_preprocess_demand_priority.py --tb=short` — **9 passed in 1.58 s**. Broader repositories and paired context-quality evaluation remain open; user decision remains scheduling-only.

### A2 — fresh canonical routing-map parity (2026-11-06)

- Read-only source slices show identical role maps in `docs/INSTALL_PROMPT.md` SHA-256 `10d43a0a3d666352956dc21f455daa370d7614c10ced94195138a055de9b1133`, lines 265–266, and `docs/UPDATE_PROMPT.md` SHA-256 `9b4a9c8faf06070da6e72ed45a57665c77c5c2eaa8739631cd7684ebae8b465e`, lines 263–264. Both map `background_code/fast_code/heavy_code/reasoning/general/vision` across the six profiles and state routes do not prove installation.
- Surrounding policy wording differs slightly, while the canonical route maps match. Both prompt files remain modified by a concurrent editor and were not changed. A2 remains partial pending owner synchronization and current installed-tag inventory.

### A2 — future-candidate regression revalidated (2026-11-06)

- Current `tests/test_opencode_future_stage.py` SHA-256 `6e2124f19f685d9ed5d8d536e82817906cd228d21014962a27591140c95d18bf`; it explicitly asserts all three retired tags are disjoint from 16 GB future candidates.
- `python -m pytest -q tests/test_opencode_future_stage.py -k retired_model_tags --tb=short` — **1 passed, 4 deselected in 0.24 s**. This validates candidate metadata only; installed-model inventory and inference admission remain separate and unverified.

### A6 — scheduling result repeatability check (2026-11-06)

- Repeated the same seeded, bounded command three times in separate Python processes: `python tools/benchmark_preprocess_demand.py --root src --files 512 --batch-size 16 --query get_dynamic_token_budget`.
- All three runs verified nonempty useful context and identical work counts: baseline reached it at batch 8 / 128 files; demand priority at batch 1 / 16 files. Each run therefore saved 7 batches / 112 files in this fixture, and both modes completed their sample.
- Baseline elapsed time ranged 332.49–381.98 ms; demand elapsed time ranged 29.25–30.79 ms. Selection p95 ranged 0.71–0.90 ms baseline and 1.91–2.14 ms demand. Timing remains a small, cache/order-sensitive synthetic scheduling measurement; it does not establish broad-repository performance or context-quality equivalence.
- This follows the user's A6 scope choice: scheduling only, with no deeper hot-file analysis. No model or GPU workload ran. Runtime changes in the shared checkout remain untouched.

### A6 — whole-repository scheduling sample (2026-11-06)

- Ran `python tools/benchmark_preprocess_demand.py --root . --files 512 --batch-size 16 --query get_dynamic_token_budget`; the bounded fixture sampled and completed 512 files.
- Baseline reached useful context at batch 25 / 400 files; demand priority reached it at batch 1 / 16 files, saving 24 batches / 384 files for this seeded query. Both modes produced verified nonempty deterministic context.
- Elapsed time was 3027.46 ms baseline and 83.49 ms demand; selection p95 was 1.52 ms and 2.20 ms respectively. One whole-repository run is preliminary and cache/order sensitive; it does not establish general latency or semantic context quality. No model/GPU workload ran.

### GPU readiness gate — fresh status (2026-11-06)

- `local_ai_status(detail="brief")` request `req_b4d7e204d5af`: Hub 5.1.3 and Ollama online; `active_model=null`, `gpu_admission_state=outcome_unknown`, `vram_pressure=unknown`; VRAM telemetry is unavailable with `sample_pending`, `sampling=true`, and `stale=true`.
- This status does not establish installed-model inventory, device residency, reservation owner, or safe admission. Keep A3/A4 GPU runs, A5 live load/infer/unload, and A7 model tool-use evaluation unverified until fresh reservation and VRAM evidence is available.

### A1 follow-up — metadata-write failure reports a false reservation (2026-11-06)

- Current `src/local_ai_hub/external_gpu_reservation.py` SHA-256 `24ed1f8cf11efafa23481b762222b31218d9787fea37e0c36adbb32cc8b5939a`: `reserve()` at lines 135–163 calls `_write_metadata(record)` but ignores its boolean result; `_write_metadata()` at lines 347–361 returns `False` for symlink or `OSError` failures instead of raising.
- Isolated, temporary-directory reproduction monkeypatched `_write_metadata` to return `False`: `reserve()` returned a lease while metadata was absent, `read()` returned no record, and the digest fence remained. This is fail-closed for admission, but the caller receives a reservation that cannot be read or safely released through the normal generation path.
- Fix required: treat a false metadata-write result as reservation failure and preserve the digest fence for explicit recovery; add a regression case. The active shared reservation source and lifecycle test are editor-owned, so this finding is recorded for the isolated implementation step rather than edited in the shared checkout.

### A1 — isolated fix candidate and regression proof (2026-11-06)

- Created managed worktree under the Codex worktree directory from `master`; current shared checkout was not changed. The bug is present in `master` source SHA-256 `cccc3ac286b4c140e4bcf49d9d990e7f969b7b515255823e4a1b1ce9c5f18789`.
- Added `test_reserve_returns_none_when_metadata_write_fails`: confirmed RED before the fix (`reserve()` returned a lease when `_write_metadata()` returned `False`). Minimal fix now returns `None` while leaving the digest fence in place for recovery.
- Worktree source SHA-256 `b7714552717647eebd8d153e894fcefb26bebe618022255125d8a59ae3eaa7be`; regression test SHA-256 `47d6415a1c0ca8d89f902293220adc127dada543584861ea6675cebd91fd45dc`.
- `python -m pytest -q tests/test_external_gpu_reservation_lifecycle.py --tb=short` — **31 passed in 0.77 s**. `git diff --check -- src/local_ai_hub/external_gpu_reservation.py tests/test_external_gpu_reservation_lifecycle.py` — clean. Candidate remains isolated; integration into the shared checkout awaits editor ownership release.
- Post-edit `local_ai_repo(action="impact")` request `req_4f7055c82d73` reports the changed code and test files, recommends the lifecycle module, and lists scheduler/HTTP server as likely dependents. The result labels its relationship method `scan-fallback`, so this is heuristic impact evidence, not exact Serena symbol proof. Semantic local review remains unavailable: current Hub status has no active model and reports external GPU reservation with stale VRAM telemetry.
- Shared-checkout recheck `local_ai_repo(action="git_status")` request `req_c23c5d1241df`: `master`, 31 modified paths, 0 staged, 1 untracked. The owned reservation source remains SHA-256 `24ed1f8cf11efafa23481b762222b31218d9787fea37e0c36adbb32cc8b5939a` and still ignores `_write_metadata()`'s false result. No release signal for the shared source/test paths; keep the candidate isolated.

### A2 — current model-catalog and canonical prompt recheck (2026-11-06)

- `docs/MODEL_CAPABILITIES.md` SHA-256 `a7bafe23423082597e7955a560b21ea251477220f590d09086c364080927142e`: the inspected table has the requested `qwen3.5:4b-nvfp4` candidate and no `qwen3.5:4b-q4_K_M`, `gemma4:12b`, or `qwen2.5-coder:14b` entries. It still has `qwen3.5:9b-q4_K_M` as a separate advisory candidate (line 37).
- Current `src/local_ai_hub/prompt_contracts.py` SHA-256 `f56f374fe2a051a0f90da23cb1ee548f478177aad5bd9dd2cf83cc0da407efd4` registry and `src/local_ai_hub/opencode_hardware.py` SHA-256 `42b5faf2dc3f9c8e33e803c153f89b96e513a7c32cce2d662929c0f2800761ef` future list use generic `qwen3.5:9b` / `qwen3.5:9b-nvfp4`; the inspected slices do not list `qwen3.5:9b-q4_K_M`.
- Canonical prompt role-map slices remain aligned: INSTALL SHA-256 `2e6f5a7771bfa13507750a81485fd7d70806bfc177f89939153880a6dbcea1dd` lines 265–266 and UPDATE SHA-256 `8a4f89204a3855b016bcbe39181fe89154d9d6f478f50cbd30390763eca14c19` lines 263–264. These slices route to generic `qwen3.5:9b` and do not establish installation or model quality.
- `qwen3.5:9b-q4_K_M` was not in the audit's explicit retired-tag set. Leave it classified as an unqualified advisory reference pending model-owner direction; do not treat it as an active route. Current status request `req_f4616bd6cfbf` has no active model, unknown VRAM, and `gpu_admission_state=preparing_model`, so installed-tag inventory remains unverified and A2 remains partial.

### A6 — user scope decision (2026-11-06)

- User selected **scheduling only** for deeper hot-file treatment. Keep A6 work on prioritization, queue progress, starvation/fairness, and scheduling latency. Do not expand this item into deeper content/model analysis of hot files.
- Existing synthetic measurements show hot-file scheduling moves selection from batch 8/128 files to batch 1/16 files on the seeded source runs, with the same 7 batches/112 files ultimately processed. The 512-file whole-repository sample selected the hot file in batch 1/16 versus baseline batch 25/400; it is a single cache-order-sensitive sample. These results are preliminary scheduler evidence only, not useful-context or model-quality evidence.
- A6 remains open for representative production scheduling/fairness evidence; no model inference or GPU claim follows from this decision.
- Repeated the bounded repository-sample scheduler benchmark three times from the isolated worktree with `python -B`; each run sampled and completed 1,991 files in 32 batches, with 0 unprocessed. Baseline selected the hot file at batch 28; demand priority selected it at batch 1. Baseline per-run median selection latency was 1.793/1.716/2.170 ms; demand was 2.383/2.303/3.022 ms. No model inference ran. This is a bounded local sample, with likely filesystem-cache effects across repetitions; it shows faster hot-file selection at a modestly higher selection cost, not representative production throughput or useful-context latency.
- Isolated scheduler source SHA-256 `0fecfdb68a1cd17eac4968933c7a1de640bc4b93327dd7b566f121de653e9473` caps preferred paths at `min(limit - 1, max(1, limit // 4))` and fills remaining slots from the regular ordered queue, leaving at least one regular slot when `limit >= 2`. Existing regression test SHA-256 `0b686102ac815e13a9671896773a40b254988472f33c89ff5da4b37d50d7dc8c` checks a regular file appears in the first demand batch and both modes process all 32 files in eight batches. Fresh focused run: `7 passed in 1.82 s`. This verifies bounded scheduler fairness in the fixture, not production-wide fairness.

### A1 — isolated candidate revalidation (2026-11-06)

- Current isolated source SHA-256 `b7714552717647eebd8d153e894fcefb26bebe618022255125d8a59ae3eaa7be` checks the metadata writer's boolean result and returns no lease on failure, leaving the digest fence for fail-closed recovery. Lifecycle test SHA-256 `258c6f969489f739fb16a9516183e6ebba5e764282303cd7e9fe579f61e5f773` covers no lease on false metadata write, retained digest fence, absent metadata, unreadable reservation, and retry after the digest-only fence expires.
- Revalidation: `python -B -m pytest -p no:cacheprovider -q tests/test_external_gpu_reservation_lifecycle.py --tb=short` — **32 passed in 0.78 s**; scoped `git diff --check` clean. Primary review of the exact working-tree diff confirms one production guard plus the two failure/recovery regressions. The indexed diff response omitted the newest test hunk; bounded native `git diff -- tests/test_external_gpu_reservation_lifecycle.py` confirmed the complete two-test addition. Impact request `req_b89041e98731` was heuristic fallback, not exact Serena proof.
- The candidate remains isolated. Shared checkout ownership for these source/test paths has not been released, so this is not an integration or runtime acceptance claim.
- Fresh shared-checkout source slice remains SHA-256 `24ed1f8cf11efafa23481b762222b31218d9787fea37e0c36adbb32cc8b5939a` and still ignores the metadata writer's boolean result at lines 160–170. The current lifecycle-test slice SHA-256 is `32b8c75d3a78773ae24124b1b30e591ea6320c1255513ba0cd82ed6c69771d8a`; lines 30–49 proceed directly to the legacy-fence test, with no A1 false-write regression at that insertion point. Keep the isolated candidate unapplied until explicit ownership release.

### Shared checkout and runtime recheck (2026-11-06)

- Fresh `local_ai_repo:git_status` request `req_1b5691cd90cf`: `master`, 31 modified paths, 0 staged, and one untracked test. This records a dirty shared checkout, not path ownership. No explicit editor release was received; keep shared source/test edits off limits.
- Fresh `local_ai_status` request `req_2b29038494a1`: Hub 5.1.3 and Ollama online, `active_model=null`, `gpu_admission_state=preparing_model`, `vram_pressure=unknown`, telemetry `sample_pending` and stale. This does not authorize model inference or establish GPU admission/capacity; A3–A5 and A7 runtime gates remain open.

### Read-only review — scheduler uncertainty and expiry order (2026-11-06)

- Current shared `src/local_ai_hub/scheduler.py` SHA-256 `f4af1ed1ae88f99c52e13a5a5903a33830e8648d1d39edea762c172af25f6046` moves `store.reap_expired()` / `store.read()` before `_internal_gpu_uncertain` returns fail-closed. The same source still makes `_claim_internal_gpu()` return `False` while uncertain, and delegates new internal admission to the atomic `ExternalGpuReservationStore.claim_internal()` path.
- The paired `test_unknown_internal_outcome_still_reaps_expired_external_fence` asserts expired digest cleanup while uncertainty continues to deny a new internal claim (`tests/test_opencode_gpu_reservation.py`, diff request `req_073d1f8f6b61`). Primary source review found the ordering consistent with the lease-expiry contract; this is not execution evidence. Shared-checkout tests were not run while editor-owned changes remain active.
- Reviewed scheduler diff SHA-256 `5e538325322e314975e03c63c3f4f0835e03d55d7b94b3a2a578e40a21be64cf`; no shared source edits made. Expiry-based stale-fence cleanup does not resolve live admission, startup-race or target-GPU qualification gates.
