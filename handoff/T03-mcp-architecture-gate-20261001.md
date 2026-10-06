# T03 MCP architecture gate — handoff receipt

Date: 2026-10-01
Worktree: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`
HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2`

## Scope and ownership

This receipt covers the narrow T03 addition of typed `full` and `agent_state` status output contracts plus their contract tests. Existing dirty paths owned by T04/T07/T13/T14/T21 were preserved. No edits were made to `mcp_server.py`, T21 adapter hunks, `/api/context/pack`, or T14 budget hunks in this continuation.

Patch: `handoff/T03-full-status-output-contracts-20261001.patch`
Patch SHA-256: `7C429FD2DC55D144D1CB60892BEA1916162180E01EE3DD25719E70A3962CD69C`
The patch is limited to `src/local_ai_hub/operation_contracts.py` and `tests/test_operation_contracts.py`; reverse `git apply --check` succeeded in this worktree.

## Contract behavior

- `full` output validates the stable success/failure envelope and typed `success`, `hub_online`, `version`, `uptime_seconds`, `features`, `runtime_stats`, and `capabilities` fields; nested objects remain forward-compatible.
- `agent_state` output validates the HTTP handler's `success`, `enabled`, task/incidents/candidates counts, string task list, and status fields.
- Success, failure, and malformed-field cases are covered by `test_status_full_and_agent_state_outputs_have_typed_success_and_failure_shapes`.
- Existing T03 acceptance covers daemon-off cold start and cleanup, missing SDK import fallback/actionable exit, invalid arguments rejected before dispatch side effects, and live registry input/output schema parity.

## Validation evidence

- TDD RED: before the schema implementation, the targeted test failed because the schema lacked `anyOf` (`1 failed in 3.31s`).
- TDD GREEN: the targeted test passed after implementation (`1 passed in 2.58s`).
- Focused T03 acceptance command:
  `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py tests/test_recovery_journal_contract.py tests/test_mcp_live_wire_schema.py`
  Result: `97 passed in 28.07s`.
- `git diff --check` on the two changed contract files emitted only Git's existing LF-to-CRLF working-copy notices; no whitespace errors were reported.
- Local AI Hub context was unavailable: `local_ai_repo(action=context, mode=adaptive)` returned `request_not_sent=true`, `outcome_unknown=false` (transport failed before write). One bounded `local_ai_status(action=brief)` health check returned `success=false`. Native evidence above is from the previously completed bounded validation in this same T03 worktree; no test rerun was made for this receipt.

## Postimage SHA-256

- `src/local_ai_hub/operation_contracts.py`: `D676494561F1B6581121CD74FB0ED6CDE6D6843796040070F1C7363729614BBA`
- `tests/test_operation_contracts.py`: `BA35FCDC9F8A4A0A5F37382A93A85AD9082A8C9BBDD734E13FC776451CEBE446`
- `docs/superpowers/plans/2026-10-01-t03-mcp-architecture-gate.md`: `E124EAEA288448496DF95C6DEB65D272F5BF0CC9D2B7C6F4644F173B7044FFB7`
