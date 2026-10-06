# T28 root-current vision input extraction handoff — 2026-10-04

Candidate-only handoff. Root was read and `git apply --check` only; patch was not applied.

## Preimages, ownership, lease

- Candidate: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Required root `services.py` preimage SHA-256: `58908C5C718A520463171B7890C0B8E1E7F7CC54D5EF62F9809BE707EFC173FE`; observed exact before patch generation and after apply-check.
- Root `tests/test_vision_service.py` preimage SHA-256: `32CB2AC2C71B697CD81D3B5A74C6A7FD4AC015CD886E01E95597B712B997735C`.
- Candidate handoff-artifact lease: `lease_9b5d5b46f8a44f5f9da5`, request `req_377298e3fba2`.
- Root worktree remains dirty under T20 ownership; no root files were written or staged.

## Patch

- Candidate artifact: `handoff/t28-vision-root-current.patch`.
- SHA-256: `B0A0DAED16EBFC21F34B98BEF02A3CC22E1EB884348863608F4756B3F373D651`.
- Root `git apply --check`: exit 0. Patch remains unapplied.
- Changes only root vision input preparation: moves the root's matching bounded image/artifact/frontend-context block to candidate `vision_inputs.py`; adds one root characterization test for data-URL normalization. Root prompt construction, `format: "json"`, timeout, model policy, parser/error mapping, runtime/cancellation behavior and coder-context response stay inline and unchanged.
- Root input block compared to extracted candidate helper: 381 lines vs 382; sole extra helper operation computes image dimensions. Root service ignores the helper's `image_size` and retains its existing guarded calculation at the response stage.
- Candidate `vision_response.py` is deliberately not transferred: its request builder adds candidate grounding suffix/default strict schema behavior, while root currently has a distinct prompt and `format: "json"` contract. Whole helper transfer would change root behavior.

## Candidate source/test pins

- `src/local_ai_hub/services.py`: `8CEC8C8F041195622642C2F52962F97176CAB251BB8A57D7F9B7909CC5A9B83C`
- `src/local_ai_hub/vision_inputs.py`: `FAA436CB9F4F0720409E27F45E7908A2BC1AB28EF90D20603A49098959EE1D40`
- `src/local_ai_hub/vision_response.py`: `14C091CBC572011827F985CD92534687AFAFCECC23DC3F516E97CF8AEA7D09BA`
- `tests/test_vision_service.py`: `D9777156B00D02139B9BD77DA2140CE51FCBF45BABAC676FB5D2424B34621B86`

## Candidate acceptance receipt

- Exact command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_service.py::test_build_vision_request_preserves_format_prompt_and_image_bounds tests/test_vision_service.py::test_build_vision_request_rejects_oversized_schema_and_prompt tests/test_vision_service.py::test_prepare_vision_inputs_normalizes_data_url_and_reads_dimensions
```

- Prehash and posthash for the test file both `D9777156B00D02139B9BD77DA2140CE51FCBF45BABAC676FB5D2424B34621B86`.
- One candidate run: exit 0, 3 passed in 0.55s. CPU-only pure helper tests; no inference/Ollama/GPU/network.
- Python AST parse passed on candidate `services.py`, `vision_inputs.py`, `vision_response.py`, and test file. Candidate `LocalAIServices.vision()` now 381 lines.
- No root tests were run. Root patch is source-parity candidate only, not acceptance evidence.

## Later integration and verification update — 2026-10-04

This section supersedes the earlier "patch remains unapplied / no root tests" status above. T20 later authorized one root selector test and integration.

- Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Root post-integration hashes: `services.py` `E781F2258A8831900AFF0D3B4995D2033176519EA7C07838BE0EC228827E6D96`; `vision_inputs.py` `1FF3A456F2CEE8E202B7AC87D069EE7928BB4B7492A2F1A88A91FA8E534FD14E`; `test_vision_service.py` `893EB305584CC525A3DFFCFB5F87B5680CF5666D051FC016132DC784E4C8750F`.
- One root command authorized and run through `local_ai_command`: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_service.py::test_prepare_vision_inputs_normalizes_data_url_without_runtime`; exit 0, 1 passed in 0.50s. Pre/post hashes matched above. No further root tests run.
- Candidate T28 full `tests/test_vision_service.py`: exit 0, 65 passed in 4.07s. Latest test-file hash: `7314D975AFDC2F355EC7423F54E088D9D039F3AFC0AF7080C5878CF26A8C14A2`.
- Candidate broader targeted command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_contracts.py tests/test_frontend_review.py tests/test_browser_bridge.py tests/test_process_utils.py tests/test_transcription_contract.py`; exit 0, 171 passed in 6.45s. Candidate only.
- Current candidate source hashes: `services.py` `8CEC8C8F041195622642C2F52962F97176CAB251BB8A57D7F9B7909CC5A9B83C`; `vision_inputs.py` `FAA436CB9F4F0720409E27F45E7908A2BC1AB28EF90D20603A49098959EE1D40`; `vision_response.py` `14C091CBC572011827F985CD92534687AFAFCECC23DC3F516E97CF8AEA7D09BA`.
- `LocalAIServices.vision()` passes `model_context.observation_sources` into `parse_vision_result()` in both candidate and root. The explicitly authorized callsite edit was already present in both; no additional edit was needed. `transcribe()` and `/api/context/pack` remain untouched by this change.
- Input preparation microbenchmark: `python -B handoff/t28-vision-input-latency.py`; parity PASS, 1,000 repetitions × 20 batches. Inline-stage median 0.004010 ms / p95 0.005680 ms; helper median 0.006776 ms / p95 0.007720 ms; median delta +68.99% (about +2.77 μs). CPU-only, mocked artifact store; not whole-vision or model latency. Live-model latency and quality remain unverified.
- Candidate `vision()` AST length: 381 lines after refactor; integrated root: 369 lines. Earlier candidate inline length was 870; root inline length before extraction was 734.
- Worktree remains dirty on 23 tracked paths plus candidate handoff/helper additions. T28-owned source/test changes are the three candidate vision files and `tests/test_vision_service.py`; remaining dirty paths are inherited/shared and not claimed here. No root edits were made by this turn.

## Final T28 receipt — 2026-10-04 (supersedes earlier status notes)

### Candidate identity and ownership

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`.
- Git state: detached HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`; `git branch --show-current` returned empty.
- T28-owned source/test paths: `src/local_ai_hub/services.py` (only `LocalAIServices.vision()` extraction hunks; file was already dirty), `src/local_ai_hub/vision_inputs.py`, `src/local_ai_hub/vision_response.py`, `tests/test_vision_service.py` (T28 additions/hunks; file was already dirty).
- T28-owned handoff files: `handoff/t28-vision-root-current.patch`, `handoff/t28-vision-root-current-receipt-2026-10-04.md`, `handoff/t28-vision-result-assembly-extraction.patch`, `handoff/t28-vision-result-assembly-receipt-2026-10-04.md`, `handoff/t28-vision-input-latency.py`.
- Inherited tracked dirty paths (21): `browser_bridge/background.js`; `src/local_ai_hub/frontend_review.py`, `mcp_server.py`, `process_utils.py`, `vision_contracts.py`; `tests/fixtures/browser_bridge/current_tab_harness.js`; `tests/test_browser_bridge.py`, `test_browser_bridge_background.js`, `test_browser_bridge_runtime.py`, `test_cloud_model_accelerators.py`, `test_completion_model_routing.py`, `test_frontend_coder_context.py`, `test_frontend_review.py`, `test_http_vision_routes.py`, `test_mcp_agent_routing.py`, `test_missing_and_high_value_features.py`, `test_process_utils.py`, `test_speculative_draft_and_split.py`, `test_transcription_contract.py`, `test_vision_artifacts.py`, `test_vision_contracts.py`.
- Other pre-existing content under untracked `handoff/` is inherited; only the five `t28-*` files listed above are claimed here. No root files were edited by this T28 work.

### Source and patch hashes

- Candidate `services.py`: `8CEC8C8F041195622642C2F52962F97176CAB251BB8A57D7F9B7909CC5A9B83C`.
- Candidate `vision_inputs.py`: `FAA436CB9F4F0720409E27F45E7908A2BC1AB28EF90D20603A49098959EE1D40`.
- Candidate `vision_response.py`: `14C091CBC572011827F985CD92534687AFAFCECC23DC3F516E97CF8AEA7D09BA`.
- Candidate `tests/test_vision_service.py`: `7314D975AFDC2F355EC7423F54E088D9D039F3AFC0AF7080C5878CF26A8C14A2`.
- Root-current patch SHA-256: `B0A0DAED16EBFC21F34B98BEF02A3CC22E1EB884348863608F4756B3F373D651`. It is input-preparation-only, not the full response extraction. It passed apply-check, was subsequently integrated in root under T20 authorization, and the one approved root selector passed. Root post-integration hashes: `services.py` `E781F2258A8831900AFF0D3B4995D2033176519EA7C07838BE0EC228827E6D96`; `vision_inputs.py` `1FF3A456F2CEE8E202B7AC87D069EE7928BB4B7492A2F1A88A91FA8E534FD14E`; `tests/test_vision_service.py` `893EB305584CC525A3DFFCFB5F87B5680CF5666D051FC016132DC784E4C8750F`.
- Candidate response-assembly extraction patch SHA-256: `1B7608D5D1347C1FDF8338400F2FFD1F88E4AC2AA4D4DF69366D0131D8078679`; candidate-only, not transferred to root because root uses its own prompt/`format: "json"` contract.

### Size and extraction status

- Candidate `LocalAIServices.vision()` AST span: 381 lines after extraction (was 870 inline before T28).
- Root `LocalAIServices.vision()` AST span: 369 lines after the input-only integration (was 734 inline before it).
- Candidate decomposition extracts input preparation and request/success-payload assembly while retaining candidate behavior. Root's full 734-line extraction is **not complete**: only input preparation moved to a helper; its root-specific request/response builder remains inline. This avoids importing the candidate's differing prompt/default-schema behavior.
- `transcribe()` and `/api/context/pack` were outside the T28 edit scope and remain untouched by it.

### Exact verification already run (no further tests run for this update)

1. Candidate full vision module:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_service.py
```

Exit 0; 65 passed in 4.07s.

2. Candidate dependent contracts:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_contracts.py tests/test_frontend_review.py tests/test_browser_bridge.py tests/test_process_utils.py tests/test_transcription_contract.py
```

Exit 0; 171 passed in 6.45s. Candidate only.

3. Root selector, the sole T20-authorized root test:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_service.py::test_prepare_vision_inputs_normalizes_data_url_without_runtime
```

Exit 0; 1 passed in 0.50s. No more root tests were run.

The separately recorded input-preparation microbenchmark is CPU-only with a mocked artifact store; it is not whole-vision or live-model latency evidence.

## Root-current v2 owner patch — 2026-10-04

Prepared only; not applied to root.

- Candidate: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`, detached HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- Root preimage: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Exact root preimage SHA-256 pins: `src/local_ai_hub/services.py` `E781F2258A8831900AFF0D3B4995D2033176519EA7C07838BE0EC228827E6D96`; `src/local_ai_hub/vision_inputs.py` `1FF3A456F2CEE8E202B7AC87D069EE7928BB4B7492A2F1A88A91FA8E534FD14E`; `tests/test_vision_service.py` `893EB305584CC525A3DFFCFB5F87B5680CF5666D051FC016132DC784E4C8750F`; new `src/local_ai_hub/vision_payload.py` is absent.
- Owner-only patch: `handoff/t28-vision-root-current-v2-result-payload.patch`, SHA-256 `530F76672BE1A6BFE81A459E77EAE380F759320A763634545535A1C961F54449`.
- `git -C C:\Users\Adam\.local-ai-hub apply --check <patch>`: exit 0. Root preimage hashes and file absence were rechecked after apply-check; root was not modified.
- Patch moves only the existing successful response map (same key set and values, same response truncation constant) into `vision_payload.py`. It does not alter request construction, capability checks, fallback, cancellation, timeout handling, prompt/schema/image limits, or facade.
- Candidate tests already run on matching pins; no duplicate run: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_service.py` — exit 0, 65 passed in 4.07s. Current candidate pins: `services.py` `8CEC8C8F041195622642C2F52962F97176CAB251BB8A57D7F9B7909CC5A9B83C`; `vision_inputs.py` `FAA436CB9F4F0720409E27F45E7908A2BC1AB28EF90D20603A49098959EE1D40`; `vision_response.py` `14C091CBC572011827F985CD92534687AFAFCECC23DC3F516E97CF8AEA7D09BA`; `tests/test_vision_service.py` `7314D975AFDC2F355EC7423F54E088D9D039F3AFC0AF7080C5878CF26A8C14A2`.
- Candidate `vision()` decomposition is tested; candidate `vision()` AST span is 381 lines. Root full 734-line extraction is not complete: input preparation is already in `vision_inputs.py`; this proposed patch extracts success-payload assembly only; root-specific prompt/request construction remains inline to preserve its distinct prompt/`format: "json"` contract. No live model/browser quality is claimed by source tests.
- T17 browser/vision/audio/profile acceptance details and runtime blockers are in `handoff/t17-browser-vision-contracts-current-receipt-2026-10-04.md`; `/api/context/pack` remains excluded.

## Independent review and measurement gate — 2026-10-04

- Independent read-only review of `handoff/t28-vision-root-current-v2-result-payload.patch` (SHA-256 `530F76672BE1A6BFE81A459E77EAE380F759320A763634545535A1C961F54449`) completed with **no findings**. Reviewer confirmed applicability to root HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`, identical eight response keys/values, 12,000-character truncation, `review=asdict(parsed)`, and no changes to capability, fallback, cancellation, timeout, prompt/schema/image limits, `/api/context/pack`, or unrelated paths. Reviewer ran no tests and made no edits.
- Root `git apply --check` passed; patch remains unapplied. No T20 one-shot GO for a test of this v2 payload-extraction patch is recorded, so no root test or integration was performed.
- Paired latency receipt already recorded: CPU-only input-preparation stage, mocked artifact store, parity PASS; inline median 0.004010 ms / p95 0.005680 ms versus candidate helper median 0.006776 ms / p95 0.007720 ms (+2.77 microseconds median; +68.99%). This is not whole-vision latency.
- Paired memory and live vision-success comparison are blocked: no same-image, same-runtime before/after execution was run for this root payload extraction; the root patch is unapplied and its helper was only statically reviewed. Candidate contract tests do not measure model memory or live quality. Earlier live vision smoke failed grounding, so it cannot serve as a successful after measurement.
- Candidate vision test receipt remains the exact prior run: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_service.py` — exit 0, 65 passed in 4.07s at the pinned candidate hashes above. No repeat was performed.
