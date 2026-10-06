# T28 vision decomposition: root preimage and test map

Date: 2026-10-03. Root read-only. No tests run; require explicit T20 GO.

## Worktree and scope

- Isolated Git worktree: `C:\Users\Adam\.codex\worktrees\t17-vision-refactor\.local-ai-hub`
- Detached base: `2b33602adef0d030fea66cdcc04ca742c60b2e32`
- Refactor target: `LocalAIServices.vision()` plus two new public-behavior golden tests in `tests/test_vision_service.py`.
- Carried forward selected T17 dirty source/test diffs from the candidate worktree. These are setup state, not T28 refactor edits.
- No `http_server.py` edit. `/api/context/pack` remains outside scope; its call inside vision is unchanged.

## Exact source preimages

| Checkout | `services.py` SHA-256 | `vision()` exact span | `transcribe()` exact span |
|---|---|---|---|
| Root `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` | `58908c5c718a520463171b7890c0b8e1e7f7cc54d5ef62f9809be707efc173fe` | lines 1888-2621; 734 lines, 38,187 B; `36becf01920abe0b0f3b5bd52d8c22f06f71079a1b159a5455d9cadf6d12c8e8` | lines 2623-2836; 214 lines, 8,265 B; `0137ad26613ceace3b486e8e7566a9528f5b29eccb3635debbfb2b58496f0890` |
| T17 candidate `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32` | `a3c9c6dbae5acfaac1d543f02783eda4fbbc89f7991d9870f849972f7224f0c0` | lines 1702-2572; 871 lines, 45,721 B; `fc4af5eff096c3fc014108de6932e449f16a2731290a9f6ab9718518ac2c47ac` | lines 2574-2785; 212 lines, 8,168 B; `73f3452ccd7f86772bcc87b3606610ba3bc4fdca58ea7068a733f59d46020c4e` |
| T28 isolated after extraction | `558634a395c54a097322d66e80e0aa0ba0f70ee1fe955bd9885118a47e3b97b4` | lines 1848-2550; 703 lines, 36,317 B; `41953ada2a06d271805e4b08be6ee2f29ca5b4005b9702d0b4d6b664c220e9f1` | lines 2552-2763; AST-identical to candidate `transcribe()` |

Root `services.py` currently reports `+1140/-83` against HEAD. AST-scoped `vision()` delta is `+31/-3`; `transcribe()` is `+206/-30`; residual outside those two symbols is `+903/-50`, including other owned/inherited source. Do not replace the whole file.

Root test-file preimages versus isolated T28 files:

| Test file | Root SHA-256 | T28 SHA-256 |
|---|---|---|
| `tests/test_vision_service.py` | `32cb2ac2c71b697cd81d3b5a74c6a7fd4ac015cd886e01e95597b712b997735c` | `89c7a86afa63d949d2e416dc46c7c5bf589d8e7609cb5de7ddfd46e34e3d44b0` |
| `tests/test_vision_contracts.py` | `583c760fa84b099775fac4da0c32e71e144d0d5cb38c606ab8f3b96994d4858b` | `ca223f99c278376809c865fa330b4baef37312a561337202ba51ebe9347fc224` |
| `tests/test_transcription_contract.py` | `decc2f2ac615176e90d0b5ee314a8a3683cc2af612848626c6dd417e425645d0` | `fa73a2967bdc8088bd03e81943b8909ea5a095f97822ea29b8980e1bb34d263d` |
| `tests/test_http_vision_routes.py` | `af88caf29817610fe12c255bd3aae64b5fc5b630af72591f72bf92bd48c0c190` | `dfc30bfc80b4a1c8e83eb4408680afe14df8ce3f60e8866d9bb247974372c8c9` |
| `tests/test_vision_artifacts.py` | `e0ddf92a86dd21316bb11539bd7edbf929ee32d3cbd62241d148e38657b6c881` | `32b29a2083a96e94a27117cf57ccaa9226a1bb01e230faa02082be2193ed6fac` |

## Root-to-candidate ownership map

- Candidate-owned additions absent from root vision: cancellation keyword/checkpoints and invalid-request guard; image-dimension capture; grounding prompt rules; default structured-output schema; numeric DOM-ID normalization.
- Root-specific behavior to preserve: `observation_sources` local binding; `degraded` flag and fallback malformed-output error; separate `ProcessCleanupUnverifiedError` import/re-raise in `transcribe()`.
- Root and candidate differ materially inside `vision()`. T28's full extracted method is not a root replacement patch. Re-anchor each portable helper hunk to a fresh root preimage before any integration.
- Root service class also contains other dirty method changes. Keep them untouched.

## T28 extraction and behavior tests

Private layers extracted: `_vision_cancelled_result`, `_vision_prompt_context`, `_vision_capability_error`, `_vision_default_schema`. Static checks: public signature unchanged; `transcribe()` AST unchanged; default schema AST unchanged; `context_pack(...)` call unchanged; source and selector-test AST parsing passed; `git diff --check` passed.

New golden tests:

- `tests/test_vision_service.py::test_vision_image_only_response_matches_golden_contract`
- `tests/test_vision_service.py::test_vision_non_multimodal_model_matches_golden_error_contract`

Preserved selectors:

- `tests/test_vision_service.py::test_vision_uses_default_structured_output_schema`
- cancellation before request, during preflight, and after generation
- prompt bound, hallucinated DOM, invalid shape, and model capability error contracts
- `tests/test_vision_contracts.py`
- transcription cancellation and HTTP model-preservation selectors

Planned focused command, **not run**:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_service.py tests/test_vision_contracts.py tests/test_transcription_contract.py::test_http_transcribe_route_preserves_requested_model tests/test_http_vision_routes.py::test_browser_capability_capture_and_review_routes_are_explicit_and_tenant_scoped tests/test_http_vision_routes.py::test_browser_stage_commit_and_abandon_http_lifecycle tests/test_http_vision_routes.py::test_token_auth_supports_bridge_and_review_preflight_without_wildcard_origin tests/test_vision_artifacts.py::test_http_binary_artifact_get_returns_complete_payload tests/test_process_utils.py::test_run_hidden_cancellation_terminates_tree_and_drains_output tests/test_process_utils.py::test_run_hidden_bounds_drain_when_descendant_keeps_pipes_open tests/test_process_utils.py::test_run_hidden_cancellation_terminates_process_tree
```

Latest T20 release thread status: `Slot denied`, lease `UNKNOWN`. No CPU test command until explicit T20 GO.

## T27 route contract lock

- `POST /api/vision/review`: sync local inference; global JSON-object body limit 16 MiB; handler prompt limit 20,000 chars; service prompt 16,000 chars, image 4,000,000 decoded bytes, schema 8,000 chars, bundle 12,000 chars. Bridge Origin/token auth; configured token binds tenant to `browser_bridge.tenant`. Vision service owns inference/parser results; handler owns auth/body failures.
- `POST /api/task/transcribe`, `/api/transcribe`: sync Whisper CLI; body `audio` or `audio_path`, optional `model` (default `base`) and string `language`; input path must be a regular file. Tenant headers `X-LocalAI-Tenant` then `X-Tenant-ID`, else `http-default`. Transcribe service owns process/input errors.
- `POST /api/browser/capability`, `/api/browser/capture`, `/api/browser/capture/stage`, `/api/browser/capture/commit`, `/api/browser/capture/abandon`: sync; capability body has `origin` <=512 chars, string/int `tab_id` and `window_id`; capture has capability <=256 chars plus tab/window identity. Bridge Origin/token checks and configured token-tenant binding; browser capture helpers own lifecycle status/errors.
- Shared handler owns Host/Origin/token/rate-limit checks, JSON-object parsing and `request_id` correlation. Error statuses include 401 auth, 403 host/origin/tenant, 429 rate limit, and body-validation statuses.
- Exact route selectors: `test_http_vision_routes.py::test_browser_capability_capture_and_review_routes_are_explicit_and_tenant_scoped`, `::test_browser_stage_commit_and_abandon_http_lifecycle`, `::test_token_auth_supports_bridge_and_review_preflight_without_wildcard_origin`, `test_transcription_contract.py::test_http_transcribe_route_preserves_requested_model`, `test_vision_artifacts.py::test_http_binary_artifact_get_returns_complete_payload`.

## Review follow-up: behavior and ownership audit

Verified 2026-10-03 in the isolated worktree; no tests run and no root files edited.

The candidate's non-object request rejection (`error_code=invalid_request`) and `cancel_event` behavior are inherited T17 behavior, not new T28 behavior. They are outside a pure decomposition change as new functionality, but are part of the carried-forward vision contract and therefore acceptance constraints: reject non-dict args terminally/non-retryably, honor cancellation before work and at the existing checkpoints, and preserve the cancelled result shape. The current order checks cancellation before validating `args`, so cancellation wins when both conditions apply. Do not claim these contracts are runtime-verified until the gated tests run.

`_vision_capability_error` is defined as `@staticmethod` at `src/local_ai_hub/services.py:1690` and called by `vision()` at line 2380. It receives `(model, response)`, reads no instance state and calls no other helper; it classifies malformed preflight responses, backend errors, model-missing responses, and capability lists. Its only external names are the `Any` annotation and built-in types/functions. Acceptance must cover the existing model-missing, transient, malformed-response, and non-vision-capability results; tests remain gated on explicit T20 GO.

### T28 worktree changed-path ownership and root preimages

`M` means dirty relative to worktree HEAD; `??` means new. Root SHA-256 values below were measured from `C:\Users\Adam\.local-ai-hub` during this audit. In `services.py` and `test_vision_service.py`, ownership is mixed within the path.

| T28 path | Ownership | Root preimage SHA-256 |
|---|---|---|
| `src/local_ai_hub/frontend_review.py` (M) | Inherited T17 candidate state; normalized content exactly matches candidate | `5d61dd3a8d681bf7f084b45f97d683566cae700c6dbe6d4546521d9c73312a2e` |
| `src/local_ai_hub/process_utils.py` (M) | Inherited T17 candidate state; normalized content exactly matches candidate | `4d5a1afbcb23bab1fe4eec6b9639743d17920de93e7a822ef64840815998d4eb` |
| `src/local_ai_hub/services.py` (M) | Mixed: T17 vision behavior carried forward; T28 owns four helper extractions and `vision()` call rewiring. `speculative_draft()`, `task_scaffold()`, and `complete_code()` retain root-preimage code; `task_scaffold()` exactly matches root after excluding inserted helper definitions. No whole-file replacement. | `58908c5c718a520463171b7890c0b8e1e7f7cc54d5ef62f9809be707efc173fe` |
| `src/local_ai_hub/vision_contracts.py` (M) | Inherited T17 candidate state plus narrow T28 gap fix: successful `parse_vision_result()` retains supplied `observation_sources` on `VisionParseResult` | `048dd7ea1a464401cbe7a8fce421cb07711763809bd7a177ea40fb196ed18f6c` |
| `tests/test_http_vision_routes.py` (M) | Inherited T17 candidate state; normalized content exactly matches candidate | `af88caf29817610fe12c255bd3aae64b5fc5b630af72591f72bf92bd48c0c190` |
| `tests/test_process_utils.py` (M) | Inherited T17 candidate state; normalized content exactly matches candidate | `4a22549d9031c648efe994b47edceb7376d19d062a891edcdc694cc66c06bd95` |
| `tests/test_transcription_contract.py` (M) | Inherited T17 candidate state; normalized content exactly matches candidate | `decc2f2ac615176e90d0b5ee314a8a3683cc2af612848626c6dd417e425645d0` |
| `tests/test_vision_artifacts.py` (M) | Inherited T17 candidate state; normalized content exactly matches candidate | `e0ddf92a86dd21316bb11539bd7edbf929ee32d3cbd62241d148e38657b6c881` |
| `tests/test_vision_contracts.py` (M) | Inherited T17 candidate tests plus T28 assertion that grounded parse results preserve supplied observation sources | `583c760fa84b099775fac4da0c32e71e144d0d5cb38c606ab8f3b96994d4858b` |
| `tests/test_vision_service.py` (M) | Mixed: inherited T17 tests plus two T28 golden tests (66 added lines); T28 file differs from candidate only by those additions | `32cb2ac2c71b697cd81d3b5a74c6a7fd4ac015cd886e01e95597b712b997735c` |
| `handoff/t28-vision-decomposition-root-preimage-map-2026-10-03.md` (??) | T28-authored handoff artifact; no root preimage | N/A |

The exact current root SHA-256 for `tests/test_vision_service.py` is `32cb2ac2c71b697cd81d3b5a74c6a7fd4ac015cd886e01e95597b712b997735c`; it matches the value already recorded in the preimage table above. The previous reviewer's truncated value could not be compared as a full hash.

The full dirty-path inventory is the ten `M` source/test paths in the table plus this new handoff file. Six of the eight paths outside `services.py` and `test_vision_service.py` match the T17 candidate after LF normalization; `vision_contracts.py` and `test_vision_contracts.py` also contain the narrow retention fix and regression assertion. `services.py` carries the explicitly mixed provenance above; `test_vision_service.py` differs from the candidate only by the two T28 golden tests. No other path is changed in this worktree.

## Observation source retention patch

The current root preimage `vision_contracts.py` SHA-256 is `048dd7ea1a464401cbe7a8fce421cb07711763809bd7a177ea40fb196ed18f6c`; the T17 candidate preimage is `a6db25171aeeeb4164cfd90009c128bd5aab733c88df98bd1fcc23a50870b3db`. Current T28 patch-file SHA-256 values: `vision_contracts.py` `cecfe2d37dac6bbabf8f030c31580d57f3ddfa7dcf3dcaf2975b6e011e84e36`, `test_vision_contracts.py` `ca223f99c278376809c865fa330b4baef37312a561337202ba51ebe9347fc224`. Both service callsites already supplied observation sources. The gap was that valid `parse_vision_result()` output omitted them from `VisionParseResult`. T28 adds that field and returns the supplied mapping unchanged. The grounded acceptance test now asserts preservation. `bound_vision_result()` uses dataclass `replace`, retaining the added field; service serialization via `asdict(parsed)` exposes it. No `services.py` or `/api/context/pack` edit was needed. Regression test not run pending T20 GO.
