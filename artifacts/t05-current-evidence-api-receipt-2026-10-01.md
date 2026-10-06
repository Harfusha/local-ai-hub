# T05 current-evidence API receipt — 2026-10-01

Scope: candidate-only change to `src/local_ai_hub/evidence.py` and `tests/test_evidence_contract.py`. Root, T14 ledger, and `/api/context/pack` were not edited. No root tests ran.

## API

- `is_evidence_id(value: Any) -> bool`
- `is_current_evidence_id(value: Any, evidence_store: Any) -> bool`
- `EvidenceStore.validate_current(evidence_id: str) -> bool`

All checks fail closed. Validation requires a well-formed ID, a successful non-stale store read, matching returned ID, and a recomputed content-addressed ID matching the supplied ID.

## Verification

- RED: before implementation, focused selector failed as expected: `AssertionError: is_evidence_id API missing`.
- GREEN: `python -B -m pytest -q -p no:cacheprovider tests/test_evidence_contract.py --tb=short` — **3 passed in 0.16s**.
- `git diff --check -- src/local_ai_hub/evidence.py tests/test_evidence_contract.py` — passed.
- `git apply --stat artifacts/t05-current-evidence-api-2026-10-01.patch` — passed.
- Root dry-run `git apply --check` — passed; no root write.

Patch SHA-256: `1F55850829F58E25A3B313AB8ED43B8039BCF5A26A248AE821047E149848A619`
Source SHA-256: `8050048407BEFAE57FB13159DA11E98A4E1D48E418652C6E817DD465957FE033`
Test SHA-256: `50794A86A3381A8EE0504DE466A7A69FB1C77AB0B305A3280CD1F308263A14B0`

Semantics boundary: current source means existing `get(verify=True)` file-hash verification. This patch also checks stored-row identity. It does not verify that stored excerpt text still matches the file line range or enforce T14 TTL freshness.
