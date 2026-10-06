# T17 browser-flow committed synchronization

Scope: `C:/Users/Adam/.local-ai-hub/.worktrees/t17-browser-flow-20261004` only.
Owner: this synchronization task. User authorized native fallback after an existing terminal Hub failure, manual merge, and committing unfinished work. Hub was not retried. No root checkout/master mutation, stash, reset, clean, new worktree/chat, push, installation, or full release suite.

## Preservation and ancestry

- Existing branch reused: `codex/sync-t17-browser-flow-20261004-20261006`.
- Starting HEAD and original tracked-dirty checkpoint: `fbe44e0cda222cdbee06227b57f3b5d6f2bfd80f`.
- Original checkpoint retained: `refs/heads/codex/checkpoint-t17-browser-flow-20261004-dirty-20261006`.
- Starting HEAD additionally retained: `refs/heads/codex/checkpoint-t17-browser-flow-original-head-20261006`.
- Master pinned once: `fcbb1d6fa7347e9b918d030f4f99d058d9846a6c`, retained at `refs/heads/codex/checkpoint-t17-browser-flow-pinned-master-20261006`.
- Before merge, commit `19d9f312fa7be93292343de43fceed0a2033e39c` preserved all five ordinary untracked source/test files: `vision_inputs.py`, `vision_payload.py`, `vision_request.py`, `vision_runtime.py`, and `tests/test_vision_service_phases.py`. Retained at `refs/heads/codex/checkpoint-t17-browser-flow-all-source-20261006`.
- No other ordinary untracked source/tests/docs/handoffs were present. Existing tracked handoffs were retained through history and merge. Runtime/test artifacts under `.validation/t17-sync-20261006/` remain preserved locally and excluded from commits.

## Manual resolution

Nine conflicted files, 36 individually reviewed hunks: browser background, frontend review, services, vision contracts/request, browser Python/JS tests, vision contracts/service tests. Master request-ID matching, strict output schema, DOM observation-fact validation, numeric DOM IDs, image bounds, cancellation and process-tree cleanup were retained. Transcription retains master `run_hidden`, JSON output, language handling and cleanup/cancellation behavior rather than the historical direct subprocess/txt path.

The pinned master already contains the original T17 vision decomposition, phase tests and browser changes. Resolving duplicate class/helper/field definitions introduced by automatic merging leaves the entire staged tree byte-identical to pinned master before this note (`git diff --cached --quiet fcbb1d6f`, exit 0). Thus no T17 source/test work was silently replaced by another decomposition. `/api/context/pack` retains pinned master behavior; no T14 redesign.

CodeGraph removal is preserved exactly as pinned master. Existing standalone-tool documentation is retained; no managed CodeGraph backend is reintroduced. No Gemini preprocessing provider implementation exists in the pinned `preprocess.py`, nor in the original checkpoint's preprocessing source. Existing Gemini audit documentation is retained. A new provider cannot be claimed from agent manifests or audit prose; implementing one remains outside this merge-only task.

## Actual targeted checks

All commands ran in the assigned worktree with `PYTHONDONTWRITEBYTECODE=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONPATH=<worktree>/src`, and `TEMP`/`TMP=<worktree>/.validation/t17-sync-20261006`. Each pytest process was wrapped in `subprocess.run(..., timeout=...)`; no installs or live model calls. Test artifacts belong to this task and stay within the assigned worktree.

Common command: `python -m pytest -q --tb=short -p no:cacheprovider` plus the arguments below.

1. `--maxfail=5 --basetemp=.validation/t17-sync-20261006/pytest tests/test_vision_contracts.py tests/test_vision_service.py tests/test_vision_service_phases.py tests/test_frontend_review.py tests/test_frontend_coder_context.py tests/test_browser_bridge.py tests/test_browser_bridge_runtime.py tests/test_browser_artifact_atomicity.py` (180-second bound): **196 passed, 5 failed**, 12.32 s, exit 1; stopped at failure cap.
2. `--maxfail=5 --basetemp=.validation/t17-sync-20261006/safety-pytest tests/test_transcription_contract.py tests/test_process_utils.py tests/test_process_utils_timeout_cleanup.py tests/test_browser_artifact_atomicity.py tests/test_t19_codegraph_removal.py tests/test_codegraph_package_policy.py` (180-second bound): **39 passed, 5 failed**, 10.23 s, exit 1; stopped at failure cap.
3. Previously unexecuted files: `--maxfail=3 --basetemp=.validation/t17-sync-20261006/removal-pytest tests/test_process_utils_timeout_cleanup.py tests/test_browser_artifact_atomicity.py tests/test_t19_codegraph_removal.py tests/test_codegraph_package_policy.py` (120-second bound): **16 passed, 3 failed**, 1.62 s, exit 1; stopped at failure cap before package-policy file.
4. Previously unexecuted file: `--maxfail=3 --basetemp=.validation/t17-sync-20261006/package-pytest tests/test_codegraph_package_policy.py` (60-second bound): **5 passed, 1 failed**, 2.77 s, exit 1.

Total observed: **256 passed, 14 failed**. These are bounded partial runs, not whole-suite acceptance. Source/tests equal pinned master, so all observed failures are present in that pinned tree; no separate baseline suite was duplicated.

`git diff --check fcbb1d6f -- src tests browser_bridge` passed. Broad `git diff --cached --check` against the old checkpoint reported inherited whitespace/CRLF issues in master-imported files and historical handoff overlays; those were not reformatted. No unresolved index entries remained after manual staging. Token-economizer setup script was absent at both installed skill locations; no installation or PATH modification attempted.

## Outstanding behavior and test mismatches

- `test_vision_result_bounds_bbox_to_image_dimensions`: old xywh fixture conflicts with current left/top/right/bottom contract.
- `test_image_dimensions_reads_png_header`: synthetic PNG omits IHDR framing required by current header validation.
- `test_coder_packet_normalizes_parsed_finding_tuples`: parsed finding rejected without image dimensions; test indexes empty findings.
- `test_vision_image_only_response_matches_golden_contract`: golden response disagrees on empty artifact IDs and `observation_sources`.
- `test_actual_current_tab_fixture_preserves_login_and_never_falls_back`: harness commit receipt lacks `request_id`; current background rejects it as ambiguous. No validation was weakened.
- `test_whisper_process_failure_never_returns_successful_transcript[nonzero]`: result lacks expected `returncode`.
- `test_whisper_process_failure_never_returns_successful_transcript[timeout]`: result lacks expected `retryable`.
- `test_run_hidden_cancellation_terminates_tree_and_drains_output`: cleanup verification raises `ProcessCleanupUnverifiedError`.
- `test_terminate_tree_escalates_explicit_group_when_leader_exits` and `test_terminate_tree_does_not_signal_reused_pid_after_group_disappears`: mocked process-group cleanup returns false.
- `test_timeout_drain_escalates_group_before_rejoining_pipe_readers`: `cleanup_confirmed` false.
- `test_codegraph_is_absent_from_hub_runtime_configuration_and_telemetry` and `test_runtime_has_no_managed_codegraph_or_kuzu_references`: generator's standalone-removal guidance still contains the forbidden literal.
- `test_optional_codegraph_docs_use_current_gcf_extra_without_hub_integration`: expected documentation phrase missing.
- Gemini preprocessing runtime support, live browser/login behavior, live vision quality and installed service behavior remain unverified. Full release suite intentionally not run.

Synchronization and preservation are complete once this merge commit exists, pinned master is its ancestor, and index has no conflicts. Functional/release acceptance remains incomplete. The only final file changed versus pinned master is this integration note.
