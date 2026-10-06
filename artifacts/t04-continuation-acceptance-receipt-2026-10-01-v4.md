# T04 continuation acceptance receipt — 2026-10-01 v4

This receipt supersedes v3 for the API/inventory selector results and current root coverage state.

## Candidate and root snapshots

- Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`.
- Candidate `docs/API_COVERAGE.md`: SHA-256 `0D04F226F2E065ED917B2B2146338503C84E6ADEAE6D36377C72F03EB3E158B4`.
- Candidate `tools/surface_inventory.py`: SHA-256 `23C1E3C8AD962EDAEB1445BA0C4A7F53A31BA81824CA6CB19426BDD2D81BB6C9`.
- Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Root `mcp_server.py`: SHA-256 `BFB3C65A513E2ADB669DDC52CFAAD6F8EC38B1624DCF5AD8F08361027C219DB3`.
- Root `tools/surface_inventory.py`: SHA-256 `862731FDB1312D2B6A604A1EB7F2559C196EAC11985C032C091633DEA960A85C`.
- Root `docs/API_COVERAGE.md`: SHA-256 `E3B5A6559C5F0E6ADEC165B6A416E6DE600C7F00B121DA4615B176ABDA397A49`.
- Root T20-owned dirty tool/docs remain untouched by this continuation.

## API, conversation, operations, inventory suite

Command in candidate worktree:
`python -B -m pytest -q --tb=short tests/test_t04_public_api_contracts.py tests/test_conversation_continue_route_contract.py tests/test_agent_state_operations.py tests/test_surface_inventory.py`

Result: `729 passed, 1 failed in 116.02s`, exit 1.

Failure: `tests/test_surface_inventory.py::test_check_cli_accepts_coverage_without_writing_it`. Its read-only subprocess returned:
`{"coverage_matches": false, "coverage_rows": 664, "drift": ["rendered coverage rows differ from docs/API_COVERAGE.md"], "success": false}`.
Candidate docs/tool files were clean relative to candidate HEAD; no candidate docs were written by the test.

## Current root coverage check

The same named test selector does not exist in the root revision; pytest reported no tests collected. Equivalent read-only command in root:
`python -B tools/surface_inventory.py --check`

Result: exit 1, `coverage_matches=false`, `coverage_rows=685`, drift `rendered coverage document differs from docs/API_COVERAGE.md`. Root tool and documentation are both T20-owned dirty files. No root files were modified here. T20 must reconcile this before inventory acceptance.

## Other current receipts

- Real SSE/auth/cancel/deadline loopback group: `5 passed in 9.29s` with `ResourceWarning` treated as error.
- Root public MCP path-hint chain: `1 passed in 9.80s`; root MCP signature accepts and forwards `path_hints`.
- T04 worktree still lacks that MCP wrapper change. Root has it in T20-owned dirty source.

## Status

T04 remains partial. Outstanding: reconcile candidate/root coverage drift, current-root API/conversation/operation/inventory acceptance, T21 adapter/runtime proof, and T20 integrated revision receipt. T20 released its slot, but no T02 baseline benchmark was run; it is outside this T04 scope.
