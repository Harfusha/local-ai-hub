# T13 deterministic acceptance — 2026-10-01

## Scope and exact pins

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub`
- Candidate HEAD: `6050c41ce5510a6de3eaeb674a180560ea404f24`
- Candidate selected tracked diff SHA-256: `ad9549987fa4149b5969c26939067e353dbff09c9dc490504e7968812d7d838a`
- Root checkout: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; read-only this turn.

Candidate SHA-256 pins:

- `src/local_ai_hub/operational_mode.py`: `f243ea73bbf204da9401b234ae1c8f0c92750991e85d5bb8a5c88bc83d00bb74`
- `src/local_ai_hub/mcp_server.py`: `6f93d152e62d094c3aade320b6ab01e78d2f386bae3daed20b4f8da9489a6b00`
- `src/local_ai_hub/http_server.py`: `60d06c590fcf0a6550365d388edc9fb06c54f78b8319a4a20fbbf4e2767f2e06`
- `src/local_ai_hub/preprocess.py`: `bd1f0bb0cdea3ef93537f8722d9def31261dfce8d6c654ebecb0d6ead73bb58e`
- `src/local_ai_hub/client.py`: `c1b9b9ebb3f1ae14da619de8875310089d6603fdedbadbea34da9b9b040daf93`
- `tools/hubctl.py`: `78f2ce87a81554ae7a7231a348de59a8c84e72a48252b7164320c83c0f5dbf5f`

Root-current SHA-256 pins, read only:

- `src/local_ai_hub/operational_mode.py`: `b72023ed7bd029ea747794a02b5c8f6783e6dc592b4bf67542bdee63f5d1f5a1`
- `src/local_ai_hub/mcp_server.py`: `44205472eca30794493082930e2d1775bfd4d7f37d189f2289e61cb3783baebf`
- `src/local_ai_hub/http_server.py`: `6f0b986255dd231f40761538227a66f0a9b97f7659064952593fb83b48130db3`
- `src/local_ai_hub/preprocess.py`: `86715359388ca1598dde14c01ffcb4a23590263f99e13554d48502b50d4e961f`
- `src/local_ai_hub/client.py`: `5518706e0e81623e3ff0184274bd17f18c9bf7f43d9bc4dd37fd754586b0d056`
- `tools/hubctl.py`: `d587d80847152aa863a06d2850a60cbc2788409eb13ef94477dce1791b9758f6`

## Receipts

All commands used `python -B -m pytest -q -p no:cacheprovider --tb=short` with the listed exact nodes.

- Deterministic acceptance set: **47 passed in 7.78s**.
- Concurrent transition guard, `tests/test_operational_mode_http.py::test_post_gaming_reserves_release_before_exposing_mode_change`: **1 passed in 0.30s**.
- Prior focused T13 cancellation/release set remains: **48 passed in 1.21s**, recorded in `T13-focused-acceptance-2026-10-01.md`.

Acceptance covered persisted active/maintenance state, cross-process revision writes, transient and Windows replace retry bounds, HTTP mode/admin route parity, MCP retry/defer and deterministic-read behavior, HubClient idempotent retry, offline/live `hubctl` transitions, persisted pause/restart/resume, and CPU/GPU preprocessor pause/yield.

The 47-case run used these exact selectors:

- `tests/test_operational_mode.py`: `test_missing_state_defaults_to_active_and_updates_revision`, `test_corrupt_state_fails_closed_to_degraded_maintenance`, `test_cross_process_updates_increment_revision_without_lost_writes`, `test_replace_retries_transient_permission_error`, `test_replace_retries_windows_sharing_violation`, `test_replace_sharing_violation_retries_are_bounded`, `test_windows_open_mode_file_blocks_replace_and_preserves_previous_state`, `test_mcp_mode_gate_allows_deterministic_reads_only_outside_maintenance`.
- `tests/test_operational_mode_http.py`: `test_get_mode_returns_persisted_snapshot_for_loopback`, `test_admin_mode_control_remains_available_in_maintenance`, `test_mode_api_rejects_non_loopback_peer`, `test_mode_api_obeys_configured_api_token`, `test_post_gaming_persists_mode_reports_transition_and_unload`, `test_sync_inference_http_gate_retries_but_read_only_context_stays_unclassified`, `test_safe_agent_api_reads_block_only_in_maintenance_before_database_call`.
- `tests/test_mcp_agent_routing.py`: `test_safe_task_job_actions_block_in_maintenance_before_backend_transport`, `test_safe_task_job_actions_remain_available_in_gaming`, `test_other_agent_mcp_tools_block_in_maintenance_before_transport`, `test_mcp_gaming_defers_inference_with_bounded_retry`, `test_mcp_maintenance_blocks_agent_action_and_job_status_before_transport`, `test_mcp_repo_deterministic_read_passes_in_gaming`, `test_mcp_repo_adaptive_context_defers_in_restricted_modes`.
- `tests/test_client_transport.py::test_client_replays_duplicate_request_until_owner_finishes`.
- `tests/test_hubctl_operational_mode.py`: `test_pause_and_resume_persist_offline_when_hub_is_unavailable`, `test_mode_command_routes_live_transition_through_mode_api`, `test_mode_command_does_not_fallback_after_uncertain_live_transition`.
- `tests/test_preprocess_operational_mode.py`: `test_mode_pause_blocks_next_preprocessing_step`, `test_restricted_mode_pauses_background_worker_with_bounded_recheck`, `test_cooperative_preprocess_yields_observe_restricted_mode`.
- `tests/test_t13_mode_resume_matrix.py::test_persisted_pause_blocks_jobs_and_active_resume_dispatches_again`.

## Root-current parity drift

T13 candidate helper permits safe job actions in gaming only; root-current helper permits them in both gaming and maintenance. Candidate MCP tests still assert status is blocked in maintenance. Root-current acceptance was separately reported by T04: `test_maintenance_blocks_agent_action_but_preserves_job_status` passed in the shared 2-test run (2 passed in 5.51s).

No patch was created. Root already has the newer safe-job exception; a candidate patch would duplicate or regress root-current behavior. No root file was changed. `async_jobs.py` stayed outside T13 edits. No runtime, Ollama, CUDA, or measured VRAM claim is made; unload tests use fakes only.

Hub command broker was unavailable in this environment, so the focused pytest commands ran natively in the candidate worktree.
