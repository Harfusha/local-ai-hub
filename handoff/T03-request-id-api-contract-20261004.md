# T03 request-ID and HTTP JSON contract checkpoint — 2026-10-04

## Scope and ownership

- Checkout: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`
- Branch: `codex/t03-contracts-resume`
- Candidate HEAD: `d68ee694c6d3f75db5c1ab2f63497226880e5010`
- T03 source ownership remains bounded by `handoff/T03-last-checkpoint-20261003.md`. Do not integrate into the root or replace dirty files wholesale.
- Current `local_ai_coord(action="leases", root=..., paths=[...])` returned success with no lease rows for the inspected T03 paths. Worktree assignment remains the ownership basis.
- T03 did not edit `resilience.py`, the shared `Handler.do_POST` recovery dispatcher, T06/T07 service or recovery APIs, T04 client transport, or T14 `/api/context/pack` in this continuation.

## Request-ID and parser finding

The candidate already has the identity-bound recovery contract: registered mutations enter `RecoveryJournal.begin(request_id, tenant, path, identity=..., payload=...)` before dispatch; concurrent duplicates use `wait_for(..., identity=..., payload_fingerprint=...)`. Existing candidate tests cover the explicit replay registry, pre-dispatch journal entry, T07 adapter states, and real-journal duplicate/payload/identity conflicts. The `RecoveryJournal` API in `resilience.py` already accepts these parameters; no compatibility port is needed in this checkout.

`Handler._read_json` already accepts JSON objects with `application/json` and `application/merge-patch+json`, rejects invalid JSON and non-object JSON with HTTP 400, and rejects unsupported media types with HTTP 415. Added one isolated T03 test module for these parsing guarantees. Test execution remains prohibited until T20 GO.

## Changed files in this continuation

- `tests/test_t03_http_json_contract.py` — new; SHA-256 `87599DECDD061C4482BC97323F809EB50C9E80212C48B2625B5AF04EC36AF02B`.
- `handoff/T03-request-id-api-contract-20261004.md` — this checkpoint.

No production source changed in this continuation. Other inherited dirty paths remain untouched.

## Current candidate hashes and HEAD preimages

SHA-256 below distinguishes the working-tree bytes from the corresponding `HEAD` blob bytes. Line-ending conversion may make hashes differ even when Git reports a clean path; Git status is authoritative for dirty state.

| Path | Working tree SHA-256 | HEAD preimage SHA-256 | Git status |
|---|---|---|---|
| `src/local_ai_hub/operation_contracts.py` | `20863DFEDE5AD7E5ABF25D356E2751650568E984E03DCD8A49EB8642122501F0` | `c77dc63759e34dac4dbe6febeee95246a1c166f5972d41123240228e6ec47ecb` | modified |
| `src/local_ai_hub/http_server.py` | `BBC2510ED6365CE52DE207869F72C715F16345E7F216AC8050842278A5F2742B` | `3047fc7c5161023586930ff4bd9dac7fa8d438c241886af08d5300fb8c70c06d` | modified |
| `src/local_ai_hub/mcp_server.py` | `24CB51FC19931D5E27508E48A3AAE59CDFA06914E7B8FD11A717C3A7EF8244E2` | `986b1eb79abf753f43d84c108e17e7be3b24cbde549bc258ded32f778f57b84c` | modified |
| `tests/test_operation_contracts.py` | `6BB806742DCE766F13A1601BC638C036E508C56B2D694F26B9186ABDD2E11234` | `d4c04bf40388fd8002e2a2085b0cfc93f4392e4d5bc998f124f0cc987f0f9fba` | modified |
| `tests/test_mcp_compact_transport.py` | `CF8E7C906C27969E70F9FBEC33EF0C2D2B701C5125B0B86A4B1B32E09E8D3636` | `569d848e8f2192d2ab51b5f7392e1294f01602e911378bc09a519087855102b8` | modified |
| `src/local_ai_hub/resilience.py` | `2F249BA6619D469D784F41D2812715059F2F6CA428099345546D7BB5A323F924` | `382b0208a32458aed2d309e71e7bf5dc6ab9805634ad04d15cf145a5c06253cd` | clean |

## Focused tests prepared; not run

Run only after fresh T20 GO and owner-serialized test slot:

```text
tests/test_t03_http_json_contract.py
tests/test_operation_contracts.py::test_http_mutation_registry_journals_only_explicit_mutations
tests/test_operation_contracts.py::test_registered_http_mutation_routes_enter_recovery_before_dispatch
tests/test_operation_contracts.py::test_mutating_http_post_uses_t07_recovery_contract
tests/test_operation_contracts.py::test_mutating_http_post_uses_identity_bound_recovery_journal
tests/test_operation_contracts.py::test_repo_path_hints_schema_is_bounded_and_scoped
```

Actual T03 result this continuation: **NOT RUN**. Historical, separate candidate receipt: `handoff/T03-final-acceptance-handoff.md` reports 274 passed on 2026-10-01; it does not verify current dirty state. Fresh T20 status: overall release GO remains closed; its one T07 selector ran and returned exit 1 (41 passed, 14 failed), so no T03 test slot is open.

## Root-current preparation — 2026-10-04

Root was read-only throughout this continuation. Current observed root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; existing root dirty files remain untouched.

| Prepared patch | Target/preimage | Receipt |
|---|---|---|
| `handoff/T03-root-current-alias-source-20261004.patch` | `src/local_ai_hub/mcp_server.py`, root SHA-256 `FDFDD51B35054A1C80A8B5DF0DD751D6745E0CF0C888AE6CF18A47D7B386EA73` | Patch SHA-256 `0380A4F6C8E472EF1FD8ADFC93F78595C734EE383CEAE2616D386EB94FEF2284`; `git apply --check` PASS. Contains source-only split from alias patch; output-schema test/registration release not broadened. |
| `handoff/T03-root-current-search-route-compat-20261004.patch` | `src/local_ai_hub/http_server.py`, root SHA-256 `C97AA26A4D84BE35FE7BFA1A18FDBB5AE9A5BA393F73D541D38E3F2DCB33D93D` | Patch SHA-256 `54A4AE2A0641128F9016F648B149B4D69B6C98962E0310B6CCCD85CA995DF362`; `git apply --check` PASS. Changes only `/api/search` branch: omits absent `path_hints`; returns explicit 501 if supplied but service signature cannot accept it. Root already imports `inspect`. |
| `handoff/T03-root-current-alias-tests-20261004.patch` | `tests/test_mcp_contract_dispatch.py`, root raw SHA-256 `1608DCFB5A57B0A4F5AE8CDDB80B2576D0A54A7D2FFE84035989041A344343D0`; root Git blob `9773f274c15c0feb37d8d3bf0ba97b87dade560e` | Patch SHA-256 `78A26890AB0FA68133A1C8B85AFCCAB73E791A9B47BA2182709508A56C35504D`; `git apply --ignore-space-change --check` PASS because root file has 412 CRLF lines. No default-whitespace check pass. |
| `handoff/T03-root-current-json-parser-test-20261004.patch` | New `tests/test_t03_http_json_contract.py`; root target absent | Patch SHA-256 `8D12937147951EB6C77578D76E88CF0A1C39BB3561E932C0C077A9BED35D4D96`; candidate test SHA-256 `87599DECDD061C4482BC97323F809EB50C9E80212C48B2625B5AF04EC36AF02B`; `git apply --check` PASS. |
| `handoff/test_t03_alias_contract-root-current-20261004.patch` | New `tests/test_t03_alias_contract.py`; root target absent | Current patch SHA-256 `6E6F204718468B20A9ABC2DC35217FD90FF18D164B9E33BFA88CA115D8168172`; test preimage SHA-256 `D5D9DFB6BFDD590412793F5596133810AD8E33FE82D0CDDD5A1D7FB1617BA992`; corrected test SHA-256 `01969762D0155351957A0C38FF4DAF2F978F38CE7CE568E8D323C2553592D31D`; `git apply --check` PASS. Test now calls established `_mcp_contract_schema("local_ai_coord")`; no expected behavior changed. Prefer this isolated T03 test over modifying shared `test_mcp_contract_dispatch.py`. |

Existing root search/path-hints contract and service integration were not changed here. Existing `T03-repo-search-output-contract.patch` concerns MCP output schemas; do not include it under the user's deferred full-output-contract decision. The old `T03-root-current-search-route-compat-20261003.patch` remains stale; use only the new root-current patch above. T03 does not own request-ID/parser/dispatcher source hunks. The candidate request-ID tests verify those shared contracts without transferring code ownership.

Add `tests/test_t03_alias_contract.py` to the focused selectors above. T20 granted one exact run: execution `31b79795f1774949b478b5cbfd34d9de`, request `req_6a404f98daf0`, repository revision `96bdca22d62eced0272f17ba336f9af332c0cd9e8b7acaa77e6e16cdb0398393`, candidate HEAD `d68ee694c6d3f75db5c1ab2f63497226880e5010`, duration 3.5009 s, exit 1; 22 passed, 1 failed in 2.58 s. Sole failure was the new alias test calling nonexistent `_mcp_input_schema`; it now calls candidate's established `_mcp_contract_schema`. Only the new test changed; no source or root file changed. Corrected alias selector is **NOT RUN**; requested fresh T20 GO. Do not rerun until granted.

The bounded Hub diff review attempt returned `Review requires 72 segments; the safe limit is 8` and no findings; it is **not** a review pass.
