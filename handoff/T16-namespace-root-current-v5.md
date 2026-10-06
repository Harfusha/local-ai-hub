# T16 namespace, writer-token floor, and rollback preflight patch v5

Patch: `T16-namespace-root-current-v5.patch`
SHA-256: `27242C3C4F9EA7113DC9E84C4179A6E937583175BF4ECEA64D605BC34A940459`
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
Candidate HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`

V5 extends immutable core v4 with two T16 fixes: namespace writer fencing tokens exceed retained legacy physical writer tokens; rollback rejects an existing non-directory ancestor during full restore-list preflight. Added one regression test for each. Published v4 and HTTP route v3 remain unchanged. No `commands.py` hunk.

## Evidence

- RED: both new tests failed before fixes (`1 > 8` assertion; missing non-directory ancestor refusal).
- GREEN: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py tests/test_t16_terminal_rollback_preflight.py` — `12 passed, 1 skipped in 5.09s`; skip is Windows symlink privilege `WinError 1314`.
- Root `git apply --check --whitespace=error` against v5: pass; root was read-only.
- Temporary composition overlay: v5 then HTTP route v3 strict apply-check passed; AST parse passed for 12 transformed Python files.

## Root preimages

- `src/local_ai_hub/leases.py`: `BF56E69ABC46DCF1B9CC4B4778251618FD1EA243329D58E48BEFE833DB1AF1CB`
- `src/local_ai_hub/work_fencing.py`: `10823461FBA3D0B9E2BA516E14E82EEE833315A00A2B11FCDEBDBBECD22CB9AA`
- `src/local_ai_hub/work_orchestrator.py`: `BA24529B8F330248A7F1A8A14847244778B74CE2A201B5DA0D7A928367130093`
- `src/local_ai_hub/project_config.py`: `4238B6A6DE1DE00F55F4679CE0DF7D431522EC1BAFABFA272258C1662F13F713`
- `tests/test_work_fencing.py`: `3CF82264563206B12AEA1CFFC0B78E12AE16D2FF650DE423730BE4A87A4A03D0`
- `tests/test_work_handoff_acceptance.py`: `ACB5249AE641BB4FCF75319C6A2FEE3EDC16CA78818CFE5D66CF79CA0EC68B7`
- `src/local_ai_hub/http_server.py` for dependent route patch: `94C44910B04F8909778F926E64D3F857975BAA5738B78979427BACE29AA3EDF3`
