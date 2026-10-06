# T13 candidate acceptance receipts — 2026-10-01

Candidate: `C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub`
Root integration: owned by T20; root was read-only in this task. No root, `mcp_server.py` T03, or `/api/context/pack` edits were made.

## Owner-scoped RED/GREEN

- Offline persistence: mutant `operational_mode.set_operational_mode` returned an in-memory revision without writing. `test_pause_and_resume_persist_offline_when_hub_is_unavailable` and the parameterized `test_offline_cli_persists_mode_under_configured_state_dir` failed (4 failed). Production GREEN is included below.
- File locking: no-op `_file_lock` mutant let the child writer complete while the parent held the lock. `test_file_lock_serializes_revision_update_across_processes` failed at the blocking assertion. Production GREEN is included below.
- Windows replace retry: single-attempt `_replace_with_retry` mutant failed `test_replace_retries_windows_sharing_violation` with `PermissionError`; production GREEN is included below.
- Preprocess pause/resume: `_operational_mode_paused` forced false mutant failed `test_mode_pause_blocks_next_preprocessing_step` and both restricted-mode cooperative-yield cases (3 failed, 4 passed). Production GREEN is included below.
- Conversation cancellation and drain: mutant skipped cancellation and returned a fabricated `cancelled` receipt; the end-to-end selector failed waiting for cancellation. A separate no-drain mutant cancelled the worker but returned before worker completion and bypassed admission drain; the test failed because unload was attempted while the worker-exit gate was held.

Focused production GREEN command selected:

```text
python -m pytest -q tests/test_operational_mode.py::test_file_lock_serializes_revision_update_across_processes tests/test_operational_mode.py::test_replace_retries_windows_sharing_violation tests/test_hubctl_operational_mode.py::test_pause_and_resume_persist_offline_when_hub_is_unavailable tests/test_t13_hubctl_offline_persistence.py::test_offline_cli_persists_mode_under_configured_state_dir tests/test_preprocess_operational_mode.py::test_mode_pause_blocks_next_preprocessing_step tests/test_preprocess_operational_mode.py::test_restricted_mode_pauses_background_worker_with_bounded_recheck tests/test_preprocess_operational_mode.py::test_cooperative_preprocess_yields_observe_restricted_mode tests/test_t13_gaming_conversation_release_receipt.py::test_gaming_release_receipt_includes_conversation_cancelled_before_snapshot
```

Result: **14 passed in 6.71s**. This is a focused mock-backed source test, not a full suite.

`git diff --check` on `src/local_ai_hub/http_server.py` and the strengthened conversation test passed; Git warned only that LF will be converted to CRLF on a future touch.

## Drain test change

`tests/test_t13_gaming_conversation_release_receipt.py` now gates worker exit after cancellation, records when unload is attempted, and holds the gate for 0.5s before permitting worker exit. The RED no-drain mutant confirmed this distinguishes premature unload from a drained release. Candidate `http_server.py` contains the previously recorded cancellation-receipt race fix; root integration remains with T20.

## Boundaries

- No full suite rerun; shared suite/acceptance remains T19's gate.
- No live Ollama, VRAM measurement, model unload, deployment, or hardware acceptance was performed. Runtime proof remains separate from these mocked tests.
- Local AI Hub `context`, `solve`, and command calls failed before transport write; one bounded health request returned `success=false`. The configured `token-economizer` setup script was absent from the supplied skill directory, so no install/setup was run.
- Mutant overlays used only for RED evidence remain under this candidate's `handoff/owner-red-*` scratch directories because automatic command review rejected recursive cleanup; no source files were changed by those overlays.
