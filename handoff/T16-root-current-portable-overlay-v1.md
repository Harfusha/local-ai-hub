# T16 root-current portable overlay receipt v1

Root: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Root remained read-only.

Overlay: `C:\Users\Adam\AppData\Local\Temp\t16-root-current-portable-overlay-qc2d3bm5`. Built from `git archive HEAD`, then replaced only T16 source paths with current-root copies and added T16 acceptance tests. Excluded dirty T06 `commands.py`, T21 `project_config.py`, and `repository_test_impact` files; those modules/files in overlay are HEAD baseline/absent. Overlay shim supplied stable coordination identity only at `WorkOrchestrator._coordination_id` because T21 producer is excluded. Linked-worktree ProjectContext and HTTP-resolver tests were not counted in this portable receipt.

## Current-root T16 source pins and origins

All source origins were under overlay `src/local_ai_hub`, confirmed at test launch.

- `leases.py`: SHA-256 `362F4A0345977B16D04D92B5AFD37C82DEB2DC24DF43F7AB057D3AC3F0E3E694`
- `work_fencing.py`: SHA-256 `4DA7E64370A1F08AED16F8C73C6DDA75C6A682F2A765839EC045FA2C356FD050`
- `work_orchestrator.py`: SHA-256 `CBCCC1480BD9B9BF1BAB6EDCF41573E7390A61147F23A2946DE3D48BDDE78337`
- `services.py`: SHA-256 `CCD292C8F91809B59BD3446D045CB550BABBD8CAEA86FAB4FCAA6D2E284564A0`
- `http_server.py`: SHA-256 `6F0B986255DD231F40761538227A66F0A9B97F7659064952593FB83B48130DB3`
- Excluded baseline `commands.py`: SHA-256 `5E3FD81C4AB55633A165237AE5C828CA2B73ACE353DA403DB67C98C65128E1D3`
- Excluded baseline `project_config.py`: SHA-256 `582513C2DBAB8897C3767445698C8444DBF174501E3FD68EEA7019B6DF35D149`

## Portable candidate test receipt against current-root T16 source

Exact command (from overlay root):

`python -B -m pytest -q -p no:cacheprovider -p t16_overlay_shim --tb=short tests/test_work_fencing.py tests/test_t16_terminal_rollback_preflight.py tests/test_t16_explicit_write_set_lifecycle.py tests/test_t16_lease_wait_namespace_isolation.py::test_legacy_wait_edges_migrate_to_namespace_inclusive_primary_key`

Result: `14 passed, 1 skipped in 3.45s`, exit 0. The skip is `test_rooted_scope_resolves_symlink_alias_to_same_path`: Windows `WinError 1314` prevented directory symlink creation. Skip is not acceptance.

Covered current root T16 fencing and token floors, terminal immutability, rollback hardlink/ancestor preflight, cross-process explicit-namespace stale-holder recovery, and lease-wait schema migration. Tests wrote only temporary directories.

## Collection blocker for wider orchestration suite

A separate broad collection attempt with root-current `services.py` plus HEAD-baseline unrelated modules failed before test execution:

`ImportError: cannot import name 'image_dimensions' from local_ai_hub.vision_contracts`

Root-current `services.py` SHA above imports that symbol; the required `vision_contracts.py` delta is outside T16 ownership and deliberately absent from overlay. Thus `test_work_orchestrator.py` and `test_work_handoff_acceptance.py` were not accepted from that failed collection. No tests were counted from failed collection. Add the owning dependency only after its owner/T20 permits a composed overlay or integration.

ProjectContext-derived linked-worktree namespace, HTTP routes, and namespace wait-edge selectors were also excluded because T21 `project_config.py` changes were excluded. Candidate receipts for those remain in `T16-acceptance-matrix-v1.md`, but they do not prove root-current integration.

## Post-integration gates for T20

1. Apply the root-current T16 patches with current preimage/hash checks; preserve excluded owner changes.
2. Run root-current T16 orchestration/handoff selectors after the `vision_contracts.image_dimensions` dependency is composed. Include `test_partial_git_apply_failure_restores_all_preimages_and_clears_journal`, terminal revival, restart recovery, retry/wait, and cancel race only with T09 owner approval.
3. Run ProjectContext-derived linked-worktree, HTTP route (`claim`, `claim_batch`, `list`, `waits`), and persisted lease-wait selectors after T21 identity code is integrated.
4. Run T06-owned `tests/test_work_handoff_acceptance.py::test_real_command_broker_accepts_forwarded_work_attempt_fence` after the broker bridge is integrated; do not merge its ownership hunk into T16 patch.
5. On a Windows runner with directory symlink capability, run `tests/test_work_fencing.py::test_rooted_scope_resolves_symlink_alias_to_same_path`. Require `1 passed`; any skip leaves gate open. Do not install packages to manufacture privilege.
6. Re-run full root-current T16 batch after integration; keep T06 broker selector and T09 completion gates separately attributed.

Root tests and writes were not performed. This overlay is portability evidence, not root integration acceptance.
