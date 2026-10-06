# T16 E2E recovery synchronization — 2026-10-06

## Committed handoff contract

- Assigned checkout only: `C:/Users/Adam/.codex/worktrees/t16-e2e-recovery-20261004/.local-ai-hub`.
- Branch: `codex/sync-t16-e2e-recovery-20261004-20261006`.
- Starting checkpoint: `80d2dcb555aa8663576fd7d3d864a667f0df49bd`.
- Original-head ref: `codex/checkpoint-t16-e2e-original-head-20261006`.
- All remaining ordinary untracked source/tests/docs and handoff artifacts committed before merge: `1240bce13b18eb14d1b0be359834b0989dc1c194`.
- Preservation ref: `codex/checkpoint-t16-e2e-all-source-20261006`.
- Master resolved once, at start: `f4c0387718d57383c2120ae0714583ad38aba6ed`, newer than the supplied `fbc965f5` observation.
- Pinned-master ref: `codex/checkpoint-t16-e2e-pinned-master-20261006`.
- Hub fallback authority: user reports prior terminal Hub failure and explicitly authorizes native checks without retries or polling. No new Hub result/evidence ID claimed.
- No root checkout edits, master ref writes, push, stash, reset, clean, packet cherry-pick, or new implementation work.
- `b9b6fa36` was not chased or applied. T14 context-pack behavior follows pinned master.

## Hunk decisions

Reviewed and resolved all 18 conflicted files. Removed duplicate methods/functions from automerge; retained newer master implementations.

- Retain T08 durable schema validation, recovery backups, non-destructive lease migrations, ordered event publication, payload versions, retention boundaries and bounded SSE replay.
- Retain master command identity/cache/environment isolation, Windows Job ownership, cleanup outcome reporting, rollback quarantine, cancellation deadlines and lifecycle fixes.
- Preserve T16 strict artifact/owner/execution-provenance verification. An `E...` evidence lookup alone does not satisfy a passed receipt.
- Preserve server-derived memory tenant/repository identity, persistent startup lock inode and worktree owner-ID forwarding.
- Preserve local fail-closed repair replay guard and regression tests, including unfinished fixtures.
- Preprocessing implementation, config/defaults, fencing implementation and `.gitignore` match pinned master. This preserves its preprocessing route; no live Gemini/model availability claim.
- CodeGraph backend remains absent. `.codegraphcontext` scan-ignore invariant remains present. No retired backend or older ignore file restored.
- Generator fallback policy kept strict; install prompt aligned. Update prompt already states the explicit terminal/non-retryable gate.

## Actual targeted checks

Native check owner: this integration task. Python bytecode and pytest cache disabled. TEMP/TMP and pytest basetemp restricted to ignored `state/t16-integration-checks/` inside assigned checkout. Some tests create/remove isolated Git fixture worktrees inside that temporary area; no production worktree added. No full release suite, deployment or model inference.

1. `python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=state/t16-integration-checks/pytest-1 tests/test_work_fencing.py tests/test_work_handoff_acceptance.py tests/test_agent_tasks.py tests/test_client_start_lock_owner.py tests/test_worktree_release_ownership.py tests/test_t16_cross_process_namespace_lease_recovery.py`
   Result: **77 passed, 13 failed, 1 skipped**, 41.47 seconds, exit 1.
2. `python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=state/t16-integration-checks/pytest-2 tests/test_agent_t08_durable_contract.py tests/test_agent_t08_migration_recovery.py tests/test_t06_durable_command_provenance.py tests/test_mcp_live_wire_schema.py tests/test_t19_codegraph_removal.py tests/test_sync_codegraph_scan_ignore.py tests/test_t21_project_config_preprocess.py`
   Result: **33 passed, 7 failed**, 31.96 seconds, exit 1. T08 durable/migration suites and scan-ignore invariant passed.
3. AST parsing: all 18 resolved Python files passed; subsequent changed-source/test check parsed 10 files, zero errors. No duplicate top-level functions/class methods in checked agent-events, agent-tasks, commands, client or process-utils modules.
4. `git diff --check`: passed. Preprocessing/config/defaults and `.gitignore`: no diff against pinned master.
5. Token-economizer setup script at the instructed `.agents` location was missing. No packages installed or PATH changed.

## Outstanding behavior and remaining checks

The branch is committed and structurally ready for integration review, **not test-green or release-accepted**. Existing and incoming fixtures still conflict with current contracts; no safety gates were weakened to make them pass.

- Work handoff: `test_real_command_broker_accepts_forwarded_work_attempt_fence` fails on `auxiliary action policy engine unavailable`; revalidate using an owned policy-enabled broker fixture.
- Agent tasks: 11 completion cases fail because fixtures change server-managed `repo_root` or create passed test receipts without `command_id`. Reconcile fixtures with trusted creation identity and broker-backed evidence, then rerun completion checks.
- Cross-process namespace recovery: hardcoded `leases.sqlite3` has no `leases` table at fixture update. Resolve actual current store location before expiration/reclaim/stale-commit acceptance.
- Durable command provenance: two cases have no minted receipt/artifact record. Revalidate execution/policy prerequisites and persisted provenance with real permitted command receipts.
- Live MCP handshake: input schema equality test does not account for master action-alias publication. Reconcile advertised versus registry schema contract; wire acceptance remains incomplete.
- CodeGraph absence test rejects the literal scan-ignore name in `repo_tools.py`, while the separate ignore-invariant test passes. Preserve ignore behavior; distinguish retired backend integration from exclusion strings.
- T21 Python fallback: missing `python_fallback_limit`, plus fixture `iter_files` does not accept `max_files` (two parametrizations). Coordinate remaining acceptance with owner; repository search implementation was not redesigned.
- Windows symlink privilege skip: real symlink normalization remains unverified.
- No live server/model/browser acceptance, full release suite or centrally arriving T16 packet acceptance performed.

## Files differing from pinned master

- `T16-client-start-lock-root-current.manifest.md`, `T16-client-start-lock-root-current.patch` (preserved artifacts only; patch not applied).
- `docs/INSTALL_PROMPT.md`, this integration note.
- `src/local_ai_hub/agent_tasks.py` (blank-line-only difference), `agent_verification.py`, `client.py`, `commands.py`, `generator.py`, `http_server.py`, `mcp_server.py`, `services.py`.
- `tests/test_agent_tasks.py`, `tests/test_worktree_release_ownership.py`.

Final handoff reports committed HEAD, clean tracked/index state, no unresolved paths and pinned-master ancestry after the merge commit is written. Ignored runtime check artifacts remain outside commits.
