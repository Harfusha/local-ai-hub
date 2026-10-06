# T17 final owner-scoped acceptance handoff — 2026-10-02

## State

- T17 candidate only: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- Shared root remains T20-owned. No root patch applied by T17. `/api/context/pack` excluded and untouched.
- Preserve dirty state and scoped ownership in `handoff/t17-final-merge-handoff.md`; do not copy whole shared `services.py`, `vision_contracts.py`, `mcp_server.py`, or tests.
- Current compact integration/evidence summary: `handoff/t17-integration-acceptance-handoff-2026-10-02.md` (candidate pins, browser receipt, vision/audio status, exact next matrix, runtime blockers).

## Locally verifiable acceptance and actual receipts

- Candidate source behavior reviewed: browser permission/tab binding, explicit stage/commit/abandon, navigation invalidation, commit replay ambiguity, fake expiry/no artifact write; vision strict shape, evidence/DOM grounding, PNG/JPEG header-based bbox bounds, unavailable/retryable/terminal result classification, cancellation checkpoints; transcription input/model/language, task-owned temporary JSON output, cancellation cleanup, malformed/empty/decode-skip failures, and HTTP route forwarding.
- Latest recorded focused candidate receipt and selector list: `handoff/t17-browser-vision-ownership-review.md`, section “Restart acceptance receipt”; **32 passed in 15.10 s**. Historical receipt, not rerun during this review.
- Additional historical receipts, exact commands preserved in `handoff/t17-final-merge-handoff.md`: candidate audio/vision **141 passed / 16.97 s**; browser/frontend **58 passed / 12.28 s**; extra audio/artifact **2 passed / 2.38 s**; aggregate candidate **201 passed / 35.45 s**; candidate contract suite **257 passed / 47.71 s** before one-line route fixture compatibility change. Do not describe historical pre-fixture suites as post-fixture full-suite proof.
- Root integration receipts in ownership review / strict-shape integration handoff: strict-shape/grounding **6 passed / 0.80 s**; expanded root acceptance **174 passed / 46.64 s**; root-current browser isolated overlay **3 passed / 24.58 s** and registered-handler Edge E2E **PASS**; fixture route overlay **1 passed / 4.12 s**. These are bounded integration receipts, not live daemon/browser-quality acceptance.
- Scoped candidate `git diff --check`: recorded **PASS**, CRLF normalization warnings only; not rerun during this review.

## Remaining distinct root test gap

- Root `tests/test_process_utils.py` tests cancellation via `KeyboardInterrupt`; T17 added candidate coverage for `cancel_event` during `communicate()`, process-tree termination, and stdout/stderr drain.
- T20 integrated test-only patch `handoff/t17-process-cancellation-drain-test-root-current-v1.patch`, SHA-256 `70F70A58FC57CCD319BF2FFD8ADC58D031CAB6D3A5F23EBB1692CD798B90C55B`. Current root test SHA-256 `4A22549D9031C648EFE994B47EDCEB7376D19D062A891EDCDC694CC66C06BD95` equals LF-normalized patch postimage; reverse apply-check passed.
- Slot E is spent; **no acceptable candidate broker receipt**. First `local_ai_command(action="run")` mistakenly targeted root `C:\Users\Adam\.local-ai-hub`, not candidate root; request `req_aa397c4c3b85`, execution `9e08b4d809b247afac8e5adada05f094`, exit 0, **1 passed in 0.24s**. After target correction, selector was run natively once in candidate cwd `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`: exact command `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_process_utils.py::test_run_hidden_cancellation_terminates_tree_and_drains_output`, exit 0, **1 passed in 0.21s**. This native result does not satisfy broker-receipt requirement. Candidate pre/post hashes unchanged: `src/local_ai_hub/process_utils.py` `b0bacbed2fcd6d0f44d82aaa0f7053e1e96feacd`; `tests/test_process_utils.py` `6c7fcb28c7f137b0c0658eb87104ec7178fb2213`. Do not rerun selector.

## Transcription selector and fixture map

- Requested model plus task-owned output cleanup: `tests/test_transcription_contract.py::test_transcribe_honors_requested_model_and_cleans_task_owned_output`; default model: `::test_transcribe_defaults_to_base_model`.
- Explicit language forwarding and auto-detection: `::test_transcribe_forwards_explicit_language_hint`, `::test_transcribe_auto_language_keeps_whisper_autodetection`; invalid language rejected before Whisper: `::test_transcribe_rejects_non_string_language_hint_before_running_whisper`.
- Malformed request, missing CLI/audio, directory, timeout/process/empty/malformed JSON, decode-skip stdout/stderr, and cancellation cleanup have dedicated selectors nearby. Worker lifetime/model release: `::test_transcribe_cancellation_waits_for_worker_and_model_release_before_cleanup`.
- HTTP route fixture accepts handler `cancel_event=` via `**_kwargs` while retaining requested model/language assertions: `::test_http_transcribe_route_preserves_requested_model`. Root fixture patch is already integrated; preserve root file's other dirty tests.
- Latest focused 32-pass receipt includes invalid request, missing CLI, cancellation lifetime, decode-skip, route behavior; earlier 257-pass contract suite includes requested-model/tempdir coverage but predates route-fixture adjustment. Natural multilingual WER remains a separate external gate.

## External acceptance — NOT VERIFIED

- Actual extension toolbar user gesture granting production `activeTab`, then screenshot/stage/commit in a real browser. Headless `<all_urls>`/registered-handler evidence does not satisfy this.
- Persistent live-daemon expiry/replay and unavailable-backend behavior. In-process app/SQLite and fake-clock tests do not prove daemon restart persistence.
- Natural/multilingual Whisper WER. Repository has no natural audio corpus; synthetic English/Czech TTS is smoke only.
- Live vision model grounded output/quality. Prior live smoke returned unsupported DOM ID and parser failed closed; this is fail-closed evidence, not successful quality proof.

## Handoff disposition

- Close candidate deterministic source-contract acceptance with above actual receipts only.
- Overall T17 end-to-end goal remains **OPEN/BLOCKED** until the separate browser, live-daemon, natural-audio, and live-vision gates have real evidence.
- T20 next action: decide whether to assign a fresh exclusive slot for the integrated process cancellation/drain selector. Previous slot E was consumed without an acceptable candidate broker receipt; do not count the separate root run or candidate native run as that receipt.

## Remaining contract-gap audit after T20 process-test integration (2026-10-02)

- Earlier static candidate review found selectors for browser capability/provenance/navigation, expiry, stage/commit/abandon, replay and ambiguous outcomes; vision schema, cancellation, availability, evidence grounding and image bounds; and transcription model/language, input/process errors, task-owned output and cancellation. Historical receipts are listed above; no new receipt is claimed.
- `image_dimensions()` extracts dimensions from PNG/JPEG headers only. For other accepted image MIME formats dimensions may be unknown; bbox findings then fail closed. Do not describe bounds support as format-independent decoded-image coverage.
- Browser source reuses the same `commitPayload`; JavaScript fixture checks equal retry bodies for lost-response and HTTP 5xx cases. Successful replies require the active `request_id`; supplied mismatches invalidate success and error replies, while ID-less errors remain valid. Server `commit_staged_capture()` adds `request_id` to terminal receipts before caching. New missing/mismatched-ID selectors are unexecuted. HTTP lifecycle coverage separately replays the same request and confirms identical response with no artifact-list growth.
- Root cancellation/drain test patch is integrated. Slot E's broker call targeted root by mistake (`1 passed in 0.24s`); candidate selector then ran natively (`1 passed in 0.21s`). Neither is an acceptable candidate broker receipt. Exact IDs, command, HEAD and file hashes are recorded above.
- That earlier audit ran no test/benchmark. Next distinct local action: only after T20 assigns a fresh explicit slot, run the integrated selector `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_process_utils.py::test_run_hidden_cancellation_terminates_tree_and_drains_output`; no wider rerun absent source changes.

## Current resume checkpoint (2026-10-02)

- Candidate baseline rechecked: HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`; 23 tracked dirty paths plus `handoff/`. This checkpoint predates the current replay-assertion test edit; no source edit or test run occurred in this review.
- One bounded Hub `local_ai_status(action="agent_state", response_profile="minimal", max_response_tokens=500)` returned `status_code=500`, `terminal=true`, `retryable=false`, error `MCP output contract failed: result does not match a declared output variant for action='agent_state'`. Per instruction, the previously hanging `local_ai_repo(context)` request was not repeated. No further Hub attempts.
- Slot E was assigned and consumed; it did not yield an acceptable candidate broker receipt. Do not run another selector until T20 explicitly assigns a fresh slot.
- At this checkpoint, latest candidate focused receipt was **32 passed / 15.10 s**. It predates the replay-assertion edit below. External browser/daemon/natural-WER/live-vision gates remain **NOT VERIFIED**.

## Latest static resume pass (2026-10-02)

- Candidate baseline remains HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`, 23 tracked dirty paths plus `handoff/`. This continuation added bounded browser response validation and test-only cases; no tests ran.
- Bounded selector inventory confirms selector presence for browser capability/provenance/navigation/expiry/replay and HTTP lifecycle; vision schema/payload/cancellation/DOM facts/bbox bounds/unavailable/network/terminal behavior; transcription model/language/temp-output/cancellation/decode-skip/HTTP behavior. Selector presence is not a fresh receipt. Browser success replies now require the expected `request_id`; supplied mismatched IDs invalidate success and error replies, while ID-less errors remain supported. Retry-body equality is asserted for lost-response, HTTP 5xx, and malformed/mismatched-ID cases. New assertions are unexecuted. HTTP lifecycle coverage separately verifies replay response equality and no artifact-list growth.
- Routed static whitespace check through `local_ai_command(action="run", cwd="C:\\Users\\Adam\\.codex\\worktrees\\t17-multimodal-resume\\.local-ai-hub", reuse_key="t17-static-diffcheck-20261002")`, exact command `git diff --check -- [scoped T17 paths]`; tool result `success=true`, `exit_code=0`, `reason=read-only git diff`, `execution_id=024f1d2c1b0646fa903e12ee1fa1b8ee`. No test/build/runtime command was run.
- One historical `local_ai_status(action="agent_state", response_profile="minimal", max_response_tokens=500)` result was terminal 500 schema error (recorded above); this audit did not use Hub.
- Next: retain source-only state. Run selectors only after fresh explicit T20 slot assignment. Keep real browser gesture, live daemon, natural WER, and live vision gates **NOT VERIFIED**.

## Minimal browser/vision test matrix for next T20 slot

- Browser state/replay: capability single-use/tab binding; timestamp and target-origin provenance; same-tab navigation; in-flight/staged expiry; lost response; HTTP 5xx; ambiguous in-progress; timeout; both responses lost; HTTP stage/commit/abandon and idempotent replay. Historical combined receipt is in `handoff/t17-browser-vision-ownership-review.md`, “Restart acceptance receipt” (**32 passed / 15.10 s**, before current response-binding and retry-body edits). Add `tests/test_browser_bridge.py::test_extension_treats_malformed_commit_response_as_unknown` for missing/mismatched success and mismatched error IDs; old 32-selector command did not include it.
- Vision: strict schema and malformed request; cancellation before request and during preflight; unavailable/network/terminal result classification; valid supplied DOM finding; fact mismatch and missing DOM ID; bbox outside PNG/JPEG dimensions; image-only valid region anchor. Exact candidate selector list is in the same receipt.
- Process utility is separate: `tests/test_process_utils.py::test_run_hidden_cancellation_terminates_tree_and_drains_output` needs a fresh explicit slot and acceptable candidate broker receipt. Previous root-targeted broker run and candidate native run do not satisfy it.
- This matrix covers deterministic contracts only. Actual toolbar `activeTab` gesture, persistent live-daemon expiry/replay, natural multilingual Whisper WER, and live vision quality remain **NOT VERIFIED**.

## Current browser source receipt — external acceptance unverified (2026-10-02)

- Candidate `browser_bridge/background.js` now requires successful commit responses to carry the expected `request_id`; a response that supplies a different ID is invalid. One bounded retry reuses the same `commitPayload`; repeated malformed/mismatched replies return `commit_outcome_unknown` without abandon.
- Candidate test edits: `tests/test_browser_bridge_background.js` checks equal retry bodies and covers missing/mismatched success IDs plus mismatched error ID; `tests/test_browser_bridge.py::test_extension_treats_malformed_commit_response_as_unknown` adds all three cases. The new tests received **7 passed in 1.17 s** under explicit T20 GO below. Historical 32-pass receipt predates these changes.
- Prepared full focused command (including HTTP lifecycle, not run): `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_browser_bridge.py::test_extension_treats_malformed_commit_response_as_unknown tests/test_browser_bridge.py::test_extension_reconciles_commit_when_response_is_lost tests/test_browser_bridge.py::test_extension_reconciles_commit_after_http_5xx_response tests/test_http_vision_routes.py::test_browser_stage_commit_and_abandon_http_lifecycle`.
- T20 explicitly authorized only the three browser selectors. Pre-run hashes matched expected candidate state: `background.js` `5602b36a67dbbbd510d8c94eb08128ec790b2c57`; browser fixture `b27aac96d4e4598ac43b449eac63b354ba9f587b`; `test_browser_bridge.py` `97061b8fcd9de1255bb81a012db1164009216fb5`.
- Exact executed command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_browser_bridge.py::test_extension_treats_malformed_commit_response_as_unknown tests/test_browser_bridge.py::test_extension_reconciles_commit_when_response_is_lost tests/test_browser_bridge.py::test_extension_reconciles_commit_after_http_5xx_response`. Native candidate run, no Hub/live service: exit 0, **7 passed in 1.17 s**. No other selector run.
- Browser test assertion receipt confirms retry-body identity for lost response and HTTP 5xx, plus missing/mismatched `request_id` classification. No production browser or daemon claim follows from these fixtures.
- Current Git blob IDs: `browser_bridge/background.js` `5602b36a67dbbbd510d8c94eb08128ec790b2c57`; `tests/test_browser_bridge_background.js` `b27aac96d4e4598ac43b449eac63b354ba9f587b`; `tests/test_browser_bridge.py` `97061b8fcd9de1255bb81a012db1164009216fb5`.
- Scoped read-only check `git diff --check -- browser_bridge/background.js tests/test_browser_bridge_background.js tests/test_browser_bridge.py handoff/t17-final-acceptance-owner-handoff-2026-10-02.md handoff/t17-browser-vision-ownership-review.md` exited 0; one existing LF-to-CRLF normalization warning on `background.js`.
- No root files changed. Vision selector slot requested from T20; no GO recorded yet. No Hub retry or live model call.

## Vision slot preflight — awaiting T20 GO (2026-10-02)

- Source review: candidate `vision()` passes supplied observation facts, valid DOM IDs, and PNG/JPEG header dimensions to the parser. Parser requires exact source/element/field/value matches, cited evidence, and in-bounds bbox for known image dimensions. Non-PNG/JPEG formats may have unknown dimensions; bbox findings fail closed.
- Prepared exact command requested from T20: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_service.py::test_vision_accepts_dom_id_from_supplied_frontend_context tests/test_vision_service.py::test_vision_rejects_dom_observation_fact_that_mismatches_supplied_source tests/test_vision_contracts.py::test_grounded_vision_rejects_dom_ids_absent_from_supplied_dom tests/test_vision_contracts.py::test_grounded_vision_accepts_observation_fact_matching_cited_dom tests/test_vision_contracts.py::test_grounded_vision_rejects_bbox_outside_supplied_image tests/test_vision_contracts.py::test_grounded_image_only_finding_requires_valid_region_anchor tests/test_vision_contracts.py::test_image_dimensions_read_png_and_jpeg_headers`.
- Preflight Git blob IDs: `src/local_ai_hub/services.py` `a6f32cefbe3851a83fcb454f805929da0d72a274`; `src/local_ai_hub/vision_contracts.py` `d520bcd8220bc1cfeb46ac39ac58d48476d7a416`; `tests/test_vision_service.py` `b0b44d6cdd6845bfbe25bd151c8ae28f35e87c3e`; `tests/test_vision_contracts.py` `ac7488d5d3ce0e48063cff4ba9c661359eb7f085`.
- No tests or live model calls until fresh explicit T20 GO. Slot request sent; no response recorded yet.
