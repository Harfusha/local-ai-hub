# T03 path-hints root-current handoff

## Scope and ownership

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`.
- Root: `C:\Users\Adam\.local-ai-hub`; no root files were modified.
- Only T03 `local_ai_repo(action="search")` accepts `path_hints`; its action contract now rejects the field for `context`.
- `/api/context/pack` was not changed by this work.
- T03 and T21 provenance/lease reconciliation is still pending. The patch is prepared, not applied to root.

## Root-current patch

- Patch: `handoff/T03-root-current-path-hints-20261002.patch`
- Patch SHA-256: `A5F28F9C645DF211BEFE971E3B0257086A1FC07CBB9353EBC39EE3569D4130F5`
- Paths: `src/local_ai_hub/services.py`; new `tests/test_t03_path_hint_search_first.py`.
- Stat: services 32 lines changed (+21/-11); new test 102 lines; total 123 insertions, 11 deletions.
- Root service preimage SHA-256: `525565A42B626A7ED2A66ADE57C6878D1802B430F2D1BD5A2818B7ADA68D3179`.
- Root service postimage SHA-256 after applying the patch to a temporary copy: `11C4B336A735220CB11BCACE11021B74227BA8B303275E43F192CBDD9C52BC27`.
- Test preimage: absent. Test postimage SHA-256: `FF43981461F039A12B660DA031581C5936A3499098E7A03F907D1BAB64204358`.
- `git apply --check --verbose` against current root passed for both paths. No root patch was applied.

## Exact integration steps for T20

1. Confirm current root `src/local_ai_hub/services.py` still hashes to `525565A42B626A7ED2A66ADE57C6878D1802B430F2D1BD5A2818B7ADA68D3179` and `tests/test_t03_path_hint_search_first.py` is absent. Stop if either preimage differs.
2. Verify the patch hash above, then run `git apply --check handoff/T03-root-current-path-hints-20261002.patch` from the root.
3. Apply that patch only after T03/T21 ownership and provenance are reconciled. It changes the root service and adds the bounded regression file; it does not include T03's simplified e809 service hunk.
4. After T02/T15 release the exclusive test slot, run `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t03_path_hint_search_first.py tests/test_t10_repo_search_path_hints.py tests/test_t21_root_path_hint_worktree_chain.py`.
5. Review only the two patch paths and confirm `/api/context/pack` remains unchanged. Do not claim root acceptance until that root test command passes.

The root hunk retains T21's `validate_path_hint`, configuration exclusion checks, and post-search `prioritize_paths_with_hints` ordering. It tries the validated, policy-filtered candidate set first. It uses that result only when it fills the requested `top_k`; invalid, stale, excluded, out-of-root, empty, or undersized hint results fall back to the existing full search.

## Validation receipts

- Root-current test patch was applied only to a temporary copy of root `src/local_ai_hub`; targeted command `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t03_path_hint_search_first.py` passed: **3 passed in 0.60s**.
- T03 candidate focused selectors for path-hint schema scope, adaptive context fields, and the paired fixture passed: **3 passed in 2.45s**.
- Candidate paired fixture keeps `src/auth.py` as the result and reduces `scanned_files` from 4 to 1.
- No additional tests were run after T02 announced its exclusive test slot.

## Candidate file hashes

- `src/local_ai_hub/services.py`: `1BDA56D89BD7540C4AE89F36B2BD13A4BEA7471BEEA35AE7E14336D2E6F55EC2`
- `src/local_ai_hub/operation_contracts.py`: `80C10F77E786B1D8E8F5CA8FA18405155EADD2B4A1D5AC894D319F8AA1254C58`
- `tests/test_operation_contracts.py`: `DF4CA2257F5639AA716B754138FB2C459872951A8762AB11D369EED143863AC9`
- `tests/test_repo_path_hints_search.py`: `D7212F31F494261B33F35267B2209E6954FB6059616A1EF4935787C50B5F2970`
