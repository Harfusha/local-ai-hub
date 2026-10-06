# T16 crash-test placement root-current manifest v1

## Scope

Pure relocation of the existing T16 process-crash recovery test from module EOF into the existing recovery-test cluster, immediately before `test_recovery_rollback_failure_fails_closed_and_preserves_journal`. Assertions and behavior unchanged. This avoids EOF append overlap with adjacent broker tests. Root was read only.

Candidate test file SHA-256 after relocation: `6682E3E9DB0C3BD6F4E53035A358491F3FC0361FAF8F53D99D537FE205CB5BDA`.

## Root-current patch

Patch: `handoff/T16-root-current-crash-test-placement-v1.patch`
Patch SHA-256: `E3CC3A615D87DC4DAAF94FD4BDE1488F7E8CCC75CDAD108F8D31C8ABB6F7044A`.
Root preimage `tests/test_work_handoff_acceptance.py` SHA-256: `896EC91BF4F96AED5F0C11288053A8B135FB5B0DCACB533CE53163F3B4D7A5C4`.
Moved root test body SHA-256: `3F301CCD3F8D42FA541B7ECA80B1370E3F5D8FE408B97D00E16F8EA039D02C8C`.

Patch changes only test function placement. No test statements removed or weakened.

## Candidate validation

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_handoff_acceptance.py::test_process_crash_after_patch_write_recovers_from_persisted_journal`

Result after candidate relocation: `1 passed in 1.00s`.

T20 reported root-current selector now passes its crash test: `1 passed in 1.15s`; not rerun here.

## Candidate/root source comparison

Extracted `_recover` method SHA-256 matches exactly on both sides: `01C0320257C53A10E4239E0DD08FAE8759524963BE959E1A69C9FD123D1D544C`.
Extracted `_ensure_workers` method SHA-256 matches exactly on both sides: `A6D7C173F5B82876A68E4C7474148B2528C8B6A2919F2CEE39EF8FE8947B14A6`.
Both crash test functions are module-level and contain no `broker._fenced_transaction_commit` reference. Root has separate `test_root_current_command_broker_namespace_guard_commits_real_write` immediately before the crash test. Candidate lacks that root/T06-specific test. Root test's assertion includes a row diagnostic; candidate assertion does not. Candidate uses pytest `monkeypatch.setattr` for `_ensure_workers`; root uses direct class assignment. Recovery/worker implementation does not differ; root's latest successful result resolves prior transient failure.
