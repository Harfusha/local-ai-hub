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
