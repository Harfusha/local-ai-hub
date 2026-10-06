# T16 namespace consumer root-current patch v2

Patch: `T16-namespace-root-current-v2.patch`
Patch SHA-256: `40783E463966C6ED996C1CFCE4EF7C33A0157E862CACFED6A7EAAF85FBC7A484`
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
Candidate HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`

Published v1 stays unchanged. V2 removes trailing added blank line. `commands.py` remains untouched; its current root SHA-256 is `1B27F83872D439B9167C9B2323BF4BE71279E688DF6094C002CA20934F761B67`.

## Root preimages

- `src/local_ai_hub/leases.py`: `BF56E69ABC46DCF1B9CC4B4778251618FD1EA243329D58E48BEFE833DB1AF1CB`
- `src/local_ai_hub/work_fencing.py`: `10823461FBA3D0B9E2BA516E14E82EEE833315A00A2B11FCDEBDBBECD22CB9AA`
- `src/local_ai_hub/work_orchestrator.py`: `BA24529B8F330248A7F1A8A14847244778B74CE2A201B5DA0D7A928367130093`
- `src/local_ai_hub/project_config.py`: `4238B6A6DE1DE00F55F4679CE0DF7D431522EC1BAFABFA272258C1662F13F713`
- `tests/test_work_fencing.py`: `3CF82264563206B12AEA1CFFC0B78E12AE16D2FF650DE423730BE4A87A4A03D0`
- `tests/test_work_handoff_acceptance.py`: `ACB5249AE641BB4FCF753819C6A2FEE3EDC16CA78818CFE5D66CF79CA0EC68B7`

The root preimages still match. T09 receipt-seam changes remain in root `work_orchestrator.py`; patch adds only its T16 context/fence hunks.

## Receipts

- `git apply --check --whitespace=error`: exit 0.
- Exact candidate batch: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py tests/test_work_orchestrator.py tests/test_work_handoff_acceptance.py tests/test_t16_project_namespace_leases.py tests/test_t16_http_lease_routes.py tests/test_t16_cross_process_namespace_lease_recovery.py -k 'not command_broker'`
- Result: `63 passed, 1 skipped, 1 deselected in 86.25s`, exit 0. Skip: Windows directory symlink privilege `WinError 1314`; deselection: T06 broker overlap.
- T20 owns root integration. Patch unapplied.
