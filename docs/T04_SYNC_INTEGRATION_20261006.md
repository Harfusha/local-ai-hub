# T04 committed checkout synchronization

Scope: existing `t04-integration/.local-ai-hub` checkout only. Companion
`t04-lock-recovery/.local-ai-hub` has its own branch and preservation commits.
Native fallback explicitly authorized after terminal Hub failure; Hub was not retried.
Delegation attempted but unavailable because the native agent limit was reached.
Token-economizer setup script was missing; no packages or PATH changes made.

## Preservation and commits

- Original HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`.
- Original checkpoint: `checkpoint/t04-integration-original-20261006` (pinned).
- Dirty source checkpoint: `checkpoint/t04-integration-dirty-20261006` =
  `398beaa7a4ccfd310677891125fa29f73198858d` (pinned).
- Branch: `codex/sync-t04-integration-20261006`.
- Pre-merge checkpoint includes all originally tracked changes and untracked
  source/tests under `src/local_ai_hub` and `tests` (33 files).
- Existing untracked handoff Markdown documents are committed with this note.
  Historical receipts remain historical, not current acceptance proof.
- Other artifact/patch/manifest files remain preserved in place, untracked.
  Runtime state, pytest temporary directories and caches are not staged.
- No stash, cleanup, hard reset, push, new checkout, or master ref writes.

## Conflict decisions

- Reviewed conflicting hunks independently; no whole-file ours/theirs checkout.
- Use master OS-held startup lock, PID creation identity and retry cooldown.
  Superseded T04 nonce/sidecar implementation survives in the checkpoint.
- Keep master cancellation, terminal/retryable flags, bounded startup waits,
  direct detached-child launch, process ownership and operational-mode module.
- Keep T04 tenant/root preflight, GET cancellation, retry deadline handling and
  in-process rejection normalization; remove duplicate cleanup/obsolete lock glue.
- Keep T03 command path hints already in master; no duplicate regression patch.
- Keep current HTTP server, preprocessing and operational-mode source from master.
  Gemini-related integration remains inherited. CodeGraph runtime removal retained.
- `/api/context/pack` source unchanged from master; T14 ownership respected.
- Resolve tests against current flags, command hints and OS-lock contract.
  Original superseded test variants remain recoverable in checkpoint history.

## Actual validation and remaining issues

- Initial targeted pytest: 113 passed, 5 failed, 1 skipped (13.20 seconds).
  Receipt: `artifacts/t04-sync-targeted-20261006.xml` (not committed).
- Four failures were old assertions/contracts; updated during integration.
- CodeGraph absence check fails on master's deliberate `.codegraphcontext`
  ignore-directory string in `repo_tools.py`; this is not a restored backend.
  Preserve master behavior; outstanding T19 contract disagreement.
- Follow-up targeted pytest: 98 passed, 6 failed (71.87 seconds).
  Receipt: `artifacts/t04-sync-followup-20261006.xml` (not committed).
  All four corrected assertions from the first run passed in this follow-up.
- Unfinished behavior/test compatibility, intentionally committed:
  - `test_async_task_submit_reuses_explicit_request_id`: Python parameter exists,
    generated public MCP schema lacks `request_id`; schema/docs parity unfinished.
  - `test_mcp_delegate_autostarts_owned_daemon_and_preserves_http_payload`:
    old fixture module lacks `operational_mode_gate_error` required by master.
    This fixture failure does not prove the installed Hub is down.
  - `test_local_ai_repo_context_forwards_guarded_pack_fields`: old test expects
    two HTTP calls, current T14 implementation makes one. No T14 redesign made.
  - `test_request_id_header_wins_over_conflicting_body_request_id`:
    old recovery stub returns None where current route requires a claim mapping.
  - Both `test_t04_candidate_start_lock_acceptance.py` cases still target removed
    `_live_start_lock` sidecar helper; superseded by master OS-lock design.
  - Initial CodeGraph absence assertion remains unresolved as described above.
- Windows directory-symlink test skipped because privilege was unavailable.
- No full release suite, deployment, live model quality, installed-daemon or
  cross-process production acceptance is claimed. Old receipts are not reused.
- Test side effects owned by this checkout under `artifacts/t04-sync-*` only;
  `PYTHONDONTWRITEBYTECODE=1`, plugin autoload/cache disabled, local basetemp.

## Final handoff

Source AST parsing passed for all 16 T04-changed Python files. Scoped whitespace
check against master passed with CRLF recognized (`core.whitespace=...cr-at-eol`).
Initial merge-range whitespace check reported inherited master CRLF/patch
whitespace; no unrelated formatting changes made.
Latest-master merges and final ancestry verified at handoff. Exact final HEAD
and changed-file list: `git rev-parse HEAD`, `git diff --name-only master HEAD`.
This note is itself part of the handoff commit.
