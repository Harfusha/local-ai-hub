# T16 root-scope cross-process fencing acceptance v1

Patch: `T16-root-scope-cross-process-root-current-v1.patch`
SHA-256: `F11D8B8D276815738867CABB55ACF490B3846A611F4AE77BBC58071AEB9AD2B5`
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
Root preimage `tests/test_work_fencing.py` SHA-256: `BE4123741CA0EFC66D9196FE2ED79F307ADC925CCF6CA78822C6C149ED9C97DB`

One test-only hunk adds the bounded spawned-process acceptance for the legacy physical root scope. Three processes open the same SQLite store in separate lifetimes: old holder claims with `coordination_id` omitted, successor reacquires after deterministic expiry and performs fenced file plus fixture commit-receipt writes, then stale holder reloads its persisted receipt and must fail both attempt and commit guards. The test pins all attempt/lease `scope_id` values to canonical physical root and verifies successor fencing tokens exceed stale tokens after database reopen.

The `commit-receipt.json` file is test fixture only; this does not prove production T07 journal integration. Namespace A/B/C isolation remains covered by `T16-cross-process-namespace-lease-recovery-v1.md` and HTTP route v3 receipt.

Candidate exact selector: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py::test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens` — `1 passed` in 0.40s.

Root `git apply --check --whitespace=error`: pass. Root source was not modified or tested. T20 retains integration and root validation ownership.
