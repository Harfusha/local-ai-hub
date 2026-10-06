# T17 candidate acceptance receipt — 2026-10-03

## Checkout and ownership

- Candidate: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`
- HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`
- Root/T20 checkout was not edited; no commit created.
- Candidate had 23 tracked modified paths plus untracked `handoff/` before this receipt. Preserve all inherited changes.
- `services.py` is mixed-owner and 438 additions / 40 deletions in candidate. This turn did not edit it. Prior user authorization covers only `LocalAIServices.transcribe()` and the `vision()` parser callsite; do not transfer the whole file.
- `/api/context/pack` remains excluded and untouched.

## Change in this turn

- `handoff/t17-browser-adapter-live-e2e.mjs`: successful fake commit response now echoes `payload.request_id`, matching candidate response binding in `browser_bridge/background.js`.
- Exact incremental patch: `handoff/t17-browser-adapter-request-id.patch`.
- SHA-256: `C62A88A7F3380317E1A501CB62673D4C9D43D4BEDFE194B987B0196331EA03CD`.
- `handoff/t17-live-vision-evidence.py`: reproducible local model smoke using temporary Edge screenshot, direct local Ollama endpoint, no Hub/config. SHA-256: `A681314DA2BF44F926BA39BF1493077E962F2AB846832AD067981309FC50FE67`.
- Existing candidate already had the authorized transcription implementation and `observation_sources` parser callsite. No source or test file was edited in this turn.

## Focused checks

- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_transcription_contract.py` — exit 0, 25 passed in 11.74 s.
- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_service.py::test_vision_accepts_dom_id_from_supplied_frontend_context tests/test_vision_service.py::test_vision_rejects_dom_observation_fact_that_mismatches_supplied_source tests/test_vision_contracts.py::test_grounded_vision_rejects_dom_ids_absent_from_supplied_dom tests/test_vision_contracts.py::test_grounded_vision_accepts_observation_fact_matching_cited_dom tests/test_vision_contracts.py::test_grounded_vision_rejects_bbox_outside_supplied_image tests/test_vision_contracts.py::test_grounded_image_only_finding_requires_valid_region_anchor tests/test_vision_contracts.py::test_image_dimensions_read_png_and_jpeg_headers` — exit 0, 7 passed in 1.04 s.
- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_http_vision_routes.py::test_browser_stage_commit_and_abandon_http_lifecycle` — exit 0, 1 passed in 7.64 s.
- `node handoff/t17-browser-adapter-live-e2e.mjs` — exit 0. Bundled Playwright + headless Edge passed permission denial, success, same-ID commit replay, expiry, and navigation-abandon scenarios against a temporary fake API.
- Browser fixture selectors from prior T20-authorized receipt — exit 0, 7 passed in 1.17 s; source pins still match.
- `$PSNativeCommandUseErrorActionPreference=$false; & .\handoff\t17-whisper-cpu-sapi-e2e.ps1` — exit 0. Local CPU Whisper, cached `base.pt`, Microsoft David Desktop synthetic English: 15 reference words, 0 errors, 0.0 WER. Invalid audio returned `invalid_audio` and failure. No network/model download.
- `git diff --check` — exit 0; Git printed existing LF-to-CRLF warnings.

## Live vision evidence and remaining acceptance blockers

- Direct `LocalAIServices.vision()` call used real local Ollama `qwen2.5vl:3b`, a temporary headless-Edge screenshot, and synthetic DOM; no Hub or personal config was used.
- Repro command `python -B handoff/t17-live-vision-evidence.py` — process exit 0, acceptance `FAIL`; model output was rejected for missing required `hypothesized` field.
- Model output with 256-token limit was malformed JSON and failed closed. Another valid response exceeded image width and failed closed.
- A later call returned `success=true` but a false-positive finding: it said button text `Continue` did not match expected `Continue`, while its cited DOM observation fact correctly said `Continue`. The parser accepted this contradictory claim. Live vision quality is therefore not accepted.
- Browser test used a fake API and `<all_urls>` in its positive-permission profile. Installed-extension toolbar/`activeTab` behavior and production daemon/browser integration remain unverified.
- Whisper evidence covers generated synthetic English only; natural and multilingual speech quality remain unverified.
- End-to-end acceptance remains incomplete. Do not claim live model/browser quality or integrate shared dirty files.

## Candidate source pins

- `browser_bridge/background.js` — `5602b36a67dbbbd510d8c94eb08128ec790b2c57`
- `src/local_ai_hub/services.py` — `a6f32cefbe3851a83fcb454f805929da0d72a274`
- `src/local_ai_hub/vision_contracts.py` — `d520bcd8220bc1cfeb46ac39ac58d48476d7a416`
- `tests/test_transcription_contract.py` — `31941a7b6b65729765ae10b31021125df69e575d`
- `tests/test_vision_service.py` — `b0b44d6cdd6845bfbe25bd151c8ae28f35e87c3e`
- `tests/test_vision_contracts.py` — `ac7488d5d3ce0e48063cff4ba9c661359eb7f085`
- `tests/test_browser_bridge.py` — `97061b8fcd9de1255bb81a012db1164009216fb5`
- `tests/test_http_vision_routes.py` — `7230119bd61532c222f4a891e524b00f956cb18b`

## Test coordination and goal status

- Current goal `01a0ce56-4fa2-72d3-bf16-1371247d3a77` entered this continuation as `blocked`. It remains incomplete because live vision quality and production browser acceptance are open. No goal status mutation was made.
- T20 task `01a0d322-b3bd-7930-b552-14e9b7020fec` is `systemError`; latest turn failed with `workspace routing discovery timed out`. T20 worktree was read-only inspected at HEAD `8314e9d3f3cf930d0618528ad8300be63fa7beb9`; its matrix remains dirty and T17 runtime gates remain open.
- Authorized coordination message failed exactly: `Cannot steer conversation 01a0d322-b3bd-7930-b552-14e9b7020fec without an active turn id`.
- Existing checkpoint `handoff/t17-test-slot-checkpoint-2026-10-02.md` says T02 owns sole test/benchmark slot pending explicit release. T02 is idle; its latest handoff says fresh T20 GO is still required. Do not treat idle as release.
- The focused test receipts listed above were run in the prior continuation before this slot conflict was rediscovered. Preserve them as candidate execution results, not T20-coordinated GO receipts. No tests ran after the current coordination check.
- Pending command, not run after coordination check:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_process_utils.py::test_run_hidden_cancellation_terminates_tree_and_drains_output tests/test_process_utils.py::test_run_hidden_bounds_drain_when_descendant_keeps_pipes_open tests/test_process_utils.py::test_run_hidden_cancellation_terminates_process_tree tests/test_transcription_contract.py::test_transcribe_reports_cancellation_after_owned_output_cleanup tests/test_transcription_contract.py::test_transcribe_cancellation_waits_for_worker_and_model_release_before_cleanup tests/test_transcription_contract.py::test_cancellation_cleans_task_owned_whisper_output tests/test_vision_service.py::test_vision_cancelled_before_request_skips_image_and_runtime tests/test_vision_service.py::test_vision_cancelled_during_preflight_skips_runtime tests/test_vision_service.py::test_vision_cancellation_after_generation_discards_output
```
- Source review confirms candidate tests cover cancel-triggered process-tree termination, stdout/stderr drain, bounded pipe-close waiting, transcription worker/model release before temp cleanup, and vision cancellation checkpoints. Consolidated candidate selectors were later run under the user's new direct test request; T20 release itself remains unverified.

## Continuation — deterministic grounding fix

- Added a narrow parser guard in `src/local_ai_hub/vision_contracts.py`: reject explicit claims of “does not match expected value/text/label X” when a cited validated observation fact equals X. Other natural-language contradictions remain outside this deterministic guard.
- Added two owned regressions in `tests/test_vision_contracts.py`: reject the false `Continue` mismatch; accept expected `Continue` when supplied DOM says `Cancel`.
- TDD red: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_contracts.py::test_grounded_vision_rejects_problem_contradicted_by_observation_fact` — expected failure, parser returned `terminal=False` before guard.
- Focused green: `python -B -m pytest -v -p no:cacheprovider --tb=short tests/test_vision_contracts.py::test_grounded_vision_rejects_problem_contradicted_by_observation_fact tests/test_vision_contracts.py::test_grounded_vision_accepts_explicit_mismatch_against_different_dom_value tests/test_vision_contracts.py::test_grounded_vision_accepts_observation_fact_matching_cited_dom` — 3 passed in 0.53 s.
- Full vision contract/service suites: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_contracts.py tests/test_vision_service.py` — 124 passed in 6.25 s.
- Cross-scope cancellation/fallback/security selectors: 30 passed in 2.53 s. Exact command, run after the user's direct request for T17 tests; candidate evidence, not a T20 release receipt:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_browser_bridge.py::test_staged_capture_requires_explicit_commit_and_abandon_is_terminal tests/test_browser_bridge.py::test_abandon_cancels_inflight_commit_before_artifact_write tests/test_browser_bridge.py::test_expiry_cancels_inflight_commit_before_artifact_write tests/test_browser_bridge.py::test_extension_abandons_stage_when_tab_or_document_changes_before_commit tests/test_browser_bridge.py::test_extension_reconciles_commit_when_response_is_lost tests/test_browser_bridge.py::test_extension_reconciles_commit_after_http_5xx_response tests/test_browser_bridge.py::test_extension_treats_malformed_commit_response_as_unknown tests/test_browser_bridge.py::test_extension_does_not_cancel_commit_with_ambiguous_in_progress_result tests/test_browser_bridge.py::test_extension_preserves_timed_out_commit_outcome tests/test_browser_bridge.py::test_extension_does_not_cancel_commit_when_both_responses_are_lost tests/test_vision_service.py::test_vision_cancelled_before_request_skips_image_and_runtime tests/test_vision_service.py::test_vision_cancelled_during_preflight_skips_runtime tests/test_vision_service.py::test_vision_cancellation_after_generation_discards_output tests/test_vision_service.py::test_vision_cloud_fallback_is_explicitly_disabled_by_default tests/test_vision_service.py::test_vision_cloud_fallback_enabled_without_provider_fails_closed tests/test_vision_service.py::test_missing_vision_model_is_explicitly_unsupported tests/test_vision_service.py::test_vision_timeout_is_retryable_not_unsupported tests/test_vision_service.py::test_vision_network_error_is_retryable_not_unsupported tests/test_vision_service.py::test_vision_runtime_failure_is_terminal_not_unsupported tests/test_vision_service.py::test_text_only_vision_override_is_explicitly_unsupported tests/test_process_utils.py::test_run_hidden_cancellation_terminates_tree_and_drains_output tests/test_process_utils.py::test_run_hidden_bounds_drain_when_descendant_keeps_pipes_open tests/test_process_utils.py::test_run_hidden_cancellation_terminates_process_tree tests/test_transcription_contract.py::test_transcribe_reports_cancellation_after_owned_output_cleanup tests/test_transcription_contract.py::test_transcribe_cancellation_waits_for_worker_and_model_release_before_cleanup tests/test_transcription_contract.py::test_cancellation_cleans_task_owned_whisper_output
```
- Post-fix live qwen smoke: `python -B handoff/t17-live-vision-evidence.py` — process exit 0, acceptance `FAIL`; output still omitted required `hypothesized`. Live model quality remains unaccepted. Previous actual contradictory result remains the reproduction that motivated this guard.
- Incremental patch: `handoff/t17-vision-mismatch-contract.patch`; `git apply --reverse --check` passed. SHA-256 `46F71C8849B83912D3CEB43873D3D2B73AD8C19030514F1A685D96DB7E39B7A8`.
- Updated blob IDs: `src/local_ai_hub/vision_contracts.py` `f9312595ae0b2aa603a804b5dc0079a830e2accf`; `tests/test_vision_contracts.py` `16d24378b934d9b4f5c757f27b99591bf522cd24`.
- T20 remains unavailable (`systemError`); no root files changed. Production browser permission and live quality gates remain open.
