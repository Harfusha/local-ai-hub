# T17 checkpoint — T02 test slot held — 2026-10-02

## State and ownership

- Goal `01a0ce56-4fa2-72d3-bf16-1371247d3a77`: status **blocked**, objective remains end-to-end T17 acceptance.
- Continue in existing T17 candidate `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`. Original advertised `8085` path is absent; no replacement worktree/task/chat created.
- Dirty baseline preserved: 23 modified tracked paths plus untracked `handoff/`. No source file edited in this checkpoint. `src/local_ai_hub/mcp_server.py` stays outside T17 ownership; `/api/context/pack` untouched.
- T20 root is `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`, independently dirty. Read-only inspection only.
- T02 owns sole test/benchmark slot per user. No tests or benchmarks run after that reservation; do not start them until explicit release.

## Root/current comparison

- Current reverse-apply checks pass for four scoped patches: browser active-tab v5, vision bbox wording, Whisper stderr decode-skip, and transcription-route test fixture. Forward checks fail because these hunks already exist in root. Do not apply or duplicate them.
- Candidate/root test names are exactly equal for `tests/test_browser_bridge.py` and `tests/test_http_vision_routes.py`.
- Name-level deltas requiring semantic review, not automatic transfer: candidate-only transcription selectors `test_transcribe_rejects_non_object_request_payload`, `test_transcribe_rejects_non_string_language_hint_before_running_whisper`, `test_transcribe_reports_cancellation_after_owned_output_cleanup`; root-only `test_whisper_decode_skip_stderr_does_not_report_successful_transcription`.
- Candidate-only vision-contract selectors: `test_dom_vision_result_rejects_whitespace_only_observation_fields`, `test_grounded_image_only_finding_rejects_dom_markup_as_evidence`, `test_grounded_image_only_finding_requires_valid_region_anchor`, `test_grounded_vision_accepts_ids_from_supplied_dom`, `test_grounded_vision_accepts_observation_fact_matching_cited_dom`, `test_grounded_vision_rejects_bbox_outside_supplied_image`, `test_grounded_vision_rejects_dom_ids_absent_from_supplied_dom`, `test_grounded_vision_rejects_observation_fact_with_value_absent_from_dom`, `test_grounded_vision_requires_observation_fact_for_dom_finding`, `test_image_dimensions_read_png_and_jpeg_headers`, `test_vision_result_rejects_confidence_below_zero`, `test_vision_result_rejects_whitespace_summary_with_findings`. Root has different DOM-fact, bbox, image-header, strict-output, and confidence selectors; names alone do not prove missing semantics.
- Candidate-only vision-service selectors: `test_vision_accepts_dom_id_from_supplied_frontend_context`, `test_vision_accepts_image_only_finding_with_valid_region_anchor`, `test_vision_cancellation_after_generation_discards_output`, `test_vision_cancelled_before_request_skips_image_and_runtime`, `test_vision_cancelled_during_preflight_skips_runtime`, `test_vision_normalizes_numeric_dom_ids_consistently`, `test_vision_prompt_mentions_every_required_default_schema_field`, `test_vision_rejects_dom_markup_evidence_without_element_id`, `test_vision_rejects_non_object_request_payload`, `test_vision_rejects_parseable_output_with_invalid_field_shape`, `test_vision_uses_default_structured_output_schema`; root includes semantically related evidence/schema/error tests under different names.
- Candidate-only process selector: `test_run_hidden_cancellation_terminates_tree_and_drains_output`. Do not transfer whole test modules; they contain owner-specific dirty changes.
- AST body hash comparison confirms `LocalAIServices.vision`, `LocalAIServices.transcribe`, and `parse_vision_result` differ between candidate and root. Patch-scoped root hunks above are integrated; preserve whole-file ownership differences.

## Existing receipts and next allowed test

- Fresh focused candidate acceptance before slot reservation: **32 passed / 15.10 s**. Exact command is in `handoff/t17-browser-vision-ownership-review.md`, SHA at prior checkpoint `3F619D13C72B57DF15EF812F09C3F4FD59B84A070D735A3ACAA4F77280C2A801`.
- Scoped diff check passed; CRLF warnings only. Prior broader contract receipt: 257 passed / 47.71 s before the one-line fixture compatibility edit; do not call it post-edit suite proof.
- After T02 releases slot, rerun only the exact focused command in the ownership review. No broader suite or benchmark planned.

## Acceptance boundary / blocker

- Source contracts have deterministic receipts. Runtime still **NOT VERIFIED**: real toolbar gesture granting `activeTab`; persistent live-daemon expiry/replay and unavailable-backend behavior; natural multilingual Whisper WER; live vision-model quality.
- No interactive browser control, live audio corpus, or usable vision runtime is available in this task. Hub remains skipped; no polling/retry.
- Next independent step: T20 may review the listed candidate-only selector semantics against its current root tests; no source/test transfer from this task until that review finds a genuine uncovered contract. Runtime gates require their real external environments.

## Independent test-preparation result (2026-10-02)

- Static comparison found a narrow subprocess cancellation coverage gap: root test only exercises `KeyboardInterrupt`; candidate-only test exercises `cancel_event` plus stdout/stderr drain after tree termination.
- Root-current test-only patch prepared at `handoff/t17-process-cancellation-drain-test-root-current-v1.patch`, SHA-256 `70F70A58FC57CCD319BF2FFD8ADC58D031CAB6D3A5F23EBB1692CD798B90C55B`; exact root test-file preimage SHA-256 `F4ABB170C15FB9E687A20EE020467FAABBC867EF406EA9AB6DE80476693AD534`. `git apply --check` PASS; patch not applied.
- Prepared selector: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_process_utils.py::test_run_hidden_cancellation_terminates_tree_and_drains_output`. Not run while T02 owns slot.
- No test/benchmark or root mutation in this checkpoint. Existing source/runtime boundary remains unchanged.
