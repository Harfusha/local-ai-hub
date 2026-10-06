# T18 telemetry classification handoff

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub` at HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`. T18-owned scope is `TelemetryStore._safe_error_message` and new test `tests/test_telemetry_sqlite_dashboard_t18.py`. Broader dirty diffs were not copied.

Root checkout was not modified. Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Root `src/local_ai_hub/telemetry.py` SHA-256: `C9666D2FB6E925151CC7343E06333A34996FE5DFF1DB17E5358F199EF8F933E8` (already dirty before this T18 work). At lines 159-169, OS diagnostics depend on `errno`; a `FileNotFoundError` without errno is stored as `FileNotFoundError: operating system failure`.

Evidence:

- Candidate focused command `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_telemetry_sqlite_dashboard_t18.py tests/test_telemetry_error_diagnostics_t18.py::test_error_diagnostics_are_actionable_bounded_and_private` -> 7 passed in 4.00s.
- Same SQLite summary test with root `local_ai_hub.telemetry` preloaded -> 1 failed in 0.76s. Exact mismatch: expected `FileNotFoundError: file not found`; got `FileNotFoundError: operating system failure`.
- Candidate telemetry test SHA-256: `73947FF8F0C09B9075F6C1A6AFDC7314F1BFB2D3124EF7416C6DD7A896586A4C`.
- Patch `T18-telemetry-error-class-sqlite-test-fix-20261001-v1.patch`, SHA-256 `BF45D78C0215F14FE6E7E8AB91A501DFA205CC4E31AFDC8CECF9FE1625F0934B`, includes only explicit `FileNotFoundError`/`PermissionError` allowlist branches and the SQLite dashboard test. `git apply --check` passed at root HEAD; patch was not applied and root tests were not run.
- Current-root mode/auth/DOM overlay and dashboard projection tests passed 2/2 when root modules were imported before pytest. A first invocation had 2 fixture import-origin failures; no source assertions ran in those two cases.
- Candidate dashboard/status/auth/degraded-mode plus telemetry selector: 64 passed; two root-pin fixtures failed only because candidate modules were imported before their pin. Rerunning the pinned fixtures with root import primed passed 2/2.
- A combined candidate-suite run with root modules preloaded gave 37 passed, 29 failed. Those tests assert candidate-only API behavior (for example `_operational_mode_api` absent from current root). Do not treat that mixed-source run as root acceptance; the standalone SQLite red is the actionable root finding.

T20 integration remains pending. Apply only this narrow patch after reviewing current ownership; run the named SQLite test and the root-pinned dashboard/status/auth selectors. No admin or operational-mode gate changes are included.
