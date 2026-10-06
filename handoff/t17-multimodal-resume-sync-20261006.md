# T17 preserved synchronization — 2026-10-06

## Ownership and committed state

Only assigned checkout: C:/Users/Adam/.codex/worktrees/t17-multimodal-resume/.local-ai-hub.
Branch: codex/sync-t17-multimodal-resume-20261006.
Original supplied checkpoint/entry HEAD: a9d9afe89c017cd47c06c424be7d18ee97ecb192.
That existing commit already preserved 24 tracked dirty paths; no tracked dirty paths remained at entry.

Owned recovery refs:
- refs/checkpoints/t17-multimodal-resume-sync-original-20261006 = a9d9afe89c017cd47c06c424be7d18ee97ecb192
- refs/checkpoints/t17-multimodal-resume-sync-master-20261006 = fcbb1d6fa7347e9b918d030f4f99d058d9846a6c
- refs/checkpoints/t17-multimodal-resume-sync-preserved-20261006 = 774d1d8cb38c5d76b811eeaaeff4466091657979

Pre-merge preservation commit 774d1d8c added all 74 ordinary untracked files: 72 handoff documents, patches, test/evidence scripts, plus vision_inputs.py and vision_response.py. Historical receipt documents are archived evidence, not fresh acceptance.
Merge commit: ef2d0316cc250c18268f49f8b5d080f6ed4d7fe0.
Parents: 774d1d8cb38c5d76b811eeaaeff4466091657979 and pinned master fcbb1d6fa7347e9b918d030f4f99d058d9846a6c.
This integration note is committed in the following handoff commit; its exact HEAD is reported separately.

No root checkout changes, master-ref updates, push, stash, reset, clean, new provider work, or new feature work.
Native fallback was explicitly authorized after the previously terminal Hub failure; no Hub retry or polling.
Token-economizer used bounded source slices and targeted patches. Its referenced ensure-tools.ps1 was absent; no tools installed or PATH modified.
An attempted read-only native subagent could not start because the agent thread limit was reached.

## Hunk reconciliation

15 conflicted paths were reconciled manually by behavior.
- Current master vision phases (vision_inputs, vision_request, vision_runtime, vision_payload) remain authoritative. Preserved standalone vision_response.py and its direct helper tests remain committed; services imports the current master helpers.
- process_utils.py, vision_contracts.py, frontend_review.py and live vision helper modules exactly match pinned master. Cleanup-unverified exceptions and ownership safeguards remain intact.
- transcribe() is AST-identical to pinned master: task-owned temporary output, invalid-audio rejection including stderr, cancellation, cleanup-unverified propagation, bounded process execution.
- HTTP _send preserves master admin auditing, transport normalization and response headers, plus inherited bounded request-ID correlation. do_GET/do_POST are AST-identical to master; T14 /api/context/pack was not edited or redesigned.
- Browser replay/malformed-commit tests from both sides remain; request-ID fixtures and stronger replay-body assertions are retained. browser_bridge/background.js matches master.
- Existing completion/draft/scaffold failure and validated=false changes remain, with their tests.
- Duplicate identical test definitions created by integration were removed, with all originals retained in checkpoint history. Distinct checkpoint variants were renamed so test collection cannot shadow them.
- Four older vision fixture expectations were aligned with current master: empty artifact IDs and observation_sources, ordered bounding boxes, valid PNG IHDR header, and image dimensions for image-only grounding.
- Gemini preprocessing, CodeGraph removal, configuration, repo_tools and INSTALL/UPDATE prompts match pinned master. No provider change was introduced.

## Actual targeted checks

All test temporary output was directed under this checkout: TEMP/TMP=.pytest_cache/t17-sync-runtime; PYTHONPATH=src; PYTHONDONTWRITEBYTECODE=1. No full release suite, install, live model inference, or real browser session.

Initial integration run (before vision fixture alignment and duplicate cleanup):
- python -B -m pytest -q --tb=short --basetemp=.pytest_cache/t17-sync-tests tests/test_vision_service.py tests/test_vision_service_phases.py tests/test_vision_contracts.py tests/test_transcription_contract.py tests/test_process_utils.py tests/test_frontend_review.py tests/test_frontend_coder_context.py tests/test_http_vision_routes.py tests/test_vision_artifacts.py tests/test_browser_bridge.py tests/test_browser_bridge_runtime.py tests/test_completion_model_routing.py tests/test_speculative_draft_and_split.py tests/test_missing_and_high_value_features.py -k "not benchmark"
- Exit 1: 324 passed, 16 failed, 79.69 seconds.

Changed-module follow-up:
- python -B -m pytest -q --tb=short --basetemp=.pytest_cache/t17-sync-reconcile-tests tests/test_vision_service.py tests/test_vision_contracts.py tests/test_transcription_contract.py tests/test_missing_and_high_value_features.py::test_audio_transcription_service tests/test_missing_and_high_value_features.py::test_audio_transcription_service_without_whisper_is_not_false_success
- Exit 1: 176 passed, 2 failed, 19.97 seconds. All vision fixtures in this selection passed.

Additional inherited routing/scaffold checks:
- python -B -m pytest -q -p no:cacheprovider --tb=short --basetemp=.pytest_cache/t17-sync-routing-tests tests/test_mcp_agent_routing.py::test_local_ai_task_transcribe_forwards_only_explicit_language_hint tests/test_cloud_model_accelerators.py::test_task_scaffold
- Exit 0: 3 passed, 3.67 seconds.

Static/Git:
- AST parse and no duplicate top-level definitions: services.py, http_server.py, process_utils.py, vision_contracts.py, vision_response.py, test_vision_service.py, test_vision_contracts.py, test_transcription_contract.py.
- Exact pinned-master path comparisons and AST equality for transcribe(), do_GET(), do_POST() passed.
- git diff --check fcbb1d6f -- src tests browser_bridge passed.
- After merge commit: git merge-base --is-ancestor fcbb1d6fa7347e9b918d030f4f99d058d9846a6c HEAD exited 0; unmerged path count 0; tracked/ordinary-untracked status clean.

## Outstanding behavior and acceptance

Synchronization is committed; acceptance is incomplete. Do not treat archived receipts or passing mocked contracts as live acceptance.

Latest follow-up failures:
- test_whisper_process_failure_never_returns_successful_transcript[nonzero]: current master service omits returncode; fixture also expects stderr text "decoder failed" rather than generic status error.
- Same test [timeout]: current master service omits retryable. Error fields were not invented or master behavior weakened during integration.

Other initial-run failures remain unresolved and were not rerun after unrelated fixture changes:
- Seven process fixtures: cancellation_terminates_tree_and_drains_output; terminate_tree_escalates_explicit_group_when_leader_exits; terminate_tree_does_not_signal_reused_pid_after_group_disappears; terminate_tree_does_not_escalate_after_group_disappears; terminate_tree_stops_when_group_liveness_is_unverifiable; terminate_tree_does_not_escalate_when_group_liveness_returns_eperm; run_hidden_bounds_drain_when_descendant_keeps_pipes_open. Current master safety code is unchanged. These fake cleanup/group fixtures do not satisfy the stricter ownership/cleanup contract; broader platform acceptance remains unfinished.
- test_speculative_draft_service: expected temporary directory root differs from canonical enclosing checkout root.
- test_command_broker_lint_fix_and_daemon_lifecycle: outdated argv/mock shape expectation.
- test_process_utils_git_worktree_lifecycle: worktree creation returned success=false. The test initialized a fixture repository inside .pytest_cache/t17-sync-tests but failed before any new worktree was created. It was not rerun.
- No fresh live vision quality, real audio/WER, real browser authorization/capture, performance, deployment, or release proof.

## Runtime/generated artifacts excluded from Git

Initial ignored inventory: .pytest_cache 5 files; .serena 5 files; source bytecode 102; test bytecode 236; tools bytecode 6. Preserved untouched; not added to Git.
Current task-generated ignored roots, retained on disk:
- .pytest_cache/t17-sync-tests/ — 460 ignored files at inventory, including fixture audio/config/state, the fixture Git repository, and test runtime artifacts.
- .pytest_cache/t17-sync-reconcile-tests/ — 270 ignored files.
- .pytest_cache/t17-sync-routing-tests/ — 3 ignored files.
- .pytest_cache/t17-sync-runtime/ — 2 ignored files.
- .pytest_cache/v/cache/ — pytest metadata; may contain earlier runs, not a standalone acceptance receipt.
Exact runtime log found outside Git: .pytest_cache/t17-sync-tests/test_browser_stage_commit_and_0/state/logs/hub.log.
No separately generated receipt JSON/JSONL was found among ignored files in this assigned checkout. No external state directory was searched or modified. Historical receipt markdown in handoff/ was intentionally preserved as ordinary documentation.
No generated cache, runtime state, log, or bytecode was newly committed.

## Changed files versus pinned master

16 source/test files:
- src/local_ai_hub/http_server.py
- src/local_ai_hub/services.py
- src/local_ai_hub/vision_response.py
- tests/fixtures/browser_bridge/current_tab_harness.js
- tests/test_browser_bridge.py
- tests/test_browser_bridge_background.js
- tests/test_cloud_model_accelerators.py
- tests/test_completion_model_routing.py
- tests/test_frontend_coder_context.py
- tests/test_frontend_review.py
- tests/test_mcp_agent_routing.py
- tests/test_missing_and_high_value_features.py
- tests/test_speculative_draft_and_split.py
- tests/test_transcription_contract.py
- tests/test_vision_contracts.py
- tests/test_vision_service.py

72 originally untracked handoff files, plus this integration note. Exact complete list: git diff --name-only fcbb1d6fa7347e9b918d030f4f99d058d9846a6c HEAD.
vision_inputs.py was checkpointed before merge and matches master in the result.
