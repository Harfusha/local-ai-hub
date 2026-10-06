# T04 owned client/current-root acceptance — 2026-10-01

Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`.

Current root overlay: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.

## Current candidate source/test hashes

- `src/local_ai_hub/client.py`: `04CD4D0CE198C20C7A68357D587F00D91FFE3828C4AD5937E65A7D6FE703AD6E`
- `src/local_ai_hub/http_server.py`: `840933FF8801832D4DDC4746853011AB1486338EA42BBA186E137393574156D7`
- `tests/test_client_transport.py`: `777CC424B651130DC96FE4D2EAC21FE6E4C152E1C19C46F18EAE380587F588F3`
- `tests/test_sse_events_stream.py`: `BCEE7A41E7A561DE6E1F4C5F7C663CCFE518CAC9616F48064A5CD86CB67EEECC`
- `tests/test_t04_client_auth_transport.py`: `56B2A4D1348EBF4B1F89F02A6493FA660BC058B9FD2A5585D2F91F662A4EBCE7`
- `tests/test_t04_client_retry_acceptance.py`: `962619E6D813DB33D6E075F9E6091DCE2125DF0DD0037A8E19C65F3475AF590D`
- `tests/test_client_startup_resilience.py`: `67264628ED9221610C346594B6385851BAC7B3D1351B0A138A426B1A03D86D9D`
- `tests/test_client_operational_mode_autostart.py`: `EF9F7A51DC2B4913B396CCBD3D62D4B848A7EBABF39CE943E33F92759398172A`
- `tests/test_t04_root_path_hint_chain.py`: `69391152DD30E4E573E62DB2541D3B0076671C6C02147D4BBC7F2C808650B672`

## Fresh owned-selector results

Candidate command covered client HTTP/1.1 pool reuse, idle reconnect, stable explicit request ID, invalid-ID preflight, client token/tenant/agent on SSE, SSE cancellation/deadline/parsing, server replay/live delivery, replay-subscribe race, and bounded timeout. T07 replay/journal selectors, T13 mode selectors, and T06 broker selectors were excluded.

Result: **12 passed in 2.83s**, exit 0.

The client-auth selector now loads `[security].api_token` and uses default `HubClient` transport against a temporary loopback HTTP server invoking real `Handler._authorized`. Correct, wrong, and missing tokens were checked; auto-start is disabled. Final selector command — **1 passed in 2.70s**. The other 11 selectors in the grouped run are unchanged and passed.

Safe GET retry and unsafe POST outcome:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_client_retry_acceptance.py` — **2 passed in 3.35s**. GET retried once with same request ID; unsafe command POST made one attempt and returned `outcome_unknown`. Existing unclassified mutation, file-writing generate, and allowlisted read-only POST selectors also passed in the grouped route run. A first draft assertion expected an absent `terminal` field; test was corrected to assert the documented unknown outcome and stable request ID.

Offline mode/startup failure and cleanup:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_operational_mode_autostart.py tests/test_client_startup_resilience.py -k 'not autostart_launches_real_hub_child_and_returns_http_search_result' tests/test_client_transport.py::test_ensure_server_mode_load_failure_blocks_autostart`

Result: **17 passed, 1 deselected in 3.06s**. Covered terminal mode refusal, no spawn/state creation, missing executable, readiness timeout, owned-child termination, lock cleanup, and stale/unreaped lock cases. The actual child cold-start selector was deselected; no user daemon was started.

Current-root controlled source-overlay command:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_root_path_hint_chain.py::test_registered_repo_search_forwards_hints_over_real_root_http`

Result on current root HTTP hash below: **1 passed in 5.18s**, exit 0. Child process asserted imports came from current root source, then exercised registered FastMCP `local_ai_repo` → real `HubClient` → real loopback `/api/search` → `repo_search`. Temporary config, state, repository, and socket only. Current root overlay chain passes; candidate branch itself still lacks T03/T21 forwarding.

## Root-current patch inventory

Current root hashes: client `252F1781BE55DD2545DD7E3B21915F7A8AE20814DD2DB351E823124C6BFA1A19`; HTTP server `CD2998708AFBEE64A22D8027AA86969E9C17A05967CBED8431BEE7A4F8D55FD5`; MCP server `BFB3C65A513E2ADB669DDC52CFAAD6F8EC38B1624DCF5AD8F08361027C219DB3`; services `1556EDBE4336E1D0FECDAC86D79593AB6F62BE12A1F13841537CAC453721DCC1`; client transport tests `03000F1016075FC4B4025F9185CFFB471043663028F04496B0CD4F42D5EA06A0`; SSE tests `FD278EF2A1472203B50C99F9D5E2D1AF0F87397B6DB3A103952D91BE5BD88CBD`.

All five read-only `git apply --check --whitespace=error` checks passed against that root snapshot:

- `handoff/t04-sse-disconnect-root-current.patch` — owned SSE production fix plus disconnect regression test. Current root still finalizes `_stream_agent_events` as success on write disconnect; patch remains needed.
- `handoff/t04-request-id-preflight-root-current.patch` — request-ID test only. Current root already has production preflight; do not duplicate it.
- `handoff/t04-client-auth-transport-test.patch` — loopback default-client token/auth test only, SHA-256 `E9EEFD6F5B7F4DB8D186BDE74AAF9727E816227E0197AB61FDAEE23F9776FD2F`.
- `handoff/t04-client-retry-acceptance-test.patch` — safe GET/unsafe POST transport test only, SHA-256 `EBF9E61F7F17B24BA7B9780FE5C62344BB36E891D6D510C60E95F38D6A665050`.
- `handoff/t04-root-path-hint-chain-test.patch` — current-root path-hint E2E test only.

Root files were not changed; no root test suite ran. Root test slot remains T20-owned. Current root request-ID preflight is present; root SSE patch remains pending T20 integration/runtime validation. Candidate replay keyword mismatch remains T07-owned and open per `artifacts/t04-request-id-root-current-and-replay-rca.md`.

HUB not used.
