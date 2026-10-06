# T01 resumed acceptance checkpoint — 2026-10-02

## State

T01 operation-level acceptance remains open. Existing dirty worktree state is preserved. This continuation changed one assertion in `tests/test_surface_inventory.py` and added an immutable run receipt. The existing goal status remains `blocked` and the review stays open; do not mark it complete from inventory totals or partial receipts.

Assigned worktree: `C:\Users\Adam\.codex\worktrees\t01-coverage-main-verify\.local-ai-hub`

## T01 targeted run

User authorized targeted pytest runs without Hub calls. After the T02 slot was explicitly released, this bounded run completed:

```powershell
$env:PYTHONPATH='src'; & 'C:\Python313\python.exe' -B -m pytest -q --tb=short tests/test_mcp_coord_operation_acceptance.py::test_http_agent_task_rejects_unknown_action_without_store_mutation tests/test_mcp_coord_operation_acceptance.py::test_local_ai_coord_task_rollback_restores_and_persists_previous_checkpoint
```

Result: `2 passed in 2.82s`; HEAD at run: `689165fbe18101feacf5f489847a4890fc27ed1f`.

Test source SHA-256: `2EA4B59D11DB9519C3FC1D2A98C22AAC78E68D67B8C31C802602F16D4FFC11B6`.
Receipt `T01-operation-level-receipt-task-rollback-20261001.md` SHA-256: `C73E0560F9FF9E70EF9A702903617DAFD74416211842763D2BCE2C4B7569C0B5`.

Resumed validation: 64 operation acceptance tests passed; 687 inventory tests passed after one stale matcher expectation was corrected; `tools/surface_inventory.py --check` reported 642 matching rows and no drift. T01 acceptance is global across the operation inventory; the 446-row gap map is therefore a required completion tracker, not 446 T01-owned edits. Latest owner scan: two candidate-only operation rows are linked (`op-28d63e90525c`, `op-65970ac00a0a`); no row is root GREEN, and all 446 remain root-open. 444 have no exact selector mapping. T17 selector maps to T13 `POST /api/task/transcribe`; T04 aggregate receipt and T03 candidate receipt do not close rows without exact selectors/integration. Exact commands, source hashes, dirty-state partition, and scope limits are in `T01-operation-acceptance-run-20261002.md`. T20 remains active; no additional test command is running here.

## Operation map and transferred evidence

The v2 deterministic delta builder preserves v1 map pins and merges claims into the 446-row operation map. Latest recorded delta result: 5 claims; 0 source-matched receipt hashes; 0 root GREEN rows. Only the T13 `POST /api/conversations/continue` operation (`op-39cb63957f93`) has a receipt-backed status update, and remains `root_reported_pass_receipt_sha_missing`.

- Builder: `T01-build-root-transfer-delta-20261001-v2.py`
- Claims: `T01-root-transfer-claims-20261001-v2.json`
- Delta JSON SHA-256: `E8ECBF1FA2499D116D7DBED67E9D3B4CD98EBCE6A7BB805AC9A13E53B34B1E19`
- Merged map CSV SHA-256: `F71D4BCD89B37877D16C6D5FCEF25F140A79CB9A9ABE0900684FE2EA0C3E0A37`

T05/T06 owner batches remain unassigned to operation IDs because selector-to-row mapping and immutable execution receipts/source pins are missing. T14/T21 remain candidate-only. `/api/context/pack` remains inventory-only and out of scope. Inventory coverage remains MCP 53/225 linked, HTTP 28/290, CLI 15/15; these counts do not satisfy operation acceptance.

## Remaining acceptance work

- Obtain immutable T05/T06 execution receipt artifacts and exact source pins, then map selectors to operation IDs before crediting row-level acceptance.
- Resolve the T06 daemon restart-stop failure (`22 passed, 1 failed`; `daemon_status.success` false) before claiming that operation accepted.
- Obtain verifiable immutable receipts for reported T13/T14/T21 evidence; do not promote candidate-only evidence to root GREEN.
- Continue operation-level acceptance beyond inventory/linkage totals while preserving the T01/T20 ownership boundary and all existing dirty work.
## Follow-up audit checkpoint — 2026-10-02

### Verified inventory and selector state

- Current operation selector batch: `handoff/T01-root-current-acceptance-selectors-20261002.txt`, 123 unique node IDs, SHA-256 `57610EC4E0B5BFA5BF1B5A36F44A28EB713144A0881C5CBBECB4F64B590BAE70`. Static AST lookup found all 123 named test functions in six modules; no pytest/import execution in this follow-up.
- Selector-operation map: `handoff/T01-root-acceptance-selector-operation-links-20261002.json`, SHA-256 `5FF085617F2F53CA4B97B2707387CB18D68F231C0FC4B7C74426D34D4577A1D5`; 220 links, 123/123 selectors mapped, 128 unique operations, zero unmapped selectors.
- Owner gap plan and CSV reconcile exactly: 387 unique uncovered operation IDs in both. Historical split is `387 without selector/owner receipt + 58 targeted-selector candidates + 1 owner-receipt-only = 446`; 20 owner groups, zero ownerless rows, zero root-GREEN rows. `/api/context/pack` remains explicitly excluded.

### Existing run receipt freshness

- Existing run record `handoff/T01-operation-acceptance-run-20261002.md`, SHA-256 `D91013399082C3577352ADE70949CD389288EA023375B00FDC136D0F2E4D5684`, records 64/64 operation acceptance tests, 687/687 inventory tests, a 642-row no-drift check, and 2/2 rollback/negative-dispatch tests. These are historical receipts for the pinned snapshots, not a fresh run in this follow-up.
- Rechecked its eight file pins: five still match. Three acceptance modules have changed, so the 64-test receipt is stale for those files:
  - `tests/test_http_route_operation_acceptance.py`: recorded `330C91CDA532142C74C47E93CDAC624E5F2B0858F831586CE0509CF114973EC5`; current `FA5C866BD05A69364EEB7DC63C6B051A86F551ABCD5738613547CBFC273CEC7C`.
  - `tests/test_mcp_command_operation_acceptance.py`: recorded `08DF71D30970349E5DA3C2AC12CF0C034E22FA9856EDABFB4120C938F1CB9D20`; current `2AEDB9E1608ED754CC4C76D5A8BC3A0295F8E798EFC9C849E2AC430419157A87`.
  - `tests/test_mcp_coord_operation_acceptance.py`: recorded `2EA4B59D11DB9519C3FC1D2A98C22AAC78E68D67B8C31C802602F16D4FFC11B6`; current `0DB2EB213FF4F8B121F8B82EA12340C5F01558EED03D1B780DC60BD0467CABB5`.

### Boundary and next acceptance step

- This checkpoint changes no source/test modules and launches no pytest or benchmark. Existing dirty state remains preserved; T20 owns root integration. T02 owns the only active test/benchmark slot.
- After T02 explicitly releases the slot, rerun the exact 123-selector batch against the agreed current candidate pins and send the command, output, and source hashes to T20. Root-GREEN remains false until T20 integrates and records root-current receipts; T01 global review stays open.

## P0 read-only-check regression — 2026-10-02

### Root-cause review

- `main()` parses `--check`, reads and compares `docs/API_COVERAGE.md`, prints drift status, then returns before the `--write-doc` branch. The only direct `doc_path.write_text()` in this script is inside `if args.write_doc`.
- `_generated_mcp_schemas()` calls `generate_mcp_tool_schemas()` for an in-memory mapping. It explicitly avoids `write_all_generated()`, which persists generated artifacts.
- Existing regression `test_check_cli_preserves_coverage_until_explicit_write_doc` checks stale target bytes/hash/mtime after `--check` and verifies explicit `--write-doc` as a separate control. Its target is a temp root, so it did not guard the running checkout's own `docs/API_COVERAGE.md` against an accidental side effect.

### Regression-first change

- Extended that test to snapshot `ROOT/docs/API_COVERAGE.md` bytes and nanosecond mtime before the subprocess check, then assert both remain identical after `--check --root <tmp_path>`.
- Test file SHA-256 after this test-only edit: `87FB29E4D22508D109008426143A21B673938FD916EB9F18FF3B59E9F1AFC693`.
- Test command after slot release: `$env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'; & 'C:\Python313\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short tests/test_surface_inventory.py::test_check_cli_preserves_coverage_until_explicit_write_doc`.
- No test or `tools/surface_inventory.py --check` has run in this continuation. T02 owns sole validation slot. After its explicit release: run this regression, fix only if it fails, then run `tools/surface_inventory.py --check` and preserve the root coverage file.
- Existing `docs/API_COVERAGE.md` remains inherited dirty; current observed SHA-256 `DCFED35E78D49C4047E1315DD88ACEAEFEC7F63D7A829A410D83BA1B00CC74E7`. This continuation did not write it.

### Validation-slot update — 2026-10-02

- T02 slot 05 ended with an interrupted benchmark and was explicitly released to T11. T02 reports no paired receipt; its partial output has 128 files / 574,827,109 bytes and must remain untouched.
- The exclusive validation slot is now assigned to T11, so T01 still launches no test or `--check`.
- Next step: wait for T11/T20 to release or reassign the slot; then run the prepared single regression first. Do not reuse T02 output or touch `docs/API_COVERAGE.md`.

### Validation-slot update 2 — 2026-10-02

- T11 reports 93 passing project-config/consumer tests, then releases slot 05 to T20. T20 currently owns the next validation decision; no T01 slot is assigned.
- T01 regression stays pending. Production flow review still finds no `--check` write path: check returns before explicit `--write-doc`; schema generation is in-memory. Make no source change unless the regression fails and identifies a reproducible cause.
- After T20 assigns a slot, run the single regression first, then `tools/surface_inventory.py --check`. Preserve inherited `docs/API_COVERAGE.md` bytes throughout.

### Pre-run inventory — 2026-10-02

- Assigned checkout: `C:\Users\Adam\.codex\worktrees\t01-coverage-main-verify\.local-ai-hub`, HEAD `689165fbe18101feacf5f489847a4890fc27ed1f`; 13 dirty status entries preserved.
- Pre-run pins: `tools/surface_inventory.py` SHA-256 `375A804B517C36A24C83BD331FAD29351E7E75D9E2AC8422389D5C43749E683D`; `tests/test_surface_inventory.py` SHA-256 `87FB29E4D22508D109008426143A21B673938FD916EB9F18FF3B59E9F1AFC693`; selector batch SHA-256 `57610EC4E0B5BFA5BF1B5A36F44A28EB713144A0881C5CBBECB4F64B590BAE70`; link map SHA-256 `5FF085617F2F53CA4B97B2707387CB18D68F231C0FC4B7C74426D34D4577A1D5`.
- Inherited `docs/API_COVERAGE.md`: length 4,423,790 bytes, SHA-256 `DCFED35E78D49C4047E1315DD88ACEAEFEC7F63D7A829A410D83BA1B00CC74E7`, mtime UTC `2026-10-01T20:18:04.7976210Z`. Preserve these bytes and mtime through validation.
- Queue from T20: T07 slot 06, T04 slot 07, T15 slot 08, T11 next. T01 has no assigned validation slot; no tests or `--check` run.
- Prepared selector command after explicit T20 slot assignment:
  `$env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'; & 'C:\Python313\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short tests/test_surface_inventory.py::test_check_cli_preserves_coverage_until_explicit_write_doc`
- Prepared drift command after regression passes:
  `$env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'; & 'C:\Python313\python.exe' -B tools/surface_inventory.py --check`
- Before/after each command, compare `docs/API_COVERAGE.md` SHA and mtime to the baseline above. Stop if either changes; do not restore or rewrite inherited file.

### T01 end-to-end remaining acceptance — 2026-10-02

- T20 current serialized queue: T04 owns slot 07 (first attempt had 9 fixture setup errors and 27 client passes); T15 slot 08; T11 next. T05 queued for slot 12 after T11. T01 has no slot assignment; no T01 tests run.
- T01 operation acceptance batch remains exactly 123 selectors in `handoff/T01-root-current-acceptance-selectors-20261002.txt`, SHA-256 `57610EC4E0B5BFA5BF1B5A36F44A28EB713144A0881C5CBBECB4F64B590BAE70`; static selector map has 123 selectors / 128 unique operations / zero unmapped.
- After T20 explicitly assigns a slot and integrates current T01 test/source hunks into its root, run the P0 regression selector first:
  `$env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'; & 'C:\Python313\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short tests/test_surface_inventory.py::test_check_cli_preserves_coverage_until_explicit_write_doc`
- Then run the 123-selector batch from T20 integration root, using the pinned selector list:
  `$selectors = Get-Content -LiteralPath 'C:\Users\Adam\.codex\worktrees\t01-coverage-main-verify\.local-ai-hub\handoff\T01-root-current-acceptance-selectors-20261002.txt'; $env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'; & 'C:\Python313\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short @selectors`
- Then run drift check:
  `$env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'; & 'C:\Python313\python.exe' -B tools/surface_inventory.py --check`
- For P0 proof, hash and stat the T20 root `docs/API_COVERAGE.md` before and after each command. Never restore or rewrite its inherited content. Any byte/mtime change fails acceptance and requires owner review before further writes.
- T01 global review stays open until these fresh root receipts exist and operation gaps are recomputed from all owner receipts. Current inventory remains 387 without selector/owner receipt, 58 targeted-selector candidates, 1 owner-receipt-only; no row is root-GREEN from static links alone.

### T01 HTTP dynamic/conditional route inventory — 2026-10-02

- Root cause: `_extract_http()` recorded method/path and prefix matching, but did not extract nested optional-backend or feature checks. `_findings()` therefore marked source-confirmed gated routes as confirmed, and their route contract omitted the gate.
- Regression first: added `test_http_route_evidence_status_captures_dynamic_and_backend_gates`. It covers a dynamic jobs prefix (confirmed), an Agent State enabled gate, a dashboard feature gate, and a browser bridge config gate (all conditional). Test file SHA-256: `B0A4658F820B71B0FC8A66C044249D0665BC647CD58EA541532098D5D1CE584E`.
- Minimal fix: `_route_availability_gates()` records nested APP availability checks (`getattr(APP, ...)`, enabled/available checks, feature checks, and `is/is not None` backend checks). HTTP route contract now carries `conditional_gates` and bounded backend-availability status; finding evidence status and coverage state become `conditional` when a gate exists. Dynamic prefix identity remains source-confirmed. `DYNAMIC_ROUTE_REGISTRY` classification still marks its registered route conditional.
- Static audit: HTTP AST scan found 63 nested APP availability-gate sites outside the excluded `/api/context/pack` branch; all 63 match the new extraction heuristic, zero APP availability conditions remain unclassified. `/api/context/pack` handler body was not inspected or modified.
- Static validation only: Python AST parse passed for `tools/surface_inventory.py`, `tests/test_surface_inventory.py`, and `src/local_ai_hub/http_server.py`; `git diff --check` passed for the two T01-owned files. No pytest, inventory execution, or `--check` ran; T11 owns slot 11 and T05 is next after T11.
- Current pins: `tools/surface_inventory.py` SHA-256 `B23C076D14E28171BFA815FA90343F79403A2B52A85B41745B0EDCBF24523F3E`; `tests/test_surface_inventory.py` SHA-256 `B0A4658F820B71B0FC8A66C044249D0665BC647CD58EA541532098D5D1CE584E`; inherited `docs/API_COVERAGE.md` SHA-256 unchanged at `DCFED35E78D49C4047E1315DD88ACEAEFEC7F63D7A829A410D83BA1B00CC74E7`.
- Exact validation after T20 slot assignment, in this T01 worktree:
  1. `$env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'; & 'C:\Python313\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short tests/test_surface_inventory.py::test_http_route_evidence_status_captures_dynamic_and_backend_gates`
  2. `$env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'; & 'C:\Python313\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short tests/test_surface_inventory.py::test_check_cli_preserves_coverage_until_explicit_write_doc`
  3. `$env:PYTHONPATH='src'; $env:PYTHONDONTWRITEBYTECODE='1'; & 'C:\Python313\python.exe' -B tools/surface_inventory.py --check`
  4. Re-run T01's 123-selector root-current batch after current T01/T20 hunks are integrated and owner receipts are refreshed.
- Hash/stat `docs/API_COVERAGE.md` before and after each command. Stop on any change; do not restore or rewrite inherited content. T01 review remains open until fresh root receipts and recomputed operation gaps exist.

- Follow-up AST boundary check found zero nested route predicates combining a path literal and `APP`; `_route_availability_gates()` does not miss such compound guards in the current HTTP source. This scan skipped the `/api/context/pack` handler branch.

### T20 queue update — 2026-10-02

- T05 owns CPU slot 12; T03 owns slot 13. T04 currently has no slot and its root compatibility v2 patch remains unapplied by instruction. T01 still has no validation allocation.
- T01 source/test diff remains candidate-only until T20 integration and serial validation. No tests or inventory command run in this update.

### T01 validation allocation — 2026-10-02

- T20 explicitly assigns T01 exclusive slot 14, after T05 slot 12 and T03 slot 13. No validation before slot 14.
- On slot 14, run P0 checks first against pinned T01 files: conditional-route regression `tests/test_surface_inventory.py::test_http_route_evidence_status_captures_dynamic_and_backend_gates`, then read-only-check regression `tests/test_surface_inventory.py::test_check_cli_preserves_coverage_until_explicit_write_doc`, then `tools/surface_inventory.py --check`. Hash/stat root `docs/API_COVERAGE.md` before/after each command; stop on any change.
- The 123-selector batch waits for T20 to provide exact integrated root input hashes and integration receipt. Do not run it against unverified root inputs.
- T01 candidate source/test hashes remain `B23C076D14E28171BFA815FA90343F79403A2B52A85B41745B0EDCBF24523F3E` and `B0A4658F820B71B0FC8A66C044249D0665BC647CD58EA541532098D5D1CE584E`. Candidate HEAD is `689165fbe18101feacf5f489847a4890fc27ed1f`; T20 root HEAD at last verified receipt is `01df56605ccf484ebfe2808ac60d696c4e81dffc`. Root integration inputs are not yet confirmed.
- Preserve inherited `docs/API_COVERAGE.md` SHA-256 `DCFED35E78D49C4047E1315DD88ACEAEFEC7F63D7A829A410D83BA1B00CC74E7` and mtime `2026-10-01T20:18:04.7976210Z`; never rewrite inherited bytes.

### T20 queue correction — 2026-10-02

- Updated serial queue: T05 slot 12, T03 slot 13, T21 config_loader slot 14, T01 slot 15. No T01 run before explicit slot 15 allocation.
- Prior T01 commands, source pins, and `docs/API_COVERAGE.md` baseline remain unchanged.
