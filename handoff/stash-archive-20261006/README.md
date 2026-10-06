# Remaining 382 stash versions: preserved archive and integration handoff

Acceptance: **NOT COMPLETE — main-owner integration pending**. This packet archives originals and supplies bounded integration findings; it does not accept or implement source behavior.

## Ownership, pin and recovery

Only checkout: C:/Users/Adam/.codex/worktrees/t17-multimodal-resume/.local-ai-hub.
Branch: codex/sync-t17-multimodal-resume-20261006.
Entry HEAD: 84cb230b7164f7f25cf8463503acdc2ba0690917.
Current master resolved exactly once, then fixed: 7c932b6f31d81a5c6e331e7537d687fb0c8d9c12.
Owned refs: refs/checkpoints/t17-stash-archive-original-20261006 and refs/checkpoints/t17-stash-archive-master-20261006.
Earlier T17 sync/reconciliation refs and all original stash objects remain unchanged. New master merge had zero conflicts.
No root checkout access/writes, active source/test/tool edits, stash mutation, tests, repository imports, models, worktree/chat creation or push.
The stdlib-only archive processor reads Git objects/AST and extracts archive bytes; it never executes authored source, overlays, patches or test fixtures. Previous terminal-Hub native fallback remains authorized.
T09 owns 22 direct untracked priority versions; T17 browser owner handles 32 tracked/index versions. Neither scope was edited or consumed here.

## Complete occurrence and duplicate coverage

The immutable docs/STASH_COVERAGE_20261006.md queue was parsed and validated:
- 404 untracked manual-review versions; exactly 22 direct src/tests/tools/docs versions excluded into manifest.excluded_direct_versions.
- All remaining 382 occurrences represented, resolving original stash/base/index/untracked-parent SHAs, path, mode, original Git blob SHA and report line.
- 301 unique exact-content cohorts; 35 multi-occurrence cohorts. Deduplication saves 81 repeated copies.
- 299 ordinary cohorts / 380 occurrences archived byte-for-byte: 70,873,144 bytes.
- 2 raw stdout cohorts / 2 occurrences retained through immutable original Git object/parent references, not copied into the newly committed archive.
- Temporary source overlay prefixes were never an exclusion criterion. .t18-*, .tmp_dashboard_patch, verify-root-* and verify-sequential-* authored code is included.

manifest.json maps every occurrence to original bytes, SHA-256, cohort, archive path or explicit withholding reason. Original modes are recorded; inert archive filenames intentionally do not execute source or retain executable semantics.
originals/<originalGitBlobSHA>.original.txt contains exact original bytes. Local .gitattributes disables line-ending conversion and automatic diff payloads for these files. Staged/committed Git blob SHA must equal immutable original SHA.
Structured historical JSON receipts and source-linked CSV operation/owner/selector matrices were retained as historical documents, not acceptance claims or generic user datasets. Binary/credential/raw-runtime screening ran before copying; an additional literal-credential scan found no flags. This is a bounded source/privacy screen, not a security certification.

## Mapping and practical integration queue

hunk-map.json provides bounded metadata, original hunk line/header, target path, added/removed digests, missing-line previews and current anchor/enclosing symbol. Exact payload remains in originals.
41 base-to-source-overlay deltas are in deltas/, with immutable base/blob and delta digest references; they cover imports/module-level changes as well as symbols.
Machine statuses include 483 patch records with added lines present, 192 candidate missing hunks, 308 AST-equal changed symbols and 299 source-symbol differences. These counts are triage records, never missing-behavior totals.

Bounded priority findings and reviewed equivalents: integration-priorities.json.
1. **P1 — confirmed static missing functional hunk**, T09/main: TaskStore.list_tasks no-query branch excludes terminal rows with expired heartbeat. Original fb0af3a160164dd355c73678fe64c6511c24c37b (patch line 5) exempts COMPLETED/CANCELLED/FAILED/ABANDONED; current src/local_ai_hub/agent_tasks.py:1140-1142 lacks that exemption. Current query branch already preserves terminals at 1177-1191. Restore only this predicate/parameter intent after owner coordination; preserve bounded index/search and newer safety.
2. **P2 — unresolved contract**, T09/main: candidate bundle 31abc80258311cd2f7203ef9f3f1c1d799a5b32c:911 adds advance_mutation_generation, absent in current TaskStore. Decide current mutation/receipt invalidation ownership first; absence alone is not proof of a regression. Do not copy old checkpoint-based state mutation blindly.

Three missing original test names were checked against alternate current coverage. Classifier path-word rejection has the exact assertion in test_verification_evidence_classification_is_conservative; lint command proof intent exists with stricter binding tests; telemetry cursor forwarding has another HTTP test. These are preserved variants, not confirmed gaps.
Strict include_body parsing is already present with different annotations/layout. Trusted completion-root logic is present with newer task-created authority. Old project-config mock helper absence is not a missing product provider.
No blob mismatch is called obsolete. Other machine candidates remain explicitly unresolved for main-owner semantic review; archives and base deltas make that review reproducible without re-reading stashes.

## Runtime/privacy boundaries and actual checks

Withheld original stdout blobs:
- 105fec5f7cf7ed3c5572ae70bd14ab01f7eeb653 — queue-race-reduced-sequence-20261002.stdout.txt
- e718f3d3138bc88674d214ef6bd16049ed09e873 — minimal-2of25-sequence.stdout.txt
Their complete immutable stash/untracked-parent origins remain in manifest.json. No originals were deleted, rewritten, applied or dropped.
Existing .pytest_cache/.serena/bytecode/runtime state was preserved; no runtime outputs or user data newly committed.

Actual validation: queue counts, immutable parent mode/blob identity, Git SHA-1 blob reconstruction, SHA-256 content checks, byte equality after extraction, complete cohort occurrence accounting, current pinned-tree/source hunk review, bounded secret/data screens, staged-blob verification and Git ancestry/ref checks. No tests, builds, live model calls or imported repository modules.
One archive mapper pass was cancelled after inefficient anchor comparison; ordinary originals remained intact. The corrected mapper completed and emitted the final bounded ledger. No fixture/source was executed.
No fresh runtime/functional acceptance is claimed. Main integration and owner validation are required for completion.

## Handoff and exact scope

This README, archive processor, manifest, hunk map, decision ledger, 299 original cohort files and 41 derived patches are the only new owned files. Active src/tests/tools/browser_bridge tree must equal fixed master after merge.
Commit includes fixed-master merge plus this archival packet. Exact HEAD and post-commit integrity are reported in chat. Earlier receipts remain historical and have not been overwritten.
