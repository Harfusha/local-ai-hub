# T13 mode failure compatibility handoff — 2026-10-01

Root: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Root remains read-only to T13.
Patch: `handoff/T13-root-mode-test-contract-current.patch`
Patch SHA-256: `DCD0E5D51AED1A08D5A02C71FADF3DABFFA130F7118486E8C7050044D28F5165`

Patch changes tests only; no production source fix warranted. It updates obsolete expectations and supplies mocks for the integrated operational-mode contract. It preserves assertions for health visibility, reserved cleanup outside the guard, stale mode protection, no database insert, and gaming retryable behavior.

## Root preimage pins

Tests:
- `tests/test_operational_mode.py`: `4A4CAA411D6E09C4C4AB769E79BEC2808811455347E0DDC6C090DFC1D19F3825`
- `tests/test_async_operational_mode.py`: `BA0CF6DECBA000A0AFD486A7B48A03A1C57208B5B02C65DB7CC496919A19F287`

Relevant integrated source at validation time:
- `src/local_ai_hub/operational_mode.py`: `50FA2F56E0B0FDECED08EA1603C78D81DB2E4451BDEFA4E1D6D219D0FD60E8F9`
- `src/local_ai_hub/http_server.py`: `CCB912FE56D153B9E8D38DD240170F6B4EDA1734BF8788A2E41B508672552770`
- `src/local_ai_hub/mcp_server.py`: `44205472ECA30794493082930E2D1775BFD4D7F37D189F2289E61CB3783BAEBF`
- `src/local_ai_hub/app.py`: `F87ECDD9871EE49AFA11D3DDED67FFF83EA6CA0CE00697C85251EAD2F0DED6ED`
- `src/local_ai_hub/async_jobs.py`: `77F33CA01FF72B22C2D4E3E080A28767259A02713AD6F7CFE84DA1BE5E2AD5B8`

## Four failure classifications

1. `test_mcp_agent_tool_is_rejected_before_dispatch_but_status_remains_available`: stale assertion. `local_ai_status` is operator-visible in maintenance by explicit current contract. Assert successful health response and second status transport call; do not expect mode rejection. Agent workload calls remain blocked before backend/Agent OS work.
2. `test_http_mode_routes_read_and_update_persisted_mode`: stale mock. It lacked release reservation and bounded admission drain methods, so production path failed closed before the second guarded revision check. Mock now models reserve, drain, release. Keep two guard cycles asserted; runtime unload asserts guard exited and reservation remains active.
3. `test_http_mode_skips_gaming_unload_after_later_resume`: stale mock. It directly edited persisted mode after transition without manager reservation/admission APIs. Mock now models those seams; test still asserts stale response, no unload, and reservation release.
4. `test_gaming_rejects_new_inference_before_database_insert`: stale test setup/contract. It monkeypatched loader but omitted paired `operational_mode_gate_error`, forcing incomplete fallback shape. Patch injects real helper. Assertions retain mode and empty DB, match current gaming contract (`terminal=False`, `retryable=True`).

## Receipts

- Original four selectors against exact root-source copy: **4 failed**, matching T20 diagnostics.
- Same exact selectors after test-contract patch in that isolated copy: **4 passed in 2.64s**.
- Existing T13 candidate deterministic-read policy selector: **1 passed in 0.12s**.
- `git apply --check` against fresh copies of both root test preimages: exit 0.
- Root received no writes.
