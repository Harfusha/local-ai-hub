# T16 root-current test postimage manifest v1

Date: 2026-10-02
Candidate worktree: `C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
Root: `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`.

T20 reported the three T16 test-only patches applied. Root was inspected read-only after that report. The postimage hashes below match the current root working tree. No root tests or writes were performed; root selectors await T20's slot release.

## Exact 3-selector batch

Run in root only after T20 releases the test slot:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t16_cross_process_namespace_lease_recovery.py::test_cross_process_lease_refresh_and_release_survive_sqlite_reopen tests/test_work_fencing.py::test_cross_process_successor_cannot_supersede_writer_inside_commit_guard tests/test_work_handoff_acceptance.py::test_process_crash_after_patch_write_recovers_from_persisted_journal
```

Earlier candidate run of that exact selector set: `3 passed in 3.83s`. Fresh resumed candidate rerun: `3 passed in 5.60s`, exit 0. This is candidate evidence only; it does not claim root runtime acceptance.

## Root patch → postimage pins

| Selector file | Root preimage SHA-256 | Root postimage SHA-256 | Applied patch SHA-256 |
|---|---|---|---|
| `tests/test_t16_cross_process_namespace_lease_recovery.py` | `B623D312916D8C9BED6B5DE90AB315D350FF8F9D21FE26EA1FEB035CD8B2F176` | `D69F65E06443E76C8979A7F020C0DDD6F744FABFDCD84D5F79103C852D40FE44` | `A2B836F28FEBF4043E06AB83FE2AA70D1A769727BDFDF1D2D6B8C2EDC1998574` |
| `tests/test_work_fencing.py` | `64115A4BC20C6F7375E39AA8C8BAD51AE24D2E1C3EAC28D96DCFEFC3DB88C9B6` | `EEB23B457ED9C96786F4AF1763507CF8B97D5EA43B79AC187E4975D151CF3FDE` | `CFCFF000F6FD1C3F1A3434B2B21BD8BB61AC5930A33D1B9AAB82C5BB027A4F66` |
| `tests/test_work_handoff_acceptance.py` | `896EC91BF4F96AED5F0C11288053A8B135FB5B0DCACB533CE53163F3B4D7A5C4` | `978B4E01CFE36116838FB22451D409F7B72DC00836913D337C2DBFCAF233BBEB` | `E3CC3A615D87DC4DAAF94FD4BDE1488F7E8CCC75CDAD108F8D31C8ABB6F7044A` |

All three root-current patches passed read-only `git apply --check --whitespace=error` before T20 applied them. Postimages were verified by read-only SHA-256 after T20's application report.

## Separate gates and drift

- Symbolic directory symlink: `NOT TESTED`, Windows `WinError 1314`. Junction coverage stays separate from this 3-selector batch.
- T06 broker and T09 cancel/completion selectors are outside this batch and retain owner control.
- `services.py` drift is separate: root SHA-256 `525565A42B626A7ED2A66ADE57C6878D1802B430F2D1BD5A2818B7ADA68D3179`; candidate SHA-256 `B1F1E117F49D566E067257E90868CD4134B736C1D3F49A783DC4EDE79BE9C97E`. This service change is not represented by these test-only patches or selectors.
- No root write/test until T20 releases the slot. Candidate changes and inherited dirty files remain preserved.
