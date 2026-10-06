# T04 to T20 acceptance handoff

Date: 2026-10-02 (Europe/Prague)
Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
Branch: `codex/t04-integration-2b33602`
Status: partial; no root checkout writes in this continuation.

## Candidate receipts

- Current API/conversation/query/inventory command is recorded in `artifacts/t04-api-conversation-current-candidate-receipt-2026-10-02-v1.md`: **40 passed in 49.27s**, exit 0. Receipt SHA-256: `FDDBB631CE7F82D870E81612DCC7CD95A8C2F1F795EC88134D5CC401CD3152D9`.
- Full assigned candidate suite: **133 passed in 27.74s**, log SHA-256 `46B51D4C7733C8E335EF885DC5F0B1F8709A818068219A7CE0AC9B4C3A0DABFF`.
- Focused client transport/auth/retry/malformed/preflight: **39 passed in 4.66s**. Actual loopback request-ID retry selector: **1 passed in 2.38s**. Daemon-off MCP stdio selectors: **2 passed in 15.31s**. Concurrency/timeout selectors: **3 passed, 9 deselected in 3.12s**.
- Continuation checks: `git diff --check` passes with existing LF-to-CRLF advisories. Tracked-file forbidden-token scan examined 456 files and found zero matches.
- Release scanner selector was run once and failed because its recursive scan includes untracked local receipts under `artifacts/`; first reported file: `artifacts/t04-api-client-acceptance-closeout-2026-10-01-v1.md`. Therefore no release-scanner pass is claimed.

## Hash-bound candidate pins

- `src/local_ai_hub/client.py` — `DCDF8BB8FF150B5FCD4EDD3A25B53991DD6B87CDB9DDDEC0714A7F11B2FAE5B1`
- `src/local_ai_hub/mcp_server.py` — `A6449D390F27ED56C89139AC56518AD0D57AB9285FFD7FAD05E7D000D6729F50`
- `tests/test_t04_public_api_contracts.py` — `AAFA9BF5713002C32EFDDE7D0CA77CFD7CD11CA9D38220F95B40BC8BF226ADFB`
- `tests/test_conversations.py` — `DA4822506DE70C66AA1204D6A44F1CECAEA766EBAD90DA012A67E933866973D7`
- `tests/test_conversation_continue_route_contract.py` — `32065B53B2D187648D8B181D106DCA59043BC609883A723F6760DB039BD2F3D5`
- Checkout-relative path-hint test — `95C85C244B968546581F5158BC29FD60DDC81BA5108C670440426CAEFEA3DF20`
- T04 plan — `F7A00A8CFD311BADAB52C8E562EFAA3BFCD3D1CBEA75C320D8470911902C0A24`

## Remaining acceptance blockers

- Candidate lacks the T03-owned public MCP `path_hints` wrapper. Do not add that hunk in T04; root verification belongs to its owner.
- T21 adapter/runtime proof is absent from T04 evidence.
- The checkout-relative root path-hint test is not evidence that the candidate supports the missing wrapper; its root-current integration check remains separate.
- No root integration was performed here. Existing dirty work and owner boundaries remain intact.

## Tenant-isolation source review (2026-10-02)

- `src/local_ai_hub/artifacts.py:545-576` — `ArtifactStore.list()` hashes the tenant identity and uses it in both v2 and legacy table queries; it keeps `max(1, min(limit, 100))`, descending `created_at`, and metadata-only output fields. Source SHA-256: `7F598EE33012F3990CE6792D32EC2C125E12BBD113F0DF2B1A75C11C91ABB5B1`.
- Existing v2 and legacy isolation selectors are `tests/test_t04_public_api_contracts.py::test_artifact_list_v2_hashes_and_isolates_tenants` and `::test_artifact_list_legacy_hashes_and_isolates_tenants`. Both are included in the 40-test receipt above. Test source SHA-256: `AAFA9BF5713002C32EFDDE7D0CA77CFD7CD11CA9D38220F95B40BC8BF226ADFB`.
- No edits to `artifacts.py` or its tests in this continuation.

## Opt-in in-process transport handoff (2026-10-02)

- `src/local_ai_hub/client.py` SHA-256: `338A2C40C982E2A079B99F2A9C7044630F70788082B6219AA6174F1EAAB82098`.
- `src/local_ai_hub/inprocess_transport.py` SHA-256: `A5567CF4F86D848CA9034ECE886E497E3DB4AAFEFCA7EC81ABD772F64AEB5C75`.
- `tests/test_inprocess_transport.py` SHA-256: `57EDD308C3BB85BDAA23575A67417FA79326A89BFE5E9E0E36BFF408623F1FE8`.
- Exact command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_inprocess_transport.py tests/test_client_transport.py` — **37 passed in 4.71s**, exit 0.
- Covers explicit opt-in, daemon-free real `LocalAIApp` initialization, Handler service route over memory I/O, no HTTP connection/process spawn, auth/tenant/request ID, payload schema and structured errors, action-based mode gate plus allowed deterministic reads, persistent tenant rate limit, work-order cancellation route, and before/after-dispatch timeout semantics.
- Contract for T03 wiring: `handoff/t04-inprocess-transport-contract-t03-v1.md`, SHA-256 `2AC552ED0ED8AACD0638F27C4E68E532E23F08A2AB992B4388DA2FF8D65A9733`. T03 owns `mcp_server.py` / `operation_contracts.py` wiring and supplies `operational_action` plus `requires_heavy_work`.
- `git diff --check` passes with existing line-ending advisories. The serial test slot was released to T05 after the green combined run.
- T04 did not edit `mcp_server.py`, `operation_contracts.py`, `http_server.py`, root checkout, or `/api/context/pack`. Actual daemon-off MCP acceptance remains pending T03 wiring; this receipt proves the injected client/core transport only.
