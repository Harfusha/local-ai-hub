# T17 vision refactor: preserved manual synchronization

Status: committed integration candidate, unfinished acceptance. No release claim.

## Ownership and preservation

- Assigned checkout only: `C:/Users/Adam/.codex/worktrees/t17-vision-refactor/.local-ai-hub`.
- Branch: `codex/sync-t17-vision-refactor-20261006`.
- Original clean HEAD: `2b33602a`, retained as `codex/checkpoint-t17-vision-refactor-original-20261006`.
- Existing tracked dirty checkpoint: `7951ebff15e335ac4a0f9634dd6596152cb10704`, ref `codex/checkpoint-t17-vision-refactor-dirty-20261006`.
- Original untracked handoff preserved by `fad072f3416a3a504efe2b43b981586958bcb23f`, retained as `codex/checkpoint-t17-vision-refactor-premerge-20261006`.
- Merge target pinned once: `a83e27707cebf94a51418170e6957d8df1a4d44b`, ref `codex/checkpoint-t17-vision-refactor-pinned-master-20261006`.
- Initial checkout had no remaining tracked dirty or ordinary untracked paths. No stash, clean, reset, root checkout edits, master-ref writes, push, new worktree, or new chat.
- Git branch/checkpoint/index/merge administration uses the assigned worktree's existing shared Git metadata. No other branch was mutated.
- User reports preceding Hub terminal failure and explicitly authorizes native fallback without retry/poll. Original Hub action/envelope/evidence IDs were not supplied in this continuation; no new Hub receipt is claimed.
- `token-economizer` bounded reads/outputs applied. Its specified `ensure-tools.ps1` was unavailable; no tools installed or PATH changed. Native delegation could not start: `collab spawn failed: agent thread limit reached`.

## Reconciliation decisions

- Reviewed individual conflict hunks in nine files; retained master's vision input/request/runtime/payload decomposition.
- Kept branch request validation, cancellation before/after provider calls, default structured schema when Ollama enabled, strict field types, bounded prompt/output, exact DOM fact validation, canonical evidence anchors, and numeric DOM ID handling excluding booleans.
- Retained master checks that facts support observed/evidence text and cannot contradict explicit expected-value mismatch claims. Preserved master recognition of actual HTML tags so visible `<Enter>` text is not DOM markup.
- Bbox uses `[left, top, right, bottom]`, matching master's prompt and preserved branch contracts. Reject empty/outside regions and missing image dimensions.
- Consolidated duplicate image header functions: branch PNG IHDR validation and JPEG marker handling, master GIF/WebP support. Consolidated duplicate dataclass fields and observation-fact keyword arguments introduced by textual merging.
- `process_utils.py` is byte-identical to pinned master: verified cleanup outcomes and fail-closed child-tree termination retained. Branch cancellation test remains committed even though its fake process does not satisfy current cleanup confirmation.
- Transcription retains master's nested missing-CLI handling and decode-skip detection plus branch contract tests. Existing error envelope/test disagreements remain explicitly unfinished.
- `http_server.py`, `repo_tools.py`, `preprocess.py`, `config.py`, `docs/INSTALL_PROMPT.md`, and `docs/UPDATE_PROMPT.md` unchanged relative to pinned master. T14 `/api/context/pack` received no redesign or edits. Master preprocessing/provider behavior retained; Gemini execution not verified. Inherited install/update notes report no Gemini preprocessing implementation at their earlier pin; that discrepancy was not repaired or reinterpreted as runtime proof.
- CodeGraph runtime source was not reintroduced. Master still contains a `.codegraphcontext` scan-ignore string; its removal test currently treats that string as a failure.

## Actual targeted checks

All test subprocesses bounded by explicit timeouts. Owner: this integration task. Python bytecode and pytest cache disabled; temporary files and test SQLite state confined through TEMP/TMP and basetemp to assigned `.t17-merge-tmp/`. That generated directory is intentionally preserved, untracked, excluded from this commit. No full release suite, installs, real-model inference, audio-quality benchmark, or browser acceptance.

1. Initial targeted command (180-second bound):
   `python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=.t17-merge-tmp/pytest tests/test_process_utils.py tests/test_transcription_contract.py tests/test_vision_contracts.py tests/test_vision_service.py tests/test_vision_artifacts.py tests/test_http_vision_routes.py`
   Exit 1: **18 failed, 222 passed in 38.68s**. Stderr: `prewarm skipped: local model backend unavailable`.
2. After image-helper/markup/HTTP assertion reconciliation (150-second bound):
   `python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=.t17-merge-tmp/vision-final tests/test_vision_contracts.py tests/test_vision_service.py tests/test_http_vision_routes.py tests/test_t19_codegraph_removal.py`
   Exit 1: **5 failed, 143 passed in 26.50s**. No inference was required.
3. Five edited source modules parsed by `ast.parse`; no duplicate function/class definitions within module/class scopes. `git diff --check` passed. An earlier diagnostic invocation had a shell-quoting `SyntaxError: unterminated string literal`; corrected invocation above passed. This was a diagnostic-command failure, not a source syntax failure.

## Outstanding failure receipts

Unchanged process/transcription paths were not rerun after vision-only fixes. Their nine initial failures remain outstanding:

- `tests/test_process_utils.py::test_run_hidden_cancellation_terminates_tree_and_drains_output`: `ProcessCleanupUnverifiedError: process cleanup could not be verified`.
- `tests/test_process_utils.py::test_terminate_tree_escalates_explicit_group_when_leader_exits`: expected true; returned false.
- `tests/test_process_utils.py::test_terminate_tree_does_not_signal_reused_pid_after_group_disappears`: expected true; returned false.
- `tests/test_process_utils.py::test_terminate_tree_does_not_escalate_after_group_disappears`: expected true; returned false.
- `tests/test_process_utils.py::test_terminate_tree_stops_when_group_liveness_is_unverifiable`: expected SIGTERM/group probe calls; actual `[]`.
- `tests/test_process_utils.py::test_terminate_tree_does_not_escalate_when_group_liveness_returns_eperm`: expected SIGTERM/group probe calls; actual `[]`.
- `tests/test_process_utils.py::test_run_hidden_bounds_drain_when_descendant_keeps_pipes_open`: `process.stdout.closed` false.
- `tests/test_transcription_contract.py::test_whisper_process_failure_never_returns_successful_transcript[nonzero]`: `KeyError: 'returncode'` (current error is exit-status text, test expects stderr `decoder failed`).
- `tests/test_transcription_contract.py::test_whisper_process_failure_never_returns_successful_transcript[timeout]`: `KeyError: 'retryable'`.

Five failures in the final targeted invocation:

- `tests/test_vision_contracts.py::test_vision_result_bounds_bbox_to_image_dimensions`: expects `image dimensions`; actual `bbox must describe a non-empty image region` (fixture uses old width/height interpretation).
- `tests/test_vision_contracts.py::test_image_dimensions_reads_png_header`: fixture lacks valid IHDR length/type; expected `(640, 480)`, actual `None`. Strict branch PNG validation retained.
- `tests/test_vision_contracts.py::test_coder_packet_normalizes_parsed_finding_tuples`: bbox parse without supplied image dimensions rejects fixture, causing `IndexError: tuple index out of range`.
- `tests/test_vision_service.py::test_vision_image_only_response_matches_golden_contract`: artifact IDs actual empty strings versus expected None; review additionally contains `observation_sources: None`.
- `tests/test_t19_codegraph_removal.py::test_codegraph_is_absent_from_hub_runtime_configuration_and_telemetry`: `AssertionError: repo_tools.py`; `.codegraphcontext` ignore entry triggers textual check. Master's file retained exactly.

Initial failures subsequently resolved in affected paths: GIF header parsing, WebP header parsing, every-cited-element error wording, `<Enter>` markup classification, and HTTP review request-ID assertion. No broad acceptance inferred from these passes.

## Files changed versus pinned master

- `handoff/t28-vision-decomposition-root-preimage-map-2026-10-03.md` (preserved original untracked handoff)
- `handoff/t17-vision-refactor-sync-20261006.md` (this integration record)
- `src/local_ai_hub/frontend_review.py`
- `src/local_ai_hub/services.py`
- `src/local_ai_hub/vision_contracts.py`
- `src/local_ai_hub/vision_request.py`
- `tests/test_http_vision_routes.py`
- `tests/test_process_utils.py`
- `tests/test_transcription_contract.py`
- `tests/test_vision_artifacts.py`
- `tests/test_vision_contracts.py`
- `tests/test_vision_service.py`

Merge commit: `ed26221bccf023e271c779aec63555b5253d3223`, parents `fad072f3416a3a504efe2b43b981586958bcb23f` and `a83e27707cebf94a51418170e6957d8df1a4d44b`. A documentation-only follow-up records these post-commit receipts; final HEAD is reported at handoff.

Post-merge `git merge-base --is-ancestor a83e27707cebf94a51418170e6957d8df1a4d44b HEAD` returned 0. `git ls-files -u` empty. Tracked checkout clean; only preserved generated `.t17-merge-tmp/` untracked. `git diff --check a83e27707cebf94a51418170e6957d8df1a4d44b HEAD` returned 0; 12 changed files versus pinned master.

The broader pre-commit `git diff --cached --check` did fail on inherited master content relative to old branch HEAD, including `.handoff/T12-model-free-root-overlay-20261001/src/local_ai_hub/cache.py:299: trailing whitespace` and many archived/CRLF paths. Its output was excessively large; later check captured and bounded output and scoped comparison to pinned master. Those inherited paths were not changed to silence the check. Historical receipts remain preserved, not treated as current acceptance.
