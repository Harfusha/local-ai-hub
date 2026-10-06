# T19 candidate acceptance receipt

Candidate worktree: T19 assigned checkout, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`. Root checkout HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. T19 did not write root.

## Candidate validation

- Exact PowerShell command: `$tests = Get-ChildItem -Path tests -Filter 'test_t19_*.py' | Sort-Object Name | ForEach-Object { $_.FullName }; python -B -m pytest -q -p no:cacheprovider --tb=short $tests` (16 matching files in sorted order).
- Result: `50 passed, 1 skipped in 24.55s`. Skip: Windows denied directory symlink creation (`WinError 1314`) in `test_t19_rollback_snapshot.py`; symlink case remains unverified on this host.
- Additional command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_codegraph_package_policy.py tests/test_setup.py tests/test_release_contract.py tests/test_release_hardening.py`.
- Result after T19 fixes: `58 passed, 2 failed, 1 skipped in 44.13s`. The two T19 failures from the initial `56 passed, 4 failed, 1 skipped` run are fixed: prompt summary expectation now follows `hardware.py`, and source hygiene excludes `handoff/`, which `MANIFEST.in` does not ship. The focused rerun of those two selectors passed `2/2`.
- Remaining failures are outside T19 scope. Exact diagnostics: `AttributeError: '_LiveProc' object has no attribute 'pid'` in `test_mcp_explicit_short_deadline_is_honored`; `AssertionError: ['forbidden directory: build/', 'forbidden directory: dist/']` in `test_release_gate_allows_the_live_installed_checkout`. Existing build/dist artifacts remain untouched. Linux `/proc` selector skipped on Windows.
- Command: `python tools/surface_inventory.py --check --task-id T19`.
- Result: `{"coverage_matches": true, "coverage_rows": 665, "drift": [], "success": true}`.
- `git diff --check` passed; output contained line-ending conversion warnings only.
- Candidate v7 package hashes reverified against runbook: sdist `9ae54e1f86e5c8e810ba32be7f9df19277485d834a38f664aac68336a1e18efb`; wheel `e2bc477680cebc36b9300651250d217214ca80ef9bfebb943c89397eff4c7f76`.

## SDK, usability, and install receipts

- `docs/PYTHON_SDK.md` maps 42 public `HubClient` methods and 43 literal public routes. Seven production-route loopback workflows passed in 12 HTTP calls with exact route/body assertions; inference was stubbed, so no model quality/latency claim follows.
- SDK wrapper plus uncertain-mutation tests: `11 passed`. The prior mutation-replay suite receipt was `37 passed, 16 failed`; remaining failures cover repair-loop output, maintenance GET, HTTP/server journal behavior, bundle import, telemetry accounting, and restart idempotency. Server replay safety remains unclaimed for those routes.
- The latest existing install receipt is `dist/t19-release-20260930-sdk-transport-fix/reinstall-receipt.json`: core-only Windows Python 3.13.2 wheel install/import/version, `pip check`, and CLI help passed; all-six-extras wheel install followed by sdist install passed, with `pip check` and CLI help clean. These were fresh venvs on the development host, not clean-host receipts.
- Its artifact hashes are sdist `c80827730b423a270612525c453253aee22ccb90237610e9f65a098f96047c08` and wheel `5522b03f593b8a3d41e25d40d3145735bc2c9048254e719f8d9b2d443135c1e3`. Read-only archive inspection confirms the sdist's Python SDK doc matches current candidate, while both prompts and API coverage are stale; the wheel includes none of these docs.
- Read-only inspection of the later SDK-transport artifact also found it stale for the latest prompt/coverage edits. Sdist `c80827730b423a270612525c453253aee22ccb90237610e9f65a098f96047c08` has INSTALL_PROMPT `0a6d0604...` vs current candidate `df5356cc...`, UPDATE_PROMPT `cf54e8c0...` vs `acac9428...`, and API_COVERAGE `b5b58550...` vs `8aead19a...`; PYTHON_SDK matches `9ef0136c...`. Wheel `5522b03f...` contains none of those docs. No new package was built before T20 integration freeze.

## Current root handoffs

- `handoff/T19-prompts-release-contract-current-root.patch`, SHA-256 `1fe2c919221ff8954ab8e7d5866474a0089846339c2b6ae4ccbb0968a65b6fec`. Scope: both install/update prompts and canonical AGENTS routing now match `hardware.py`; parity assertions cover high/max roles and balanced wording; `handoff/` remains excluded from the release-content scan in `tests/test_release_contract.py`. Scoped candidate selectors passed 2/2. `git apply --check --verbose` passed against the current dirty root; patch remains unapplied by T19. High maps involved work to 7B and ordinary/reasoning/vision to 9B; max maps all four routes to 9B. Older `T19-high-routing-current-root.patch` is superseded; do not apply both.
- Old `handoff/T19-API_COVERAGE-current-root.patch` is superseded and must not be applied. T01 removed duplicate findings in its owned worktree. Current root coverage has 685 rows and one T01-owned GET `/api/context/pack` row. Root bytes are CRLF; renderer output is LF, but line contents match.
- Earlier coverage-owner source/test patch is integrated in root by T20. Candidate retains separate T19 changes and tests.

## Release gates still open

- Clean-host Windows and Linux receipt templates remain `pending_run`. Earlier Windows candidate v7 installs, `pip check`, and CLI help passed, but those are not clean-host receipts; no Linux receipt exists.
- T08 rollback-recovery receipt is still missing and has cross-owner prerequisites recorded in `T19_RELEASE_VALIDATION_RUNBOOK.md`.
- T20 later integrated T01's corrected generator/docs and reported root inventory check at 685 rows, drift 0, with 724 root tests passing. That supersedes the earlier intermediate `149 failed, 574 passed` result.
- T20's latest root gates still report a T08 live-order publication failure and a T11 real-reranker root failure (`should_stop` unsupported); T13/T06 candidate gates also remain open. These are outside T19 ownership and do not transfer candidate-only receipts to root.

T19 candidate tests pass except the documented privilege-dependent skip. Full release acceptance is not complete until external receipts and root integration gates close.
