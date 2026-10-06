# T16 root-current portable overlay receipt v2

Root: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Root remained read-only.

Overlay: `C:\Users\Adam\AppData\Local\Temp\t16-root-current-portable-overlay-qc2d3bm5`. Started from `git archive HEAD`. Overlaid current-root T16 `leases.py`, `work_fencing.py`, `work_orchestrator.py`; copied root-current T20 fixture versions of `test_work_orchestrator.py` and `test_work_handoff_acceptance.py`; added T16-only tests `test_work_fencing.py`, `test_t16_terminal_rollback_preflight.py`, `test_t16_explicit_write_set_lifecycle.py`, `test_t16_lease_wait_namespace_isolation.py`, and the partial-apply selector. `commands.py` and `project_config.py` stayed at HEAD baseline. `repository_test_impact` was absent. A test plugin injected a stable coordination ID at WorkOrchestrator seam; it did not change product source.

For this combined receipt, `services.py` and `http_server.py` were restored to HEAD baseline to avoid pulling non-T16 module dependencies. Their T16 root-current deltas were not exercised here. Exact overlay imports:

- `work_fencing.py` origin under overlay, SHA-256 `4DA7E64370A1F08AED16F8C73C6DDA75C6A682F2A765839EC045FA2C356FD050`
- `work_orchestrator.py` origin under overlay, SHA-256 `CBCCC1480BD9B9BF1BAB6EDCF41573E7390A61147F23A2946DE3D48BDDE78337`
- `leases.py` origin under overlay, SHA-256 `362F4A0345977B16D04D92B5AFD37C82DEB2DC24DF43F7AB057D3AC3F0E3E694`
- HEAD baseline `services.py` SHA-256 `7A3B9C73073D47F26E55AF876B7F080565C32228A8E1AA281C442AB090777DF2`
- HEAD baseline `http_server.py` SHA-256 `4C10B31778BA89FA694C0029FC95B363AF7ACFFC4C2CACEB5E52CE4B9A9BFF80`
- excluded HEAD baseline `commands.py` SHA-256 `5E3FD81C4AB55633A165237AE5C828CA2B73ACE353DA403DB67C98C65128E1D3`
- excluded HEAD baseline `project_config.py` SHA-256 `582513C2DBAB8897C3767445698C8444DBF174501E3FD68EEA7019B6DF35D149`

## Combined portable receipt

Exact command, from overlay root with `PYTHONPATH=<overlay>\src`:

`python -B -m pytest -q -p no:cacheprovider -p t16_overlay_shim --tb=short tests/test_work_fencing.py tests/test_work_orchestrator.py tests/test_t16_terminal_rollback_preflight.py tests/test_t16_explicit_write_set_lifecycle.py tests/test_t16_lease_wait_namespace_isolation.py::test_legacy_wait_edges_migrate_to_namespace_inclusive_primary_key tests/test_work_handoff_acceptance.py -k 'not command_broker and not local_service and not compare_and_swap and not cancel and not completion_cas and not cancel_and_completion and not concurrent_continue'`

Result: `55 passed, 1 skipped, 8 deselected in 18.76s`, exit 0. Skip is Windows directory-symlink `WinError 1314`. Deselects include T06 broker/service selectors and T09 cancel/completion races.

Test file pins:

- `tests/test_work_fencing.py`: `022A63AC48C44473416FB5CEF252748111240538B5C06C05E5778D3175B4F31F`
- `tests/test_work_orchestrator.py`: `ABDA9C9A72F325E1B5534C2C0BD34C2482C2DB567E2AAC124A8C7F2D7DEDC724`
- overlay `tests/test_work_handoff_acceptance.py`: `A371B88E92FE84099F5AE65CF9B64422F3DF5BFA68F15511BD6A395A03C074C4`
- `tests/test_t16_terminal_rollback_preflight.py`: `041E3B08B3E2E53B9880781427C51C2E785B3D00B6A4B882D8D2B4D6E97B1403`
- `tests/test_t16_explicit_write_set_lifecycle.py`: `CA9021A1FC1B3619CC7FCE59A08C321354EDD39F576B7D991FF312D3C54B3A7A`
- `tests/test_t16_lease_wait_namespace_isolation.py`: `1375CE1218362BF08D540F3ECE3243322148E8A3C81E3C1DD2D74B1A8B3FD0F1`

An earlier collection attempt using root-current `services.py` with baseline `vision_contracts.py` stopped at `ImportError: cannot import name 'image_dimensions' from local_ai_hub.vision_contracts`. This integration dependency is outside T16 ownership. Combined receipt above uses baseline services/http; it does not clear that gate.

## Not covered in portable overlay

- T21 ProjectContext-derived linked-worktree namespace, HTTP lease routes, and namespace wait cleanup were excluded with T21 `project_config.py`; keep their candidate receipts separate.
- T16 root-current `services.py` and `http_server.py` integration were not exercised in combined receipt.
- T06 real broker bridge excluded.
- T09 cancel/completion race selectors excluded.
- Windows symlink behavior remains unverified: skip is not green.

## Post-integration gates

1. Resolve/compose `vision_contracts.image_dimensions` with its owner, then run root-current T16 service/orchestration/handoff selectors against exact integrated sources.
2. Run `tests/test_t16_project_namespace_leases.py`, `tests/test_t16_lease_wait_namespace_isolation.py`, `tests/test_t16_http_lease_routes.py::test_http_lease_routes_resolve_namespace_and_isolate_linked_worktrees`, and `tests/test_t16_cross_process_namespace_lease_recovery.py::test_two_process_linked_worktree_lease_expiry_reclaim_rejects_stale_commit` with T21 ProjectContext code integrated.
3. Run T06-owned `tests/test_work_handoff_acceptance.py::test_real_command_broker_accepts_forwarded_work_attempt_fence` only after broker bridge integration; keep ownership separate.
4. Run T09 cancellation/completion race selectors with T09 owner.
5. On Windows runner with directory symlink capability, require `tests/test_work_fencing.py::test_rooted_scope_resolves_symlink_alias_to_same_path` to report `1 passed`; skip leaves gate open.
6. Run final root-current T16 acceptance batch after integration; root writes and root tests remain T20-owned.

This receipt is isolated-overlay portability evidence, not root integration acceptance.
