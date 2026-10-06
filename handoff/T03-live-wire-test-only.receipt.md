# T03 live-wire test-only handoff receipt

Date: 2026-10-01 (Europe/Prague)
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
T03 worktree HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2`

## Patch

Only changed path: `tests/test_mcp_live_wire_schema.py`.

The T03 worktree preimage already contains the interactive stdio handshake and child cleanup. The root-integrated postimage adds explicit initialize-response assertion to the daemon-off call plus `test_stdio_main_does_not_gate_handshake_on_hub_startup` regression. It checks lazy MCP initialization is not gated by a failed Hub startup probe.

- Worktree preimage SHA-256: `18EEEFCDC44D370F8DEA214802619A3C70781948E65F5AF966395FC9D5680B62`
- Root/current postimage SHA-256: `772D47A36C65A076B42CF2C70C3834C8EB99CEB0FA6E2E7808AF84B523CDDD29`
- Patch: `T03-live-wire-test-only.patch`
- Patch SHA-256: `3975FEAF0CC027814C6DD74210234F114AF3DB7D14F4D02D13B337F7673E4545`
- Patch stat: one path, 21 insertions.

Root already contains this exact postimage. `git apply --reverse --check --whitespace=error` against current root: PASS. Forward apply-check fails because the change is already integrated. No root writes performed.

## Tests

Root integration acceptance:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_live_wire_schema.py::test_stdio_main_does_not_gate_handshake_on_hub_startup tests/test_mcp_live_wire_schema.py::test_stdio_status_call_cold_starts_isolated_hub_and_cleans_up
```

Result: `2 passed in 18.01s`.

T03 assigned worktree acceptance:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py tests/test_recovery_journal_contract.py tests/test_mcp_live_wire_schema.py
```

Result: `96 passed in 28.89s`.

Candidate fail-first for the main regression: `1 failed in 2.86s`, `SystemExit` before `mcp.run()` when `ensure_server` returned false. Candidate after removing preflight: targeted main regression + real daemon-off initialize/status call: `2 passed in 18.62s`.
