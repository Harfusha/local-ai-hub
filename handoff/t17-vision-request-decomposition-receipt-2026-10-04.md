# T17 candidate vision decomposition receipt — 2026-10-04

Source-only. No tests, benchmarks, or builds run. T20 serial test slot remains closed.

## Goal, checkout, ownership, preimages

- Existing objective: T17 multimodal/browser end-to-end acceptance. Historical checkpoint `t17-test-slot-checkpoint-2026-10-02.md` recorded the goal blocked; current `get_goal` returned null. T17 acceptance remains open.
- Candidate only: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`. No root edits.
- Initial dirty preimage for this refactor: `services.py` SHA-256 `505990A19AF517103A7AEA24EE52289098B3967FC7EE9CC81059A90F983A1568`; `test_vision_service.py` `CE70055A26DACDE600A76C508EDF4C84C8C4E19833D8CF8797B99C5FF4225BCC`.
- Before input extraction, current preimage was `services.py` `70E44832AC394741652A24921B8243DF5AA67F8113383D5E76D8F442164D1F4C`, `vision_response.py` `14C091CBC572011827F985CD92534687AFAFCECC23DC3F516E97CF8AEA7D09BA`, and test `test_vision_service.py` `798038C6EC0FC5A3BE6319CCE4CCCC80933604042B769D1CCBAF10AEFA9A38B0`.
- Leases acquired before edits: `lease_bb44e6e92a9749178cf3` for first stage; `lease_333d40d028da4b1c8b29` for input extraction paths `services.py`, `vision_inputs.py`, `vision_response.py`, `test_vision_service.py`.
- `transcribe()`, `/api/context/pack`, routes, and all other service methods were not edited in this refactor.

## Decomposition

- `services.py::vision()` candidate size: 870 → 381 lines.
- `src/local_ai_hub/vision_inputs.py::prepare_vision_inputs` owns image/path/artifact validation, bounded bundle resolution, frontend evidence assembly, and image dimensions. Existing error dictionaries and artifact tenancy remain unchanged; method now unpacks a `VisionInputs` result or returns its error result.
- `src/local_ai_hub/vision_response.py::build_vision_request` owns schema-size validation, prompt grounding/bounds, default strict schema, and provider payload assembly.
- `vision_response.py::vision_success_payload` owns successful response assembly and parsed review serialization.
- Added tests: `test_prepare_vision_inputs_normalizes_data_url_and_reads_dimensions`, `test_build_vision_request_preserves_format_prompt_and_image_bounds`, and `test_build_vision_request_rejects_oversized_schema_and_prompt`; existing success-payload test now calls the extracted pure helper.
- Runtime/model request order, auth/tenant artifact access, cancellation checks, timeout, model capability/fallback/error classification, output parsing and coder-context follow-up remain in `vision()`.

## Current hashes

- `services.py`: `8CEC8C8F041195622642C2F52962F97176CAB251BB8A57D7F9B7909CC5A9B83C`
- `vision_inputs.py`: `FAA436CB9F4F0720409E27F45E7908A2BC1AB28EF90D20603A49098959EE1D40`
- `vision_response.py`: `14C091CBC572011827F985CD92534687AFAFCECC23DC3F516E97CF8AEA7D09BA`
- `test_vision_service.py`: `D9777156B00D02139B9BD77DA2140CE51FCBF45BABAC676FB5D2424B34621B86`

## Static review and pending acceptance

- Python AST parse passed for `services.py`, `vision_inputs.py`, `vision_response.py`, and `test_vision_service.py`; current `vision()` AST length is 381 lines.
- `git diff --check` exit 0 for tracked service/test changes; new helper files checked for trailing whitespace.
- Focused candidate source tests, run only after next explicit T20 GO:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_browser_bridge.py tests/test_frontend_review.py tests/test_http_vision_routes.py tests/test_process_utils.py tests/test_transcription_contract.py tests/test_vision_contracts.py tests/test_vision_service.py
node tests/test_browser_bridge_background.js
```

- This covers input/schema/prompt/result contracts; DOM grounding and image anchors; cancellation, capability/error/fallback behavior; browser capability and stage/commit/abandon; tenancy/origin; subprocess cleanup; transcription contracts.
- Optional candidate adapter harness after GO: `node handoff/t17-browser-adapter-live-e2e.mjs`. Fake API/headless Edge only; does not prove installed-extension permission or production daemon behavior.
- Live browser permission/tab behavior, persistent daemon expiry/replay, natural multilingual Whisper WER, and live vision quality remain NOT VERIFIED pending real-runtime receipts.
- No tests or benchmarks run here. Historical receipts do not apply to current hashes. Do not mark T17 complete before current source acceptance and required external runtime receipts pass.
