# T13 mode matrix and T04 SSE compatibility — 2026-10-01

## Root-current port

Regenerated mode consumer patch: `handoff/T13-rootcurrent-mode-cancellation-regenerated.patch`
SHA-256: `036DD510B7A20FBECFBEA8B456A0249826A5A1CFE24EA95F5C24103199636D55`

Root preimage SHA-256:

- `http_server.py`: `15F497AEFDE4E2EDFF4D8B6BA158C87FF70731C7F40762F10BE64445646F9278`
- `services.py`: `1556EDBE4336E1D0FECDAC86D79593AB6F62BE12A1F13841537CAC453721DCC1`
- `preprocess.py`: `14CDD83395263470DE8468A907045C083C9DA54127490CED4B81C5696716AD69`
- `background_gpu.py`: `B47DA57DBD8640F4C37CA3840818705772CBD861C0C87176ED3971C0B4806BB5`

Regenerated patch applies to current root and contains only one HTTP receipt field. Other mode/cancellation hunks are already present in root's inherited working-tree changes, so regenerated patch excludes them. T04, regenerated T13 consumer, and T13 app-context patches apply in both orders on isolated current-root copies. Ten transformed Python files parsed. No root file was written.

Root's current `AsyncJobManager` has no `inference_actions_active`, `wait_for_inference_actions`, or `when_inference_actions_drained` tracking APIs (source SHA-256 `A524078F716D4915F6ABFFB27347C4625FDBB9C34A1373F5F8442D7102AEF935`; only `operational_mode_change_guard` exists). Patch therefore reports `inference_admission_release.state=unavailable` and skips model/accelerator release while gaming. Scheduler activity alone is insufficient because direct embedding/reranking can bypass it. Patch preserves top-level persisted mode fields and current revision guard. T08 owns admission tracking; T20 owns root integration.

Mode integration contract from current caller: gaming transition in `http_server.py` queries `inference_actions_active`, waits through `wait_for_inference_actions`, and registers deferred release with `when_inference_actions_drained`. Async HTTP jobs enter through `APP.async_jobs.submit`; app callback `_execute_async_task` reserves `inference_admission(action)`. T08's manager implementation must expose these exact APIs with matching ownership lifetime. Root currently does not satisfy that contract.

T13 candidate API source-check: `inference_admission(action)`, `inference_actions_active(exclude_actions=...)`, `wait_for_inference_actions(actions, timeout_seconds)`, and `when_inference_actions_drained(actions, callback)` exist in candidate `async_jobs.py`. Root remains unchanged. A candidate-only drain regression fix now tracks the outer durable async executor admission until its executor returns; see the controlled overlay receipt below.

## T04 SSE compatibility

T04 worktree HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`.

- T04 `http_server.py` source SHA-256: `20D0E9FE3EA625FC77AE18D12BB98F5FC2E77D88F00F6801B06D4BECE43C0932`
- T04 `client.py` source SHA-256: `04CD4D0CE198C20C7A68357D587F00D91FFE3828C4AD5937E65A7D6FE703AD6E`
- Extracted SSE HTTP patch SHA-256: `D257BA9B757B250CCE5F32AB96AC1B6C69DDD09CBC2F21BCC5AE83362EAC10BF`

T04 HTTP hunk changes `_stream_agent_events` disconnect/error accounting. T13 hunk changes cancellation registry, `/api/admin/mode`, conversation routes, and transcription route. Symbols and hunk regions are disjoint. Applying T04 then checking T13 passed; applying T13 then checking T04 passed on isolated copies of the current root preimage.

## Candidate mode matrix receipts

Focused operational HTTP suite after the receipt fix:

`python -B -m pytest -q --tb=short tests/test_operational_mode_http.py`

Result: `22 passed in 0.59s`. This includes bounded Whisper cancellation, unavailable admission tracking, no unload during active work, and mode response outcomes.

Cancellation seams after handler changes:

`python -B -m pytest -q --tb=short tests/test_t13_cancellation_seams.py`

Result: `6 passed in 0.45s`.

Complete candidate mode matrix command (T12 unload-owned cases deselected):

```text
python -B -m pytest -q --tb=short tests/test_operational_mode.py tests/test_operational_mode_http.py tests/test_preprocess_operational_mode.py tests/test_hubctl_operational_mode.py tests/test_async_jobs.py::test_timed_out_accelerator_release_keeps_inference_admission_reserved tests/test_async_jobs.py::test_dispatch_defers_queued_job_until_owned_resource_release_finishes tests/test_async_jobs.py::test_dispatch_requeues_claimed_job_when_release_starts_before_admission tests/test_async_jobs.py::test_timed_out_wait_returns_active_state_without_cancelling tests/test_async_jobs.py::test_running_cancel_ack_does_not_wake_waiter_before_terminal_state tests/test_async_jobs.py::test_persisted_modes_gate_async_admission_without_test_overrides tests/test_async_jobs.py::test_submit_before_restricted_mode_is_cancelled_at_dispatch tests/test_async_jobs.py::test_submit_mode_gate_and_queue_insert_are_atomic_with_mode_transition tests/test_async_jobs.py::test_dispatch_paused_before_admission_is_cancelled_by_mode_transition -k 'not test_gaming_ollama_release_maps_owner_receipts_without_inventing_success and not test_gaming_ollama_release_fails_closed_if_owner_callback_is_missing and not test_in_process_release_reports_false_return_with_loaded_model_as_timed_out and not test_embedding_and_reranker_release_only_loaded_accelerator_models and not test_embedding_release_defers_while_request_is_loading_model and not test_reranker_release_defers_while_request_is_loading_model'
```

Result: `65 passed, 11 deselected in 5.36s`. Covers gaming/maintenance background pauses, inference admission, persisted restart state, offline CLI pause/resume, async queued/running transitions, bounded cancellation, and no new launches.

The first unfiltered run reported `68 passed, 8 failed in 8.06s`. Two T13 HTTP issues were fixed and the focused suite above passes. Six failures were T12-owned unload/accelerator receipt tests (including missing release methods and an undefined `SimpleNamespace` test import); T13 did not edit those seams.

T13 whole acceptance remains open; no GPU, shared ports, root tests, or root writes used.

## Isolated state-file and offline CLI acceptance

`python -B -m pytest -q --tb=short tests/test_operational_mode.py::test_cross_process_updates_increment_revision_without_lost_writes tests/test_operational_mode.py::test_replace_retries_transient_permission_error tests/test_operational_mode.py::test_replace_retries_windows_sharing_violation tests/test_operational_mode.py::test_replace_sharing_violation_retries_are_bounded tests/test_operational_mode.py::test_windows_open_mode_file_blocks_replace_and_preserves_previous_state tests/test_operational_mode.py::test_corrupt_state_fails_closed_to_degraded_maintenance tests/test_hubctl_operational_mode.py::test_pause_and_resume_persist_offline_when_hub_is_unavailable` — `7 passed in 0.75s`.

The process-contention test spawned three processes and verified all 12 revisions. The real Windows test held `operational_mode.json` open without delete sharing, verified bounded replace failure, preserved prior mode/revision, removed temp files, then verified successful update after handle close. CLI pause/resume used isolated `tmp_path` state and an offline fake `HubClient`; no user profile, live Hub, GPU, or root tests touched.

## Async project-context dispatcher receipt

`app.py` now copies the async payload before mapping action aliases. Dispatcher retains `root` and `cwd`, drops caller-supplied `project_context`, `project_model_profile`, and `system_prefix`, and preserves workspace roots through `second_opinion`, `compress`, and `route`. Batch rejects non-list or empty `tasks`; valid batch items inherit only missing `root`/`cwd` fields. T12 resolves project profile and system prefix from the selected root.

Earlier root-current app-only context patch: `handoff/T13-rootcurrent-app-context.patch` (SHA-256 `2C85860070141AFFA4906CF3A57642AF57207FAC7DF25AAC303041BD0E1472E2`). Root `app.py` preimage SHA-256: `4050325BCC0F319941A0A183C2DA7CA529A33820236062A39E86E817DCB7705E`. It passed `git apply --check` but predates the validation and root/cwd propagation changes below; treat it as superseded, not a complete T20 input. No root write performed.

Integration test used root `project_config.py` SHA-256 `4238B6A6DE1DE00F55F4679CE0DF7D431522EC1BAFABFA272258C1662F13F713` and T12 candidate `services.py` SHA-256 `5C8866C6C7C19242B376019B1AB09A48E360184D66DA423BBBB97A8131964CF8`. It asserted both modules' exact `__file__` paths. Test submitted `reason`, `review`, and `batch` through the real candidate `AsyncJobManager`, T13 app dispatcher, root `resolve_project_context`, T12 `LocalAIServices`, and captured fake `/api/generate` runtime. All three outputs used the root project's `model_profile = "max"` and server-resolved `system_prompt_prefix`; caller-supplied prompt fields are now removed before dispatch.

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t13_async_project_context.py` — `9 passed in 1.06s`. This includes the three-task T12 resolver integration, secondary-action root propagation, untrusted-prefix removal, malformed batch rejection, and service admission callback wiring. Earlier test-first run failed on the expected lost fields.

Restart/resume dispatch receipt:

`python -B -m pytest -q --tb=short tests/test_t13_mode_resume_matrix.py` — `1 passed in 0.32s`. Test recreates the manager from the same state path after gaming and maintenance; both reject work, active resume dispatches and completes work.

## Async executor drain regression

T08's controlled T13/T12 overlay initially failed because the drain callback fired while the T12 service call was active. `inference_admission(action, job_id=...)` validated the durable row but did not create an in-memory admission token, so `when_inference_actions_drained` observed no owner. Candidate `async_jobs.py` now creates the outer token for every inference admission at context depth zero. Nested app admission remains deduplicated by the context variable. Root and T08 worktrees were not edited.

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_async_jobs.py::test_async_executor_admission_drain_waits_for_service_exit tests/test_async_jobs.py::test_transcription_admission_drain_waits_for_http_handler_exit` — `2 passed in 0.47s`.

Controlled integration overlay from `C:\Users\Adam\.codex\worktrees\t08-agent-os\.local-ai-hub`, using T13 candidate `6050c41ce5510a6de3eaeb674a180560ea404f24` and T12 candidate `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t08_t13_t12_consumer_overlay.py` — `1 passed in 0.70s`. It exercised the real T13 dispatcher and `AsyncJobManager`, real T12 `LocalAIServices.delegate`, SQLite async-job storage, and a controlled model boundary. It verified cancellation/drain ownership remained active until the service returned. This is controlled integration evidence, not model or GPU evidence.

The complete candidate async-job module passed after the ownership fix: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_async_jobs.py` — `64 passed in 17.49s`. One earlier run had a timing-sensitive dispatch timeout; isolated retry passed, and the complete rerun passed.

## Conversation trace system redaction

Conversation start and continuation now pass a trace-only system placeholder to `_generate`. Runtime payload keeps the original system prompt. `DebugTraceObserver` receives a copied request payload with only its `system` field replaced, preventing conversation-specific system prefixes from entering durable model-request traces.

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_conversations.py` — `24 passed in 0.40s`. Coverage checks both conversation call sites use the redacted trace system and the trace payload copy leaves the runtime system unchanged.

## Async workspace root fallback

Service dispatch now selects the first non-empty value among `root`, `cwd`, and `.` for speculative draft, speculative lint, and repository discovery. Empty `root` no longer masks a valid `cwd`.

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_speculative_draft_and_split.py::test_speculative_draft_service` — `1 passed in 0.49s`. The test supplies `root=""` and a temporary `cwd`; affected-test discovery receives the temporary workspace.

## Remaining independent review findings

Immutable review `D108A873AC95E15E0D2F3111F078607DCEBE741C0BD9CD47ED41B375F5059B5A` returned `WITHFIXES`, not approved. T13-owned conversation trace redaction and empty-root fallback are addressed in this candidate. T12 owns unresolved llama.cpp gaming inventory behavior: an enabled backend with unknown inventory must not report successful cleanup; inventory must include served endpoint IDs beyond configured aliases; pre/post checks need fresh bounded reads. No T12 source was edited here. Physical VRAM reclamation remains unproven and must stay `false` until real hardware evidence exists.

## Joined async and HTTP conversation drain receipt

T08 reported a refreshed joined candidate overlay: one real T13 `AsyncJobManager` async delegate and one production T13 HTTP `/api/conversations/continue` handler ran concurrently through T12 `LocalAIServices._generate` and controlled barriers. Gaming transition kept drain and resource release pending, rejected a new async job without inserting a durable row, and did not call Ollama unload until both calls returned. Then HTTP response completed, drain callback fired, and release ownership cleared. The combined candidate suite with memory/task regressions passed `38/38 in 16.83s`. This is external T08 receipt; not rerun in this worktree. Updated immutable root-current patch SHA-256 `4508A1FAA910BD8E324E6F5EE91E72E452EE9275A9677624EF192112E25831DC` remains unapplied. Fake backend only; no production source/root change or real model/GPU claim.

## Root consumer patch closure review

A separate T13 source review found existing root-current patches are not dependency-closed: root `AsyncJobManager` lacks inference admission and drain ownership APIs; the app-context patch omits the executor wrapper; the HTTP mode patch adds receipt metadata without bounded async drain. Root integration needs T08-owned actual executor lifetime tracking, bounded drain before unload, and a barrier test proving no post-pause generation starts. Preserve root request-id/journal/T16 contracts. Review also flags malformed batch input validation and missing root/cwd propagation through `second_opinion`, `compress`, and `route`; T12 must resolve model/prefix server-side rather than trust caller prefixes. No root write or duplicate root patch was made in this candidate slice. Coordinate ownership through the established T08/T20 flow. Hub was intentionally not used per human instruction.

T13 candidate now exposes `AsyncJobManager.inference_admission` to `LocalAIServices` as `services.inference_admission(action, *, job_id=None)`. It yields a denial dict or `None`; accepted admission remains tracked until context exit. Pass normalized owning action: `delegate`, `reason`, `review`, `review_diff`, `second_opinion`, `compress`, `route`, `batch`, or one of `embed`, `rerank`, `transcribe`, `vision`, `benchmark`, `complete_code`, `scaffold`, `speculative_draft`, `generate_tests`, `solve`, `eval_suite`, `prompt_eval`, `eval_drift`. For example, `/api/conversations/continue` uses `delegate`.

Async executor and HTTP handler keep outer admission through service lifetime. T12 service adapter must enter nested `services.inference_admission(action)` after generation payload preparation and immediately before backend request. It rechecks persisted mode after preparation. If gaming persistence wins first, nested admission returns denial and runtime receives no request. If nested admission wins first, operation counts as active and gaming release waits for it. Context manager releases the mode lock before `yield`; do not hold that lock over network generation. T13 test verifies callback wiring; T12 owns consuming it at `_generate` and adding the barrier regression.

Root-current consumer patch `handoff/T13-rootcurrent-consumer-v2.patch` SHA-256 `2DFD20E54161C20F57C447A2433BAAA2570DD3F31DCBEDB1EFDD1FA403237948`. It touches only `src/local_ai_hub/app.py` and `src/local_ai_hub/http_server.py`. Root preimages: app `4050325BCC0F319941A0A183C2DA7CA529A33820236062A39E86E817DCB7705E`, HTTP `6BA4B79AD0A7D06C11151E07E7261AFD9CAD515C1EF8FBA5A0DB0A34CEAA40CA`. Postimages: app `F7360F3A7B266030FF0A79E5C1EA46780D5F3E28E96D2AD89254070656C53A60`, HTTP `4B635B978EF556A69863507D9B7672604068997BE32C55CEFA1E1C1CCCC9C8BE`.

`git apply --check C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub\handoff\T13-rootcurrent-consumer-v2.patch` from root returned exit 0; `git apply --stat` reported 2 files, 66 insertions, 11 deletions. Check was read-only; root files remain unchanged. Patch expects T08 producer APIs `inference_admission`, `inference_actions_active`, and `wait_for_inference_actions`; producer patch remains separately owned by T08. No root tests or integration run.
