# T01 MCP, HTTP and CLI operation acceptance handoff

Snapshot only: operation-level source references and missing acceptance receipts for current MCP, HTTP and CLI inventory rows.

- Rows: 530; direct behavior-selector rows: 153; post-release gaps: 376; owner-receipt-only: 1; root-green: 0.
- All rows retain exact source references. Candidate links are candidates, not direct links or execution receipts. Root-green remains false for every row.
- No listed row has a current root-green execution receipt. Direct links and candidate links are selector evidence only, not execution.
- 377 operations without direct behavior selectors remain post-release work. No inferred candidate was retained for them. One owner-receipt-only selector stays separate; it is not root-green.
- /api/context/pack is included only as route-registry evidence; its handler remains outside T01 scope.
- Source references came from the preserved coverage snapshot. Candidate discovery searched exact backend-route literals in asserted existing test functions; it did not run tests. Snapshot predates the T01 conditional-route classifier change. No inventory/root metadata was rewritten.

## Review priority

- P0 security: 7 rows by name/action heuristic.
- P1 mutation review: 254 rows by POST/action heuristic.
- P2 other: 269 rows. Labels are triage heuristics, not verified side-effect classifications.

## Candidate mapping

Candidate selectors preserve exact pytest node IDs and remain separate from direct links. Candidate routes and matching basis are included per row in the CSV. No candidate or direct link sets root_green.

## Counts by surface

| Surface | Rows |
|---|---:|
| CLI operation | 15 |
| HTTP GET | 68 |
| HTTP POST | 222 |
| MCP action alias local_ai_command | 4 |
| MCP action alias local_ai_coord | 12 |
| MCP action alias local_ai_repo | 4 |
| MCP action alias local_ai_task | 3 |
| MCP action local_ai_artifact | 3 |
| MCP action local_ai_command | 27 |
| MCP action local_ai_coord | 51 |
| MCP action local_ai_rag | 7 |
| MCP action local_ai_repo | 81 |
| MCP action local_ai_status | 5 |
| MCP action schema gap local_ai_command | 1 |
| MCP action schema gap local_ai_coord | 7 |
| MCP action schema gap local_ai_repo | 3 |
| MCP action schema gap local_ai_status | 4 |
| MCP detail local_ai_status | 5 |
| MCP tool | 8 |

## Evidence fingerprints

- Current operation selector evidence: bff32cd60d5236779173009498b8259ca8d416f547a70637ca14fcf2adc82238
- Historical node map: d10d49fce365260595ca94aacd70d5381a3e4e2c012bc2d65b8b27df688dad77
- Preserved docs/API_COVERAGE.md snapshot: dcfed35e78d49c4047e1315dd88aceaefec7f63d7a829a410d83ba1b00cc74e7
- Selector links are static evidence; the two inventory artifacts report zero root-green rows.

## Next slot

Run the prepared root-current acceptance selectors in handoff/T01-root-current-acceptance-selectors-20261002.txt after T02 explicitly releases slot 15. Do not claim acceptance from this table; attach fresh focused/root receipts, then reconcile the existing selectors and operation rows.

Detailed operation table: T01-unverified-MCP-HTTP-CLI-acceptance-20261002.csv.
