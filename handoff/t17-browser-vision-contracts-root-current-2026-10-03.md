# T17 Browser and vision contracts: root-current handoff

Date: 2026-10-03. Source-only receipt. No tests, benchmark, service edit, or root edit performed.

## Candidate and patch

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.

Root-current patch: `handoff/t17-browser-vision-contracts-root-current.patch`, SHA-256 `675fa73c00808e3d40387314272f72eaae414cf14d67c8e91df0aa32b2a68dc7`.

Read-only `git apply --check` against current root returned 0 for all hunks. The patch is not applied. It changes six files:

- `browser_bridge/background.js` plus `tests/test_browser_bridge_background.js`: bind successful commit response to the request ID submitted, reject mismatched response IDs, add replay/missing/mismatched-ID coverage.
- `src/local_ai_hub/frontend_review.py` plus `tests/test_frontend_review.py`: derive trusted scalar observation sources from stable DOM IDs and accessibility/style/runtime maps; omit `element_id` itself as evidence; omit blank/invalid facts; reject boolean DOM IDs; update integration fixture to cite computed-style evidence.
- `src/local_ai_hub/vision_contracts.py` plus `tests/test_vision_contracts.py`: retain supplied `observation_sources` on successful `VisionParseResult`; add direct pass-through regression.

Root-current preimage SHA-256: `background.js` `804e8a497c7c9a879ce7def0de7317cb1b05db60f596280509606491263f57fd`; browser test `a0d4130e70c990e071c6a47f96a26274b151849d25bc083ce43c42f45f806c5e`; `frontend_review.py` `5d61dd3a8d681bf7f084b45f97d683566cae700c6dbe6d4546521d9c73312a2e`; frontend test `740b93b167b01a91ab59d00105bfef7a1daf53132c159296a4689dc89eb07f67`; `vision_contracts.py` `048dd7ea1a464401cbe7a8fce421cb07711763809bd7a177ea40fb196ed18f6c`; vision test `583c760fa84b099775fac4da0c32e71e144d0d5cb38c606ab8f3b96994d4858b`.

Candidate file hashes and exact source hunks are visible in the patch. Candidate `services.py` SHA-256 `a3c9c6dbae5acfaac1d543f02783eda4fbbc89f7991d9870f849972f7224f0c0`; root `services.py` SHA-256 `58908c5c718a520463171b7890c0b8e1e7f7cc54d5ef62f9809be707efc173fe`. No service hunk included.

## Vision orchestration seams and gate

Root `LocalAIServices.vision()` already builds frontend model context and passes its observation-source map into `parse_vision_result()`. Root-current parser validates cited source values but drops the map from successful `VisionParseResult`; the patch fixes that return contract. Public vision output otherwise retains existing keys; `review.observation_sources` is additive.

Service integration remains separate: root and candidate `services.py` are both dirty, have different hashes and materially different `vision()` bodies. Root method contains its malformed-output fallback shape. Candidate adds `cancel_event`, pre-request/preflight/post-generation cancellation checkpoints, input object validation, and capability classification. Whole-method replacement risks losing root output details. Keep cancellation shape (`success=false`, `cancelled=true`, terminal, non-retryable), capability distinctions (missing/non-vision model unsupported; transient backend failure retryable), output keys, and raw artifact IDs as acceptance conditions. No service edit until exact root-current hunks are isolated and scoped.

`/api/context/pack` stays excluded. No route code is changed by this patch.

## Acceptance after explicit T20 GO

Run in T17 candidate worktree first:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_frontend_review.py::test_build_model_context_includes_screenshot_dom_and_prompt tests/test_frontend_review.py::test_project_live_dom_rejects_boolean_element_ids tests/test_frontend_review.py::test_service_passes_screenshot_and_dom_bundle_to_vision_model tests/test_vision_contracts.py::test_grounded_vision_accepts_observation_fact_matching_cited_dom tests/test_vision_contracts.py::test_grounded_vision_rejects_observation_fact_with_value_absent_from_dom tests/test_vision_service.py::test_vision_cancelled_before_request_skips_image_and_runtime tests/test_vision_service.py::test_vision_cancelled_during_preflight_skips_runtime tests/test_vision_service.py::test_vision_cancellation_after_generation_discards_output tests/test_vision_service.py::test_missing_vision_model_is_explicitly_unsupported tests/test_vision_service.py::test_vision_timeout_is_retryable_not_unsupported tests/test_vision_service.py::test_text_only_vision_override_is_explicitly_unsupported tests/test_vision_service.py::test_vision_accepts_image_only_finding_with_valid_region_anchor tests/test_vision_service.py::test_vision_rejects_dom_observation_fact_that_mismatches_supplied_source tests/test_http_vision_routes.py::test_browser_capability_capture_and_review_routes_are_explicit_and_tenant_scoped tests/test_http_vision_routes.py::test_browser_stage_commit_and_abandon_http_lifecycle tests/test_http_vision_routes.py::test_token_auth_supports_bridge_and_review_preflight_without_wildcard_origin
node tests/test_browser_bridge_background.js
```

After applying the root-current patch, run its new direct retention regression too:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_contracts.py::test_vision_parse_result_preserves_observation_sources
```

Acceptance: all selectors pass; exact cancellation/error/result shapes preserved; observation source values are retained and factual; image-only evidence uses valid image anchors; browser commit requires matching request ID; HTTP tenant/origin/capability lifecycle unchanged. Root integration then requires rechecking patch preimages/apply-check and rerunning focused root selectors under T20 GO. Live-model quality and performance remain separately unverified; no claim from static evidence.

Current test status: **NOT RUN; T20 GO absent**.
