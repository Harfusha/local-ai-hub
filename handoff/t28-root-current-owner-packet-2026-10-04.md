# T28 root-current owner packet — 2026-10-04

Read-only parity audit. Prepared in the T17 candidate worktree only. No root files or tests changed during this audit.

## Exact worktree pins

- Candidate: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`, detached HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- Candidate SHA-256: `services.py` `8CEC8C8F041195622642C2F52962F97176CAB251BB8A57D7F9B7909CC5A9B83C`; `vision_inputs.py` `FAA436CB9F4F0720409E27F45E7908A2BC1AB28EF90D20603A49098959EE1D40`; `vision_response.py` `14C091CBC572011827F985CD92534687AFAFCECC23DC3F516E97CF8AEA7D09BA`; `test_vision_service.py` `7314D975AFDC2F355EC7423F54E088D9D039F3AFC0AF7080C5878CF26A8C14A2`; `test_vision_contracts.py` `747D01B55A251A142B742DC787A2656136EBDE188F167EAD5C55319EF5DCB4BF`.
- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Current root SHA-256: `services.py` `5B450E1C960B8B55D29FF482BD425C7F3208B178FEE9C1135224984492CA12E0`; `vision_payload.py` `CF850DE6259EEA308F00EB42168BCBBD84927D214FB52FD965421A4132B96FF9`; `test_vision_service.py` `893EB305584CC525A3DFFCFB5F87B5680CF5666D051FC016132DC784E4C8750F`; `test_vision_contracts.py` `583C760FA84B099775FAC4DA0C32E71E144D0D5CB38C606AB8F3B96994D4858B`.

## T28 slice disposition

The candidate-only patch `handoff/t28-vision-result-assembly-extraction.patch` has SHA-256 `1B7608D5D1347C1FDF8338400F2FFD1F88E4AC2AA4D4DF69366D0131D8078679`. Its candidate preimages and postimages are recorded in `handoff/t28-vision-result-assembly-receipt-2026-10-04.md`.

The root-current v2 patch `handoff/t28-vision-root-current-v2-result-payload.patch` has SHA-256 `530F76672BE1A6BFE81A459E77EAE380F759320A763634545535A1C961F54449`. Its old root pin expected `services.py` `E781F2258A8831900AFF0D3B4995D2033176519EA7C07838BE0EC228827E6D96` and `vision_payload.py` absent. Those preconditions no longer match current root hashes above. Do not apply that patch.

Root already has `vision_payload.vision_success_payload()`. Static source comparison shows same successful response fields and values as candidate `vision_response.vision_success_payload()`: success, model, bounded response, parsed review, prompt, artifact IDs. Both preserve `review.observation_sources`. Root callsite now passes `model_context.observation_sources` directly. The T28 success-payload extraction is therefore already represented in root; no duplicate helper or transfer patch is needed.

## Remaining source parity

- Root retains its `vision_request.py` request contract, including `format: "json"` and root schema handling. Candidate `vision_response.py` adds grounding instructions about supplied DOM IDs, image-coordinate boxes, and observed evidence. Keep these request builders separate unless a later owner authorizes a behavior change.
- Candidate `LocalAIServices.vision()` accepts `cancel_event` and checks cancellation around runtime phases. Root `vision()` has no cancellation parameter. This is a remaining lifecycle parity difference; this packet does not change it.
- Candidate and root HTTP/MCP vision routes call their respective service paths. Route parity does not establish installed-browser or production-daemon behavior.

## Acceptance still open

- Candidate receipts report simulated browser harnesses only. Installed extension permissions and a real browser-to-production-daemon connection remain unverified.
- Prior live local-model smoke failed grounding: output used an unsupported DOM ID. Transport success is not accepted vision quality. Fresh live-model evidence with valid grounded output remains required.
- Candidate test receipts are historical source/contract evidence only; this audit ran no tests and did not repeat them. The recorded candidate T28 selector was 149 passed; it does not close either live runtime gate.

## Owner decision

Close the T28 payload-extraction transfer as already represented in current root. Retire the old root-current v2 patch for this root state. Track cancellation parity and browser/live-model acceptance separately under T17 ownership. `/api/context/pack` remains excluded.