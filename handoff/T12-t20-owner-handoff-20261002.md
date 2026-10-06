# T12 → T20 owner handoff — 2026-10-02

Candidate worktree: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`  
Candidate HEAD: `933c0129079fcc0c894a71fe842cbbb5e6ad7285`  
Root: `C:\Users\Adam\.local-ai-hub` (read-only from T12)

## Ownership

T12 owns its routing policy/model behavior and targeted tests listed below, plus this task's handoff artifacts. In `AGENTS.md`, `docs/INSTALL_PROMPT.md`, and `docs/UPDATE_PROMPT.md`, T12 owns only the model-routing/token-economizer policy hunks; T19 owns its separate SDK, lifecycle, schema, and ingestion doc hunks. T12 does not own or modify shared `src/local_ai_hub/services.py`.

The T12 root-current policy patch is already present in root: read-only forward `git apply --check --whitespace=error` fails at `AGENTS.md:52`, `docs/INSTALL_PROMPT.md:168`, and `docs/UPDATE_PROMPT.md:95`; reverse check passes. This is not a request to reapply it. Root was not written by T12.

## Exact receipts

Focused deterministic selector command:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_model_routing.py tests/test_agent_policy.py tests/test_token_economy_tools.py tests/test_completion_model_routing.py tests/test_model_policy_sampling_floor.py tests/test_llama_cpp_routing.py
```

Result: **66 passed, 20 subtests passed in 3.92s**. Earlier broad receipt: **347 passed, 10 subtests**; not rerun in this continuation.

Candidate-only consumer command:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t12_project_model_consumer.py
```

Result: **2 failed, 4 passed, 5 skipped in 0.58s**. Candidate lacks `src/local_ai_hub/project_config.py`; two failures expect project-specific model/prompt settings and five cases skip on import. A separate read-only compatibility run exposing root `project_config.py` through package `__path__` passed **7/7 in 1.91s**; this does not make the candidate self-contained or close the candidate-only failure.

Offline harness command: `PYTHONDONTWRITEBYTECODE=1; PYTHONPATH=src; python -B tools/t12_model_free_harness.py` → exit 0, ~4.66s, `synthetic_model_free`. Live inference false; quality not measured; VRAM null. Static AST check passed for all four configured profile maps. No live benchmark ran.

## Hash-bound files (SHA-256)

T12 source/test paths:

- `src/local_ai_hub/model_policy.py` — `8A3111368C0CCCD6616C87B27EAE366359F8D5821D1261E337E5CD9982F19013`
- `src/local_ai_hub/router.py` — `AC089C43BD6A3CBEE26F3A742D80C92E7252D5A803491842EA7CB5D9C2E74B49`
- `tests/test_model_routing.py` — `4681E55CE6B149FB41D54C35C48104D6734769AC068A18B8AD945540EF006AA4`
- `tests/test_agent_policy.py` — `87F6E52F7DBA6BFA6370540AF163CB8C04155E4D63AFA5427CBA1C742434D7BC`
- `tests/test_token_economy_tools.py` — `BBF627D4F17812B61C9B04552A32A8D73FE1B554C85BE40A6B8F0BBA3BF3DF7E`
- `tests/test_completion_model_routing.py` — `3C37562CCAF9F54EE5E3F0FD0FF5743F0F45C14AE077013FDC7B9B011FD10FFF`
- `tests/test_model_policy_sampling_floor.py` — `3355B2B3DB8F3EAEA6EDD7B6C217CB24033254CD5886EF01AD693E5477B59D22`
- `tests/test_llama_cpp_routing.py` — `D67C7F65EAC5940FB682A60AD063DCDFB1D0BB2D13099A5FD7753712407CB6C2`
- `tests/test_t12_project_model_consumer.py` — `8B6DF0F536FB5F3392E7729DD7368BC592C7F07D14E5D11EFD840E7885B42603`
- `tools/t12_model_free_harness.py` — `51091A7778D2C24555BF4258E27E203A8A746B3246284BF171D16EE7A3FBD9D8`

Current whole-file snapshots for policy docs (T12 owns only its hunks; T19 owns its separate hunks): `AGENTS.md` `F6A8E38845F4D92F4843D66692ACD7B5AB9700829BB4561784E34AFE75577200`; `docs/INSTALL_PROMPT.md` `2F09D9C17F5ABFB9E9C592FFD925C7CC663A601D87FC9DFC7FA3528F6D4F1E18`; `docs/UPDATE_PROMPT.md` `F56E684D4DBECF18FB9B8AB4C8F255D561602A751A06C6AD2B8A8E8416691B3E`.

Receipt artifacts:

- `handoff/T12-routing-policy-adoption-20261002.md` — `38362AEBAAE72F3E7B36AF897B85680D113DA702E53B8725831F092141AAC4EF`
- `handoff/T12-offline-routing-runtime-20261002.md` — `DE84D798C10147EC9E5ABC278422564F3FE6F2D5F235EE8175CF79EB0A04B1CB`
- `handoff/T12-model-free-offline-20261002.json` — `DC9B0BB07F377106D40CC7B44544A0F601E567C3A77711E1CAE1928A66127DA9`
- `handoff/T12-model-free-offline-20261002.md` — `704718E5BB3B65081B882EE9672165052A4D8C2A30D8817648216A5F160A2FA7`
- `.handoff/t12-resume-receipt-20260930.json` — `D53BAD8920CC6A81B8B03E243830B6AB8359AA6179301F7D9F95DF97B6CD0BC1`
- `handoff/T12-root-current-routing-policy-20261002.patch` — `38BC78E9315668ED0D6D36001AFF3722E7448187957EB4F20DCF87C9347174D3` (already applied in root; do not reapply)

## Open acceptance gates

Only a balanced RTX 4060 host is available. Integrated/high/max live profiles are unavailable. T02 baseline artifact is absent; comparison is skipped and no optimization claim is made. Live quality, latency, VRAM, overload/cancel/fallback behavior, and multi-profile acceptance remain unproven. Candidate-only project consumer tests remain blocked by missing `project_config.py`. T12 is therefore incomplete.

## End-to-end acceptance checkpoint — 2026-10-02

T20 integrated the root-current source/test patch without running tests. Postimage hashes confirmed by T20:

- `src/local_ai_hub/llama_cpp.py` — `571A07F82CC813029F75977B5F7329C51CA003E480A750937CA15AF87571FBBD`
- `src/local_ai_hub/scheduler.py` — `D728327691E486421E0C661D2C9CBB8EDDF1FDEB7CA9DDAF20B704EBB0376ED1`
- `tests/test_t12_llama_cpp_transport.py` — `C2EADB338D0787A6FDF8F69008CEE3AFEE93DC10924F0C154916968FBDD31C1F`
- `tests/test_t12_scheduler_scenarios.py` — `D87981173A913A7C9E725C59E726497B293BFAD9269D9FE06E05252FBC2D5292`

Candidate focused receipt remains: the five T12 transport/scheduler regression selectors passed, `5 passed in 0.26s`. Root post-integration selectors are **pending**; no root tests ran. Exact root command is the same five selectors against `tests/test_t12_llama_cpp_transport.py` and `tests/test_t12_scheduler_scenarios.py`, as sent to T20.

Current slot owner is T02. Do not run root selectors or benchmarks until T02 explicitly releases the serial slot and T20 confirms the queue is clear. Next action: run the five prepared root selectors, capture the receipt, then continue end-to-end acceptance only within an assigned slot.

| Acceptance area | Current evidence | Status |
|---|---|---|
| Routing/policy source | Root integration hash-confirmed; earlier candidate focused suite 66 passed | Source integrated; root selectors pending |
| Transport and pre-start cancellation | Candidate regressions 5/5; root versions integrated | Root selectors pending |
| Integrated/balanced/high/max live profiles | Only balanced RTX 4060 host available; no fresh live profile receipt | Incomplete; other hosts unavailable |
| Model quality, latency, and VRAM | Offline model-free harness was synthetic; no fresh live receipt | Unverified |
| Scheduling, batch, overload, cancel, fallback | Source and synthetic/model-free evidence only; no end-to-end runtime receipt | Unverified |
| T02 paired baseline / optimization | Baseline artifact absent | Comparison skipped; no optimization claim |

End-to-end acceptance remains incomplete. Current slot owner is T02; T12 root selectors wait for T02 release and T20 queue clearance. The existing app goal still reports `blocked`; this checkpoint does not mark it complete.

## Root-current static routing and cancellation review — 2026-10-02

Review was read-only against `C:\Users\Adam\.local-ai-hub`. Root source was not edited; no tests, benchmarks, or live runs were started.

Concrete root gap: `AffinityScheduler._perform_switch` supplies `should_stop` and `deadline` controls to runtime preparation. With `smart_ollama.enabled`, `app.py` wraps runtime in `TieredOllamaRuntime`; root `TieredOllamaRuntime.prepare_model` accepts only `unload_others`, so scheduler model switching can fail with unexpected-keyword `TypeError`. Root wrapper also lacks `supports_post_unload_admission`, so scheduler cannot use the target runtime's post-unload VRAM admission capability. Root `TieredOllamaRuntime.request_interruptible` drops scheduler deadline when forwarding to selected runtime. Candidate implementations exist in candidate `src/local_ai_hub/tiered_ollama.py`; root-current focused patch is `handoff/T12-tiered-wrapper-root-current-20261002.patch` (SHA-256 `ABD0E8A67DE3B38AB71E275AAABFFB9132CD2EC82DCE608B31BCEDBBDB3EC6DD`). Patch targets root `tiered_ollama.py` hash `981E339CA6FB054ACAD5E5AFF4FAD24A303E67DB56A8235D2D161D6927C5A394` only.

Root `tests/test_tiered_ollama_runtime.py` lacks assertions for preparation-control and request-deadline forwarding. Candidate test file adds `test_model_prepare_forwards_cancellation_controls_to_selected_runtime` and `test_interruptible_request_forwards_deadline_to_selected_runtime`; it still lacks direct coverage for the admission capability/callback wrapper path. Add that selector before claiming wrapper admission coverage. No test was run.

Second concrete deadline gap: `AffinityScheduler.submit` runs synchronous `preempt_hook` before its timeout loop. App binds hook to `IdleGPUWorker.preempt_foreground`, which calls `OllamaRuntime.stop_managed_server`; that calls `terminate_tree(..., grace_seconds=5.0)`. A short request deadline can therefore overrun by the synchronous stop duration before scheduler notices timeout. This review proposes a regression case; it does not change shared `services.py` or root files.

No static defect found in role override quality floor or explicit runtime fallback behavior. Router enforces role rank; selected-tier runtime errors remain retryable errors rather than silent cross-tier downgrades.

Prepared isolated post-slot acceptance set: five root transport/cancellation selectors already listed above, plus the two Tiered wrapper forwarding selectors after T20 ports their test changes. Add one direct Tiered post-unload admission selector. Keep all root selectors behind T02 release and T20 queue-clear confirmation. No T02 baseline artifact exists; skip paired comparison and make no optimization claim. Only balanced RTX 4060 host exists, so integrated/high/max live profile claims remain unavailable.

Balanced-only live protocol after slot release: record host/GPU/driver, active profile, model IDs and quantization, config hash, thermal/power state, and clean initial VRAM. Pin workload prompts, input/output token sizes, concurrency, seeds where supported, and scorer. Run warmup separately; record per-request queue wait, load/unload time, time-to-first-token, generated tokens/sec, end-to-end latency, peak VRAM, cancellation latency, deadline overruns, fallback/error class, and task-quality score. Preserve raw run receipt and summarize p50/p95 plus failures. A single RTX 4060 run can establish balanced-profile behavior only; no cross-profile or optimization conclusion.

Root source hashes at review: `tiered_ollama.py` `981E339CA6FB054ACAD5E5AFF4FAD24A303E67DB56A8235D2D161D6927C5A394`; `scheduler.py` `D728327691E486421E0C661D2C9CBB8EDDF1FDEB7CA9DDAF20B704EBB0376ED1`; `ollama.py` `1C7D6E58234EAD892D42AC9A95818C9690E5162816CA3572DBE9B9BE79D04E42`; `background_gpu.py` `B47DA57DBD8640F4C37CA3840818705772CBD861C0C87176ED3971C0B4806BB5`; `process_utils.py` `4D5A1AFBCB23BAB1FE4EEC6B9639743D17920DE93E7A822EF64840815998D4EB`; root `tests/test_tiered_ollama_runtime.py` `99F2F732C0055D8E041434F766BD72BCBAB6AA85430652E6EE167ED5C5BA0DA7`.

## Tiered wrapper coverage patch — 2026-10-02

Prepared test-first coverage in the T12 worktree only. Changed `tests/test_tiered_ollama_runtime.py`; production source and root checkout untouched. New selector `test_post_unload_admission_capability_delegates_to_selected_runtime` verifies capability dispatch follows model tier. Expanded `test_model_prepare_forwards_cancellation_controls_to_selected_runtime` to assert `should_stop`, `deadline`, and `post_unload_admission` all reach selected runtime. Existing candidate selector `test_interruptible_request_forwards_deadline_to_selected_runtime` covers deadline forwarding.

Test patch: `handoff/T12-tiered-wrapper-tests-20261002.patch`, SHA-256 3721865D94777D721FC2B201EBE79479AF2259FF6FDCAAD7E3E394EED57E3831. Candidate test file SHA-256 196DC7F68C3CB8E4DDA55D5C4A62F7AFFC4E9D1EAD674B7687EF2477773B5B01. `git diff --check` passed. No tests/runtime/benchmark run; T07 owns slot 06. Root integration awaits T20 review and slot clearance.

Acceptance risk: wrapper delegation remains unverified until these selectors run against root-current integrated code. Coverage does not yet test missing/non-callable capability fallback. Synchronous preemption deadline overrun remains open: stop path passes `grace_seconds=5.0`; add a separate bounded regression only after slot release and design review.


Patch review correction — 2026-10-02: regenerated root-current wrapper patch to preserve existing un_benchmark_scenario location and avoid duplicate method. Patch remains one-file scope; root apply-check passes; root unchanged. Updated patch SHA-256 ABD0E8A67DE3B38AB71E275AAABFFB9132CD2EC82DCE608B31BCEDBBDB3EC6DD.

## Current-root reconciliation — 2026-10-02

Confirmed active T12 thread checkout is attached worktree `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`. Current root source preimage `src/local_ai_hub/tiered_ollama.py` SHA-256 `981E339CA6FB054ACAD5E5AFF4FAD24A303E67DB56A8235D2D161D6927C5A394`; current root test preimage `tests/test_tiered_ollama_runtime.py` SHA-256 `99F2F732C0055D8E041434F766BD72BCBAB6AA85430652E6EE167ED5C5BA0DA7`. Root reports both paths dirty against index; no root files changed during reconciliation.

Corrected root source patch `handoff/T12-tiered-wrapper-root-current-20261002.patch` SHA-256 `ABD0E8A67DE3B38AB71E275AAABFFB9132CD2EC82DCE608B31BCEDBBDB3EC6DD`; root `git apply --check` passed. Candidate test patch `handoff/T12-tiered-wrapper-tests-20261002.patch` SHA-256 `3721865D94777D721FC2B201EBE79479AF2259FF6FDCAAD7E3E394EED57E3831` does not apply to current root test preimage because its hunk context starts from candidate's already-extended fake runtime. Root-current test patch prepared at `handoff/T12-tiered-wrapper-tests-root-current-20261002.patch`, SHA-256 `CDBAA0A875D52E0F9EA540D6D65A75AA4FC3602C1D35AAFEF3D80C3DE5016ECC`; root `git apply --check` passed. No patch applied. It touches one test file only.

Exact post-slot selectors: `tests/test_tiered_ollama_runtime.py::test_post_unload_admission_capability_delegates_to_selected_runtime`, `tests/test_tiered_ollama_runtime.py::test_model_prepare_forwards_cancellation_controls_to_selected_runtime`, and `tests/test_tiered_ollama_runtime.py::test_interruptible_request_forwards_deadline_to_selected_runtime`. T20 owns execution gate. No tests, runtime, or benchmark run here.

## T20 slot coordination — 2026-10-02

Requested T20 review of the root-current source/test patches and an exclusive slot for the three wrapper selectors. T20 thread remains active; bounded wait returned no response or slot clearance. No tests run. Blocker: T20 review and explicit exclusive slot grant pending. Do not execute selectors before grant.

## Static routing and gaming-unload lifecycle audit — 2026-10-02

Routing review: role-quality floors remain enforced by `ModelRouter.apply_model_override`; Ollama-disabled selection routes explicitly to llama.cpp and reports errors when unavailable; selected-tier request failures do not silently downgrade to another tier. No additional routing defect found in these paths.

Handoff risk found in `TieredOllamaRuntime._details`: it catches every inventory exception and returns an empty list. `_unload_peer` and `_handoff` polling used this best-effort helper, so an exception could look like zero loaded models and permit a tier switch without verified peer unload. T12 candidate source now adds `_handoff_details(force_refresh=True)` and uses it for pre-unload and post-unload checks; exceptions/malformed rows fail the switch. Candidate source SHA-256 `B9A66148272185EAA87E958EC40A99EE57BE79464D71A32277ABC014F628E96D`. Selector prepared: `tests/test_tiered_ollama_runtime.py::test_tiered_handoff_fails_closed_when_peer_inventory_raises`.

Residual: `OllamaRuntime.loaded_model_details(force_refresh=True)` can itself fall back to llama inventory/cache after an Ollama `/api/ps` error. The new handoff helper catches raised/incomplete results but cannot distinguish that fallback-empty result from a complete empty inventory. Full fail-closed proof needs an inventory API with explicit completeness status; do not claim this patch closes all backend-inventory failure modes.

Gaming unload method `OllamaRuntime.unload_configured_models` gathers fresh pre/post inventories, unloads every reported name via `keep_alive=0` / llama endpoint unload, and returns false for `physical_vram_reclaimed`. No source call site exists yet. `TieredOllamaRuntime` is the app runtime when `smart_ollama.enabled` but lacks `unload_configured_models`; a future gaming-mode caller through that facade would fail. Do not add a combined facade receipt until endpoint aggregation semantics are owned/defined; calling both runtimes naively duplicates shared llama.cpp inventory and creates ambiguous flattened model IDs.

Separate deadline risk remains: `IdleGPUWorker.preempt_foreground` synchronously stops its managed server; `OllamaRuntime.stop_managed_server` passes `grace_seconds=5.0`. Foreground request deadline can expire during hook before scheduler timeout loop resumes.

Root-current source patch SHA-256 `3313B4B809CABA90BEF4C536A6889542F03BBC2D2AC09186CCD10CA1FB269F14`; root-current test patch SHA-256 `E96FF1AA9618A5182C933C7BB13E7A8052F4FAAB306068D650029B673E1E8324`. Both target T12-owned `tiered_ollama.py` and `test_tiered_ollama_runtime.py`; source patch adds best-effort-failing handoff inventory checks, test patch adds raising-inventory regression while retaining wrapper-forwarding selectors. Apply-check only; no root changes. Tests remain slot-gated.

## Inventory completeness design decision — 2026-10-02

No safe narrow source patch closes the complete inventory gap yet. A temporary Tiered helper was discarded: it forced refresh and propagated raised/malformed inventory, but `OllamaRuntime.loaded_model_details` can still turn Ollama `/api/ps` failure into llama/cache fallback rows. Empty fallback can still look like complete empty inventory, so the temporary helper did not satisfy fail-closed acceptance.

Required contract before implementation: return one structured snapshot with `complete`, monotonic observation time, per-backend/per-endpoint status, and rows retaining stable backend/endpoint identity plus model ID. Query every enabled route with forced freshness. Timeout, error, malformed payload, or missing endpoint status must be incomplete, never empty-success. Handoff unload must target the row's owning backend, then re-query every peer endpoint; switch proceeds only when all inventories are complete and peer rows are empty. Gaming unload aggregates per-endpoint receipts, succeeds only when all are complete and empty, preserves duplicate IDs by endpoint, and always reports `physical_vram_reclaimed=false`. Tests need empty-success, endpoint failure, malformed/incomplete response, duplicate IDs across endpoints, wrong-backend unload prevention, and failed post-unload verification cases.

Current vetted wrapper patches restored; experimental partial inventory helper/test removed. Root source patch SHA-256 `ABD0E8A67DE3B38AB71E275AAABFFB9132CD2EC82DCE608B31BCEDBBDB3EC6DD`; root-current test patch SHA-256 `7A2CC279B828D6146B571F3F9BF2E0F490ACB240C7B131FAC58B66FB99A85207`; both root apply-check pass and remain unapplied. Candidate test patch SHA-256 `EA7625A99B10DCE81DD36EDA3AC209B6395521EE74709E9B7D3B1870B19E18EA`. Candidate source/test hashes `E9E12D3319BE1CB71D463E1DAD46ADE5C673087189CA40C1D7C39F872F72DC11` / `C02362CEDD4C3378C95CEEA4850FB8291DA5B0293A1FF4D808493FACFF8F8D02`. No root edit, test, runtime, or benchmark performed. Slot remains required.

## Approved strict inventory and gaming unload implementation — 2026-10-02

The user approved completing the inventory and gaming-unload contract in the T12 worktree. Implementation is in `src/local_ai_hub/llama_cpp.py`, `src/local_ai_hub/ollama.py`, and `src/local_ai_hub/tiered_ollama.py`; acceptance coverage is in `tests/test_t12_llama_model_inventory.py`, `tests/test_ollama_gaming_mode.py`, and `tests/test_tiered_ollama_runtime.py`. Root checkout remains untouched.

`LlamaCppRouter.loaded_model_inventory` now reports explicit status by endpoint URL. `OllamaRuntime.loaded_model_inventory` force-queries enabled Ollama and configured llama.cpp routes, validates model rows, preserves backend and endpoint identity, and returns incomplete on request errors, timeouts, malformed responses, or missing endpoint evidence. `unload_inventory_model` routes unload to the owning backend and llama.cpp endpoint. Gaming unload now records per-endpoint requested/remaining receipts and unloads identical served IDs independently at each llama.cpp endpoint. Malformed initial rows make the overall inventory incomplete. `TieredOllamaRuntime` uses strict fresh snapshots for handoff, unloads through row ownership, rechecks every peer route before starting the target tier, exposes a tiered inventory API, and aggregates fast/smart gaming receipts. Smart-tier gaming unload excludes shared llama.cpp endpoints so the fast-tier call owns those receipts. All gaming results keep `physical_vram_reclaimed=false`.

Acceptance selectors for T20 (not run in this worktree):
- `tests/test_t12_llama_model_inventory.py::test_loaded_inventory_lists_unmapped_served_ids_and_marks_each_endpoint_status`
- `tests/test_ollama_gaming_mode.py::test_strict_inventory_keeps_failed_ollama_endpoint_incomplete`
- `tests/test_ollama_gaming_mode.py::test_strict_inventory_preserves_backend_and_endpoint_identity`
- `tests/test_ollama_gaming_mode.py::test_strict_inventory_marks_malformed_ollama_rows_incomplete`
- `tests/test_ollama_gaming_mode.py::test_gaming_unload_routes_duplicate_llama_ids_to_each_endpoint`
- `tests/test_tiered_ollama_runtime.py::test_handoff_refuses_incomplete_peer_inventory`
- `tests/test_tiered_ollama_runtime.py::test_handoff_unloads_exact_inventory_owner_and_endpoint`
- `tests/test_tiered_ollama_runtime.py::test_handoff_preserves_duplicate_model_identity_across_endpoints`
- `tests/test_tiered_ollama_runtime.py::test_tiered_inventory_reports_each_tier_endpoint_and_completeness`
- `tests/test_tiered_ollama_runtime.py::test_gaming_unload_returns_tiered_receipts_without_vram_claim`
- `tests/test_tiered_ollama_runtime.py::test_gaming_unload_keeps_incomplete_endpoint_unverified`
- Retain wrapper selectors `test_post_unload_admission_capability_delegates_to_selected_runtime`, `test_model_prepare_forwards_cancellation_controls_to_selected_runtime`, and `test_interruptible_request_forwards_deadline_to_selected_runtime`.

No test, runtime, or benchmark was run; T20 owns the slot. Only this host's balanced RTX 4060 profile is available. No T02 baseline artifact exists, so no paired comparison or optimization claim is made. A setup attempt for `C:\Users\Adam\.agents\skills\token-economizer\scripts\ensure-tools.ps1 -PlanOnly` reported that the script path is missing; no installer ran. Static `git diff --check` and final file hashes are pending.

Candidate file pins for this handoff:
- `src/local_ai_hub/llama_cpp.py`: `026A53B11FD4E3FDA46750DEA7BD89378355447BAE85509FE8FA60F5664AC3C1`
- `src/local_ai_hub/ollama.py`: `C0B63E75E5639ACA26619B2718695A6725029A3948ABC7E687A510E3E256EFC4`
- `src/local_ai_hub/tiered_ollama.py`: `C21644B24CB996FD682A1D7EEE11C5B3FD2763597891AFA0F427D3208E04F5FB`
- `tests/test_t12_llama_model_inventory.py`: `2A130B82FC4A657B2CE9D9BBA7F948FAEA19000F53A508C45A48CF29D85ECFB0`
- `tests/test_ollama_gaming_mode.py`: `FBD0DA069FEDAB7276A327DEC5792D85404E1ECC8AE03023A0EC28E7E89C832E`
- `tests/test_tiered_ollama_runtime.py`: `182602DFBB8B6780C51B2D8359C5FD08313B41DAE91B6DF1EBE74C264522785D`

## Additive routing regression — 2026-10-02

Review found that `apply_project_settings` treated an absent project `model_profile` as `balanced`. A prompt-only project context could therefore downgrade a host configured for `high` or `max`. The T12-owned fix leaves profile selection unchanged when the project setting is absent; request-scoped prompt context still applies.

Changed owned paths:
- `src/local_ai_hub/model_policy.py` — missing profile now means no project profile override; SHA-256 `07B26603663FBA0BAE195E755B613F6E307CFD206D32748D7F90A9999127F7E7`.
- `tests/test_t12_project_model_consumer.py` — added `test_prompt_only_project_settings_preserve_host_model_profile`; SHA-256 `8546648F18CF835CA3B9971B5BDA4F0E908CE53960B990D5A10A3817E807BEA4`.

`git diff --check -- src/local_ai_hub/model_policy.py` passed; `rg -n -m 5 '[\t ]+$' tests/test_t12_project_model_consumer.py` returned no matches (exit 1). No tests run: T20 reports the queue blocked at L/T06 (`Transport closed`, no receipt); L remains UNKNOWN, followed by M/T05 then N/T04. T12 has no slot. New distinct selector, eligible only after explicit T20 GO:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t12_project_model_consumer.py::test_prompt_only_project_settings_preserve_host_model_profile
```
