# T17 / T28 vision provenance receipt

Date: 2026-10-03. Read-only provenance checks; no tests run, no root files edited.

## T17 owner hunk

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.

The `observation_sources` retention hunk is already present in this dirty T17 candidate: `VisionParseResult.observation_sources` at `src/local_ai_hub/vision_contracts.py:174`, successful `parse_vision_result()` return at line 585, and regression assertion at `tests/test_vision_contracts.py:165`. `LocalAIServices.vision()` already supplies the mapping at lines 2495-2497. Candidate hashes: `vision_contracts.py` `75207f69f9a71e67ee353201b007d9a67678f3caca5c3e78a4544b37b82ef7c6`; `test_vision_contracts.py` `747d01b55a251a142b742dc787a2656136ebde188f167ead5c55319ef5dcb4bf`; `services.py` `a3c9c6dbae5acfaac1d543f02783eda4fbbc89f7991d9870f849972f7224f0c0`.

Vision-method ownership relative to root: T17 adds `cancel_event` checkpoints, non-object request rejection, image-dimension capture, grounding prompts, default structured schema, and numeric DOM-ID normalization. Root-specific malformed-output fallback/error detail remains outside the extraction hunk. The `services.py` dirty remainder and browser/audio/MCP files are existing T17/inherited worktree state; this turn edits none of them.

## Root preimages and wrapper receipt gap

Current root is a separate dirty checkout at `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`. Current root SHA-256: `services.py` `58908c5c718a520463171b7890c0b8e1e7f7cc54d5ef62f9809be707efc173fe`; `vision_contracts.py` `048dd7ea1a464401cbe7a8fce421cb07711763809bd7a177ea40fb196ed18f6c`; `tests/test_vision_contracts.py` `583c760fa84b099775fac4da0c32e71e144d0d5cb38c606ab8f3b96994d4858b`; `tests/test_transcription_contract.py` `decc2f2ac615176e90d0b5ee314a8a3683cc2af612848626c6dd417e425645d0`.

Root `VisionParseResult` has no `observation_sources` field; its parser accepts the argument but drops it on success. Root `services.py` does pass its observation-source mapping to the parser. Candidate-to-root source patch remains untransferred.

Latest root plan `docs/superpowers/plans/2026-09-22-hub-quality-performance-master-plan.md` SHA-256 `f34b9cdcfb6595979bde037a8bb61975a6a9959623e9cf9ee45144aca49bdef`, line 1803, marks T28 active and says root apply-check, root/test preimages, and T17 multimodal acceptance remain pending. An earlier dirty root-plan snapshot in this turn (SHA-256 `601c3e303931bf1eee7bbd590544b3f9d8e76c80599ed5fd65b00f0cbe0a30de`) recorded 136 pass / 1 fail mentioning `request_id`, but that entry has since changed. Treat that count as an unverified historical report, not current test evidence. The current root transcription fixture preimage SHA-256 is above; lines 493, 501, and 509 set `t17-transcribe-route-request`, send `X-LocalAI-Request-ID`, and expect the same `request_id` in the response. No exact root acceptance command or authoritative receipt is available in the current plan entry.

Root/candidate `tests/test_vision_service.py` SHA-256 values are `32cb2ac2c71b697cd81d3b5a74c6a7fd4ac015cd886e01e95597b712b997735c` and `25e7055a1ba98ea1446c1f06c3c073a3e46766453b11305cdfd3cbdb049dfee8`, respectively. The extraction patch's added test depends on T17's `VisionParseResult.observation_sources` field, which root lacks until the T17 source hunk is transferred.

## Separate T28 extraction patch

`handoff/t28-vision-result-assembly-extraction.patch`, SHA-256 `1b7608d5d1347c1fdf8338400f2ffd1f88e4ac2aa4d4df69366d0131d8078679`. It extracts only the common successful response-dictionary assembly from `vision()` into a pure helper and adds a runtime-free unit test. The malformed-output branch remains in place, preserving root-specific fallback error behavior. Candidate `git apply --check` passed; root-current `git apply --check` failed at the differing `vision()` signature and test insertion context. Patch is not applied and is candidate-preimage-specific. `/api/context/pack` and other routes are untouched.

Prepared selectors; both **NOT RUN** pending T20 serial GO:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_contracts.py::test_grounded_vision_accepts_observation_fact_matching_cited_dom
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_service.py::test_vision_success_payload_assembles_review_without_runtime
```
