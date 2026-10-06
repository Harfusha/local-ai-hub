# T14 root-current response-budget fix — 2026-10-04

## Confirmed cause

The root context projection passed `tuple(authoritative)` to `budget_response`. That set includes full `context` and `query` strings. With the E2E fixture, the 512-token request cannot preserve every protected field; root returns `success=false` and `error="max_response_tokens too small"`. The test expectation is valid: the T14 projection keeps identity, citation, contract, and provenance while allowing bulky context text to compact.

## Candidate-only diagnostics

- Root's reported selector: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_context_pack_budget_e2e.py::test_mcp_adaptive_context_pack_crosses_http_with_bounded_provenance` — `1 failed in 4.22s`, at `result["success"] is True`.
- Reproduced root policy in T14 worktree only by temporarily overlaying root `response_budget.py` and passing `tuple(authoritative)`: `success=false`, error `max_response_tokens too small`, requested 512, original 2019, returned 254, rejected. All files restored byte-for-byte.
- Same root budget implementation with T14's narrower protected context keys: targeted E2E `1 passed in 4.27s`. Temporary overlay restored byte-for-byte.
- Candidate normal E2E after restoration: `2 passed in 4.28s`.
- Candidate focused acceptance batch: `24 passed in 7.84s`.

## Root preimage and projected postimage

- Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Root `mcp_server.py` preimage SHA-256: `04FF58CA3F82E1A8271D499585DE5F99F5A28986B4650DD0E0CCC5DBDE659B0F`.
- Projected `mcp_server.py` postimage SHA-256 after packet application to a scratch copy: `FAC349BB193F674CA53484BFCCE5AA5A516553C0A8EF65A5A9884518719CDC63`.
- E2E test is not changed by this packet; current root SHA-256 remains `102E788121141C4F7AF8C3360AEC314A4D4EF755A88ABEF4FFABEEB099182D9E`.
- Packet SHA-256: `7E7FF8E43F36AD7B0949763068CF57C2AE120008D8CA4E39F7B9AFE4D204AEDB`.

## Validation and handoff

- Root-current `git apply --check`: passed.
- Root was not edited or tested.
- Packet changes only the context projection's protected response keys and final token accounting; assertions stay intact.
- Apply only against the root source preimage SHA above.
