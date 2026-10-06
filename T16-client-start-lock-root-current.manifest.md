# T16 client start-lock import patch manifest

## Pinned root preimage

- Root: `C:\Users\Adam\.local-ai-hub`
- HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
- `src/local_ai_hub/client.py` preimage SHA-256: `4E250AD3496E665F428FAC5B0E231238AE71017ED9078C2682513932797CA632`
- `src/local_ai_hub/client.py` expected postimage SHA-256 after this patch only: `2A546D0B5C74FABA304242843F5AED53ED77F3FD5978A7AD38E0332F1F996FEE`
- `tests/test_client_start_lock_owner.py` preimage: absent
- `tests/test_client_start_lock_owner.py` postimage SHA-256: `4902C9712938A7D5C68E7416313AB01F442C0F5EE440637D0CC676D18BA003EA`
- Patch: `T16-client-start-lock-root-current.patch`
- Patch SHA-256: `5BE4957195BB68F5171FA8365241F7F6402901984D3AB6A722BB2504DBA9A5F7`
- `git apply --check` against pinned root passed; no root files changed.

## Root selectors after authorized integration

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short `
  tests/test_mcp_autostart_contract.py::test_daemon_off_concurrent_mcp_clients_share_cold_start `
  tests/test_mcp_autostart_contract.py::test_daemon_off_start_timeout_is_bounded_and_retains_cooldown_lock `
  tests/test_mcp_live_wire_schema.py::test_stdio_status_call_cold_starts_isolated_hub_and_cleans_up `
  tests/test_client_start_lock_owner.py
```

Not run on root by T16. Delegated root run before patch reported 72 passed, 4 failed; failures include three above with `NameError: process_identity is not defined`.

## Candidate receipt

Worktree: `C:\Users\Adam\.codex\worktrees\t16-e2e-recovery-20261004\.local-ai-hub`, detached HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short `
  tests/test_client_start_lock_owner.py tests/test_hubctl_start.py tests/test_client_transport.py `
  tests/test_worktree_discovery.py tests/test_work_orchestrator.py tests/test_work_handoff_acceptance.py `
  tests/test_work_fencing.py tests/test_t16_cross_process_namespace_lease_recovery.py `
  tests/test_worktree_release_ownership.py `
  -k "not coord_pubsub_poll_uses_after_seq_in_json_body"
```

Result: **93 passed, 1 skipped, 1 deselected in 28.58s**. Skip: Windows symlink privilege (`WinError 1314`). Deselection: unrelated pubsub selector failed in prior broader candidate run. New lock tests first reproduced missing `client.process_identity`, then passed after import fix.

Candidate `client.py` also contains a separate T16 worktree-release forwarding hunk; it is excluded from this immutable root patch. Patch changes only the import line and adds the two new tests.
