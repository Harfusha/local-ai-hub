# T16 Windows junction reparse-point acceptance v1

Patch: `T16-windows-junction-acceptance-root-current-v1.patch`
SHA-256: `C53136D6B06E7A90BE168F03BFF2D4132004C8CA4564119C090F215733872E1A`
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`

## Root test preimages

- `tests/test_work_fencing.py`: SHA-256 `BE4123741CA0EFC66D9196FE2ED79F307ADC925CCF6CA78822C6C149ED9C97DB`
- `tests/test_t16_terminal_rollback_preflight.py`: SHA-256 `77E556562217D68F0C3E248EFCD49CCB9E1063C26126AFB7888A9A8302378F28`

Patch adds two Windows-only tests and imports `subprocess`:

- `test_rooted_scope_resolves_junction_alias_to_same_path` creates a directory junction via `cmd.exe /c mklink /J`, asserts `Path.is_junction()`, compares normalized alias and real path.
- `test_rollback_rejects_junction_before_restoring_any_file` points a junction to an internal sibling, ensuring ordinary root containment alone would pass; rollback must reject the reparse point before changing the first file. Target data remains intact.

## Receipt

Privilege probe: `mklink /J` succeeded without elevation in temporary directory; `is_junction=True`.

Exact current-root-worktree overlay command:

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py::test_rooted_scope_resolves_junction_alias_to_same_path tests/test_t16_terminal_rollback_preflight.py::test_rollback_rejects_junction_before_restoring_any_file`

Run from `C:\Users\Adam\AppData\Local\Temp\t16-current-root-worktree-overlay-iar0xslc` with `PYTHONPATH=C:\Users\Adam\AppData\Local\Temp\t16-current-root-worktree-overlay-iar0xslc\src`. The two test files were copied from current T16 candidate. Product module origins were current root working-tree overlay:

- `work_fencing.py` SHA-256 `4DA7E64370A1F08AED16F8C73C6DDA75C6A682F2A765839EC045FA2C356FD050`
- `work_orchestrator.py` SHA-256 `CBCCC1480BD9B9BF1BAB6EDCF41573E7390A61147F23A2946DE3D48BDDE78337`

Result: `2 passed in 0.21s`, exit 0. No symlink privilege skip; junction/reparse checks passed. Symbolic directory symlink creation remains unverified (`WinError 1314` in existing symlink-only selector); do not equate junction coverage with symbolic-link coverage.

Root `git apply --check --whitespace=error`: pass. Root was not modified or tested. T20 owns root integration.
