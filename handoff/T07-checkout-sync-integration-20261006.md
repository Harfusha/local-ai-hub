# T07 committed checkout synchronization — 2026-10-06

## Scope and preservation

- Assigned checkout: `C:/Users/Adam/.codex/worktrees/t07-idempotence-root-current-20261003`.
- Reused branch: `codex/sync-t07-idempotence-root-current-20261003-20261006`.
- Original source HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`, retained as parent of dirty checkpoint.
- Tracked dirty checkpoint: `c041d450a685c0c2f225270c7113c075aec585ae`, ref `codex/checkpoint-t07-idempotence-root-current-20261003-dirty-20261006`.
- Original untracked inventory contained exactly two relevant files: `handoff/T07-root-current-replay-classifier-tests.patch` and `handoff/T07-root-current-replay-classifier.receipt.md`. Both committed unchanged before merging at `062ebf1d`; additional checkpoint ref `codex/checkpoint-t07-idempotence-root-current-20261003-handoff-20261006`.
- No stash, reset, clean, new worktree/chat, push, dependency install, root checkout edits, or master-ref writes. No runtime database/cache staged. Existing ignored artifacts preserved.
- Native fallback explicitly authorized by user after terminal Hub failure; no Hub retry/poll. Exact prior terminal envelope was not available in this resumed turn; no evidence ID invented.
- Token-economizer setup script at the instructed `.agents/skills/token-economizer/scripts/ensure-tools.ps1` path was missing. No replacement installation attempted.

## Merge decisions

- Actual master was `382f33798bad6048cad8e4728151dcb654c0c39d`, beyond the user's earlier `fbc965f5` snapshot. Merge committed as `e88953cf`.
- During synchronization master advanced to `b0779fc889309aa4d048c54f83dba4156d952051`; second clean merge committed as `16db251f80e46d2b2e3df176ae1579026aab6c8a`.
- Final master advance `5e8424c46ab0368541f8683e73920fde77aba670` adds T04 integration records and preserved handoff overlays, with no `src/` or `tests/` changes against `b0779fc8`. Included by a third clean merge together with this updated note; targeted test input source remains unchanged.
- Manually reviewed conflicts in `commands.py`, `http_server.py`, and `test_mutation_replay.py`; resolved individual hunks, no whole-file ours/theirs operation.
- Preserve master fail-closed repair replay: only explicit `replay_safe=True` permits replay. Old default-validation-safe expectation survives in historical checkpoint/patch; active tests follow newer policy, including unclassified validation rejection.
- Preserve response headers/admin audit, recovery availability guards, bounded wait configuration, request-ID initialization/validation, operational-mode routes, and optional debug persistence isolation. Remove redundant second recovery claim and duplicate `hashlib` import produced by merge.
- Resolved production source and replay tests equal merged master byte-for-byte in Git. No new product fixes. `/api/context/pack` inherited from master; no T14 redesign.
- Master preprocessing implementation preserved unchanged. It describes Local AI idle GPU semantic-card generation; inspected `preprocess.py` contains no Gemini implementation and runtime Gemini matches found elsewhere concern agent configuration. New Gemini preprocessing cannot be certified present in this committed master; no implementation invented or outside-checkout dirty work imported. Integrator must reconcile separately if the intended Gemini change is still uncommitted elsewhere.

## Actual checks and limitations

- Native targeted command, once: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mutation_replay.py tests/test_rollback_cache_delete_failure.py tests/test_codegraph_package_policy.py tests/test_t19_codegraph_removal.py`, with process-local `PYTHONDONTWRITEBYTECODE=1` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.
- Exit 1: **98 passed, 1 failed in 15.97s**. Sole failure: `tests/test_t19_codegraph_removal.py::test_codegraph_is_absent_from_hub_runtime_configuration_and_telemetry`; `repo_tools.py` still contains `.codegraphcontext` in ignored-directory names. Package-removal tests passed; strict textual absence acceptance remains incomplete. No test/product adjustment made.
- Validation was side-effecting through pytest temporary fixtures, not a read-only audit. Main agent owned execution; default pytest temporary location was used, outside assigned checkout. This exceeded the literal write-only-checkout constraint for disposable test fixtures; no other checkout source was edited. No subsequent tests or cleanup attempted.
- `git diff --check` on merge resolutions and `git diff --check b0779fc8 HEAD -- src tests` passed. Final Git source equality against `5e8424c4` and diff check of the integration note also passed. Broad cached merge check against old branch HEAD emitted inherited CRLF/trailing-whitespace diagnostics from imported master docs/patches; no mass formatting performed. This is not a clean broad whitespace receipt.
- No full release suite, live Hub/model run, deployment, or Gemini runtime proof. Historical receipts remain historical; they do not establish current acceptance.
- Final handoff verifies master and checkpoint ancestry, no unresolved index entries, no remaining tracked/untracked source changes, and exact changed-path inventory. Final HEAD is reported by the completing chat; this note is committed in that HEAD.

## T06 overlap for main integrator

- `commands.py` is shared broker surface owned by T06 elsewhere. Preserve master task-owned worktree/write-set guards, authoritative attempt and writer commit fencing, monotonic recovery fencing, source/postimage verification, tenant/task/root provenance, receipt restrictions, health-aware cache reads, and unknown-outcome cache invalidation/incident policy together. T07 result adds no broker delta against merged master.
- Independent read-only source audit identified a possible POSIX deletion replacement race: after `postimage_still_matches()`, deletion uses pathname `os.unlink(leaf, dir_fd=parent_handle)`; existing `test_rollback_preserves_concurrent_replacement_when_removing_created_path` injects replacement after the final check. Static concern only; POSIX test not executed on this Windows checkout. T06/main integrator owns follow-up.

## Changed paths against merged master

- `handoff/T07-root-current-replay-classifier-tests.patch` — original historical patch, preserved unchanged.
- `handoff/T07-root-current-replay-classifier.receipt.md` — original historical receipt, preserved unchanged.
- `handoff/T07-checkout-sync-integration-20261006.md` — this integration note.

Synchronization is committed; product/release acceptance remains incomplete as recorded above.
