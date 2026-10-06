# T17 root-current handoff — 2026-10-03

Root: C:\Users\Adam\.local-ai-hub. Root unchanged in this pass. /api/context/pack excluded.

## Root-present patch receipts

Reverse git apply --check against root returned PASS:

| Patch | SHA-256 | Scope |
|---|---|---|
| t17-vision-mismatch-root-current-v2.patch | 23226a9abeb2214ad8944f9a1540681d2654d630a62d1da51417a4ab3352c0fa | vision parser + tests |
| t17-browser-active-tab-root-current-v5.patch | a5d82b2ce80fd0db5015abf45b2fe06992243d0e3c1077f893cba333e5819ad6 | browser background + fixture |
| t17-browser-background-fixture-root-current.patch | 4c5a1714b0c8dac1b715a90911d032bf895d0fd22efe777f7617ff44127a08f0 | browser fixture tests |
| t17-browser-harness-root-current-v2.patch | e3c68c130731dd22657772035f681a4fee68485b27e65600e505880d2e1b9323 | harness + HTTP vision route tests |
| t17-multimodal-acceptance-root-current-v4.patch | 87ac0c9db80eb41d2cf5f43fbd93cd42c6e4cdac2fe01fcb2d3d98616bf8315e | browser fixture + HTTP route + transcription tests |
| t17-vision-bbox-root-current.patch | 4e9274e0bfa1d464f82f091a1c4aa0a5a8967aaf02c0a94390ff8ccd402ec42c | service callsite + vision service tests |
| t17-transcribe-stderr-root-current.patch | b976a325e5b77d42740ad0cf65cace7e43f06ce8b0d183224a13cf67f685f2cb | transcription service/tests |
| t17-transcribe-route-fixture-root-current-v1.patch | 431656d385be76e22e523da37126ed1df23a1c8366474f4eb5713bafe9a08966 | transcription route fixture |
| t17-whisper-cancellation-cleanup-assertion-root-current.patch | f03eeed5f63c339ca2e7c8a24b9b1b9af6bca47cfac8343b4a549ac6491fa6f3 | transcription cleanup assertion |

Stale/nonmatching patches excluded: browser-disconnect, browser-root-current, whisper-cancellation source/tests, vision-transcribe-malformed-cancel. Reverse checks failed; these are not root-present receipts.

## Missing T17-owned root-current deltas, prepared only

No patch applied to root.

1. handoff/t17-hypothesized-root-current-v1.patch
   - SHA-256: d89f9accbd56457f32d8cb5add07ceff82a8c9f43d0f66545db2eda30b27ff05
   - Adds offline regression for live output missing hypothesized.
   - Root test preimage SHA-256: ad98c5ca24987c01a5cffe0cfebf89a12076fb3cdf152b6a491ec66d2d0711c2
   - Postimage SHA-256: 583c760fa84b099775fac4da0c32e71e144d0d5cb38c606ab8f3b96994d4858b
   - Root git apply --check: PASS; temporary exact postimage check: PASS.

2. handoff/t17-transcribe-invalid-request-root-current-v1.patch
   - SHA-256: 9232ee558218ef309a4f576e4fa5a01592fb26f65843f8c9698d9d90fd4103ac
   - Adds non-object request guard inside LocalAIServices.transcribe() only; adds two contract tests for non-object request and invalid language.
   - Root preimages: services.py 525565a42b626a7ed2a66ade57c6878d1802b430f2d1bd5a2818b7ada68d3179; transcription tests d37ca57154d5323ad8bd55cc9dc23d2fb5c205e392fd2ed1d72f66d65cdbdab5.
   - Postimages: services.py 58908c5c718a520463171b7890c0b8e1e7f7cc54d5ef62f9809be707efc173fe; tests 7b917ad18d0266ce879262bae85c3f1729a279c6a2be26ed036c1aa0009d3e3c.
   - Root git apply --check: PASS; temporary exact postimage check: PASS.
   - Existing root ProcessCleanupUnverifiedError handling preserved.

## Exact offline test receipts

All below predate T04 completion; not post-T04 acceptance.

- Execution 9882bf, exit 0, 105 passed:
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_contracts.py tests/test_vision_service.py
- Execution 7b0cc6, exit 0, 9 passed:
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_browser_bridge.py::test_staged_capture_requires_explicit_commit_and_abandon_is_terminal tests/test_browser_bridge.py::test_abandon_cancels_inflight_commit_before_artifact_write tests/test_browser_bridge.py::test_expiry_cancels_inflight_commit_before_artifact_write tests/test_browser_bridge.py::test_extension_abandons_stage_when_tab_or_document_changes_before_commit tests/test_browser_bridge.py::test_extension_reconciles_commit_when_response_is_lost tests/test_browser_bridge.py::test_extension_reconciles_commit_after_http_5xx_response tests/test_browser_bridge.py::test_extension_does_not_cancel_commit_when_both_responses_are_lost tests/test_browser_bridge.py::test_extension_treats_malformed_commit_response_as_unknown
- Execution 25fc5f, exit 0, 1 passed:
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_contracts.py::test_grounded_vision_rejects_live_output_missing_hypothesized
- Earlier candidate receipt: python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_transcription_contract.py — 25 passed, 11.74 s. No execution ID recorded; not current-root/post-T04 receipt.
- T04 latest receipt says finished; test slot released to T01. No tests run here after T04.

## Runtime quality — separate

- Browser installed-extension/activeTab/user gesture: NOT VERIFIED.
- Whisper WER acceptance: NOT VERIFIED. Prior synthetic CPU smoke only: 15 English words, reported WER 0.0; not natural/multilingual acceptance.
- Live vision model: NOT ACCEPTED. Earlier live output failed required hypothesized; no model loaded during critical VRAM incident.


## Refresh — root hashes and latest offline runs

Root HEAD: 7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf. Root tracked source/test files unchanged by this pass.

Current root file SHA-256:
- src/local_ai_hub/vision_contracts.py: 048dd7ea1a464401cbe7a8fce421cb07711763809bd7a177ea40fb196ed18f6c
- tests/test_vision_contracts.py: ad98c5ca24987c01a5cffe0cfebf89a12076fb3cdf152b6a491ec66d2d0711c2
- src/local_ai_hub/services.py: 525565a42b626a7ed2a66ade57c6878d1802b430f2d1bd5a2818b7ada68d3179
- tests/test_transcription_contract.py: d37ca57154d5323ad8bd55cc9dc23d2fb5c205e392fd2ed1d72f66d65cdbdab5
- browser_bridge/background.js: 804e8a497c7c9a879ce7def0de7317cb1b05db60f596280509606491263f57fd
- tests/test_browser_bridge.py: d3bc3318f9d42652a7ca5b7886bcd0ae9ebf9a2e2d63511fa55ae01865747631
- tests/test_browser_bridge_background.js: a0d4130e70c990e071c6a47f96a26274b151849d25bc083ce43c42f45f806c5e

Current root reverse-check confirmed PASS for all nine patches listed under Root-present patch receipts above. Prepared missing deltas remain unapplied.

Root offline bundle — execution ae3439 — exit 1: 136 passed, 1 failed in 11.00 s. Exact command:

    python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_contracts.py tests/test_vision_service.py tests/test_transcription_contract.py tests/test_browser_bridge.py::test_staged_capture_requires_explicit_commit_and_abandon_is_terminal tests/test_browser_bridge.py::test_abandon_cancels_inflight_commit_before_artifact_write tests/test_browser_bridge.py::test_expiry_cancels_inflight_commit_before_artifact_write tests/test_browser_bridge.py::test_extension_abandons_stage_when_tab_or_document_changes_before_commit tests/test_browser_bridge.py::test_extension_reconciles_commit_when_response_is_lost tests/test_browser_bridge.py::test_extension_reconciles_commit_after_http_5xx_response tests/test_browser_bridge.py::test_extension_does_not_cancel_commit_when_both_responses_are_lost tests/test_browser_bridge.py::test_extension_treats_malformed_commit_response_as_unknown tests/test_process_utils.py::test_run_hidden_cancellation_terminates_tree_and_drains_output tests/test_process_utils.py::test_run_hidden_bounds_drain_when_descendant_keeps_pipes_open tests/test_process_utils.py::test_run_hidden_cancellation_terminates_process_tree

Failure: tests/test_transcription_contract.py::test_http_transcribe_route_preserves_requested_model. Route now returns request_id; exact-dict fixture does not expect it. No route/test ownership edit made.

Root T17 bundle excluding only that route selector — execution 1d320f — exit 0, 136 passed, 1 deselected in 5.96 s. Exact command:

    python -B -m pytest -q -p no:cacheprovider --tb=short --deselect=tests/test_transcription_contract.py::test_http_transcribe_route_preserves_requested_model tests/test_vision_contracts.py tests/test_vision_service.py tests/test_transcription_contract.py tests/test_browser_bridge.py::test_staged_capture_requires_explicit_commit_and_abandon_is_terminal tests/test_browser_bridge.py::test_abandon_cancels_inflight_commit_before_artifact_write tests/test_browser_bridge.py::test_expiry_cancels_inflight_commit_before_artifact_write tests/test_browser_bridge.py::test_extension_abandons_stage_when_tab_or_document_changes_before_commit tests/test_browser_bridge.py::test_extension_reconciles_commit_when_response_is_lost tests/test_browser_bridge.py::test_extension_reconciles_commit_after_http_5xx_response tests/test_browser_bridge.py::test_extension_does_not_cancel_commit_when_both_responses_are_lost tests/test_browser_bridge.py::test_extension_treats_malformed_commit_response_as_unknown tests/test_process_utils.py::test_run_hidden_cancellation_terminates_tree_and_drains_output tests/test_process_utils.py::test_run_hidden_bounds_drain_when_descendant_keeps_pipes_open tests/test_process_utils.py::test_run_hidden_cancellation_terminates_process_tree

Candidate-only new T17 contracts — execution 9848ae — exit 0, 5 passed in 0.43 s. Exact command:

    python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_contracts.py::test_grounded_vision_rejects_live_output_missing_hypothesized tests/test_transcription_contract.py::test_transcribe_rejects_non_object_request_payload tests/test_transcription_contract.py::test_transcribe_rejects_non_string_language_hint_before_running_whisper

Runtime remains separate: installed browser extension NOT VERIFIED; real/natural or multilingual Whisper WER NOT VERIFIED (old synthetic CPU 15-word smoke is limited); live vision NOT ACCEPTED. No model loaded.


## Consolidated missing-source patch

Prepared only, not applied: handoff/t17-missing-owned-root-current-v2.patch
SHA-256: 56200ea64f4032a36c27f18a014e3ff5b505dec4d66dd343af50860a3f2c12b2
Root apply-check: PASS. Temporary application also matched exact postimage hashes.

Included T17-owned files only:
- tests/test_vision_contracts.py: root preimage ad98c5ca24987c01a5cffe0cfebf89a12076fb3cdf152b6a491ec66d2d0711c2; postimage 583c760fa84b099775fac4da0c32e71e144d0d5cb38c606ab8f3b96994d4858b.
- src/local_ai_hub/services.py: root preimage 525565a42b626a7ed2a66ade57c6878d1802b430f2d1bd5a2818b7ada68d3179; postimage 58908c5c718a520463171b7890c0b8e1e7f7cc54d5ef62f9809be707efc173fe.
- tests/test_transcription_contract.py: root preimage d37ca57154d5323ad8bd55cc9dc23d2fb5c205e392fd2ed1d72f66d65cdbdab5; postimage 7b917ad18d0266ce879262bae85c3f1729a279c6a2be26ed036c1aa0009d3e3c.

Adds only hypothesized-missing vision regression, transcribe non-object request guard, and two input contract tests. No root files written.

## Evidence classes

Automated offline tests:
- root bundle 136 passed, 1 failed (execution ae3439); failing transcription HTTP fixture expects exact dict without request_id.
- root bundle excluding only that selector: 136 passed, 1 deselected (execution 1d320f).
- candidate-only new contracts: 5 passed (execution 9848ae).
- No tests run while preparing consolidated patch; next gate after shared test slot clears.

Runtime/model quality:
- installed browser extension: NOT VERIFIED.
- Whisper acceptance WER: NOT VERIFIED; prior synthetic CPU 15-word smoke only.
- live vision: NOT ACCEPTED; no model loaded.

## Next offline gate — selectors only, not run

Slot clearance remains unconfirmed: T01 is idle and reports it did not run pytest; T02 is notLoaded and its latest receipt says its test slot was not used. Following the active instruction, no tests run in this pass.

Candidate command after explicit shared-slot clearance:

    python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_contracts.py tests/test_vision_service.py tests/test_transcription_contract.py tests/test_browser_bridge.py::test_staged_capture_requires_explicit_commit_and_abandon_is_terminal tests/test_browser_bridge.py::test_abandon_cancels_inflight_commit_before_artifact_write tests/test_browser_bridge.py::test_expiry_cancels_inflight_commit_before_artifact_write tests/test_browser_bridge.py::test_extension_abandons_stage_when_tab_or_document_changes_before_commit tests/test_browser_bridge.py::test_extension_reconciles_commit_when_response_is_lost tests/test_browser_bridge.py::test_extension_reconciles_commit_after_http_5xx_response tests/test_browser_bridge.py::test_extension_does_not_cancel_commit_when_both_responses_are_lost tests/test_browser_bridge.py::test_extension_treats_malformed_commit_response_as_unknown tests/test_process_utils.py::test_run_hidden_cancellation_terminates_tree_and_drains_output tests/test_process_utils.py::test_run_hidden_bounds_drain_when_descendant_keeps_pipes_open tests/test_process_utils.py::test_run_hidden_cancellation_terminates_process_tree

This candidate run covers existing vision/audio contracts, browser commit lifecycle, and subprocess cancellation. It does not prove installed-extension behavior, human speech WER, or live vision quality. Root-only transcription HTTP request_id mismatch remains a separate failed fixture receipt.

## Current root refresh — patch already present

Observed current root SHA state matches the postimages of t17-missing-owned-root-current-v2.patch. This agent did not write root in this refresh.

- Combined patch SHA-256 56200ea64f4032a36c27f18a014e3ff5b505dec4d66dd343af50860a3f2c12b2: reverse apply-check PASS. Forward apply-check fails because hunks are already present; do not apply again.
- src/local_ai_hub/services.py current SHA-256 58908c5c718a520463171b7890c0b8e1e7f7cc54d5ef62f9809be707efc173fe; exact patch scope remains transcribe() guard only.
- tests/test_transcription_contract.py current SHA-256 7b917ad18d0266ce879262bae85c3f1729a279c6a2be26ed036c1aa0009d3e3c.
- tests/test_vision_contracts.py current SHA-256 583c760fa84b099775fac4da0c32e71e144d0d5cb38c606ab8f3b96994d4858b.
- vision_contracts.py parser source hunk reverse-check PASS. Old vision mismatch patch test-file hunk no longer matches because hypothesized regression was appended; combined patch verifies current exact test postimage.
- Python AST parse: services.py PASS; vision_contracts.py PASS.

No tests run during this refresh. T01, T02, T04 all active in separate acceptance worktrees; shared test slot not clear. Existing automated receipts remain historical; rerun T17 candidate selectors after slot release.
