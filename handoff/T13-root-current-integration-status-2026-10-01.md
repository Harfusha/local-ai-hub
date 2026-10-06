# T13 root-current integration status — 2026-10-01

Candidate `6050c41ce5510a6de3eaeb674a180560ea404f24`; root `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.

## Read-only apply checks

Ran `git apply --check` against `C:\Users\Adam\.local-ai-hub`. No root files changed.

- PASS `T13-async-schema-root-current.patch` — SHA-256 `3CC52080639C106503A71968897D5ABC58273967B9BA740AAC45B4FC51C0D25E`.
- PASS `T13-async-batch-test-finally-root-current.patch` — SHA-256 `8C49DA1E22E99C3D1790ABAD61DD1F79CE0FA497EF754247D3594577ECCCA6D4`.
- FAIL `T13-async-status-root-current.patch`, `T13-conversation-route-guards-root-current.patch`, `T13-conversations-root-current.patch`, `T13-conversations-source-root-current.patch`, `T13-lifecycle-root.patch`, `T13-operational-mode-root.patch`, and `T13-root-accelerator-release-lifecycle.patch`.
- Failures are context mismatches in root's concurrently changed `projection.py`, `mcp_server.py`, `services.py`, `http_server.py`, `conversations.py`, `async_jobs.py`, and `operational_mode.py`. Do not apply stale patches or replace root mode module.

## Integration boundary

Candidate contains T13 gaming-release, async admission/drain, Ollama verification, in-process accelerator release, and Whisper cancellation changes. New regression tests cover missing admission APIs, unverified Whisper cleanup, and conversation cancellation during gaming transition. Root already has operational-mode state, HTTP/MCP gates, and bounded Ollama unload, but not all candidate release-ownership behavior. Root files are heavily dirty across other task owners; integrate only after exact hunk ownership and current-source review.

Root-current comparison: root already has `ProcessCancelledError`, `cancel_event` polling in `run_hidden()`, Whisper cancellation argument, conversation reservation/expiry behavior, and empty conversation-task guards. Root lacks verified tree-cleanup reporting, conversation cancellation plumbing, active-call registries, and async-manager admission/release APIs. Root `/api/admin/mode` still calls async-job cancellation and runtime unload directly. Candidate gaming release code depends on manager methods absent from root (`begin_resource_release`, `wait_for_inference_actions`, `when_inference_actions_drained`, `inference_actions_active`). No root files changed.

## Root-current patch receipts

- PASS `handoff/T13-whisper-process-cleanup-root-current.patch` — SHA-256 `D2B793524F60043D4B4F1F770A1A3625BD01D0093676250D4A76D1642EE98A2B`; `git apply --check` against root worktree at HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a` passed. Contains only `process_utils.py` cleanup verification hunk.
- FAIL `handoff/T13-conversation-route-guards-root-current.patch` — SHA-256 `01D797D2E3477E11A65A4C6252CD0DCFDBC7E2FD566D4913BD752D438F8585DF`; service and HTTP route contexts drifted.
- FAIL `handoff/T13-conversations-source-root-current.patch` — SHA-256 `F5AE37BA842535FCA55D4277666799D33FAF61E68445AE2A6E8AD8AEF79BFE90`; conversation storage is already integrated differently in root.
- FAIL `handoff/T13-conversations-root-current.patch` — SHA-256 `69C931AE1018C8B45B548979BC8CE3A717A15484224F939E129351DA9C3BA9E8`; conversation storage/service/test hunks overlap root-current edits.
- FAIL `handoff/T13-root-accelerator-release-lifecycle.patch` — SHA-256 `BBA20DDAF1B5E137EA1332C31B05F90CFC703DADDCEEA77299D58DF2CBCE79CA`; HTTP mode handler context drifted.
- FAIL `handoff/T13-lifecycle-root.patch` — SHA-256 `669C2E56971A48874B1650ECFA70AF1E813B157F69EFB94C7EBD6E7C404EAAC5`; conversation, async manager, and test contexts overlap root-current changes.
- FAIL `handoff/T13-operational-mode-root.patch` — SHA-256 `1E08306CBBDD80840BFB9DA4AD284A028C4B143449F7C6618EE9589B69D24CB9`; mode core/tests already differ in root.

Conversation cancellation and admission/release need fresh root-owned hunks before an applyable patch is safe. Existing failed patches remain unchanged for audit; do not apply them.

`/api/search` and `/api/context/pack` route hunks remain untouched by T13 candidate changes. Keep both outside any integration patch.

## Validation / blocker

`git diff --check` passed in candidate; only line-ending warnings. No tests/builds run. T01 owns the exclusive test slot; wait for T20 assignment before running tests. The token-economizer `ensure-tools.ps1` path is unavailable in this environment, and Local AI Hub repository/command tools are not exposed here.

Pending test selectors after T20 assigns slot: `tests/test_operational_mode_http.py::test_gaming_fails_closed_when_admission_tracking_is_unavailable`, `tests/test_operational_mode_http.py::test_gaming_keeps_release_token_when_whisper_cleanup_is_unverified`, `tests/test_operational_mode_http.py::test_unverified_whisper_cleanup_keeps_registry_active`; `tests/test_whisper_cancellation.py::test_run_hidden_reports_unverified_cleanup_when_child_tree_survives`, `tests/test_whisper_cancellation.py::test_transcribe_propagates_unverified_process_cleanup_without_success_fallback`; `tests/test_conversation_continue_route_contract.py::test_gaming_cancels_active_conversation_before_unload`, `tests/test_conversation_continue_route_contract.py::test_gaming_skips_unload_when_conversation_ignores_cancellation`.

Pending runtime proof: real child/process-tree termination and observed exit, real Whisper cleanup failure behavior, live cancellable generation returning before unload, timeout path skipping unload, and async admission/release ownership under a gaming transition.

## Source review findings

- Candidate fixes fail closed when admission tracking is unavailable, retains release ownership when drain callbacks are unavailable, reports unverified Whisper cleanup, and holds the transcription registry active until process exit is observed.
- Candidate passes cancellation events through `/api/delegate` conversation and `/api/conversations/continue`; gaming sets the event and waits boundedly before unload. Non-interruptible generation causes timeout and skips unload.
- No findings in conversation tenant/turn locking. No edits or tests by read-only reviewers.
