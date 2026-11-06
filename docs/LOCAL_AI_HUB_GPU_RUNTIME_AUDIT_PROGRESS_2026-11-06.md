# Local AI Hub GPU/runtime audit progress — 2026-11-06

Continuation of [the main audit](LOCAL_AI_HUB_GPU_RUNTIME_AUDIT_2026-11-04.md) and [the 2026-11-05 progress note](LOCAL_AI_HUB_GPU_RUNTIME_AUDIT_PROGRESS_2026-11-05.md). This note records a fresh runtime diagnosis. It does not establish GPU acceptance.

## GPU admission — stale state remains unresolved

Fresh Hub status `req_aa70410552d5` reported version `5.1.3`, `active_model=null`, `gpu_admission_state=outcome_unknown`, and stale VRAM telemetry (`sample_pending`, `vram_pressure=unknown`). GPU reservation status `req_916e51675f5a` reported `reservation_present=false`, `state=free`, and no manual intervention requirement.

With the user's authorization to remediate the GPU/runtime audit, the authorized reservation recovery action ran once (`req_085be750525d`, `mutation_applied=true`). A single status check afterward (`req_18a986542398`) still reported `gpu_admission_state=outcome_unknown`. Do not repeat the release action: the external reservation is already absent, and the recovery marker did not clear the reported scheduler state.

### Source diagnosis

Current checkout `src/local_ai_hub/scheduler.py` (SHA-256 `f4af1ed1ae88f99c52e13a5a5903a33830e8648d1d39edea762c172af25f6046`) sets `_internal_gpu_uncertain=True` after an executed operation has an uncertain or qualifying failed outcome. `status()` gives that internal latch precedence over external reservation state and reports `outcome_unknown`. The inspected constructor initializes the latch to false. This makes internal uncertainty a plausible explanation for the live status; status output does not expose the latch, so the exact runtime cause remains unconfirmed.

Current checkout `src/local_ai_hub/mcp_server.py` (SHA-256 `0f5bbcb3ba7b41e1517cb74813277ffc620b1da0f8201f660998aa824cf8b5a8`) handles external reservation status and consented generation release in the inspected coordination branch. The installed MCP surface also exposed an authorized recovery action. Source/runtime parity for that action is not verified.

### Boundary and next action

The scheduler and MCP server are editor-modified paths. No code edit, restart, model unload, or GPU workload was started. Reconcile the internal unknown outcome using the owning operation's authoritative lifecycle evidence; if none exists, the runtime owner must recover the Hub process under its normal release boundary. Keep model-load, concurrency, VRAM, embeddings, and reranker acceptance **NOT VERIFIED** while telemetry is stale.

## Checkout ownership

At `req_8b9341e69b0a`, the checkout had 41 modified tracked paths and one untracked test file. Shared audit, scheduler, hardware, reservation, model lifecycle, reranker, and test paths remain editor-owned. This note is a new disjoint continuation; the existing audit files were not changed.

## A4 — Preserve reranker failure detail with deterministic fallback

Source review found that `reranker_failed` was handled by an `elif` after `heuristic_fallback`. A failed CUDA reranker always selects the heuristic fallback, so the `reranker` failure marker was unreachable. Responses reported `heuristic_rerank` but lost the backend failure detail.

Changed `src/local_ai_hub/rag.py` to record both markers, preserving `fallback="heuristic_rerank"` as the primary compatibility field. Added `tests/test_rag_quality_contract.py::test_cuda_reranker_failure_is_reported_with_deterministic_fallback`; it asserts results remain available, both fallback markers are present, and the primary fallback stays unchanged.

TDD evidence: the new test first failed because `reranker` was absent from `fallbacks`; after the minimal change it passed. Full focused module: `python -m pytest -q tests/test_rag_quality_contract.py --tb=short` — 19 passed, 1 skipped. The skip is the existing opt-in latency/memory benchmark (`RAG_BENCHMARK=1`). Scoped `git diff --check` passed. No CUDA model was loaded; this verifies failure reporting and deterministic fallback only, not GPU execution or relevance quality.

Local semantic diff review was unavailable: `local_ai_repo:review_diff` returned terminal `gpu_outcome_unknown` (`req_5e3baf8f0d8c`). The primary agent reviewed the bounded source change and focused regression test directly.

Latest Hub status `req_06847fd2f973` reported `gpu_admission_state=unknown`, degraded scheduler and Ollama profile probes (`probe_timeout`), and stale VRAM telemetry. External reservation remains free (`req_8a28135694bd`). Runtime capacity, load/switch/unload, embeddings/reranker GPU execution and quality remain **NOT VERIFIED**.

## A1 — Current scoped whitespace check

The main audit records a trailing blank line in `tests/test_external_gpu_reservation_lifecycle.py` for the then-audited commit comparison. Fresh `git diff --check -- tests/test_external_gpu_reservation_lifecycle.py` now passes on the current worktree. This checks only that file's current diff; no reservation tests were rerun, and the file remains editor-owned. Keep the historical commit result and current worktree result distinct.

## A2 — Current future-profile candidates

Current `src/local_ai_hub/opencode_hardware.py` (SHA-256 `42b5faf2dc3f9c8e33e803c153f89b96e513a7c32cce2d662929c0f2800761ef`) lists `qwen3.5:9b` and `qwen2.5-coder:7b` for `12gb`; `16gb` lists `qwen3.5:9b-nvfp4`, `qwen2.5-coder:7b`, and `qwen3.5:4b-nvfp4`. The module explicitly treats these as capacity hints, not inference approval or benchmark evidence. Latest `local_ai_status` reports `active_model=null`; it does not provide an installed-model inventory. Stale-reference scan and current installed-tag confirmation remain open.

## A2/A6 — Follow-up source review

Fresh checkout status `req_a8526c7b081a` reports 43 modified tracked paths and two untracked paths. The main audit, model-policy/configuration files, scheduler, reservation, llama.cpp, reranker and most related tests are shared editor-owned changes; this pass made no overlapping source edits.

The complete 75-line `opencode_hardware.py` source was inspected in bounded slices at SHA-256 `42b5faf2dc3f9c8e33e803c153f89b96e513a7c32cce2d662929c0f2800761ef`. Its future-profile candidate tuples are the current lists above; the retired `qwen3.5:4b-q4_K_M` tag is not in this module. An indexed exact-tag search reports 16 current-source matches, including historical audit/evaluation evidence and retired-tag regression assertions. Paginated results did not establish complete repository-wide coverage. A2 therefore remains open for an exhaustive active/advisory-reference sweep and a current installed-tag snapshot. Current status `req_f54a882f3a22` has `active_model=null`, so it cannot provide that inventory.

Later exact-tag searches `req_af821a92a436` and `req_838a5a3394a8` reported 17 Q4-tag matches and 16 Gemma matches. Both had `path_hint_usage.fallback_used=true`, and returned historical audit/progress evidence first; these counts do not prove whether active/advisory paths still contain stale references. Do not infer closure from the incomplete index search.

For A6, the user chose scheduling-only prioritization. Current `preprocess.py` (SHA-256 `0fecfdb68a1cd17eac4968933c7a1de640bc4b93327dd7b566f121de653e9473`) bounds learned lookup to four hot queries and caches against query/index state. `_find_next_files()` gives preferred paths at most `min(limit - 1, max(1, limit // 4))` slots, then fills from regular candidates and caps at `limit` (source lines 3697–3808). This preserves regular scheduling slots; no deeper analysis was added. No source fix is justified by this review. A6 still needs representative hot/cold scheduling measurements and freshness/starvation evidence.

Current GPU reservation status `req_3237f22376e0` is free, while Hub status `req_f54a882f3a22` still reports `gpu_admission_state=outcome_unknown`, `vram_pressure=unknown`, and stale `sample_pending` telemetry. Local semantic review was unavailable: `local_ai_repo:solve` returned terminal `outcome_unknown` (`req_09a4692bae0b`). Runtime acceptance remains **NOT VERIFIED**.

## Fresh runtime check

The next bounded status check `req_1cd790a0e9d8` still reports `gpu_admission_state=outcome_unknown`, `active_model=null`, unknown VRAM pressure and stale `sample_pending` telemetry; `preprocessing.stats` also timed out. Reservation status `req_c64a88ac79b0` remains free. No release, restart, model load or GPU workload was repeated.

## A2 — Complete indexed reference sweep

The Hub current-source lexical searches were paginated using each returned `next_offset`: `qwen3.5:4b-q4_K_M` returned 17 matches (`req_af821a92a436`, `req_d39a385dfdc3`, `req_8bca9bd68f6a`, `req_c56c1fef062c`, `req_d1066657dd2a`); `gemma4:12b` returned 16 (`req_838a5a3394a8`, `req_7f347e4a79d4`, `req_855c206edc08`, `req_e50a74eca4c6`, `req_ddbfdd952e23`); `qwen2.5-coder:14b` returned 18 (`req_ef29e11ef543`, `req_6b6cb4771fad`, `req_f51c9ea6f3d1`, `req_3e6bf043e5bc`, `req_2ed49c2682c7`, `req_52642a9fb61b`). The returned paths were audit/progress/history, dated plans/specifications, or tests. No hit was in either canonical prompt, `MODEL_CAPABILITIES.md`, `prompt_contracts.py`, generated guidance in `generator.py`, or `opencode_hardware.py`. The indexed sources therefore show no remaining active recommendation/candidate reference in those paths. `docs/superpowers/plans/2026-11-02-blackwell-fp4-high-profile.md` explicitly records all three tags as retired from current recommendations; its editor-owned changes were left untouched. `tests/test_opencode_model_names.py` retains Coder 14B as an arbitrary valid installed tag for name validation, not as a recommendation.

The search tool reported `index_state=current_sources` and exact match counts, but path hints fell back; this closes the scan only against the Hub's indexed source corpus. Current installed-tag inventory and live GPU qualification remain open.

The clean, disjoint `tests/test_opencode_future_stage.py` passed on the current worktree: `python -m pytest -q tests/test_opencode_future_stage.py --tb=short` — 5 passed in 0.40s. This verifies that future-profile candidates exclude the three retired recommendation tags and remain explicitly unverified; it does not establish current installed inventory or runtime eligibility.

## A1/runtime — fail-closed admission persists

Fresh status `req_5faf66f4bb72` reports `gpu_admission_state=outcome_unknown`, `active_model=null`, and `vram_telemetry.stale=true` with `error=sample_pending`. Its top-level `vram_pressure=nominal` is not a fresh VRAM sample and must not be used as capacity evidence. Reservation status `req_a8b998bddf2d` remains free.

Current scheduler source SHA-256 `f4af1ed1ae88f99c52e13a5a5903a33830e8648d1d39edea762c172af25f6046` rejects both `submit()` and `admit()` while `_internal_gpu_uncertain` is set (lines 795–797 and 985–987), retaining the fail-closed outcome. The regression path in `tests/test_mixed_scheduler_integration.py` drives an unknown preparation result and asserts the latch and external exclusion. Scheduler and test files remain editor-owned; this turn made no edits or lifecycle action. Runtime recovery and GPU acceptance remain **NOT VERIFIED**.

The newest status `req_9f4165aa4a95` returned `vram_pressure=unknown` again, with `stale=true` and `sample_pending`; the prior `nominal` value was also attached to a stale sample. Reservation `req_a5057034e750` remains free. No current VRAM pressure or GPU capacity is established.

## A3 — stale telemetry fallback source check

Clean `src/local_ai_hub/vram_balancer.py` (SHA-256 `f22621c5ce89acd1a0cade0883e9b819e2222d969f838553593bb0b87ed7452d`) intentionally exposes a recent last-valid pressure only with `telemetry_stale=true` and `telemetry_error=sample_pending` while its bounded refresh is pending (lines 115–128). Timeout fallback changes pressure to `unknown`, caps context factor at 0.25 and enables background throttling (lines 134–180). The MCP status projection keeps `vram_pressure` separate from explicit telemetry freshness fields.

Two clean CPU-only stale-probe tests passed: `python -m pytest -q tests/test_vram_balancer.py::test_status_wait_timeout_returns_conservative_unavailable_without_second_sampler tests/unit/test_vram_balancer_non_blocking.py::test_status_returns_while_gpu_probe_is_blocked_and_coalesces_callers --tb=short` — 2 passed in 0.52s. This supports the fail-closed timeout path and nonblocking sampling; it is not GPU/capacity evidence. No source fix is indicated in this clean module. A3's real workload, residency, latency and concurrency qualification remains open.

## A5/A7 — live model qualification remains gated

The main audit requires a llama.cpp `load → inference → unload → different-model load` lifecycle with cancellation, failure fallback, reservation release, and measured VRAM release (A5). A7 requires labeled tool-use cases with measured model/provider identity, valid-call rate, grounded result use, recovery, latency, and VRAM. Neither requirement can be closed from source or mocked tests.

Fresh Hub evidence on 2026-11-06: status `req_5981d0283962` reports `gpu_admission_state=outcome_unknown`, `vram_pressure=unknown`, and stale `sample_pending` telemetry; reservation status `req_a1fe674cb6fc` is free. This does not qualify a model workload. The llama.cpp implementation and lifecycle tests are editor-modified (`req_bb4da130676a`, `req_b250e454bfe4`); no changes were made to either. Do not start load/inference/unload or model-quality runs until admission has a resolved, fresh state and the owner authorizes runtime qualification. Keep A5 and A7 **NOT VERIFIED**; resume with the plan's labeled cases and capture actual backend/model identity, tool outcomes, GPU residency/VRAM, latency, cleanup, and scheduler reservation release.

## A1 — keep expiry cleanup active under GPU uncertainty

Read-only review of the editor-owned `src/local_ai_hub/scheduler.py` change (`req_853b872c9814` failed terminally with `gpu_outcome_unknown`; bounded native `git diff --unified=24` was then used) found the uncertainty latch moved after `ExternalGpuReservationStore.reap_expired()` and `read()`. This preserves fail-closed admission (`_external_gpu_reserved()` still returns true) while allowing expired external state to be cleaned up. The scheduler source remains editor-modified; no production code was changed here.

Added a disjoint CPU-only regression in `tests/test_scheduler_unknown_gpu_reaps_expired_external_reservation.py` (SHA-256 `995407d573f7d0b316e957742bd949b96f4d732402f7b4a63fbaaf8c7090308a`). It uses the real temporary reservation store with an expired digest-only fence and asserts both that admission stays reserved and that expiry cleanup removes the fence. `python -m pytest -q tests/test_scheduler_unknown_gpu_reaps_expired_external_reservation.py --tb=short` — 1 passed in 0.29s. Local `solve`/semantic review was unavailable (`req_dcdf79af3e51`, GPU outcome unknown); source and behavior were checked directly. No model workload ran.

Companion integration validation: `python -m pytest -q tests/test_mixed_scheduler_integration.py --tb=short` — 16 passed in 59.59s. It exercised scheduler/fallback behavior against the test HTTP backend only; no live model, GPU residency, or VRAM conclusion follows.

## A2 — future-candidate guard verified

The clean `src/local_ai_hub/opencode_hardware.py` (`42b5faf2dc3f9c8e33e803c153f89b96e513a7c32cce2d662929c0f2800761ef`) lists only `qwen3.5:9b-nvfp4`, `qwen2.5-coder:7b`, and `qwen3.5:4b-nvfp4` for the 16 GB future profile. The clean `tests/test_opencode_future_stage.py` (`b9ad13c29abb2af410adbbded5352716c4394e0e2ee61bd15df4b91322b196ba`) includes a behavioral assertion that the retired Qwen Q4, Gemma 12B, and Coder 14B tags are disjoint from those candidates. Fresh targeted validation: `python -m pytest -q tests/test_opencode_future_stage.py --tb=short` — 5 passed in 0.39s. This closes the tested future-candidate list only; it does not prove installed tags, runtime readiness, or A3/A5/A7 qualification.

## Runtime recheck — GPU uncertainty persists

At 2026-11-06 16:17 UTC, Hub status `req_6d87c1675092` still reports Hub/Ollama online, `active_model=null`, `gpu_admission_state=outcome_unknown`, `vram_pressure=unknown`, and stale telemetry `error=sample_pending`. External reservation status `req_118679bcf3ed` is `free`. The free cross-process marker does not clear or explain the internal unknown outcome; cause remains unproven. `scheduler.py` is still editor-modified. No restart, model load, or admission reset was attempted.

## A3 — `sample_pending` source diagnosis

Clean `src/local_ai_hub/vram_balancer.py` (`f22621c5ce89acd1a0cade0883e9b819e2222d969f838553593bb0b87ed7452d`) shows the nonblocking `status(force=False)` path returns `sample_pending` while the daemon sampler remains active; without a recent valid sample, its payload is conservative (`available=false`, `pressure_level=unknown`). `telemetry_wait_timed_out=false` is expected there because that call did not wait. The sampler clears its active flag in `finally` after the provider returns.

Editor-modified `src/local_ai_hub/gpu_monitor.py` (`b9da23798d2caa1f9bad6bed52a9aebb952a7c538a91199852061f84ec389616`) currently bounds `nvidia-smi` and `rocm-smi` calls to 2 seconds, its Windows PowerShell sample to 4 seconds, and skips optional OpenVINO discovery in the telemetry fallback. This source review does not identify which provider the installed process is waiting on, or why the sampler has not completed. No telemetry code was changed; A3 remains **NOT VERIFIED** for real-time VRAM, residency, latency, and concurrency.

## A6 — Scheduling-only evidence (2026-11-06)

- Scope follows the operator choice: scheduling only; no deeper usefulness/context-quality analysis.
- Clean `src/local_ai_hub/preprocess.py` (`SHA-256 0fecfdb68a1cd17eac4968933c7a1de640bc4b93327dd7b566f121de653e9473`) applies learned query priority in `_step_rag` before choosing pending files. It still filters to files needing RAG indexing and uses the ordinary ordering for remaining candidates.
- Editor-owned `tests/unit/test_preprocess_demand_priority.py` (`SHA-256 80f4188816d46e142eee4c3eab1f9c7b7ffed92dcd8f06450d577a7d8bf19bd1`) covers mixed hot/regular selection, search-recorded demand reaching preprocessing, and a deterministic demand benchmark. The benchmark assertions require both baseline and demand runs to finish all 32 files in 8 batches with zero unprocessed files; demand schedules a hot file in batch 1 while retaining at least one regular file in that batch.
- Editor-owned `tools/benchmark_preprocess_demand.py` (`SHA-256 09e944a0399ef9d53d799c358f72f6b40c83080ba1e080034ddcce0e947f25fd`) explicitly measures queue selection plus simulated completion, without model inference. Its repository mode samples bounded text files and records the query/sample metadata. `useful_context_verified=false` is correctly explicit.
- Audit result: scheduling correctness has source-level coverage. No production defect justified an edit in this slice. No benchmark was executed in this turn; do not claim measured throughput, latency, quality, GPU residency, or end-to-end runtime acceptance. A6 remains NOT VERIFIED for live performance/runtime.
## Fresh live gate (2026-11-06)

- `local_ai_status` request `req_eb497518553c`: Hub and Ollama online, `active_model=null`, `gpu_admission_state=outcome_unknown`, `vram_pressure=unknown`; telemetry unavailable with `sample_pending`, `sampling=true`, `stale=true`.
- `gpu_reservation_status` request `req_41cf953c2267`: external reservation absent and state `free`. This does not clear or explain internal GPU admission `outcome_unknown`.
- Therefore no live model load, inference, unload, GPU benchmark, or service restart was run. A3/A4/A5/A7 runtime and quality acceptance remain **NOT VERIFIED**. Next safe step is source-only work or wait for an authorized/healthy runtime state; never treat external reservation `free` as proof of GPU availability.
## A2 — Current source and focused validation (2026-11-06)

- Current clean `src/local_ai_hub/opencode_hardware.py` (`SHA-256 42b5faf2dc3f9c8e33e803c153f89b96e513a7c32cce2d662929c0f2800761ef`) stages 16 GB candidates `qwen3.5:9b-nvfp4`, `qwen2.5-coder:7b`, `qwen3.5:4b-nvfp4`; it explicitly labels them as staging candidates, not GPU admission or inference proof.
- Current clean `src/local_ai_hub/prompt_contracts.py` (`SHA-256 f56f374fe2a051a0f90da23cb1ee548f478177aad5bd9dd2cf83cc0da407efd`) contains the `qwen3.5:4b-nvfp4` advisory entry and preserves restrictions against architecture/security decisions, risky migrations, edits and final verification. The supported-model test excludes `qwen3.5:4b-q4_K_M`, `gemma4:12b`, and `qwen2.5-coder:14b`; future-profile and packaged-default tests exclude the same tags from recommendations/defaults.
- Exact paginated current-source searches completed for all three retired tags: Q4 (18 results), Gemma (17), Coder 14B (19). Remaining hits are audit/progress records, dated evaluation/planning history, and tests/fixtures. No hit was in either canonical prompt or the active model registry/default/future-candidate source. `qwen2.5-coder:14b` also appears in a generic model-name test and a restricted fallback-capability test; neither configures or recommends that tag.
- Canonical prompt snapshots: `docs/INSTALL_PROMPT.md` SHA-256 `431476997f2c8be22956f7d2c5fa7bfbf28cf386c5a5d3fe09786d301432fb78`; `docs/UPDATE_PROMPT.md` SHA-256 `c1e3ed56f476c7552979f1c64972b3d29675674f092cb6c81b1eb2603a04461d`. Exact retired-tag search found no prompt hits. Both files are clean in the current Git status.
- Fresh focused validation: `python -m pytest -q tests/test_prompt_contracts.py tests/test_opencode_future_stage.py tests/test_opencode_model_names.py tests/test_release_defaults_consistency.py --tb=short` — **24 passed in 1.80s**.
- A2 source/config recommendation correction is verified in this checkout; no duplicate edit was needed. Current installed-model inventory is still unavailable: `active_model=null` does not prove that no models are installed, so installed-tag confirmation and any live GPU claim remain **NOT VERIFIED**.
## A3 — Fresh live-state update (2026-11-06)

- `local_ai_status` request `req_a40fff228da3` now reports Hub/Ollama online, `active_model=qwen3.5:4b-nvfp4`, and `gpu_admission_state=available`. It still reports `vram_pressure=unknown`, `context_budget_factor=0.25`, and VRAM telemetry `sample_pending`/`sampling=true`/`stale=true`.
- `gpu_reservation_status` request `req_e979150892a4` reports no external reservation and `state=free`. This does not establish free VRAM or settle the pending telemetry sample.
- This supersedes the earlier `outcome_unknown` snapshot as current admission state, while preserving its history. I did not start a benchmark or switch/unload the active model. A3/A4/A5/A7 live performance, residency, and quality gates remain **NOT VERIFIED**; no configuration limit is changed without paired hardware evidence.
## A3 — Current telemetry and ownership check (2026-11-06)

- Fresh `local_ai_status` request `req_abaa528e09eb` reports Hub/Ollama online, `active_model=null`, `gpu_admission_state=available`, `vram_pressure=unknown`, and `context_budget_factor=0.25`. Telemetry remains `sample_pending`, `sampling=true`, `stale=true`, and `wait_timed_out=false`.
- Fresh `gpu_reservation_status` request `req_acbec7d088ea` reports `reservation_present=false` and `state=free`. This does not prove VRAM availability or clear the pending telemetry sample.
- Current clean `src/local_ai_hub/vram_balancer.py` SHA-256 `f22621c5ce89acd1a0cade0883e9b819e2222d969f838553593bb0b87ed7452d` starts one daemon sampler and runs `get_gpu_telemetry()` outside its state lock. A timed-out status remains fail-closed. Current source evidence does not justify changing admission behavior or adding duplicate probes.
- `get_gpu_telemetry()` in editor-modified `src/local_ai_hub/gpu_monitor.py` SHA-256 `b9da23798d2caa1f9bad6bed52a9aebb952a7c538a91199852061f84ec389616` calls vendor probes while holding `_GPU_LOCK`; this was read only. The editor owns that file and related GPU/runtime paths, so no edits were made there.
- Fresh `local_ai_repo:git_status` request `req_f2cfde362cc7` still reports 43 modified tracked paths and 3 untracked paths. This progress note remains our only owned path. No benchmark, model load/switch/unload, restart, or test run was performed.
- A3/A4/A5/A7 runtime, residency, performance, and quality acceptance remain **NOT VERIFIED**. Next safe step: wait for editor release or obtain a fresh completed telemetry sample before selecting a runtime validation gate. Do not change VRAM/context/concurrency limits without paired target-hardware evidence.

## A3 — Probe timeout check (2026-11-06)

- Current editor-owned `src/local_ai_hub/gpu_monitor.py` SHA-256 `b9da23798d2caa1f9bad6bed52a9aebb952a7c538a91199852061f84ec389616` bounds the `nvidia-smi` subprocess with `timeout=2.0` (`_nvidia_live`, lines 135–148). The status `sample_pending` alone therefore does not prove an unbounded probe or stuck sampler.
- The indexed search page for a broader probe-timeout query failed terminally with HTTP 413; the exact source slice above succeeded. No wider scan or duplicate telemetry request followed.
- No sampler/admission code change is justified by current evidence. Preserve single-worker behavior and fail-closed pressure until a completed sample or a concrete timeout failure is recorded.

## A1 — Read-only diff review attempt (2026-11-06)

- `local_ai_repo(action="review_diff", path="src/local_ai_hub/external_gpu_reservation.py")` request `req_40a00294216e` failed before review: `local_backend_transport` / `QueueFullError`; both `qwen3.5:4b-nvfp4` and `qwen3.5:9b-nvfp4` were rejected for `insufficient VRAM`, with `last_admission_reason=vram_budget` and `last_admission_state=rejected`.
- This is local review-model admission evidence, not a hardware benchmark or proof of general GPU capacity. I did not retry inference or use native diff fallback because the Hub result was retryable, not terminal.
- A1 editor-owned source and tests remain unchanged by this review attempt. Primary diff review and integration remain open until bounded deterministic evidence or model admission becomes available.

## A1 — Static recovery-path inspection (2026-11-06)

- Current editor-owned `src/local_ai_hub/external_gpu_reservation.py` SHA-256 `1068d0770a5f9cce43ebd9f38cfa1479b0310a70112283cb4e23fe8bef4fd2ad` contains a metadata-only orphan recovery path in `release_with_consent` (lines 200–228). It rejects any remaining or symlinked digest fence, requires the exact generation and explicit consent, then requires expiry or confirmed owner-process death before cleanup.
- `_remove_unlocked` still removes the digest before metadata (lines 320–339); the recovery path appears to address that failure window. This bounded source inspection is not a full diff review and does not refresh the earlier 12-test receipt. A1 remains pending primary diff review and current focused validation.

## Fresh runtime state after goal resume (2026-11-06)

- `local_ai_status` request `req_ceeefc2c2834` reports `vram_pressure=nominal` and telemetry `available=true`, with `active_model=null` and `gpu_admission_state=preparing_model`.
- `gpu_reservation_status` request `req_31c4ee165afb` reports no external reservation and `state=free`.
- This supersedes the prior `sample_pending` telemetry snapshot, but `preparing_model` is not an available admission state and `active_model=null` does not prove the candidate model is ready. No benchmark, inference, model lifecycle operation, or competing review-model request was started.

## Review retry and Hub transport state (2026-11-06)

- At turn start, `local_ai_status` request `req_7b2687fe42cd` reported `active_model=qwen3.5:4b-nvfp4`, `gpu_admission_state=available`, `vram_pressure=unknown`, and telemetry `sample_pending`/`sampling=true`/`stale=true`. `gpu_reservation_status` request `req_0027d95c88f7` reported `state=free`.
- Narrow A1 `review_diff` request `req_e2b6e1dce00c` was rejected because the requested response budget was too small. The explicit larger-budget attempt and the single health check then both failed with HTTP transport errors to `http://127.0.0.1:11436/mcp` and returned no terminal/retryability receipt.
- No further review retry, native fallback, test, benchmark, model operation, or source edit was performed. The active checkout still has 43 modified tracked paths and 3 untracked paths (`local_ai_repo:git_status` request `req_e213b28ee66a`).

## A1 — Review follow-up with full guard context (2026-11-06)

- Narrow `review_diff` request `req_d52df5b1ad05` admitted `qwen3.5:4b-nvfp4` with nominal pressure and reviewed the complete single-file diff. Its semantic result is explicitly advisory/unverified (`review_consistency.status=unverified`, `semantic_truth_verified=false`) and raised uncertainty about removing `not metadata_orphan` from the owner-death predicate.
- Bounded inspection of `release_with_consent` (`src/local_ai_hub/external_gpu_reservation.py`, SHA-256 `1068d0770a5f9cce43ebd9f38cfa1479b0310a70112283cb4e23fe8bef4fd2ad`, lines 200–244) resolves that concern: the unchanged exact-generation check still applies; cleanup proceeds only when the record expired or `_owner_process_is_gone()` confirms owner death. The orphan branch also rejects any extant or symlinked digest fence and removes metadata only after audit append succeeds. This matches the documented release contract.
- Primary review manually checked the full guard context and deterministic diff against the consent/expiry/dead-owner contract. Fresh focused tests pass; semantic model output remains advisory and unverified. No editor-owned file was changed.

## A1 — Fresh focused validation (2026-11-06)

- Ran `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_external_gpu_reservation_lifecycle.py tests/test_opencode_gpu_reservation.py --tb=short` from the authoritative worktree. Result: **93 passed in 6.50s**, exit code 0.
- This is focused source/test evidence for the current dirty checkout, not GPU/runtime acceptance. It supplements the source guard inspection and advisory diff review; it does not refresh A3/A4/A5/A7 hardware gates.

## A1 and A6 focused checks (2026-11-06)

- A1: `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_external_gpu_reservation_lifecycle.py tests/test_opencode_gpu_reservation.py --tb=short` — **93 passed in 6.50s**, exit code 0.
- A6 (user selected scheduling-only scope): `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/unit/test_preprocess_demand_priority.py tests/unit/test_learning_hot_query_cache.py --tb=short` — **11 passed in 3.48s**, exit code 0.
- Narrow `review_diff` for `src/local_ai_hub/learning.py` request `req_bd2d153b7906` returned terminal `outcome_unknown=true`, `error_code=gpu_outcome_unknown`; Hub reported a previous inference outcome unknown and reservation retained. I did not repeat or release it.
- One `gpu_reservation_status` check `req_940099d31a86` reports no external reservation and `state=free`. This does not resolve internal GPU outcome uncertainty; no more GPU/model work was started.
- These tests validate the current dirty source/test snapshot. They do not establish A3/A4/A5/A7 runtime acceptance or replace review of the full integrated diff.

## A6 — Scheduling-only source inspection and current GPU state (2026-11-06)

- Current `src/local_ai_hub/preprocess.py` SHA-256 `0fecfdb68a1cd17eac4968933c7a1de640bc4b93327dd7b566f121de653e9473` bounds learned demand to four queries, caches by root/query/index signature for 15 seconds, and caps preferred files at one quarter of a batch. Remaining capacity is filled from the ordinary structural priority queue. This matches the user's scheduling-only choice; no deeper analysis path was added.
- Targeted A6 tests remain **11 passed** (see focused validation above). This source inspection does not measure time-to-useful-context, work saved, or freshness under a representative repository.
- Fresh `local_ai_status` request `req_69504b534eb5` reports `active_model=null`, `gpu_admission_state=outcome_unknown`, `vram_pressure=unknown`, and telemetry `sample_pending`/`sampling=true`/`stale=true`. `gpu_reservation_status` request `req_1987b9c30604` reports external reservation `free`; this does not clear internal admission uncertainty.
- No model review, benchmark, lifecycle operation, reservation release, or runtime acceptance was attempted after this state.

## A1 — Test coverage review (2026-11-06)

- Current `tests/test_external_gpu_reservation_lifecycle.py` SHA-256 `a2ffb4fde9f7d086ecab43a0b09bae85c21db85d5a4bdff9da65e940a0819207` covers the metadata-unlink crash window after digest removal, digest-unlink failure, refusal to replace an orphan, malformed-orphan fail-closed behavior, exact-generation/consent/audit-reason checks, active-owner expiry, and confirmed dead-owner release.
- `test_consent_release_recovers_metadata_orphan_after_partial_cleanup` verifies the old digest is absent, metadata remains after injected unlink failure, then consented recovery removes it after expiry. The fresh A1 focused run above passed these current tests.
- A1 source and targeted test acceptance are verified for this checkout snapshot. Full project integration and unrelated GPU/runtime acceptance remain open.

## A2 — Fresh active-reference scan and focused validation (2026-11-06)

- Hub lexical searches for the retired Q4 tag in both canonical prompts and Gemma in `prompt_contracts.py` returned terminal HTTP 413 (`retryable=false`) because the search page exceeded budget. After those failures, one bounded native search over active recommendation files (`INSTALL_PROMPT.md`, `UPDATE_PROMPT.md`, `MODEL_CAPABILITIES.md`, `prompt_contracts.py`, `generator.py`, `opencode_hardware.py`) returned no hits for `qwen3.5:4b-q4_K_M`, `gemma4:12b`, or `qwen2.5-coder:14b` (exit code 1, no output).
- Fresh clean A2 tests: `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_prompt_contracts.py tests/test_opencode_future_stage.py tests/test_opencode_model_names.py --tb=short` — **23 passed in 0.90s**, exit code 0. The editor-modified `test_release_defaults_consistency.py` was not included in this run.
- Current `local_ai_status` request `req_dacf38db833c` still reports `active_model=null` and `gpu_admission_state=outcome_unknown`; it does not expose installed-model inventory. Thus active recommendations are clean in the bounded scan, but current installed tags remain **NOT VERIFIED**.

## A4/A5 — Focused source-path validation (2026-11-06)

- A4 targeted command `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_embedding_cache.py tests/test_rag_quality_contract.py tests/unit/test_accelerators_embeddings_reranker_wave13.py tests/unit/test_benchmark_rag_reranker.py --tb=short` — **55 passed, 1 skipped in 8.90s**, exit code 0. Skip: `tests/test_rag_quality_contract.py:616` requires explicit `RAG_BENCHMARK=1`; no latency/memory benchmark ran. These tests exercise cached/fallback/quality code paths, not active CUDA execution.
- A5 mocked runtime command `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_llama_cpp_runtime.py --tb=short` — **54 passed, 36 subtests passed in 0.63s**, exit code 0. Current test source SHA-256 `bade43ebeea12552614443ac71003e9bf3e88d4312fec704a8863cb38ee2c8f3` uses temporary state, synthetic endpoints, and stubs. This does not prove managed backend load/inference/unload, GPU residency, or VRAM release.
- A4/A5 focused tests pass for the current dirty checkout. GPU/runtime acceptance still requires separate target-device measurements and lifecycle evidence; no live GPU operation ran.

## Runtime gate recheck after A4/A5 source tests (2026-11-06)

- `local_ai_status` request `req_fcd08be5bd05` reports `active_model=qwen3.5:4b-nvfp4`, `gpu_admission_state=available`, but `vram_pressure=unknown` and telemetry `sample_pending`/`sampling=true`/`stale=true`.
- `gpu_reservation_status` request `req_2d3ed16b3dde` reports external reservation `free`. This does not establish usable VRAM, CUDA embedding/reranker execution, or model residency.
- Despite admission being `available`, no hardware benchmark or model lifecycle operation was started because telemetry remains unknown. A3/A4/A5/A7 runtime evidence remains **NOT VERIFIED**.

## A7 — Tool-harness contract checks (2026-11-06)

- `tests/test_local_model_eval_tool_harness.py` uses `FakeScheduler` and `FakeRuntime`; it exercises harness/schema/control-flow contracts without invoking a model.
- Ran `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_local_model_eval_tool_harness.py --tb=short` — **18 passed in 5.15s**, exit code 0.
- This verifies the local evaluation harness only. A7 remains **NOT VERIFIED** for actual model tool attempts, valid-call rate, grounded result use, recovery, latency, or VRAM. Current live status still reports `vram_pressure=unknown` and telemetry `sample_pending`; no model evaluation was launched.
## Current-turn A6 follow-up (2026-11-06)

- Fresh Hub status `req_dea231d36af6` reported admission `available`, active model `qwen3.5:4b-nvfp4`, and stale VRAM telemetry (`sample_pending`, `vram_pressure=unknown`). No live model or GPU workload was started.
- Re-ran only the CPU scheduling regression: `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/unit/test_preprocess_demand_priority.py --tb=short` — **8 passed in 4.12s**.
- This confirms current scheduling test behavior only. A6 remains **NOT VERIFIED** for representative hot/cold throughput, freshness, starvation, or runtime performance. No source changes made; editor-owned test and implementation paths remain untouched.
## A6 — Synthetic scheduling benchmark (2026-11-06)

- Ran `PYTHONDONTWRITEBYTECODE=1 python tools/benchmark_preprocess_demand.py --files 4096 --batch-size 64`; synthetic queue selection only, no model inference. Compact result captured from a fresh run.
- Baseline selected the hot match in batch 64; demand priority selected it in batch 1. Both completed all 4096 files with zero unprocessed files. First batch retained 63 regular files under demand priority (64 baseline).
- Selection latency: baseline median/p95 **2.736/3.748 ms**; demand median/p95 **2.892/5.761 ms**. One synthetic run only; timing is machine- and run-sensitive. `useful_context_verified=false`.
- This gives evidence of scheduling benefit and measured selection cost for one synthetic hot query. It does not test real repository demand, multiple hot queries, starvation bounds, freshness, context usefulness, or end-to-end performance. A6 remains **NOT VERIFIED** for those criteria. Current Hub status `req_a2f584f8742a` is degraded with admission `unknown` and stale VRAM telemetry; no GPU workload ran.
## A6 — Bounded repository-sample scheduling benchmark (2026-11-06)

- Ran `PYTHONDONTWRITEBYTECODE=1 python tools/benchmark_preprocess_demand.py --files 512 --batch-size 64 --root . --query ProjectPreprocessor`. The tool sampled 512 text files (7,799,157 bytes; scan cap not reached), then used a temporary fixture outside the checkout. No model inference ran.
- The query matched 157 sampled files. Demand priority put 20 matches in the first batch versus 4 baseline, while retaining 44 regular files versus 60 baseline. Both runs completed all 512 files with zero unprocessed files.
- The tool's lexicographically selected hot target appeared in batch 7 in both runs; this broad query did not improve that target's batch. Selection median/p95: baseline **0.996/1.355 ms**, demand **1.645/5.150 ms**. `useful_context_verified=false`.
- This is a bounded repository-text scheduling simulation, not actual RAG/preprocessing completion or relevance quality. It shows more query-matched candidates scheduled early with added selection cost, but does not prove freshness, starvation bounds across workloads, useful context, or end-to-end performance. A6 remains **NOT VERIFIED** for those gates.
## A6 — First-match metric and repeatability check (2026-11-06)

- Repeated the same bounded repository command to capture `batches_to_first_query_match`. Second run sampled 512 files and 7,800,353 bytes; previous run sampled 7,799,157 bytes. Treat runs separately because the dirty checkout changed between samples.
- The query still matched 157 files. First matching file appeared in batch 1 in both baseline and demand runs; the tracked lexicographically first hot target remained batch 7 in both. Demand still raised first-batch matches 4→20 and reduced regular first-batch slots 60→44.
- Second-run selection median/p95: baseline **0.971/1.267 ms**, demand **1.545/5.181 ms**. No context quality was measured. Together, these runs show earlier scheduling of more broad-query matches, not faster first-hit latency or a stable performance estimate.
- Do not use this broad-query result to accept A6. Need stable candidate snapshot and targeted hot/cold cases with freshness/starvation checks; live GPU/runtime gates remain blocked on unknown admission and stale VRAM telemetry.
## A1 — Current expired-reservation regression recheck (2026-11-06)

- Verified test source SHA-256 `995407d573f7d0b316e957742bd949b96f4d732402f7b4a63fbaaf8c7090308a`; it creates an expired digest-only reservation under pytest `tmp_path`, calls `_external_gpu_reserved()`, and asserts reservation cleanup plus continued reserved/fail-closed result.
- Ran `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_scheduler_unknown_gpu_reaps_expired_external_reservation.py --tb=short` — **1 passed in 0.41s**. No Hub reservation or GPU operation ran.
- This verifies the isolated cleanup regression only. Scheduler's live internal `outcome_unknown` remains unresolved; current status `req_0b252683245e` reports stale `sample_pending` telemetry and unknown VRAM. Production scheduler/recovery acceptance remains **NOT VERIFIED**.
## A4 — Current deterministic reranker fallback recheck (2026-11-06)

- Verified regression source SHA-256 `cbbb7129f6738b7e535e88dc0ec47da7fb6eb94c13ed78c15bf5f89d59b82fad`; it injects a fake CUDA reranker that returns `success=false` and asserts successful deterministic search results, primary `heuristic_rerank` fallback, and retained `reranker` failure detail.
- Ran `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_rag_quality_contract.py::test_cuda_reranker_failure_is_reported_with_deterministic_fallback --tb=short` — **1 passed in 0.49s**.
- This verifies simulated failure handling only. It does not measure actual CUDA execution, relevance, latency, throughput, or VRAM; those A4 gates remain **NOT VERIFIED**. Current status `req_06537dcb741d` reports `outcome_unknown`, unknown VRAM, and stale `sample_pending` telemetry.
## A2 — Current prompt and candidate regression recheck (2026-11-06)

- Ran `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_prompt_contracts.py tests/test_opencode_future_stage.py tests/test_release_defaults_consistency.py --tb=short` — **15 passed in 0.89s**.
- This rechecks prompt contracts, future candidates, and packaged-default consistency on the current worktree. It does not prove current installed-model inventory or runtime eligibility. Current status `req_06537dcb741d` has `active_model=qwen3.5:4b-nvfp4`, but admission is `outcome_unknown` and VRAM telemetry is stale/unknown; no inference was run.
## A5 — Current llama.cpp lifecycle suite recheck (2026-11-06)

- Verified current test file `tests/test_llama_cpp_runtime.py` SHA-256 `bade43ebeea12552614443ac71003e9bf3e88d4312fec704a8863cb38ee2c8f3`; suite uses test doubles, temporary state, mocked endpoints and local test sockets.
- Ran `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_llama_cpp_runtime.py --tb=short` — **54 passed, 36 subtests passed in 0.62s**.
- This verifies unit/runtime-control paths only. No real model load, inference, unload, switch, GPU residency, VRAM release, or live scheduler reservation was tested. A5 remains **NOT VERIFIED**. Current status `req_06537dcb741d` still reports admission `outcome_unknown` and stale VRAM telemetry.
## A6 — Current scheduling and freshness verification (resumed goal)

- Reviewed clean `src/local_ai_hub/preprocess.py` at SHA-256 `0fecfdb68a1cd17eac4968933c7a1de640bc4b93327dd7b566f121de653e9473`. Learned demand is capped at four queries, 16 FTS paths per query and 32 unique paths overall; a 15-second cache also keys on query list and file-index revision. `_find_next_files()` caps preferred entries at one quarter of the batch (at least one when batch size permits) and fills the remaining slots through regular ordering.
- Fresh CPU tests: `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/unit/test_preprocess_demand_priority.py --tb=short` — **8 passed in 2.19s**; focused content-change invalidation and learned-query recovery tests — **2 passed in 2.79s**.
- Tests cover hot/regular selection and content-change invalidation/recovery. This source review found no additional production fix justified in the bounded scheduling slice; no deeper analysis was added, matching the user's scheduling-only choice.
- A6 remains **NOT VERIFIED** for useful-context time/work saved, representative workload latency, broad-query benefit, and starvation across sustained workloads. Fresh Hub status `req_a0f33671fb93` reports admission `available` but VRAM `unknown` with stale `sample_pending`; no GPU work ran.
## A3 — Current stale-probe fallback recheck (resumed goal)

- Verified clean test sources: `tests/test_vram_balancer.py` SHA-256 `67b1967ab3cdd0a7c6b754d8b0f5d168c84f77d1113eb26627f65ebce3044c34`; `tests/unit/test_vram_balancer_non_blocking.py` SHA-256 `4a32f0377d24d0929e64eaab793c764f1a09a041a3ce116df2f299bd6189c710`. Both use controlled blocked samplers and temporary in-process state.
- Ran `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_vram_balancer.py::test_status_wait_timeout_returns_conservative_unavailable_without_second_sampler tests/unit/test_vram_balancer_non_blocking.py::test_status_returns_while_gpu_probe_is_blocked_and_coalesces_callers --tb=short` — **2 passed in 0.49s**.
- This verifies the CPU-simulated timeout/coalescing fallback only. It does not identify the live telemetry provider or establish current VRAM, residency, capacity, or latency. Fresh Hub status `req_a0f33671fb93` still had stale `sample_pending` telemetry and `vram_pressure=unknown`; A3 hardware qualification remains **NOT VERIFIED**.
## A6 — Larger repository sample with lifecycle-symbol query (resumed goal)

- Ran `PYTHONDONTWRITEBYTECODE=1 python tools/benchmark_preprocess_demand.py --files 2048 --batch-size 64 --root . --query LlamaCppManagedRuntime`. It sampled 2,013 files / 23,499,241 bytes; file and directory-entry caps were not reached. No model inference ran.
- The lexical query matched 564 sampled files. Baseline and demand both scheduled a matching file in batch 1; the benchmark's tracked hot target remained batch 9 in both. Demand increased first-batch matches 5→20 and retained 44 ordinary files (baseline 59).
- All 2,013 files completed with zero unprocessed. Selection median/p95: baseline **1.766/2.250 ms**, demand **2.242/3.187 ms**. `useful_context_verified=false`.
- The symbol query is broad under the benchmark's OR-token matching. These results show more matching files scheduled early, but not lower first-hit or target latency, useful-context time, work saved, or starvation bounds. A6 remains **NOT VERIFIED**; no production code change is justified by this synthetic queue-selection measurement.
## Fresh live-state gate (resumed goal)

- Hub status `req_03a87b282524`: Hub/Ollama online, `active_model=null`, `gpu_admission_state=preparing_model`, `vram_pressure=unknown`, and stale VRAM telemetry `sample_pending`. Requesting `extra_fields=["installed_models"]` did not return an installed-model inventory; `active_model=null` is not proof that no models are installed.
- GPU reservation status `req_ccf665048013`: `reservation_present=true`, `state=unknown`, `manual_intervention_required=true`. No release or recovery action attempted; owner/generation/liveness evidence is insufficient and the shared GPU may be in use.
- Do not start model load/inference/unload, benchmarks, embeddings, reranker, or context/concurrency workload until the reservation has a valid resolved owner state and VRAM telemetry is fresh. A2 current installed inventory and A3–A5/A7 live GPU gates remain **NOT VERIFIED**.
## Reservation state transition (resumed goal)

- `gpu_reservation_status` `req_ccf665048013` reported `reservation_present=true`, `state=unknown`, `manual_intervention_required=true`.
- A later read-only status request `req_ea7c72b123e1` reported `reservation_present=false`, `state=free`, `manual_intervention_required=false`. No release or recovery action ran from this agent; the cause of the transition is not established.
- The latest Hub status observed in this turn (`req_03a87b282524`) still had `gpu_admission_state=preparing_model` and stale VRAM `sample_pending`. External reservation `free` alone does not establish GPU capacity or usable VRAM. No GPU/model operation was started; runtime acceptance remains **NOT VERIFIED**.
## A1 — Current reservation lifecycle suite recheck (resumed goal)

- Verified current `tests/test_external_gpu_reservation_lifecycle.py` source SHA-256 `a2ffb4fde9f7d086ecab43a0b09bae85c21db85d5a4bdff9da65e940a0819207`; operations use pytest temporary paths, including cross-process claim races.
- Ran `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_external_gpu_reservation_lifecycle.py --tb=short` — **34 passed in 5.07s**, process exit code 0. Output showed all tests complete before the command session exited; no failure output appeared.
- This verifies the current local lifecycle regressions and isolation tests only. It does not resolve the separate live reservation transition or scheduler `preparing_model` state; no global reservation or GPU operation ran.

## 2026-11-06 — Root-bound VRAM fallback review

- Correction: an earlier source lookup in this resumed review omitted `root`; Hub returned files from `C:\Users\Adam\.local-ai-hub`, not this worktree. Those source slices are not evidence for this checkout. All source evidence below is explicitly bound to `C:\Users\Adam\.codex\worktrees\gpu-reserve-a1-fix\.local-ai-hub`.
- Current worktree `src/local_ai_hub/vram_balancer.py` source SHA-256: `f22621c5ce89acd1a0cade0883e9b819e2222d969f838553593bb0b87ed7452d` (558 lines). The reviewed timeout fallback forces `available=false`, `pressure_level=unknown`, caps context budget at 0.25, reduces dynamic context, throttles background work, disables speculative inference, and clears sample timestamp/age. This is fail-closed behavior; no source defect was established by this bounded review.
- Read-only status request `req_b4d1e3ee1811`, root-bound to this worktree: detached `HEAD`, 43 tracked modified paths, none staged; 3 untracked paths. The editor still owns the GPU/runtime modifications. No source changes or runtime operations were made.
- Acceptance remains **NOT VERIFIED**: this source review does not prove live GPU telemetry, memory capacity, model lifecycle, or runtime quality.

## 2026-11-06 — Candidate stale-telemetry admission gap

- Root-bound source evidence: `vram_balancer.py` SHA-256 `f22621c5ce89acd1a0cade0883e9b819e2222d969f838553593bb0b87ed7452d`; `scheduler.py` SHA-256 `f4af1ed1ae88f99c52e13a5a5903a33830e8648d1d39edea762c172af25f6046`.
- In `_sampling_timeout_fallback_locked` (`vram_balancer.py:130–169`), the last status is copied and marked `available=false` / `pressure_level=unknown`, but positive `vram_total_mb` and `vram_available_mb` from the old sample are retained. The scheduler `_admission` (`scheduler.py:620–722`) builds `vram_fields` from those numeric values without checking `resource["available"]`; it can calculate an `admitted` VRAM state and return an overall `degraded` result due to the 0.25 context factor. `submit` (`scheduler.py:808–823`) rejects only `state == "rejected"`, so a degraded job is queued.
- This is a source-level candidate that may violate fail-closed admission while telemetry is stale. It has not been confirmed with a regression test or runtime reproduction. No changes were made because `scheduler.py` and its GPU/runtime tests are editor-owned in this checkout. Acceptance remains **NOT VERIFIED**.
- Proposed next verification/fix after ownership is released: add a focused scheduler regression with `available=false`, `pressure_level=unknown`, stale but positive VRAM totals, and a fitting target estimate; assert the submit is rejected and no job is queued. Then gate normal admission on a current available telemetry sample (keeping the separate post-unload path's existing availability check) and run the focused regression plus the relevant scheduler suite.
- Coverage review: clean `tests/test_vram_balancer.py` SHA-256 `67b1967ab3cdd0a7c6b754d8b0f5d168c84f77d1113eb26627f65ebce3044c34`; its timeout regression (lines 241–270) starts with no prior sample, so it checks the zero-data fallback but not retention of positive stale capacity after a successful sample. No existing test in this reviewed slice exercises scheduler submission against that retained stale capacity. This is static coverage analysis only; no test was run.

## 2026-11-06 — Ownership recheck

- Root-bound Git status `req_5faee4b753f4` still reports 43 tracked modifications, 0 staged, and 3 untracked files; `scheduler.py` remains among the modified paths. Two active project tasks were also observed validating GPU-tiering/scheduler work. Their tool snapshot showed `inProgress`; no completion or ownership release was observed. Shared source and tests remain untouched by this goal.
- Fresh readiness evidence: Hub status `req_e0d038b3f4db` reports Hub/Ollama online, `active_model=null`, `gpu_admission_state=outcome_unknown`, `vram_pressure=unknown`, and stale `sample_pending` telemetry. Separate reservation status `req_8036552e5e04` reports the external reservation absent/free. Free reservation does not resolve the scheduler's uncertain admission or stale VRAM sample; no inference, benchmark, or reservation mutation was attempted.
- A6 scheduling-only review: current editor-owned diff in `tests/unit/test_preprocess_demand_priority.py` adds a sustained-hot-query case that requests four batches of four cards and expects one hot plus three cold cards per batch (4 hot and 12 cold total), and a learned-query benchmark test that scopes the learner by repository and asserts the private query is not emitted in the result. This addresses fairness and query-scope/privacy at the test-source level; the changed test has not been run or independently validated here. GPU/runtime acceptance remains open.
- A2 artifact check: clean `docs/MODEL_CAPABILITIES.md` SHA-256 `a7bafe23423082597e7955a560b21ea251477220f590d09086c364080927142e` was reviewed in bounded slices covering lines 1–166. It routes the 4B candidate as `qwen3.5:4b-nvfp4`; none of `qwen3.5:4b-q4_K_M`, `gemma4:12b`, or `qwen2.5-coder:14b` appears in this file. This closes only that artifact's stale-reference check; canonical prompts, generated guidance, future candidate lists, and current installed-tag evidence remain separate.
- After Hub lexical search returned historical-audit hits and a bounded page rejection (`413`, `terminal=true`, `retryable=false`), one exact-path local scan covered `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`, `docs/MODEL_CAPABILITIES.md`, `src/local_ai_hub/prompt_contracts.py`, `src/local_ai_hub/generator.py`, and `src/local_ai_hub/opencode_hardware.py`; it emitted no matches for `qwen3.5:4b-q4_K_M`, `gemma4:12b`, or `qwen2.5-coder:14b`. These paths are currently clean. Historical audit/inventory files were intentionally excluded. A2 source-reference closure is supported for the named paths; current installed-tag inventory remains **NOT VERIFIED** because compact Hub status exposes no inventory and no authorized command receipt was available.
- A6 source review: clean `src/local_ai_hub/preprocess.py` SHA-256 `0fecfdb68a1cd17eac4968933c7a1de640bc4b93327dd7b566f121de653e9473`. `_find_next_files` caps learned-priority rows to `min(limit-1, max(1, limit//4))`, then fills remaining batch slots from regular structural ordering with path deduplication. `_learned_priority_paths` bounds queries/terms/results and keys its 15-second cache by query set plus index revision (or a bounded aggregate fallback for legacy schemas). Static behavior supports bounded priority and cold-file progress; it does not prove benchmark usefulness or replace running the editor-owned fairness/invalidation tests.
- Stale VRAM regression probe: a temporary focused test seeded a successful 8 GiB sample with 7168 MiB available, blocked the refresh, and confirmed timeout fallback sets `available=false`/pressure `unknown` while still returning `vram_available_mb=7168.0`; the test failed exactly at the stale-headroom assertion (`1 failed in 0.59s`). The test was removed afterward; `tests/test_vram_balancer.py` is clean again. This confirms the dataflow but does not fix the scheduler admission gate. The correct change must reject unavailable/stale resource snapshots in scheduler admission; `scheduler.py` is still editor-owned (current diff is confined to a separate reservation block), so no production edit was made.

## 2026-11-06 — Normal admission now rejects stale VRAM values

- Ownership was rechecked in this worktree: `git status --short --branch` showed detached `HEAD`, 43 modified tracked paths, and 3 untracked paths. `git diff -- src/local_ai_hub/scheduler.py` showed only the pre-existing two-line reorder in `_external_gpu_reserved`; `tests/test_scheduler_post_unload_telemetry.py` was clean. Hub path leases were acquired for the scheduler, its focused telemetry test, and this audit note before editing.
- Added `test_normal_admission_rejects_unavailable_stale_vram_capacity` with `available=false`, `pressure_level=unknown`, a 0.25 context factor, and stale positive VRAM headroom. Before the fix it failed: scheduler returned `degraded` instead of rejecting (`1 failed`).
- Fixed `_admission`: numeric VRAM values are trusted only with `available is True`. If valid numbers remain while the sample is unavailable or lacks canonical availability, scheduler returns `state=rejected`, `reason=vram_telemetry_unavailable`, `vram_admission=unknown`, and omits stale byte counts. It does not replace missing telemetry with fabricated zeros.
- Validation: focused regression passed (`1 passed in 0.29s`); full `tests/test_scheduler_post_unload_telemetry.py` passed (`10 passed in 0.30s`); `git diff --check` exited 0. It emitted only existing LF-to-CRLF working-copy warnings in unrelated files. These tests use synthetic telemetry and do not establish live GPU admission.
- Current source review confirms the pre-existing `_external_gpu_reserved` reorder remains intact. The semantic `local_ai_task(review)` request failed closed with `gpu_outcome_unknown`; no local-model review result was received. Primary review was limited to the exact source, test, and diff shown here.
- Concurrent runtime diagnostic thread reported startup blocked by a legacy `state\\agent_state.sqlite3` and missing readable canonical `agent_state.sqlite`; after `quick_check=ok` on the canonical DB and one supervised restart, it reported Hub/Ollama online. This is the other thread's operational finding; its primary service-log evidence is not attached here, so treat it as a Hub startup failure report, not proof that `llama-server` itself crashed.
- Fresh bounded status `req_2df760ea8395`: Hub/Ollama online, `active_model=qwen3.5:4b-nvfp4`, GPU admission `available`, but VRAM telemetry still `sample_pending` and stale. Reservation status `req_ce9e7b307b7b`: free. No GPU benchmark or `llama-server` restart was run by this audit. The repeated `llama-server` non-response still needs a timestamped process health result and stdout/stderr to distinguish process exit from request timeout; acceptance remains **NOT VERIFIED**.

## 2026-11-06 — Conflicting live admission observations

- Active thread `01a1a227-17df-7b70-984e-260ff5dcaead` reported at cursor `6fd2c119-4749-4f9f-9097-2c432c4ca61a:59` and again at `:65` that admission was `preparing_model`, the 4B model was active, and a 9B comparison was deferred.
- Active thread `01a1a5f7-7f1c-7401-9d47-2612a898a186` later reported at cursor `e33b2241-11ed-4dbd-9d81-b9cd0c690d76:30` that its fence marker was released, the reservation was free, but GPU admission remained `outcome_unknown`; it did not start CUDA.
- These are separate agent-thread observations, not one atomic status sample. Treat GPU admission as unstable/unknown until a fresh direct status and stable reservation evidence agree. No GPU workload was started from this audit. The observations still do not prove that `llama-server` itself exited; timestamped process health and stderr remain required.

## 2026-11-06 — `llama-server` non-response report: evidence boundary

- User reports that `llama-server` is reported as unresponsive several times per hour. This is a symptom report, not yet a captured process exit or server log.
- Fresh Hub status request `req_d38efda41dbc` reports Hub online and Ollama online, but `success=false`, `degraded=true`, `active_model=null`, GPU VRAM telemetry unavailable with `sample_pending`/stale, and `dependency_status.ollama_profile.reason=probe_timeout` at a 250 ms deadline.
- This proves a slow/timed-out Ollama profile probe in that status sample. It does not identify `llama-server` as the timed-out process and does not prove a crash. The sample is consistent with a short health-probe deadline, but that causal link remains unverified.
- Read-only Service health dashboard snapshot at 22:44:57 showed current runtime `Healthy`, process liveness `live`, complete data, 0 supervisor restarts, and 0 retained unclean exits. It listed 9 retained request-failure samples since restart. The process session table had no active entries, so it did not add a server PID/exit record.
- The same dashboard showed Ollama error fingerprints: `delegate:review` / `Error: unexpected failure` count 14; interrupted model attempts count 10; and one `SchedulerTimeoutError: model request timed out` at 22:35:36. These support recurrent model-request failures/timeouts, not a confirmed `llama-server` process crash. The fingerprints do not expose the underlying server stderr or model process identity.
- Later status request `req_ff2788f602b6` was not degraded: Hub/Ollama online, GPU admission `available`, `active_model=null`, `vram_pressure=moderate`, and VRAM telemetry still `sample_pending`/stale. This is another snapshot without active model identity or fresh VRAM measurement.
- New status request `req_aa6d11ffbaae` now reports `active_model=qwen3.5:4b-nvfp4`, GPU admission `outcome_unknown`, `vram_pressure=unknown`, context factor `0.25`, and stale `sample_pending` VRAM telemetry. No new GPU or model workload was started from this audit.
- A concurrent benchmark agent reported a 9B request rejected before inference while GPU utilization was 99% and VRAM was 13,276/16,303 MiB. Its timestamp is not correlated with the retained Ollama error fingerprints, so GPU pressure remains a plausible contributor to slow requests, not an established cause of the reported non-responses.
- Root-bound source slice `src/local_ai_hub/ollama.py` SHA-256 `a941b96d0ca437ff147fb7866f09a7c55c42274edd7bad1ec87965f409627e2f`, lines 695–725, forwards the remaining caller deadline to `llama_router.request_stream`; when the result is marked `timed_out` or `preempted`, the normal backend fallback path is skipped. This explains how a request timeout can surface as a non-response without proving the server process exited. It does not establish why that deadline is reached.
- Concurrent edits currently include `src/local_ai_hub/llama_cpp.py` and `tests/test_llama_cpp_runtime.py`; this audit did not modify them. Keep the runtime diagnosis with that editor to avoid overlapping instrumentation.
- Next evidence needed: timestamped managed-server PID/exit state, health-request duration and timeout category, plus captured server stderr for the same incident. Compare with GPU admission and model load/switch activity at that timestamp. Until then classify the user-visible event as **repeated non-response reported; process crash unverified**.

## 2026-11-06 23:02 Europe/Prague — llama-server „neodpovídá“: nové rozlišení

- Čerstvý `local_ai_status` `req_6596d1cd4c14`: Hub 5.1.3 a Ollama online, ale celkově `success=false`, `degraded=true`, `active_model=null`, GPU admission `unknown`, VRAM sample pending/stale. Devět dependency probe položek (včetně `ollama_profile`, scheduler, background_gpu a agent_state) hlásilo `probe_timeout` na 250 ms. To dokládá pomalé/degradované kontroly Hubu, ne ukončený llama-server.
- Dashboard Requests v 23:01:53 ukázal 3 souběžné aktivní API požadavky: `/api/rag/index` 1m25s, `/api/solve/repo` 1m2s a `/api/search` 21s. Scheduler panel současně hlásil 0 položek ve frontě/běhu a GPU admission `available`; tyto HTTP operace proto samy nedokazují GPU inference ani saturaci llama-serveru.
- Načtených 50 posledních API záznamů mělo 4 selhání: dva `/api/agent-state/tasks` HTTP 400, `/api/coord/plan_task_edit` HTTP 400 a `/api/work-orders` business failure při HTTP 200. `/api/search` doběhl úspěšně za 41,1 s; další úspěšné searchy trvaly 10,6 s a 5–8 s. Activity filtr Failures ukázal 0 retained událostí. V tomto výřezu není konkrétní chyba llama-serveru; trace availability je u většiny řádků neověřená.
- Starší dashboard snapshot z 22:44 měl 9 retained request failures, 14 chyb `Ollama delegate:review`, 10 interrupted model attempts a `SchedulerTimeoutError: model request timed out` v 22:35:36. Spolu se zdrojovým `ollama.py` (řádky 695–725, SHA `a941b96d0ca437ff147fb7866f09a7c55c42274edd7bad1ec87965f409627e2f`) podporuje request deadline/timeout jako skutečný symptom. Není to důkaz, že OS proces llama-server skončil nebo že supervisor jej restartoval.
- Závěr: opakované hlášení může odpovídat timeoutu health probe nebo požadavku při zátěži; dostupné důkazy nerozhodují mezi těmito příčinami a skutečným pádem procesu. Nezvyšovat timeouty naslepo a neměnit llama_cpp/supervisor soubory, dokud běží vlastník těchto změn. K určení příčiny je potřeba časově korelovaný PID/exit/restart důkaz a omezený výřez `hub_stderr.log`, `hub.log`, `supervisor.log` včetně přesných timestampů a request ID. Následující krok: při dalším výskytu uložit přesný čas a text hlášení, porovnat jej s těmito logy/health checkem a záznamem requestu; zdrojově či provozně potvrdit, zda jde o probe timeout, inference timeout/cancel, GPU admission, SQLite/state issue nebo exit procesu. Aktuální stav zůstává `NOT VERIFIED`.

### Doplnění po zobrazení Service health (23:05 Europe/Prague)

- Panel hlásil aktuální Hub runtime `Healthy`, process `live`, data `complete`; restart count `0`, unclean exits `0`, scheduler counters 0. Session history tabulka byla prázdná. To popisuje pouze právě běžící proces a tuto telemetrickou projekci.
- Operativní log tail téhož panelu obsahoval mnoho skutečných `hub started version=5.1.3` záznamů s různými PID během 06:29–22:58 dne 2026-11-06; příklady: 22:03:44 PID 7232, 22:08:18 PID 42256, 22:08:31 PID 41892, 22:46:... PID 35632, 22:58:32 PID 46700. To je důkaz opakovaných startů Hub procesu v témže logu, ne důkaz restartů samotného llama-serveru ani příčiny startů. Počty z telemetry `supervisor restarts=0` a `unclean exits=0` s tímto logem neladí; mohou být omezené na aktuální supervisor/process session nebo jinak neúplné.
- Filtr logu `llama` nenašel žádný řádek; filtr `supervisor` také žádný. Z dostupného panelu proto nejde určit, kdo Hub znovu spouští, zda při tom končí Ollama/llama-server, ani zda starty odpovídají očekávaným aktualizacím/testům. Nespouštět restart jako test. Další diagnóza: potvrdit původ `hub.log`/`supervisor.log`, získat procesní rodič/exit status pro konkrétní sousední starty a porovnat s Windows Service/Task Scheduler událostmi a Ollama server logem ve stejných časech. Dokud to nebude svázané, stav příčiny `NOT VERIFIED`; potenciální podezření se nyní přesouvá i na vnější lifecycle/launcher Hubu.

## 2026-11-06 — Ověření lease drive-relative root fixu

- Fresh source at worktree HEAD: `src/local_ai_hub/leases.py` SHA-256 `78d5e17885d09c9c640058c4d475f66e417c27ca3be58a18f662aa166451eed1`; `ScopeLeaseStore.claim` rejects roots unless `Path(root).is_absolute()` or `PureWindowsPath(root).is_absolute()`, before `_root()` resolution. Thus `C:repo` rejects on POSIX and Windows; this closes the previously recorded POSIX drive-relative path concern.
- Focused regression: `python -m pytest -q --tb=short tests/unit/test_lease_drive_relative_root.py` → exit 0, 1 passed. Test file SHA-256 `18f52325ef42d297486220abc4433e22013ee3a023149164352062f82ce2b95b`.
- Acceptance is limited to this focused source/test pair. Full lease claim/release, Windows/UNC behavior and integrated candidate remain separately unverified; do not upgrade the plan task beyond its existing source-ready/unverified boundary.
