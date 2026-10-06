# T17 root-current vision delta and offline evidence

Root: C:\Users\Adam\.local-ai-hub
Root patch: handoff/t17-vision-mismatch-root-current-v2.patch
Root patch SHA-256: 23226a9abeb2214ad8944f9a1540681d2654d630a62d1da51417a4ab3352c0fa

Root preimage -> postimage SHA-256:
- src/local_ai_hub/vision_contracts.py: 0f42f51ed39c7fdbff2a70d5be08490407bfd02dd91198b2ae20b787dc971c5a -> 048dd7ea1a464401cbe7a8fce421cb07711763809bd7a177ea40fb196ed18f6c
- tests/test_vision_contracts.py: f325f3080696e49c17bc062c8697e158c07888080dff1dd59c665702e1de0454 -> ad98c5ca24987c01a5cffe0cfebf89a12076fb3cdf152b6a491ec66d2d0711c2

Patch is applied to exactly these two T17 root paths. No further root edits. /api/context/pack untouched.

T04 gate: active when this receipt was updated. All test executions below predate the gate; repeat after T04 completes before treating as acceptance.

## Exact offline commands and prior execution IDs

Vision contracts/service — ID 9882bf — pre-T04, exit 0, 105 passed:

    python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_contracts.py tests/test_vision_service.py

Browser staged capture/replay/abandon — ID 7b0cc6 — pre-T04, exit 0, 9 passed:

    python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_browser_bridge.py::test_staged_capture_requires_explicit_commit_and_abandon_is_terminal tests/test_browser_bridge.py::test_abandon_cancels_inflight_commit_before_artifact_write tests/test_browser_bridge.py::test_expiry_cancels_inflight_commit_before_artifact_write tests/test_browser_bridge.py::test_extension_abandons_stage_when_tab_or_document_changes_before_commit tests/test_browser_bridge.py::test_extension_reconciles_commit_when_response_is_lost tests/test_browser_bridge.py::test_extension_reconciles_commit_after_http_5xx_response tests/test_browser_bridge.py::test_extension_does_not_cancel_commit_when_both_responses_are_lost tests/test_browser_bridge.py::test_extension_treats_malformed_commit_response_as_unknown

Offline hypothesized regression — ID 25fc5f — pre-T04, exit 0, 1 passed:

    python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_contracts.py::test_grounded_vision_rejects_live_output_missing_hypothesized

The regression is in candidate tests/test_vision_contracts.py: test_grounded_vision_rejects_live_output_missing_hypothesized. Candidate test file SHA-256: bd567c4c6aa7f921eaab0aa983a3bb394585f03472d6ebb1acca607fc02ce314.

Post-T04 execution IDs/results: pending; no test run after the gate yet.

## Runtime evidence — separate from offline tests

- Browser extension integration: NOT VERIFIED. Unit selectors do not prove installed-extension activeTab/user-gesture behavior.
- Whisper: limited synthetic English CPU smoke previously reported WER 0.0 on 15 words; real speech, multilingual quality, and broader runtime acceptance NOT VERIFIED.
- Vision model: NOT ACCEPTED. Prior live smoke output lacked required hypothesized. No live run during the T12 critical-VRAM incident.
