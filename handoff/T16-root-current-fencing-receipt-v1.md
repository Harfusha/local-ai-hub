# T16 root-current fencing/recovery receipt v1

## Ownership and worktree

- T16 candidate: `C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- T20 root: `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`.
- Candidate/root source and status inspected read-only. No root source or test writes. T21 `project_config.py` and T06 `commands.py` remain outside T16 ownership.
- Candidate has inherited dirty T16, T21, and shared integration paths. No reset/stage/commit performed.

## Candidate verification

Final candidate test change: move crash-recovery test into recovery cluster; disable only child-process background worker startup before orchestrator construction. Fencing leases, write-set checks, and commit guards remain enabled. Assertions unchanged.

Exact candidate command:

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_handoff_acceptance.py::test_process_crash_after_patch_write_recovers_from_persisted_journal`

Result after final edit: `1 passed in 1.04s`.

Candidate SHA-256 pins:

- `src/local_ai_hub/work_orchestrator.py`: `70C5084F02D4D1202C5375194324A6E6754C5623C4389DED19846CF4CE9B3AD5`
- `src/local_ai_hub/work_fencing.py`: `287DA1CDC5A8CA31EA96CE08D9D3D2EDC641F7BF7DC0F815BC3B2AECCED2F214`
- `src/local_ai_hub/services.py`: `B1F1E117F49D566E067257E90868CD4134B736C1D3F49A783DC4EDE79BE9C97E`
- `tests/test_work_orchestrator.py`: `69B0AAEBB8F37CEC1537BBB59A3C2D3EC9133895499F303464A0D752196A19CC`
- `tests/test_work_handoff_acceptance.py`: `75F7B4AD282AC28257527FDEC1B6B3755F3DB471F52BC426C24B3F6336A66208`
- `tests/test_work_fencing.py`: `E7C82981577F48144E849B80EC473FBBA258B269EEEC05E84584228E04CA5A0D`

## T20 root-current receipt (owner-reported)

T20 recorded exact root command and result: `7 passed in 2.10s`:

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py::test_commit_guard_revalidates_path_and_attempt_tokens_before_commit tests/test_work_fencing.py::test_commit_guard_rejects_expired_parent_attempt tests/test_work_fencing.py::test_expiry_reacquire_fences_stale_write_and_commit_without_side_effects tests/test_work_fencing.py::test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens tests/test_work_handoff_acceptance.py::test_process_crash_after_patch_write_recovers_from_persisted_journal tests/test_work_handoff_acceptance.py::test_recovery_requeues_after_crash_between_journal_clear_and_state_update`

T20 also reported crash-only root selector `1 passed in 1.15s`. T16 did not rerun root tests.

Root SHA-256 pins at receipt:

- `src/local_ai_hub/work_orchestrator.py`: `CBCCC1480BD9B9BF1BAB6EDCF41573E7390A61147F23A2946DE3D48BDDE78337`
- `src/local_ai_hub/work_fencing.py`: `C93C22210A479DA74A8ACD19134BAE2BC80979BDDD55E9E5FA08A50042ECBDD0`
- `src/local_ai_hub/services.py`: `CCD292C8F91809B59BD3446D045CB550BABBD8CAEA86FAB4FCAA6D2E284564A0`
- `tests/test_work_fencing.py`: `64115A4BC20C6F7375E39AA8C8BAD51AE24D2E1C3EAC28D96DCFEFC3DB88C9B6`
- `tests/test_work_handoff_acceptance.py`: `896EC91BF4F96AED5F0C11288053A8B135FB5B0DCACB533CE53163F3B4D7A5C4`
- T06 `src/local_ai_hub/commands.py`: `DC125391DC6BC06C8C5777018E524230233E41E68D09894174D66E6BABF0344E`
- T21 `src/local_ai_hub/project_config.py`: `4238B6A6DE1DE00F55F4679CE0DF7D431522EC1BAFABFA272258C1662F13F713`

Extracted `_recover` method hashes match candidate/root: `01C0320257C53A10E4239E0DD08FAE8759524963BE959E1A69C9FD123D1D544C`. Extracted `_ensure_workers` method hashes match: `A6D7C173F5B82876A68E4C7474148B2528C8B6A2919F2CEE39EF8FE8947B14A6`.

## Exact optional root-current handoff

Placement-only patch: `handoff/T16-root-current-crash-test-placement-v1.patch`.
Patch SHA-256: `E3CC3A615D87DC4DAAF94FD4BDE1488F7E8CCC75CDAD108F8D31C8ABB6F7044A`.
Root test preimage SHA-256: `896EC91BF4F96AED5F0C11288053A8B135FB5B0DCACB533CE53163F3B4D7A5C4`.
Read-only `git apply --check --whitespace=error` against current root: `PASS`.

Patch moves crash-recovery test into recovery cluster, preserving current root body and assertions. Root crash selector already passes; patch is optional integration hygiene, not a required production fix. Recheck preimage before applying.

## Remaining acceptance boundary

Root T16 7-test receipt is owner-reported by T20 and pinned above; no independent root rerun. Symbolic directory-symlink selector remains `NOT TESTED` because Windows returned `WinError 1314`; junction/reparse coverage passed. Do not mark T16 complete until acceptance owner resolves or approves that gap.
