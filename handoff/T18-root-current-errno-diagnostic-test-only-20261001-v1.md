# T18 root-current errno diagnostic handoff

Patch is test-only and intentionally narrow. Current root already contains T18 `_safe_error_message` branches for timeout, connection, invalid JSON, missing file, permission, and errno-specific OS errors. No production hunk is needed.

## Patch

- File: `T18-root-current-errno-diagnostic-test-only-20261001-v1.patch`
- SHA-256: `9F43C740E38AB4D2062FE77432E28645546B2E00CE0DC490343193879ACC5E4F`
- Adds `tests/test_telemetry_error_errno_diagnostics_t18.py`: real SQLite persistence assertions for base `OSError` with `ENOENT` and `EACCES`, plus synthetic prompt/source/token/absolute-path sentinels. Confirms safe type/category labels, <=96-character messages, and no raw-text leak.
- Root `git apply --check` passed against current root working tree. Patch target was absent. Patch was not applied; root remained read-only.

## Exact pins

- Candidate worktree HEAD: `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`; `src/local_ai_hub/telemetry.py` SHA-256 `607736CE42A16C348F3032FC514C5FDB19C35A15E2FFA77A260E3F88E99EA14D`.
- Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Root `src/local_ai_hub/telemetry.py`: `79146032D1C904FA57875858A4C4265A8FE6D02BCC62F9CBCEE258D7DAF685EE`.
- Root `tests/test_telemetry_error_diagnostics_t18.py`: `325323CD2FFA5F2C34DDC3D54D5BEFFF2A032BBC988291F0E9719128E379D0AD`.
- Root `tests/test_telemetry_sqlite_dashboard_t18.py`: `6F841BAE86741DE4D6A01A7A2BD227CBCF8524EF982E9A6AC2FDED430E0705AC`.
- Root sources/tests are dirty/untracked from prior owners. T18 made no root edits.

## Isolated overlay receipt

Created temporary overlay under the candidate worktree with only root `telemetry.py`, `json_utils.py`, `trace_context.py`, `sqlite_support.py`, `dashboard.py`, `__init__.py`, root T18 diagnostic/SQLite tests, and the patch test. The overlay telemetry SHA matched `79146032D1C904FA57875858A4C4265A8FE6D02BCC62F9CBCEE258D7DAF685EE`; no inherited project diffs were copied.

Command:

```text
python -B -W error::ResourceWarning -c <assert isolated telemetry path and SHA; pytest.main(['-q','-p','no:cacheprovider','--tb=short','tests/test_telemetry_error_diagnostics_t18.py','tests/test_telemetry_sqlite_dashboard_t18.py','tests/test_telemetry_error_errno_diagnostics_t18.py'])
```

Result: **11 passed in 6.16s**.

Isolated overlay remains preserved at `.t18-root-overlay-errordiag-v1` for reproducibility and contains only listed root source dependencies/tests. Root integration remains T20-owned; apply patch only after owner review.

