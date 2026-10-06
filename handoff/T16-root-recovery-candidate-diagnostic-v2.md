# T16 crash-recovery boundary diagnosis v2

## Result

Candidate worktree `C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.

Candidate test was relocated into recovery-test cluster and isolated from child worker startup. Focused run after both edits:

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_handoff_acceptance.py::test_process_crash_after_patch_write_recovers_from_persisted_journal`

Result: `1 passed in 1.04s`.

T20 separately reported root-current crash selector `1 passed in 1.15s`; not rerun here.

## Cause and comparison

Root and candidate extracted `_recover` method hashes match exactly: `01C0320257C53A10E4239E0DD08FAE8759524963BE959E1A69C9FD123D1D544C`.
Root and candidate extracted `_ensure_workers` method hashes match exactly: `A6D7C173F5B82876A68E4C7474148B2528C8B6A2919F2CEE39EF8FE8947B14A6`.

Cause was test-process setup, not recovery transition. Root crash-test child disabled `_ensure_workers` before constructing `WorkOrchestrator`; candidate child did not, so its automatic background worker could race the simulated crash/recovery row. Candidate now disables that child worker. Assertions unchanged.

Crash-test function is a module-level function on both sides and contains no broker reference. Root has T20/T06 broker test as a separate function before it. Candidate moved T16 crash test from module EOF into recovery-test cluster to avoid append-hunk overlap. Remaining body difference: root adds `dict(row)` to assertion failure diagnostics; assertion semantics match.

## Optional root-current placement patch

`handoff/T16-root-current-crash-test-placement-v1.patch` moves only root test function placement; preserves current root body and assertions. Root preimage SHA-256: `896EC91BF4F96AED5F0C11288053A8B135FB5B0DCACB533CE53163F3B4D7A5C4`. Patch SHA-256: `E3CC3A615D87DC4DAAF94FD4BDE1488F7E8CCC75CDAD108F8D31C8ABB6F7044A`.

Root now passes selector, so this placement-only patch is optional. Do not apply if root preimage changed; no root edits made by T16.

## Current candidate file pin

`tests/test_work_handoff_acceptance.py` SHA-256: `75F7B4AD282AC28257527FDEC1B6B3755F3DB471F52BC426C24B3F6336A66208`.
