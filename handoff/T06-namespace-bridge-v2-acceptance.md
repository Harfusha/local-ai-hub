# T06 namespace bridge v2 acceptance

Status: isolated root-current patch and focused acceptance receipt. No root files were written.

## Patch scope

`T06-namespace-bridge-v2-root-current.patch` changes only `src/local_ai_hub/commands.py`. It:

- resolves `coordination_id` from trusted `resolve_project_context(source, configured_state_dir(config))`;
- passes that same ID to the path lease and authoritative writer fence for transaction creation, imports, and journal recovery;
- fails closed when only one store supports namespaces or the project ID is missing;
- preserves compatibility when neither store API supports namespace arguments.

The patch is independent from the T09 receipt producer patch. T20 owns root integration.

## Focused acceptance

One test passed against a temporary copy of current root sources plus the T06 bridge patch. The test used the actual `/api/leases/claim_batch` HTTP route in one linked worktree, then called the real patched `CommandBroker` from a second linked worktree. The broker denied the overlapping write set before execution.

Module source origins for that run:

- `commands.py` preimage: copied from `C:\Users\Adam\.local-ai-hub\src\local_ai_hub\commands.py`, then patched only in the temporary overlay.
- `leases.py`, `work_fencing.py`, `work_orchestrator.py`, and `http_server.py`: copied from current root T16 v5 + HTTP v3 sources.
- Test: `tests/test_t06_project_namespace_bridge.py` from the T06 worktree.
- Temporary overlay was removed after the run. No Docker process started; test stubbed sandbox readiness and asserted lease denial before command execution.

Current source SHA-256 values:

- T16 `leases.py`: `362F4A0345977B16D04D92B5AFD37C82DEB2DC24DF43F7AB057D3AC3F0E3E694`
- T16 `work_fencing.py`: `4DA7E64370A1F08AED16F8C73C6DDA75C6A682F2A765839EC045FA2C356FD050`
- T16 `work_orchestrator.py`: `CBCCC1480BD9B9BF1BAB6EDCF41573E7390A61147F23A2946DE3D48BDDE78337`
- T16 HTTP v3 `http_server.py`: `6BA4B79AD0A7D06C11151E07E7261AFD9CAD515C1EF8FBA5A0DB0A34CEAA40CA`

## Root-current patch identity

- Root `commands.py` preimage SHA-256: `11887A31E422891DF1B29C7300AAC49B3FB57047343024ADE9493531B3AA2D0B`
- T06 patch SHA-256: `9DD78F09779131762CE581F862E2B6C6DAB83D1B44DAB5A913DFAFC6A457ED6C`
- Expected patched `commands.py` SHA-256: `39E92B34A7185C2DBC3F38BCF507627276B049BB9A5D145EAD7C9574A87D949E`
- `git apply --check` passed against the exact preimage in a temporary copy.

The root checkout was later observed at that expected namespace-bridge postimage. A separate composed producer handoff now targets that exact current source:

- `T06-T09-validation-receipts-v6-root-namespace-current.patch`
- Base SHA-256: `39E92B34A7185C2DBC3F38BCF507627276B049BB9A5D145EAD7C9574A87D949E`
- Patch SHA-256: `2BC2AAED85A83126906D0F347C25BFD059FFF816B413093D09E3242804D22982`
- Result SHA-256: `21E8F325B652ED338F30714EC0DD341B3A898A9D608814A62CAB86915BECC71C`
- `git apply --check` passed in a temporary copy of the observed root source.

Receipt contract and focused producer evidence are recorded in `T06-command-proof-contract-v1.md`. The composed producer test passed in a temporary overlay with current root package sources and the v5 T09 proof logic (`1 passed in 10.09s`). T20 remains the root integrator; these checks do not write or test the root checkout.

T20 still owns root integration and its registration batch. This receipt proves only the T06 namespace collision boundary; it does not replace broader T16 recovery or Docker runtime acceptance.
