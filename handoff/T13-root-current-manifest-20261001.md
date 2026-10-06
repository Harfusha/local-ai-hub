# T13 root-current handoff manifest — 2026-10-01

Destination: T20 thread `Local AI Hub T20 — release acceptance` (`01a0d322-b3bd-7930-b552-14e9b7020fec`).
Candidate: `C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub`.
Root: `C:\Users\Adam\.local-ai-hub` — read-only throughout; no tests rerun.

## Patch

- `handoff/T13-root-current-test.patch` (SHA-256 `EC33E0536E282A4C6780B67E653D34A75450664B622B9ECC075D8800C7B308BD`)
- Scope: only strengthen the existing conversation-release acceptance test with an explicit worker-exit gate and unload-attempt observation. Preserves root's current `mode_result` response contract and all surrounding test content.
- Isolated overlay: `handoff/T13-root-current-overlay/` began as a copy of root's current test file.
- `git apply --check --whitespace=error` in that overlay: **PASS**. Patch then applied to the overlay.
- Target file SHA-256: root pre-patch `DD7266EC46E03BAB5F2CC6002D22867CEA832656A2152261CAB6DDD73117FD43`; overlay post-patch `4334271F47273A5FA99520BBF56E6E1D311A60F1CCAA79D189D86D721073DAB4`; root post-check remains `DD7266EC46E03BAB5F2CC6002D22867CEA832656A2152261CAB6DDD73117FD43`.

## Root source receipt and inherited hunks

Root T20 working tree already had dirty integration state before this handoff: modified `src/local_ai_hub/http_server.py`, `src/local_ai_hub/preprocess.py`, `tools/hubctl.py`; untracked mode, preprocess-mode, hubctl-mode, and conversation-receipt tests. These root-owned changes were read only.

The T13-owned `_ActiveTranscriptionRegistry.enter_gaming`, `cancel_and_wait`, and `finish` function slices have identical normalized SHA-256 in root and candidate respectively:

- `enter_gaming`: `5ff682c63c98bb551b6276cd56673cc3bbd181747124a5d0d0dbacd7971cbcd4`
- `cancel_and_wait`: `bb45a9bd57c2273c53a36b24ba095cb5b1744817c9ad7bed5000ca27aaffb82c`
- `finish`: `bb93cfa081d19981233d06dde6c981868fd7cd7cf8df7a58010e997c0e617703`

No source hunk for these functions is included.

Root already has its own operational-mode implementation and acceptance coverage; it is not byte-identical to the candidate's implementation, so candidate files are not copied over root-owned versions. Root coverage is present in `tests/test_operational_mode.py` (writer lock and sharing-violation retry), `tests/test_hubctl_mode.py` (offline persistence), and `tests/test_preprocess_operational_mode.py` (pause/restricted-mode yields). Root `tests/test_t13_gaming_conversation_release_receipt.py` is the only patch target because its current test lacks the candidate's worker-exit ordering assertions.

Root whole-file SHA-256 pre/post checks (unchanged by this handoff):

| Root path | SHA-256 pre = post |
|---|---|
| `src/local_ai_hub/operational_mode.py` | `B72023ED7BD029EA747794A02B5C8F6783E6DC592B4BF67542BDEE63F5D1F5A1` |
| `src/local_ai_hub/http_server.py` | `BDB4ECF50C149FCB144F3745EC9AB58FCE029F900A6ED83A41C5FAF1D2C9BECB` |
| `src/local_ai_hub/preprocess.py` | `FB7A0B55D05BEE9C84FC0C1AA988DC74D48346FA11CFB6529FDB40CDDD582F57` |
| `tools/hubctl.py` | `D587D80847152AA863A06D2850A60CBC2788409EB13EF94477DCE1791B9758F6` |
| `tests/test_operational_mode.py` | `558A4800F126C0E3D6D2FC724AE137DB0F51BFDDDA4646A861CF1E7F10A8392A` |
| `tests/test_preprocess_operational_mode.py` | `A169B90608F1D34C7740B892F24FCA8F329BCCE5918E8C277346C2283C1BCFC9` |
| `tests/test_hubctl_mode.py` | `5F90B0480F1862760F30841800E97CFABF44F82CD08DEFDF773461C5F38A74F8` |
| `tests/test_t13_gaming_conversation_release_receipt.py` | `DD7266EC46E03BAB5F2CC6002D22867CEA832656A2152261CAB6DDD73117FD43` |

Candidate-to-root whole-file hash differences in dirty source files are inherited/owner divergence, not a basis for bulk replacement. The handoff carries only the single root-current test patch above.

## Active goal checkpoint — 2026-10-01

**State: REVIEW REQUIRED; existing app goal remains BLOCKED, not complete.** Candidate `HEAD` is `6050c41ce5510a6de3eaeb674a180560ea404f24`, whose direct parent is the required base `2b33602adef0d030fea66cdcc04ca742c60b2e32`; preserved ref `codex/t13-lifecycle-core` remains at `c3f372b0a728298104ff8a7735dd36f7ad0b6bf0`. Existing dirty owner/shared changes remain preserved; new work in this continuation is limited to the root-current handoff patch, manifest, and isolated overlay.

T13 focused candidate acceptance has the earlier recorded result **14 passed in 6.71s**. T20 received the test-only root-current patch and manifest; root integration/review is pending. T19's latest available receipt is a 70-passed/1-skipped focused group plus packaging/docs checks, not a full-suite receipt; T19 explicitly leaves release gates open. Therefore the existing goal's T19 full-suite acceptance gate is unsatisfied. No tests were rerun in this continuation.

## Resume checkpoint — 2026-10-02

Root integration now contains the exact patch postimage: `tests/test_t13_gaming_conversation_release_receipt.py` SHA-256 `4334271F47273A5FA99520BBF56E6E1D311A60F1CCAA79D189D86D721073DAB4`, equal to the isolated overlay. The single newly strengthened root selector was run once after confirming no root-scoped pytest was active:

```text
python -m pytest -q --tb=short -p no:cacheprovider tests/test_t13_gaming_conversation_release_receipt.py::test_gaming_release_receipt_includes_conversation_cancelled_before_snapshot
```

Result: **1 passed in 4.82s**. No other candidate/root tests were repeated.

## Async/conversation selector receipt — 2026-10-02

Candidate-only selector `tests/test_async_jobs.py::test_async_job_submit_rejects_conversation_payload_before_dispatch` passed: **1 passed in 0.30s**. The previously recorded candidate conversation-release receipt selector also passed: **1 passed in 4.81s**. No source edits made in this continuation; inherited async job files remain dirty and preserved.

## MCP command policy regression — 2026-10-02

Added candidate-owned `tests/test_t13_mcp_command_mode_policy.py`; patch: `handoff/T13-rootcurrent-mcp-command-mode-policy-20261002.patch`. Its single selector failed as expected: `local_ai_command(action="run", command="python -m pytest -q")` reached the generic tool gate with `requires_heavy_work=False`. Test disables command execution, so no subprocess ran. `src/local_ai_hub/mcp_server.py` had inherited T03 dirty state; no T03 source changed in this continuation. Production integration remains T03-owned.

T03 follow-up reported a separate candidate fix: `local_ai_command` classifies `map`/`code_index` as lightweight and `run` as heavy; its targeted dispatch selector passed (1 passed in 2.52s), with source SHA-256 `B83ADBDFEF3C77070FD8611DCF9AD2F400419BE3E070A4EE298177E855EEA4D8` and test SHA-256 `1DC7B8F7677BC207E35189B28111140F7CF139CBB45428D7094B24D121291AF0`. This is a reported T03-candidate receipt, not T13-integrated evidence. T13 candidate still has `src/local_ai_hub/mcp_server.py` SHA-256 `6F93D152E62D094C3AADE320B6AB01E78D2F386BAE3DAED20B4F8DA9489A6B00`; `tests/test_mcp_contract_dispatch.py` is absent here. No cross-owner patch was transferred.

## Scoped operational-mode review — 2026-10-02

Confirmed and fixed malformed Ollama receipt acceptance in `unload_ollama_models_for_gaming`: non-list `remaining` previously became `[]`, allowing `success=True` despite missing inventory proof. It now stays unverified and cannot produce success. Added malformed-receipt case at `tests/test_operational_mode.py:248`. RED selector failed with `state=complete` before fix. GREEN targeted command below passed **10 tests in 3.05s**:

```text
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_operational_mode.py::test_gaming_ollama_release_maps_owner_receipts_without_inventing_success tests/test_operational_mode.py::test_file_lock_serializes_revision_update_across_processes tests/test_hubctl_operational_mode.py::test_pause_and_resume_persist_offline_when_hub_is_unavailable tests/test_preprocess_operational_mode.py::test_mode_pause_blocks_next_preprocessing_step
```

Reviewed mode persistence/gating, offline CLI transition, preprocessor pause and queued background-GPU handoff paths. No additional confirmed defect in those inspected slices. MCP command classification remains a separate T03 integration gap documented above.

Follow-up acceptance selectors: **14 passed in 2.80s** across multiprocessing revision updates, inference-active unload deferral, missing-owner fail-closed behavior, offline mode persistence, live API transition routing, uncertain-outcome no-fallback, bounded background-worker pause, and cooperative preprocessing yields. Combined with the prior **10 passed in 3.05s**, owned concurrency/offline/unload/background-gating candidate selectors total **24 passed**.

Focused root-current reconciliation patch: `handoff/T13-rootcurrent-unload-receipt-validation-20261002.patch`. `git apply --reverse --check` passed against the candidate postimage. Root checkout was not inspected or modified; T20 must reconcile if its operational-mode preimage differs.

T19's current receipt is its complete T19 regression set (18 `test_t19_*.py` files): **70 passed, 1 skipped**; package smoke **2 passed**. T19 explicitly marks release **NOT RELEASE-READY**: clean Windows/Linux installer hosts and T20 integrated live/restart/concurrency/final verification gates are still absent. This is not an integrated repository-wide full-suite receipt. Existing goal remains **BLOCKED / REVIEW REQUIRED**, not complete; current T20 root acceptance still has non-T13 blockers.

## Review follow-up — 2026-10-02

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub`, HEAD `6050c41ce5510a6de3eaeb674a180560ea404f24`. Root/T20 checkout was not edited.

Focused candidate verification command:

```text
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_operational_mode_http.py tests/test_operational_mode.py tests/test_preprocess_operational_mode.py tests/test_hubctl_operational_mode.py tests/test_t13_hubctl_offline_persistence.py tests/test_t13_gaming_conversation_release_receipt.py
```

Result: **85 passed in 9.65s**. This covers persistence/process-lock races, HTTP mode authorization, preprocess pause/restricted-mode behavior, and mock-backed cancellation/drain/unload order. It does not prove live Ollama unload or VRAM reclamation.

HTTP auth evidence: `GET /api/mode` passes through the shared authorization check and then loopback validation; tests cover configured-token rejection and non-loopback rejection. `POST /api/admin/mode` requires the configured API token; the authorized non-loopback case is an explicit contract test.

Operational-mode helper tests allow bounded deterministic reads in gaming and block them in maintenance. A remaining review blocker is in dirty, T03-owned `src/local_ai_hub/mcp_server.py`: its generic wrapper calls the gate with `requires_heavy_work=False` for all non-status tools, while `local_ai_command` has no action-specific gate at its entrypoint. This leaves command actions without a demonstrated classification between cheap reads and tests/builds in gaming mode. T13 did not edit this shared file. A T03-owned decision/change plus a regression test is required.

At this checkpoint, T13 was **REVIEW REQUIRED / BLOCKED** on the MCP command-action classification, integrated full-suite/release gate, and live model-unload evidence. The updated T13-owned candidate status follows below. Root edits remain absent.

## Candidate-only gate checkpoint — 2026-10-02

Dirty-state audit before the selector: candidate `HEAD 6050c41ce5510a6de3eaeb674a180560ea404f24` (detached), preserved `codex/t13-lifecycle-core` ref `c3f372b0a728298104ff8a7735dd36f7ad0b6bf0`, 1,258 dirty paths across T13 and other owners. No dirty source was reverted. T13-specific candidate pins before and after run: `src/local_ai_hub/http_server.py` SHA-256 `CD384F1E28B9FCE65251C6A93E2F652382A5D606323D026F1A64DEB966860A41`; `tests/test_t13_gaming_conversation_release_receipt.py` SHA-256 `B02800EBC6E45E2E26BE550B977CC2F296F3A1A2F85C7B4AD30D44DB334A7ECC`.

Hub `local_ai_command` failed before dispatch (`request_not_sent=true`); one native fallback ran only the unique T13 candidate selector:

```text
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_t13_gaming_conversation_release_receipt.py::test_gaming_release_receipt_includes_conversation_cancelled_before_snapshot
```

Result: **1 passed in 4.81s**. No root tests, merge, source edits, or full-suite rerun. T20 controls root integration testing. Existing goal remains **REVIEW REQUIRED / BLOCKED** until the integrated acceptance gate is supplied.

## T13-owned acceptance completion — 2026-10-02

T13-owned candidate criteria are complete: file-lock/revision concurrency, atomic replace retries, offline/live CLI transitions, Ollama unload receipt validation and all-loaded-model iteration, in-process accelerator/CUDA release, preprocessing/background gating, and `/api/mode` authorization all passed targeted selectors. One confirmed T13-owned defect was fixed: `ollama.py::unload_configured_models` used `math.isfinite` without importing `math`; the all-model selector caught `NameError`, then passed after the import was added. No hardware or live Ollama run occurred; physical VRAM reclaim remains unverified.

Additional ownership/offline/background command:

```text
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_operational_mode.py::test_cross_process_updates_increment_revision_without_lost_writes tests/test_operational_mode.py::test_gaming_ollama_release_defers_during_inference_without_calling_owner tests/test_operational_mode.py::test_gaming_ollama_release_fails_closed_if_owner_callback_is_missing tests/test_hubctl_operational_mode.py::test_mode_command_persists_any_mode_when_hub_is_offline tests/test_hubctl_operational_mode.py::test_mode_command_routes_live_transition_through_mode_api tests/test_hubctl_operational_mode.py::test_mode_command_does_not_fallback_after_uncertain_live_transition tests/test_preprocess_operational_mode.py::test_restricted_mode_pauses_background_worker_with_bounded_recheck tests/test_preprocess_operational_mode.py::test_cooperative_preprocess_yields_observe_restricted_mode
```

Result: **14 passed in 2.80s**.

Unload/replace/CUDA/HTTP authorization command:

```text
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_operational_mode.py::test_replace_retries_transient_permission_error tests/test_operational_mode.py::test_replace_retries_windows_sharing_violation tests/test_operational_mode.py::test_replace_sharing_violation_retries_are_bounded tests/test_operational_mode.py::test_windows_open_mode_file_blocks_replace_and_preserves_previous_state tests/test_t13_ollama_unload_all_models.py::test_gaming_unload_requests_every_loaded_ollama_model_and_verifies_empty_set tests/test_operational_mode.py::test_gaming_ollama_release_maps_owner_receipts_without_inventing_success tests/test_operational_mode.py::test_in_process_accelerator_release_uses_component_cuda_cleanup_receipts tests/test_operational_mode.py::test_in_process_accelerator_release_defers_while_inference_active tests/test_operational_mode.py::test_in_process_accelerator_release_bounds_stalled_component tests/test_operational_mode.py::test_in_process_cuda_cache_cleanup_uses_mocked_torch_without_hardware tests/test_operational_mode.py::test_in_process_cuda_cache_cleanup_respects_deadline tests/test_operational_mode.py::test_embedding_and_reranker_release_only_loaded_accelerator_models tests/test_operational_mode_http.py::test_mode_api_rejects_non_loopback_peer tests/test_operational_mode_http.py::test_mode_api_obeys_configured_api_token tests/test_operational_mode_http.py::test_post_admin_mode_accepts_authorized_non_loopback_peer tests/test_operational_mode_http.py::test_post_admin_mode_requires_api_token tests/test_operational_mode_http.py::test_post_gaming_persists_mode_reports_transition_and_unload tests/test_operational_mode_http.py::test_post_gaming_reserves_release_before_exposing_mode_change tests/test_operational_mode_http.py::test_post_active_defers_while_accelerator_release_owns_resources tests/test_operational_mode_http.py::test_post_gaming_defers_in_process_release_for_running_preprocess tests/test_operational_mode_http.py::test_post_gaming_reports_mocked_cuda_cleanup
```

Result: **28 passed in 0.72s**. `handoff/T13-rootcurrent-unload-receipt-validation-20261002.patch` and `handoff/T13-rootcurrent-ollama-unload-20261002.patch` reverse-check against the candidate postimage. Root still untouched.

Direct GET `/api/mode` missing-token check passed separately: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_operational_mode_http.py::test_get_mode_requires_configured_api_token` -> **1 passed in 0.23s**. Incremental test patch: `handoff/T13-rootcurrent-mode-api-get-auth-20261002.patch`; reverse-check passed against the candidate postimage.

MCP classifier remains T03-owned and absent from this candidate: current `mcp_server.py` SHA-256 is `6F93D152E62D094C3AADE320B6AB01E78D2F386BAE3DAED20B4F8DA9489A6B00`; prior T13 command-policy selector is still a confirmed RED. T03 separately reported its classifier fix and passing test, but no cross-owner patch was transferred. Integrated/root acceptance stays open pending that integration, live unload evidence, and T20 release gates.

Earlier T13-owned operational-mode selectors passed in the candidate. A later source-review regression case (verified remaining model but no unload reported) was submitted once through T20 slot09; Hub returned `outcome_unknown=true` (`req_31241f6fa3a3`), so that selector is **UNKNOWN**, with no retry/fallback. See `handoff/T13-slot09-unknown-20261002.md` and updated `handoff/T13-operational-mode-source-review-20261002.md`. Umbrella T13 goal remains **BLOCKED** pending the unknown selector disposition, a clean candidate, and T19's valid full-suite receipt. Runtime Ollama inventory/CUDA reclamation remain **NOT VERIFIED**.

Offline persistence/restart review: production path statically matches serialized atomic local writes when Hub is offline and no local fallback after an online uncertain transition. Added T13-owned fresh-process persistence selector `test_offline_hubctl_mode_survives_fresh_process_restart` in `tests/test_hubctl_operational_mode.py` (SHA-256 `8CF303E41288F32E98356F65351480B96B2D4F17DB860D51E6FC64692B270560`). AST/diff checks pass; selector awaits T20 serial validation slot. Receipt detail: `handoff/T13-operational-mode-source-review-20261002.md`.

## T13 end-to-end checkpoint — 2026-10-02

- T20 integrated the root-current no-migration fail-closed `async_jobs.py` hunk. Root source SHA-256: `CBB599D76A08BFF38F95A2AFA34DA11FFCFC96C54065D0F313E518B69D9CB950`. Root test file was unchanged by that hunk (SHA-256 `15B9D64B92C6FC71A0E6C50A1ECF9A83B88F0BA059197AFB8B525E587C70384A`). Exact patch and T20 result: `handoff/T13-root-current-async-jobs-fail-closed-20261002.patch`, `handoff/T13-root-current-async-jobs-fail-closed-20261002.md`.
- Candidate now aligns T13-owned async-job schema behavior to no migration shim. Current scoped delta and hashes: `handoff/T13-candidate-async-jobs-no-migration-20261002.patch`, `handoff/T13-candidate-async-jobs-no-migration-20261002.md`. Its two narrow selectors remain pending because T02 owns the exclusive benchmark/test slot.
- Confirmed root-current async-job selectors passed in T20: `test_async_jobs_rejects_non_current_schema_without_deleting_rows`; `test_async_jobs_rejects_legacy_schema_without_mutating_rows`. The same batch's tracked release-source selector passed. Separate T10-owned release-contract selector remains failed on a pre-existing `ALTER TABLE` marker in `src/local_ai_hub/code_index.py`; no T13 edit.
- Hub remains unavailable; no retry/poll. `/api/context/pack`, benchmark/harness paths, and other owners' source were not changed.
- Existing system goal stays **BLOCKED** pending a clean candidate and valid T19 full-suite result; no narrow selector is counted as full-suite acceptance.
- Read-only root/candidate schema-block review after candidate alignment: identical normalized `_init_db` schema blocks, SHA-256 `A9DCB9B354F99D821009A28DB5FDC741572E73597122DB5CB4FC745FC62558D9`.
- Operational-mode source review found and corrected one receipt-label edge case: `success=True`, no models reported unloaded, but a verified non-empty `remaining` inventory previously received `not_applicable`. Candidate now returns `partial`/`success=False`; regression case is added. Receipt: `handoff/T13-operational-mode-source-review-20261002.md`. Focused selector remains pending the T20 slot. Runtime Ollama inventory and CUDA/physical VRAM reclamation remain **NOT VERIFIED**.
