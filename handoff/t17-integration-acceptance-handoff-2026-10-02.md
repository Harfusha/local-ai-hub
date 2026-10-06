# T17 integration and acceptance handoff — 2026-10-02

## Ownership and integration state

- Candidate checkout: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- T20 release matrix row currently says T17 candidate is not integrated; it records the browser fixture receipt and live browser/model limits, with a separate vision slot pending.
- No root files were written in this continuation. This handoff is candidate-local. `/api/context/pack` remains Agent 2-owned and untouched.
- Preserve shared dirty files. Do not copy whole `services.py`, `vision_contracts.py`, `frontend_review.py`, MCP files, or tests into root. Use `handoff/t17-root-current-patch-manifest-2026-10-02.md` and T20 ownership for scoped integration only.

## Candidate pins

Git blob IDs at handoff time:

- `browser_bridge/background.js` — `5602b36a67dbbbd510d8c94eb08128ec790b2c57`
- `browser_bridge/manifest.json` — `272ac2272815e5a1ce53d574feb8a3804689bd93`
- `src/local_ai_hub/services.py` — `a6f32cefbe3851a83fcb454f805929da0d72a274`
- `src/local_ai_hub/vision_contracts.py` — `d520bcd8220bc1cfeb46ac39ac58d48476d7a416`
- `src/local_ai_hub/frontend_review.py` — `fc89e795defb1b42e0619d4fdf4088d25544136b`
- `tests/test_browser_bridge.py` — `97061b8fcd9de1255bb81a012db1164009216fb5`
- `tests/test_browser_bridge_background.js` — `b27aac96d4e4598ac43b449eac63b354ba9f587b`
- `tests/test_http_vision_routes.py` — `7230119bd61532c222f4a891e524b00f956cb18b`
- `tests/test_vision_service.py` — `b0b44d6cdd6845bfbe25bd151c8ae28f35e87c3e`
- `tests/test_vision_contracts.py` — `ac7488d5d3ce0e48063cff4ba9c661359eb7f085`
- `tests/test_transcription_contract.py` — `31941a7b6b65729765ae10b31021125df69e575d`

## Acceptance evidence

### Browser

- Fresh T20-authorized candidate command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_browser_bridge.py::test_extension_treats_malformed_commit_response_as_unknown tests/test_browser_bridge.py::test_extension_reconciles_commit_when_response_is_lost tests/test_browser_bridge.py::test_extension_reconciles_commit_after_http_5xx_response` — exit 0, **7 passed in 1.17 s**.
- Pre-run hashes matched the candidate pins for `background.js`, `tests/test_browser_bridge_background.js`, and `tests/test_browser_bridge.py` above.
- This receipt covers fixture response-ID binding and replay behavior. It does not prove installed extension behavior, toolbar user gesture, Chrome `activeTab` grant, or a production daemon.
- Exact HTTP stage/commit/abandon lifecycle selector is prepared but was not included in that GO or run: `tests/test_http_vision_routes.py::test_browser_stage_commit_and_abandon_http_lifecycle`.

### Vision

- Source review: callsite passes supplied observation facts and DOM IDs into parser. Parser requires fact values to match supplied source data, rejects unsupported IDs and invalid evidence, and bounds bbox only where PNG/JPEG header dimensions are recognized. Other accepted image formats can have unknown dimensions; bbox findings then fail closed.
- Historical 32-pass candidate receipt includes schema, malformed request, cancellation, availability/error classification, DOM rejection/fact mismatch, bbox bound, and image-only anchor selectors. It predates the latest browser response-binding edits and is not a new receipt for those edits.
- Vision-specific positive selectors for a valid supplied DOM ID, matching observation fact, and PNG/JPEG dimension parsing are not all present in the 32-selector command. A seven-selector vision command is prepared in `handoff/t17-final-acceptance-owner-handoff-2026-10-02.md`; T20 GO remains pending. No vision test or live model ran in this continuation.
- Live vision smoke previously failed closed on an unsupported model-emitted DOM ID. No successful live grounded result or quality score exists.

### Audio / transcription

- Historical candidate receipts: transcription/vision group **141 passed / 16.97 s**; aggregate candidate **201 passed / 35.45 s**; larger contract suite **257 passed / 47.71 s** before route-fixture compatibility adjustment; most recent focused 32-selector receipt **32 passed / 15.10 s** included malformed request, missing CLI, worker/model cancellation lifetime, decode-skip, and HTTP route behavior.
- Requested model/task-owned output cleanup coverage is present in earlier selector receipts, but the 257-pass suite predates the route-fixture adjustment; do not label it as a post-adjustment full-suite pass.
- Synthetic Whisper smoke only: English WER 0/10; synthetic Czech WER 2/7 (28.6%). No natural multilingual audio corpus/reference exists here. Recorded-speech multilingual WER remains **NOT VERIFIED**.

## Exact next validation matrix

- Browser recent patch receipt is green; do not repeat its three selectors absent code changes.
- Vision command, only after explicit T20 serial GO: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_service.py::test_vision_accepts_dom_id_from_supplied_frontend_context tests/test_vision_service.py::test_vision_rejects_dom_observation_fact_that_mismatches_supplied_source tests/test_vision_contracts.py::test_grounded_vision_rejects_dom_ids_absent_from_supplied_dom tests/test_vision_contracts.py::test_grounded_vision_accepts_observation_fact_matching_cited_dom tests/test_vision_contracts.py::test_grounded_vision_rejects_bbox_outside_supplied_image tests/test_vision_contracts.py::test_grounded_image_only_finding_requires_valid_region_anchor tests/test_vision_contracts.py::test_image_dimensions_read_png_and_jpeg_headers`.
- Do not run process cancellation/drain selector under the spent slot E; it lacks acceptable candidate broker receipt. Need fresh T20 GO if still required.
- No tests, install, root write, or live-model call in this handoff turn.

## Remaining acceptance blockers

- Actual Chrome/Edge toolbar click granting production `activeTab`, followed by capture/stage/commit: **NOT VERIFIED**.
- Persistent running-daemon expiry/replay and unavailable-backend behavior: **NOT VERIFIED**.
- Natural multilingual Whisper WER: **NOT VERIFIED**.
- Live vision grounded-output quality: **NOT VERIFIED**.
- T20 integration/release acceptance remains open. Source contracts, fixture tests, historical receipts, and synthetic smoke do not close runtime/model gates.
