# T16 root-current orchestration/handoff manifest v1

Date: 2026-10-02
Candidate: `C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
Root: `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`. Root remained read-only; no root tests or writes.

## Safe root-current test patches

These three test-only patches passed `git apply --check --whitespace=error` against the current root working tree. None was applied.

| Patch | SHA-256 | Root preimage | Purpose |
|---|---|---|---|
| `T16-root-current-cross-process-atomic-lease-v1.patch` | `A2B836F28FEBF4043E06AB83FE2AA70D1A769727BDFDF1D2D6B8C2EDC1998574` | `tests/test_t16_cross_process_namespace_lease_recovery.py` SHA-256 `B623D312916D8C9BED6B5DE90AB315D350FF8F9D21FE26EA1FEB035CD8B2F176` | Adds successful process-A claim → process-B SQLite reopen/renew/release → process-C successor claim regression. Candidate postimage SHA-256 `57D65635171198D378F74B34440B2892373C029FB1A9280AB51256D7DD046831`. |
| `T16-root-current-cross-process-commit-race-v1.patch` | `CFCFF000F6FD1C3F1A3434B2B21BD8BB61AC5930A33D1B9AAB82C5BB027A4F66` | `tests/test_work_fencing.py` SHA-256 `64115A4BC20C6F7375E39AA8C8BAD51AE24D2E1C3EAC28D96DCFEFC3DB88C9B6` | Adds regression preventing an expired successor from superseding a writer inside `commit_guard`. |
| `T16-root-current-crash-test-placement-v1.patch` | `E3CC3A615D87DC4DAAF94FD4BDE1488F7E8CCC75CDAD108F8D31C8ABB6F7044A` | `tests/test_work_handoff_acceptance.py` SHA-256 `896EC91BF4F96AED5F0C11288053A8B135FB5B0DCACB533CE53163F3B4D7A5C4` | Places crash-recovery regression with the root-current recovery fixture. |

Application order: independent test-file patches; verify each exact root preimage immediately before application. `T16-cross-process-namespace-lease-recovery-v2.patch` is the full candidate file-add patch, not root-current; do not apply it to root because the root test file already exists. Use the incremental root-current patch above instead.

## Production source decomposition and ownership

No production-source patch is included. Root currently contains dirty T20 integration and source hashes differ from the candidate:

| File | Root working SHA-256 | Candidate SHA-256 | Disposition |
|---|---|---|---|
| `src/local_ai_hub/work_orchestrator.py` | `CBCCC1480BD9B9BF1BAB6EDCF41573E7390A61147F23A2946DE3D48BDDE78337` | `70C5084F02D4D1202C5375194324A6E6754C5623C4389DED19846CF4CE9B3AD5` | Keep root/T20 bytes; symbol-level reconciliation needed before source transfer. |
| `src/local_ai_hub/work_fencing.py` | `C93C22210A479DA74A8ACD19134BAE2BC80979BDDD55E9E5FA08A50042ECBDD0` | `287DA1CDC5A8CA31EA96CE08D9D3D2EDC641F7BF7DC0F815BC3B2AECCED2F214` | Keep root/T20 bytes; do not replace wholesale. |
| `src/local_ai_hub/services.py` | `525565A42B626A7ED2A66ADE57C6878D1802B430F2D1BD5A2818B7ADA68D3179` | `B1F1E117F49D566E067257E90868CD4134B736C1D3F49A783DC4EDE79BE9C97E` | Keep root/T20/owner bytes; root service integration has an unresolved `vision_contracts.image_dimensions` dependency. |
| `src/local_ai_hub/leases.py` | `362F4A0345977B16D04D92B5AFD37C82DEB2DC24DF43F7AB057D3AC3F0E3E694` | `362F4A0345977B16D04D92B5AFD37C82DEB2DC24DF43F7AB057D3AC3F0E3E694` | Already byte-identical; no patch needed. |

Do not include `http_server.py`, `project_config.py`, `commands.py`, or T08/T09-owned changes in the T16 patch. T06 broker and T09 cancel/completion acceptance remain owner gates. No files were staged or committed.

## Candidate verification receipts

- Scoped cross-process lease/fencing/crash command: `7 passed in 7.04s`.
- Broad candidate orchestration batch: `79 passed, 1 skipped, 1 deselected in 71.38s`, exit 0. Command is recorded in `T16-acceptance-matrix-v1.md`. Skip is symbolic-link creation (`WinError 1314`); deselection is T06-owned broker coverage.
- Separate candidate junction alias/rollback selectors: `2 passed in 0.22s`.
- No root test was run. Root patch checks above were read-only.

## Open gates

- Symbolic directory symlink remains `NOT TESTED` due Windows `WinError 1314`; junction coverage does not prove symlink semantics.
- T06 broker and T09 cancel/completion owner-specific tests remain excluded from candidate batch.
- Root service overlay still requires resolution of the `vision_contracts.image_dimensions` dependency by its owner.
