# T16 namespace, terminal-state, wait, and rollback patch v4

Patch: `T16-namespace-root-current-v4.patch`
SHA-256: `5CFB42C73B1095F63C3FFFFB3482B01D46B016095E6AF21450ABEA3DA785DD81`
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
Candidate HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`

V4 is immutable. Published v1/v2/v3 artifacts stay unchanged. V4 was composed on an isolated copy of current root preimages plus v2, then applied T16-only terminal, wait-key, and restore-preflight deltas. Root `work_orchestrator.py` receipts seam is retained. No `commands.py` hunk; current compatibility preimage SHA-256 `11887A31E422891DF1B29C7300AAC49B3FB57047343024ADE9493531B3AA2D0B`.

## Root preimages

- `src/local_ai_hub/leases.py`: `BF56E69ABC46DCF1B9CC4B4778251618FD1EA243329D58E48BEFE833DB1AF1CB`
- `src/local_ai_hub/work_fencing.py`: `10823461FBA3D0B9E2BA516E14E82EEE833315A00A2B11FCDEBDBBECD22CB9AA`
- `src/local_ai_hub/work_orchestrator.py`: `BA24529B8F330248A7F1A8A14847244778B74CE2A201B5DA0D7A928367130093`
- `src/local_ai_hub/project_config.py`: `4238B6A6DE1DE00F55F4679CE0DF7D431522EC1BAFABFA272258C1662F13F713`
- `tests/test_work_fencing.py`: `3CF82264563206B12AEA1CFFC0B78E12AE16D2FF650DE423730BE4A87A4A03D0`
- `tests/test_work_handoff_acceptance.py`: `ACB5249AE641BB4FCF753819C6A2FEE3EDC16CA78818CFE5D66CF79CA0EC68B7`
- `src/local_ai_hub/http_server.py` for dependent route patch: `94C44910B04F8909778F926E64D3F857975BAA5738B78979427BACE29AA3EDF3`
- New tests `test_t16_cross_process_namespace_lease_recovery.py`, `test_t16_terminal_rollback_preflight.py`, `test_t16_lease_wait_namespace_isolation.py`: absent.

## Acceptance

- Exact candidate command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py tests/test_work_orchestrator.py tests/test_work_handoff_acceptance.py tests/test_t16_project_namespace_leases.py tests/test_t16_http_lease_routes.py tests/test_t16_cross_process_namespace_lease_recovery.py tests/test_t16_terminal_rollback_preflight.py tests/test_t16_lease_wait_namespace_isolation.py -k 'not command_broker'`
- Result: `68 passed, 1 skipped, 1 deselected in 57.32s`, exit 0. Skip: Windows directory-symlink privilege `WinError 1314`; deselection: T06-owned broker selector.
- Composed strict `git apply --check --whitespace=error`: namespace v4 then route v3, pass. AST parse: 10 transformed Python files, pass. Temporary overlay only.
- No root source write or root test run. T20 owns integration.

## Ownership and blockers

- T16: namespace lease and wait scope, terminal state transitions, worker claim preflight, all-files rollback hard-link preflight.
- T21: `ProjectContext.coordination_id` producer; T16 patch consumes it.
- T06: real CommandBroker lease caller still omits server-derived `coordination_id`; not changed here. T06/T20 must bridge it.
- The fence test commit receipt is a fixture file. Production T07 journal code remains untouched; no end-to-end journal coupling claim.
