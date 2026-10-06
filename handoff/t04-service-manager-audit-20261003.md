# T04 service manager audit — 2026-10-03

Scope: T04 candidate/root-current reconciliation only. No root writes, no T03 proxy edits, no HUB calls, no tests run.

## Findings

T04 candidate `HubClient.ensure_server` already has bounded readiness, an OS-backed cross-process guard, nonce-scoped lock metadata and `process_identity` checks. Two `_live_start_lock` stale recovery cases need repair: an aged partial PID sidecar can pin the lock forever; a reused PID with mismatched creation identity falls through to `pid_alive` and can pin it again.

Current root has a different manager implementation: `_acquire_start_lock` writes only PID + timestamp and treats a live PID under the stale-age window as owner. It cannot identify PID reuse. Root patch adds process creation identity to new marker metadata and rejects known identity mismatches. Candidate helper patch preserves the candidate sidecar/guard architecture and fixes partial metadata + mismatch decisions.

## Prepared patches

All patch preimages remain unchanged; patches are not applied.

- Candidate helper: `artifacts/t04-startup-lock-candidate-20261003.patch` — SHA-256 `5C40FA32A2F7CB6D4DD4C441970B6DF877B061D9FA11E7D5FCD8B90CACF4256E`.
  - Candidate preimage `src/local_ai_hub/client.py`: `C7C5CCBEEC0E8E970AA13CCDC30BA8C452F8CF8DEAFD179ED4A83D4A103028E9`.
- Root-current manager: `artifacts/t04-root-current-startup-lock-20261003.patch` — SHA-256 `AF77C4024C08C667799010E90F9979404C5A50DF981E7193CEB39121DA73FB0E`.
  - Root base HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; current client preimage SHA-256 `C2CDC6EF131D9134D39251B7597DE84200DCD093118C9A2EC1CE863CB440D50D`.
- Root-current lock tests: `artifacts/t04-root-current-startup-lock-tests-20261003.patch` — SHA-256 `2353E7D8E93B7062CE42AF64734A8C7A2B201FB33A70D16AACFF2282A2B75EEA`. Adds marker identity, PID-reuse, same-owner, and mocked 30-client selectors.
- Candidate lock tests: `artifacts/t04-candidate-startup-lock-tests-20261003.patch` — SHA-256 `5E68FBF5E56BF7B7D8948F1331C087A0C00E0D323729EBEE0013D2005F6B2271`.

`git apply --check` passed for candidate source + test patches against T04 worktree and root-current source + test patches against current root. Root was not mutated. Candidate source was not mutated. Existing candidate 30-client draft in `tests/test_client_startup_resilience.py` AST-parses; SHA-256 `1F4FAC7CB7F396896FA12742C971EC4F7AF9504A72043D4A299A75A0E24D8ADC`.

## Tests for later serial release

Candidate/mock group: `tests/test_client_startup_resilience.py::test_30_concurrent_offline_clients_share_one_startup`, `::test_cross_process_offline_clients_share_one_unmanaged_autostart`, stale partial-sidecar/PID-reuse selectors, plus `tests/test_t04_candidate_start_lock_acceptance.py`.

Root/mock group: `tests/test_t04_root_start_lock_acceptance.py` (four selectors, including 30 concurrent clients).

Real process proof stays separate. Root currently has `tests/test_t04_mcp_status_actual_hub_child.py::test_first_mcp_status_starts_and_reaps_real_hub_entrypoint`. Candidate has `tests/test_t04_mcp_stdio_daemon_independent.py::test_stdio_handshake_starts_one_hub_for_simultaneous_cold_clients` and `::test_stdio_handshake_timeout_reaps_owned_hub_child`.

T01/orchestrator owns the current root validation slot. No test command was run here, per latest instruction.
