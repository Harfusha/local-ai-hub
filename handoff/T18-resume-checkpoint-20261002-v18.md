# T18 resume checkpoint — 2026-10-02 v18

## Scope and ownership

Candidate worktree `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`. T18-owned candidate regression and handoff only. No root apply/write. T20 owns root integration and serial validation. T13-owned auth/supervisor hunks preserved. `/api/context/pack` untouched. Local AI Hub not used for repository discovery.

## Telemetry cursor regression correction

The prior candidate batch ran once under T20 GO #11: broker request `req_9483dd9b4409`, execution `0cb3346a007f4c8ca680c68e0766f807`, command exit 1, `1 failed, 4 passed in 0.59s`. Failure was the new test's count assertion. `_bound_telemetry_report` truncates `rows` in place; test compared `len(kept)` with `len(rows)`, same list reference, producing `2 < 2` and stopping before cursor assertions.

Candidate test now snapshots `original_row_count` before the call and compares retained length against that value. It remains unrun after correction. Do not treat prior batch as telemetry cursor acceptance.

- Candidate test `tests/test_telemetry_report_bounds_t18.py`: SHA-256 `AA0D1D9C563A590B3401BBDB136EF2F12A02A54879008560430C0B15AC0D07E2`.
- Candidate source `src/local_ai_hub/telemetry.py`: SHA-256 unchanged `B58636B4FDD994279C5BA2659A80FCF87D4C7233AF3D7337FB7CCB1685D5E338`.
- Corrected test-only root patch `handoff/T18-root-telemetry-report-cursor-budget-test-only-20261002-v2.patch`: SHA-256 `DBF914CA219290CCDBE0A66BE18FEC5691CA7013F162BD7A7BC04A5E5D7AE52E`.
- Current-root read-only `git apply --check --whitespace=nowarn` for this one corrected patch: exit 0, empty output. Patch not applied. Root test target remains untracked and unchanged.
- Prior test-only patch v1 is superseded by v2; preserve v1 receipt for audit history.

## Root pins and next gate

Root HEAD remains `01df56605ccf484ebfe2808ac60d696c4e81dffc`; dashboard SHA `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760`, HTTP server SHA `A8DF17496129DDA67BB74711A7D83568385FC301AB670AF3FB8F1659C7E3221D`, telemetry SHA `59A8F461CCF11C09526624EDEBD4D4FD99FB314935BE893BBFCE052CAF09281`.

T20 revoked/superseded candidate-only GO #11 and requires authorized root integration first, then five selectors against integrated root. No tests after correction. Wait for fresh T20 serial GO after root integration; do not run candidate selector, apply patch, or claim root acceptance before then. Original live `status-full` HTTP 500 remains unverified.
