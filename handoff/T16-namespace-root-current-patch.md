# T16 namespace consumer root-current patch

## Patch artifact

`T16-namespace-root-current.patch` was generated against root worktree `C:\Users\Adam\.local-ai-hub`. `git apply --check` passed against the current root worktree. The patch is not applied.

Patch SHA-256: `26C83E5B29E81EC4B8A011806D259399EB273E85CBAFC34616540D4ED7369DC8`.

Root-current predecessor SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `src/local_ai_hub/leases.py` | `BF56E69ABC46DCF1B9CC4B4778251618FD1EA243329D58E48BEFE833DB1AF1CB` |
| `src/local_ai_hub/work_fencing.py` | `10823461FBA3D0B9E2BA516E14E82EEE833315A00A2B11FCDEBDBBECD22CB9AA` |
| `src/local_ai_hub/work_orchestrator.py` | `BA24529B8F330248A7F1A8A14847244778B74CE2A201B5DA0D7A928367130093` |
| `src/local_ai_hub/project_config.py` | `4238B6A6DE1DE00F55F4679CE0DF7D431522EC1BAFABFA272258C1662F13F713` |
| `src/local_ai_hub/commands.py` | `1B27F83872D439B9167C9B2323BF4BE71279E688DF6094C002CA20934F761B67` |
| `tests/test_work_fencing.py` | `3CF82264563206B12AEA1CFFC0B78E12AE16D2FF650DE423730BE4A87A4A03D0` |
| `tests/test_work_handoff_acceptance.py` | `ACB5249AE641BB4FCF753819C6A2FEE3EDC16CA78818CFE5D66CF79CA0EC68B7` |

Regenerate patch if any predecessor hash changes. Root status before and after overlay verification showed no writes to these files.

## Symbol ownership

- T21 owns producer identity. Patch consumes existing `ProjectContext.coordination_id`; it does not recalculate Git/common-directory identity.
- T16 owns `ScopeLeaseStore` namespace conflict identity, `FencingLeaseStore` namespace and physical-resource fields, and `WorkOrchestrator` server-side context resolution and wiring.
- T06 owns `CommandBroker.set_fencing_lease_store` and broker transaction implementation. Patch leaves `commands.py` unchanged and records its current hash as the compatibility source.
- T16 owns the linked-worktree namespace matrix and broker compatibility test additions in `tests/test_work_handoff_acceptance.py`.

## Acceptance evidence

- Candidate suite: `63 passed, 1 skipped, 1 deselected` in 34.91s. Windows skipped directory-symlink case (`WinError 1314`). Deselect is the existing T06 real broker test.
- After adding attempt-scope inference used by T06 broker adapter, focused candidate fencing and two-process namespace selectors passed: `2 passed` in 3.73s.
- Root-current source overlay compatibility test passed: `1 passed` in 1.08s. It imported `CommandBroker` from the exact root-current `commands.py`, loaded namespace-aware `work_fencing.py` from overlay, verified canonical physical root, committed a real file write inside broker `commit_guard`, then rejected expired attempt without changing file.
- Root-current patch check passed. No root test suite ran and no root file changed.

## Apply condition

T20 root integration gate remains active. Apply only after gate release and predecessor hashes still match. If hashes drift, rebuild this patch from new root-current source; do not replace whole `commands.py` or `work_orchestrator.py` files.
