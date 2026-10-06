# T03 committed preservation addendum

This addendum supersedes the earlier decision to leave ordinary patch/JSON/overlay artifacts uncommitted. Synchronization is complete against the pinned master; functional acceptance remains partial as recorded in T03-sync-integration-20261006.md.

## Commit and ownership

- Branch: `codex/sync-t03-master-20261006`.
- Preservation commit: `f250e7429352db1a36b560fd4d3362d7b33ce1ec`.
- Exact-byte checkpoint: `codex/checkpoint-t03-original-artifacts-20261006` at that commit.
- Original source HEAD checkpoint: `codex/checkpoint-t03-original-20261006` at `ad622f8a90a81e349e94d3402f297f2995e733b2`.
- Pre-merge dirty source checkpoint: `codex/checkpoint-t03-dirty-20261006` at `3dc82bba6dcfb7653bb61fa1086af8194ead2aaa`.
- Master pinned at this clarification's start: `f8ba97fe9eafa38810dbbbc3c4184800da7bafcd`, ref `codex/checkpoint-t03-master-start-20261006`. Original synchronization started at `fbc965f5`; both are ancestors. No moving-master merge performed during this clarification. Orchestrator owns later moving-head integration.
- Writes stayed in assigned T03 checkout and its explicitly authorized Git preservation refs/objects. No product fixes, root/master writes, push, stash/drop/reset/clean, installation or new worktree/chat.

## Recoverable bytes

`handoff/T03-preservation-20261006.zip` contains 158 exact-byte snapshots: 77 ordinary artifact/source/test/document paths plus 81 nested Git snapshot metadata files. Original remaining artifacts were captured as observed at this clarification. Earlier source history remains in the original/dirty checkpoints; no claim is made that Git-normalized earlier checkpoint text reconstructs its former pre-filter working-copy bytes.

`handoff/T03-preservation-20261006.json` enumerates every archive entry, original relative path, byte length and SHA-256, plus archive SHA-256. Archive entries were hashed and compared with current original files; all 158 matched. Archive's raw Git object hash equals its committed blob hash, proving text normalization did not alter this byte-preserving checkpoint.

Remaining original handoff patches and JSON receipts, overlay source/tests/rejected patch, generated check-runner source and pytest receipt log were committed at ordinary paths. Nested `.git` metadata exists inside the archive, avoiding unresolved gitlinks or modification of those original snapshot repositories. Earlier historical Markdown handoffs were already committed and also captured in the archive.

To recover original bytes, extract selected entries from the checkpoint's ZIP into an explicitly chosen recovery directory. Do not overwrite live source or excluded runtime state implicitly. To verify the current originals, run `./handoff/Preserve-T03-OriginalArtifacts.ps1 -VerifyOnly` from the assigned checkout. This performs hashes only; it does not recreate the archive or restage files.

## Enumerated exclusions preserved on disk

`handoff/T03-preservation-excluded-20261006.json` lists all **885 exact excluded file paths**, byte lengths, SHA-256 and reasons. All were verified still present and byte-identical after preservation commit.

- 514 generated validation temporary/runtime/configuration files beneath `.t03-sync-checks/`: pytest-temp, pytest-followup, pytest-path-hints, state and local check configuration. The ordinary check.py and pytest.log are committed separately.
- 366 runtime/index/test cache files: `.pytest_cache/`, `.serena/`, and Python caches under src/tests/tools.
- 3 generated/user-local overlay configs: `.t03-main-preflight-overlay/candidate/config.toml`, `.t03-root-current-overlay/candidate/config.toml`, `.t03-root-current-overlay/preimplementation/config.toml`.
- 2 overlay runtime DBs: `.t03-main-preflight-overlay/candidate/state/adoption_metrics.sqlite3`, `.t03-root-current-overlay/candidate/state/adoption_metrics.sqlite3`.

`.gitignore` adds only explicit generated T03 test-temp directory rules. It does not hide ordinary handoffs, source or test artifacts. No excluded file was removed, moved, overwritten, archived into Git, or recreated.

## Checks and handoff

- Exact-byte archive/original verification: PASS, 158 files.
- Excluded on-disk hash verification: PASS, 885 files.
- Committed ZIP equals raw archive Git blob: PASS.
- Pinned master ancestry: PASS.
- Unmerged index entries: none.
- Tracked dirty files and ordinary untracked files: none.
- No source/product differences introduced versus previous handoff in src/, tests/, tools/. Preservation adds artifacts only; previous targeted test results and outstanding behavior remain unchanged. No tests rerun for this archival clarification.
- Preservation commit changes 57 files (ordinary paths, archive/manifests/helper and scoped gitignore). This addendum is a separate final documentation commit.

The final HEAD is the commit containing this addendum. Original source/checkpoint refs, all ordinary preservation files and the exact-byte archive are reachable from this branch. Later master movement remains for the orchestrator.
