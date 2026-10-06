# T01 owner release and acceptance snapshot

Captured: 2026-10-01 20:00 UTC
Workspace: `C:\Users\Adam\.codex\worktrees\t01-coverage-main-verify\.local-ai-hub`

## Current assignment evidence

- Owner-gap JSON: `handoff/T01-unlinked-MCP-HTTP-owner-gaps-20261001-v2.json`, SHA-256 `848329C7DC956E53C9564360E9CF29E2172DAB87B490C5CD84577ADF74679BB5`.
- Owner-gap CSV: `handoff/T01-unlinked-MCP-HTTP-owner-gaps-20261001-v2.csv`, SHA-256 `EF8A777C71E14D8C50204D4E5F38274590862FF61E3B300F0937F3A651B94F51`.
- Matrix records 434 behavior-unlinked MCP/HTTP operations; unassigned count is 0. By surface: MCP 53/225 linked (172 unlinked), HTTP 28/290 linked (262 unlinked), CLI 15/15 linked.
- Owner counts: T01 1, T02 3, T03 14, T04 72, T05 9, T06 1, T08 61, T09 9, T10 159, T11 13, T12 8, T13 9, T14 5, T15 31, T16 3, T17 11, T18 20, T19 3, T20 1, T21 1. T01's sole row is conditional `/api/context/pack`; excluded from implementation.
- Root-current delta CSV: `handoff/T01-root-current-owner-coverage-delta-20261001-v3.csv`, SHA-256 `5207D7612DCCCF62DBB242B38468BCD3DBEE827B06DEB6C90443B38B8F33E42B`. Its 151 rows are assigned to T03 (25), T08 (105), T13 (14), T14 (7). Of those, 51 have asserted behavioral test links; 100 are metadata-only and behavior-unverified.

## Owner coordination

- T03: explicitly released none.
- T08: explicitly released none.
- T13: explicitly released none.
- T14: no release response received by capture time; remains owner. No IDs transferred.
- T20: asked to coordinate a disjoint transfer; no operation IDs received by capture time.
- Result: zero IDs eligible for T01 audit. No operation was audited twice or reassigned speculatively.

## Available validation evidence

Earlier bounded T01 run (no Hub calls):

```powershell
& 'C:\Python313\python.exe' -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider tests/test_surface_inventory.py::test_check_cli_preserves_coverage_until_explicit_write_doc tests/test_surface_inventory.py::test_behavioral_links_only_reference_inventoried_operations
```

Result: `2 passed in 9.72s`.

Earlier read-only inventory check:

```powershell
& 'C:\Python313\python.exe' -B tools/surface_inventory.py --check
```

Result: exit 1; `coverage_rows=642`, `coverage_matches=false`; drift reports rendered coverage differs from `docs/API_COVERAGE.md`, and source MCP tools `local_ai_task` and `local_ai_work` lack generated schemas. Document SHA-256 stayed `4B83315C990B6FC74F3BF89CBB49337CFF9AA085266FE3DA4004EEA72AC80C72`; size/time stayed 4,712,974 bytes / 2026-10-01 10:17:26 UTC.

## Scope and remaining acceptance

No tests or benchmarks ran during this snapshot. No source or generated document changed. User/T20 direction is no further tests until separately coordinated. Existing evidence proves inventory links and `--check` drift only; it does not prove behavior for 434 unlinked operations. T01 remains open. Continue only after an owner releases exact operation IDs or the operation-level receipts arrive from assigned owners.

