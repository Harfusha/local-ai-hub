# T16 cross-process and T06 broker root-worktree overlay receipt v1

Root checkout: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Root remained read-only; tests ran only under `C:\Users\Adam\AppData\Local\Temp\t16-current-root-worktree-overlay-iar0xslc`.

Overlay reproduced tracked current root working-tree bytes plus current untracked T16 files. This includes integrated dirty T06 `commands.py`, T20 fixture files, root current T16 modules, and root `vision_contracts.py` needed by current `services.py`. It excludes `repository_test_impact.py` and unrelated repository-impact tests. Candidate `tests/test_work_fencing.py` was used because root version lacked physical-root subprocess selector. Imports were asserted from overlay paths before test launch.

## Module pins and origins

- `commands.py`: overlay `src/local_ai_hub/commands.py`, SHA-256 `3E348A6A955AA72E0ADBCCEAA94DC19ABED75B0F64B60FAAC701B741B81CED9F`
- `leases.py`: overlay `src/local_ai_hub/leases.py`, SHA-256 `362F4A0345977B16D04D92B5AFD37C82DEB2DC24DF43F7AB057D3AC3F0E3E694`
- `work_fencing.py`: overlay `src/local_ai_hub/work_fencing.py`, SHA-256 `4DA7E64370A1F08AED16F8C73C6DDA75C6A682F2A765839EC045FA2C356FD050`
- `work_orchestrator.py`: overlay `src/local_ai_hub/work_orchestrator.py`, SHA-256 `CBCCC1480BD9B9BF1BAB6EDCF41573E7390A61147F23A2946DE3D48BDDE78337`
- `services.py`: overlay `src/local_ai_hub/services.py`, SHA-256 `CCD292C8F91809B59BD3446D045CB550BABBD8CAEA86FAB4FCAA6D2E284564A0`
- `vision_contracts.py`: overlay `src/local_ai_hub/vision_contracts.py`, SHA-256 `0F42F51ED39C7FDBFF2A70D5BE08490407BFD02DD91198B2AE20B787DC971C5A`
- `http_server.py`: overlay `src/local_ai_hub/http_server.py`, SHA-256 `6F0B986255DD231F40761538227A66F0A9B97F7659064952593FB83B48130DB3`
- `project_config.py`: overlay `src/local_ai_hub/project_config.py`, SHA-256 `4238B6A6DE1DE00F55F4679CE0DF7D431522EC1BAFABFA272258C1662F13F713`

Test pins:

- `tests/test_work_fencing.py`: `022A63AC48C44473416FB5CEF252748111240538B5C06C05E5778D3175B4F31F`
- `tests/test_work_handoff_acceptance.py`: `247A15B6D6DEB7567B857205D90ABE894BC3F5D6B97C439E94C902B6BF11CB59`
- `tests/test_t16_cross_process_namespace_lease_recovery.py`: `B623D312916D8C9BED6B5DE90AB315D350FF8F9D21FE26EA1FEB035CD8B2F176`
- `tests/test_t16_explicit_write_set_lifecycle.py`: `64B82CAEF4279AD5B4FADBE4B075A65CCD78AE44FAB183A174BEB4B042CDC4B7`

## Exact command and result

From overlay root with `PYTHONPATH=<overlay>\src`:

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py::test_cross_process_contenders_get_one_overlapping_writer tests/test_work_fencing.py::test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens tests/test_work_handoff_acceptance.py::test_real_command_broker_accepts_forwarded_work_attempt_fence tests/test_t16_cross_process_namespace_lease_recovery.py::test_two_process_linked_worktree_lease_expiry_reclaim_rejects_stale_commit tests/test_t16_explicit_write_set_lifecycle.py::test_explicit_namespace_write_set_stale_owner_cannot_commit_after_sqlite_restart`

Result: `5 passed in 9.75s`, exit 0.

The receipt joins competing process lease claims, namespace linked-worktree collision/reclaim, persisted SQLite reopen and stale-owner refusal, physical root-scope token monotonicity, explicit write-set rejection, and actual `LocalAIServices.command` to integrated T06 `CommandBroker` fence forwarding/expiry rejection. The broker selector returns successful stdout for current attempt and refuses stale attempt after deterministic expiry. No `commands.py` edit occurred.

The namespace test fixture writes a test-only commit receipt; this does not prove production T07 journal coupling. This focused five-selector run does not cover directory-symlink traversal; Windows `WinError 1314` skip remains explicit. Previous portable overlay receipt covers broader orchestration: see `T16-root-current-portable-overlay-v2.md`.

Root tests, writes, staging, and commits were not performed. T20 owns root integration/acceptance.
