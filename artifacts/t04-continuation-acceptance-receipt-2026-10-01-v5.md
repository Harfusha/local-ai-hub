# T04 continuation acceptance receipt — 2026-10-01 v5

This receipt supersedes v4 with current-root API-adjacent results.

## Current snapshots

- Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`.
- Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Root `mcp_server.py` SHA-256: `BFB3C65A513E2ADB669DDC52CFAAD6F8EC38B1624DCF5AD8F08361027C219DB3`.
- Root `tools/surface_inventory.py` SHA-256: `862731FDB1312D2B6A604A1EB7F2559C196EAC11985C032C091633DEA960A85C`.
- Root `docs/API_COVERAGE.md` SHA-256: `E3B5A6559C5F0E6ADEC165B6A416E6DE600C7F00B121DA4615B176ABDA397A49`.
- Root T20-owned dirty files were not modified.

## Root results

- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_conversation_continue_route_contract.py tests/test_agent_state_operations.py`
  - `22 passed in 163.85s`, exit 0.
- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_surface_inventory.py`
  - `721 passed, 1 failed in 34.63s`, exit 1.
  - Failure: `test_check_cli_accepts_coverage_without_mutating_it`; renderer found 685 rows and reported `coverage_matches=false`.
- Equivalent direct read-only check `python -B tools/surface_inventory.py --check`
  - exit 1; `coverage_matches=false`, `coverage_rows=685`.
- Root has no `tests/test_t04_public_api_contracts.py`; that T04-specific public API contract file remains candidate-only.
- Fresh root path-hint E2E from v3 passed `1/1`; it exercises public `local_ai_repo` through FastMCP, HubClient, HTTP `/api/search`, and `repo_search`.

## Candidate result

`tests/test_t04_public_api_contracts.py`, conversation continuation, agent-state operations, and surface inventory:
- `729 passed, 1 failed in 116.02s`, exit 1.
- Only failure: candidate `test_check_cli_accepts_coverage_without_writing_it`; 664 rendered rows differ from candidate `docs/API_COVERAGE.md`.

## SSE result

- Real loopback SSE/auth/cancel/deadline plus client cancel/deadline selectors: `5 passed in 9.29s` with ResourceWarning as error.

## T02 benchmark request

No T02 baseline work exists in this T04 scope. No benchmark was run.

## Status

T04 remains partial. Root conversation/operations and root path-hint chain passed. Inventory acceptance blocked by T20-owned coverage drift. T04 public API contract tests are absent from root, and T21 adapter/runtime proof plus T20 integrated revision receipt remain outstanding.
