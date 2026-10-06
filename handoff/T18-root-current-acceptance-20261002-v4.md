# T18 root-current acceptance handoff — 2026-10-02 v4

## Repositories and source pins

Candidate: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`.

Root: `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`.

| Source | Candidate SHA-256 | Root SHA-256 |
|---|---|---|
| `src/local_ai_hub/http_server.py` | `771D62EA4C5809255E985F40CF46E59A8093AF2F5381813E49A1C74BDFAA93F0` | `8443F8E178C717C92C063394C585C8C38721BD18F644DB053DB6EF81A5F0E047` |
| `src/local_ai_hub/telemetry.py` | `B58636B4FDD994279C5BA2659A80FCF87D4C7233AF3D7337FB7CCB1685D5E338` | `59A8F461CCF11C09526624EDEBD4D4FD99FB314935BE893BBFCE052CAF09281B` |
| `src/local_ai_hub/dashboard.py` | `91AAAD7FD3D881EA6EEE428AABA38F9DCDFB1E32DF10430F629075AD57C21705` | `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760` |

Root source remained unchanged during this review. Its three source files remain dirty mixed-owner files. Do not replace whole files.

## T18 owned production delta

Source-only `git apply --reverse --check --include=<owned source path>` exited 0 against both candidate and root for each exact T18 hunk:

- Telemetry writer retry: `handoff/T18-telemetry-flush-retry-20261002-v1.patch`, SHA-256 `09BBC8E951F5DE8654C40F19E9120AE8C800D3621DDF6F902D411A49DBFE400F`, path `src/local_ai_hub/telemetry.py`.
- Safe telemetry error classification: `handoff/T18-telemetry-error-class-sqlite-test-fix-20261001-v1.patch`, SHA-256 `BF45D78C0215F14FE6E7E8AB91A501DFA205CC4E31AFDC8CECF9FE1625F0934B`, path `src/local_ai_hub/telemetry.py`.
- Dashboard transition failure display: `handoff/T18-root-current-operator-display.patch`, SHA-256 `C65C257D082B180B908F6DCAC49DB09CA0131BF05E290D353CD7D9F9DCB579CC`, path `src/local_ai_hub/dashboard.py`.

Read-only AST segment hashes match candidate and root for `TelemetryStore.flush` (`A04C7AC45C4F68AC3E4A3AEB98F2C50E419A707EA7D0B01E3DBCFF59EB715C95`), `TelemetryStore.report` (`AA5D3DACB0C1471BC5E5A5AD699C18F69DFFA5B7C6454B30B434A56724F973D1`), and `Handler._handle_db_query` (`50A1F03CC43516BB896069188DC5B5C58442F4B761BCFEC2F608C7AC732D2489`). T18-owned production code deltas in these paths are already present at current root pins; no source patch remains to apply.

## Dashboard/status owner delta

Detailed path/test inventory: `handoff/T18-dashboard-status-current-owner-delta-20261002-v1.md`, SHA-256 `65013B51822D44823FB443F89CBA0C854C9130D1F39660EB464D5D59B637D8B5`.

Candidate and root have matching transition display source hunk. Seven focused node IDs exist in both current test files. Three supplemental candidate node IDs were absent from root. Test-only patch `handoff/T18-root-dashboard-status-tests-only-20261002-v1.patch`, SHA-256 `66D7083A45D9811C112C11C333C960DBF8FFBC2FCBBA86783E0E75230046919C`, adds only those three function bodies (26 lines) in the two existing mixed-owner root test files. Root `git apply --check --whitespace=nowarn` exited 0; patch remains unapplied. Candidate-only previous receipts are 5 passed and 6 passed; they do not prove root acceptance. Root's historical 48-pass receipt predates these three node IDs. Preserve the existing mixed-owner files and apply only with T20 integration ownership.

## Mode/admin test handoff

Candidate `tests/test_root_current_mode_overlay_t18.py` SHA-256 `ABD81ACFB19EF096BC3A3CED535DB1F108BA3D39B3C1A1A71074592776EAEAB2`; root file is absent. This candidate test now sets a configured global API token, exercises real loopback `GET /api/mode`, and asserts non-loopback unauthenticated `GET /api/mode` receives 401 through root `Handler._require_authorized`. Python AST parsing passed. Test-only root patch `handoff/T18-root-mode-auth-overlay-test-only-20261002-v1.patch`, SHA-256 `2FB7EE50274ACEC0D86E9EEBA05723DA6596F1B150537D0B60479827324AEB45`, adds this single 225-line file. Current root `git apply --check --whitespace=nowarn` exited 0; patch remains unapplied, root test file remains absent. The selector has not run. T13 owns mode production; T20 owns root integration and test-slot assignment. After the test-only file is approved and applied, run this exact root command only after T20 assigns the serial slot:

```powershell
$env:T18_ROOT_SOURCE='C:\Users\Adam\.local-ai-hub\src'
$env:T18_ROOT_HTTP_SERVER_SHA256='8443F8E178C717C92C063394C585C8C38721BD18F644DB053DB6EF81A5F0E047'
& 'C:\Python313\python.exe' -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_root_current_mode_overlay_t18.py
```

## Test gate and release status

Fresh thread reads on 2026-10-02: T02 is active on static-only work; latest states no test or benchmark repeat and no T02 slot assignment. T02's last stated queue was T11, T05, T03, T08, then T02; T20 has since reprioritized based on a new T21 root gate: T05 slot 12, T03 slot 13, T21 slot 14, T01 slot 15, and T08 no earlier than slot 16. T02's position after this reorder is not confirmed. T07 slot 06 ended `UNKNOWN`. T04 released slot 07 after 31 passed/5 failed; broker result `UNKNOWN`, with no repeat. T15 explicitly released slot 08 after `outcome_unknown=true` (`req_c346aa085510`); receipt SHA-256 `658F1EA53F0EEFCC549E38B0FAEFFFCD45CEA9688F31741ACDB0477EE20AB4FA`, manifest SHA-256 `7776CD49BEB5D43E69EAC6F5B879D92FC62336D64AB21D3598164BEC11FD07FB`. T13 slot 09 ended `UNKNOWN` and was explicitly released to T20; T13 records the receipt in its handoff. T20 reports slot 11 closed for T11: privacy `1 passed`, offline suite `179 passed, 3 skipped`; both native runs after new permission, not broker-validated. T20 later confirmed all 18 source pins still matched after those runs. T05 slot 12 ended without test execution: the pin guard found `agent_memory.py` SHA drift; T05 applied only its approved test-only hunk, did not revert, then released the slot. T03 slot 13 ended before test execution because of transport hash drift. T20 now verifies pins before its T21 root gate; this is not a T02 release for T18. Earlier T19 runbook integration also halted on patch SHA mismatch before apply-check, with root unchanged. This turn rehashed the five T18 source/test files in candidate and root; hashes match handoff pins. No T18 inputs changed. No benchmark ran. T20 retains root integration, serial slot assignment and overall release acceptance. No T18 slot assignment exists. No T18 pytest or benchmark command ran during this handoff update. Do not run selectors before T02 explicitly releases the single slot and T20 assigns it to T18.

Latest external snapshot: T02 is idle with review-only `-05` manifest `handoff/T02-paired-matrix-20261002-v1/manifest-T02-CPU-20261002-05-draft.json`, SHA-256 `0FE9D7D8D0BE90D7D4B93309F8D4BF6D50EA0F2CF36016EB375D00AC695D259C`. It says `review_only_not_runnable`, `measurement_allowed=false`, `slot=null`; `-04` remains preserved. No slot is assigned or released to T18. T20 reports T03 slot 13 ended before test due to transport hash drift. T21 slot 14 was closed from the existing log as `5 passed, 69 deselected`; receipt SHA-256 `69D46E50B5B86DC4F241A00FF034387518B387FA61E051F64FC02FCBB29872FC`. T20 did not repeat the test, released slot 14, and requested fresh manifest/pins from T02; benchmark has not run. T20 now asks for approval to extend work to T03 output-schema and T12 selector after slots 15–18; no T18 slot assignment exists. T19 runbook integration had halted before apply-check on a SHA mismatch; root unchanged. T13's latest state keeps mode gates untouched and releases only MCP/schema scope to T03. T20 remains active. These updates do not satisfy the T02 gate or assign a slot to T18.

After T02 releases the slot and T20 assigns it, run the exact selector command in the detailed inventory. Apply the three-function supplemental test patch only after T20 integration review, then include those IDs. Run the current root-pinned mode overlay only after its test-only file receives T20/T13 integration review.

T20 retains overall release acceptance. T01/T21/T19 evidence remains separate. This handoff does not claim full release acceptance. Local AI Hub was not used. `/api/context/pack` was not changed.
