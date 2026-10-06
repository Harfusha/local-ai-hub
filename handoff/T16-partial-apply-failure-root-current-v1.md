# T16 partial apply failure regression handoff v1

Patch: `T16-partial-apply-failure-root-current-v1.patch`
SHA-256: `89C3C954C4D0CCF2EAAF09D2CA9F742AE20080D36FE4DC7E5BEA5BFFE8B7A081`
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
Root preimage `tests/test_work_handoff_acceptance.py` SHA-256: `247A15B6D6DEB7567B857205D90ABE894BC3F5D6B97C439E94C902B6BF11CB59`

One test-only hunk adds `test_partial_git_apply_failure_restores_all_preimages_and_clears_journal`. It injects a failed apply after the first target changes; the selector verifies both preimages restored and in-memory plus persisted journals cleared. No production source hunk.

Candidate receipt: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_handoff_acceptance.py::test_partial_git_apply_failure_restores_all_preimages_and_clears_journal` — `1 passed in 0.65s`.

Root `git apply --check --whitespace=error`: pass. Root source was not modified or tested. T20 retains integration and root validation ownership.
