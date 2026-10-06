# T08 pinned synchronization — committed unfinished handoff

Scope: only C:/Users/Adam/.codex/worktrees/t08-agent-os/.local-ai-hub.
Branch: codex/sync-t08-agent-os-20261006. No root checkout edits, master ref writes,
push, stash, reset, clean, new worktree, installation or release suite.
Resolved merge commit: 93fd7626c7bc51aa4bceecf3dfbfe78af49a8371.
Post-merge gates: pinned master, original HEAD and dirty checkpoint are ancestors;
index and tracked worktree clean, no unresolved entries. 1118 paths differ from
pinned master, including preserved artifacts; 43 src/test files (+4133/-534 lines).
Final syntax/AST rerun inspected 43 paths, zero syntax failures.
User explicitly authorized native fallback after terminal Hub failure; no Hub retry.
Native subagent review was unavailable (thread limit); integration remained single-owner.
Token-economizer bounded slices and surgical apply_patch edits were used; its missing
ensure-tools script was not replaced with installation or PATH mutation.

## Preservation and pinned merge

- Original pre-dirty HEAD: 2b33602adef0d030fea66cdcc04ca742c60b2e32.
- Existing dirty checkpoint: 4ce893c1a957217756be3268116a72018223493c,
  codex/checkpoint-t08-agent-os-dirty-20261006 (unchanged).
- Premerge artifact checkpoint: 1926d7f36ea128be2e815e8c4a56165238cf7d11,
  codex/checkpoint-t08-agent-os-artifacts-20261006; preserved 1086 additional
  nonruntime source/test/doc/handoff/patch/receipt/snapshot files.
- Supplemental complete original-artifact snapshot:
  7153deb5fe0b5548b8992e3210ffe2cea72d4552,
  codex/checkpoint-t08-agent-os-all-20261006. Created after reconciliation via
  isolated index, parent 1926d7f3, preserving the original snapshot plus five
  initially ignored acceptance logs, not reconciled source.
- Pinned merge parent: b0779fc889309aa4d048c54f83dba4156d952051,
  actual master when this merge began. Master subsequently moved. User instructed
  not to chase it; root T05 fc950005 is NOT merged into this worktree.
- Runtime SQLite/DB/cache/test-temp and generated install metadata remain in place,
  excluded from commits. New pytest temp state is confined to
  handoff/.sync-runtime-tests; no runtime cleanup or relocation performed.
- Historical receipts/logs are preservation artifacts, not fresh acceptance proof.

## Manual reconciliation

38 conflicted files were reviewed by hunk; no whole-file ours/theirs replacement.
Kept T08 task memory adoption, physical-worktree identity and scoped provenance,
atomic memory compaction/events and rollback handling. Preserved master's newer
receipt ownership/generation/type/evidence binding, immutable project completion
configuration, ordered mutations/deletion selectors and trusted context identity.
Reconciled ancillary-only state layouts, lease_waits old/new key layouts/schema
hash and version bookkeeping, event-page dictionary/AgentEvent adapters, SSE
cursor initialization/dedup/deadline bookkeeping, and duplicate auto-merged methods.
Kept T03 bounded replay/page contract and safety policies. Kept master's optimized
context identity serialization despite an older T08 streaming expectation.
Gemini projection/canonical preprocessing is unchanged against the pinned parent;
CodeGraph removal remains. T14 /api/context/pack core was not redesigned; retained
trusted T08 context identity propagation. T09 overlaps belong to central integrator.

Root T05 fc950005 durable memory-event transaction, sanitization/corrupt-row bounds
and scoped memo deletion remain a later integration responsibility, not claimed here.
Both standalone transport tests copied from that revision are preserved in
tests/test_t08_sync_transport_remaining.py, with the 403 expectation unchanged.

## Actual targeted checks

All pytest commands used python -B -m pytest, -p no:cacheprovider,
PYTHONDONTWRITEBYTECODE=1, PYTHONPATH=src and TEMP/TMP inside the assigned
handoff/.sync-runtime-tests directory. These checks execute code and create only
worktree-local runtime test state; they are not a read-only audit.

1. Initial targeted batch: -q --tb=short --maxfail=10,
   --basetemp=handoff/.sync-runtime-tests/pytest-first; files:
   test_t08_sync_transport_remaining, test_t08_coordination_identity,
   test_agent_context_identity, test_agent_task_memory_adoption,
   test_agent_t08_live_order, test_agent_t08_event_page_snapshot,
   test_agent_t08_receipt_transaction, test_t08_http_memory_context_immutable.
   Result 10 failed, 37 passed, 21.79s; stopped at ten failures.
2. Intermediate selected transport/receipt/context/SSE follow-up:
   -q --tb=short --maxfail=10, pytest-final temp directory.
   Result 10 failed, 3 passed, 19.58s. Ancillary-layout and cursor initialization
   failures were subsequently reconciled; not final acceptance evidence.
3. Final reconciled batch: -q --tb=line,
   --basetemp=handoff/.sync-runtime-tests/pytest-reconciled:
   tests/test_t08_sync_transport_remaining.py
   tests/test_agent_t08_receipt_transaction.py::test_receipt_projection_helper_is_caller_transaction_atomic
   tests/test_t08_coordination_identity.py::test_http_context_ignores_client_coordination_identity
   tests/test_t08_http_memory_context_immutable.py
   tests/test_sse_events_stream.py
   Result 7 failed, 18 passed, 61.42s. Standalone no-evidence PASS rejection and
   transaction-atomic receipt helper passed. Two failures were a merged SSE test
   fixture missing its old stream_finishes observation; reconciled fixture keeps
   both master's finished_stream_request and original stream_finishes fields.
4. Only those two fixture-affected nodes rerun, -q --tb=line,
   --basetemp=handoff/.sync-runtime-tests/pytest-fixture:
   tests/test_sse_events_stream.py::test_sse_disconnect_is_recorded_as_failure
   tests/test_sse_events_stream.py::test_sse_stream_timeout_bounds_queue_wait
   Result 2 passed, 1.39s. No assertion/expectation changed.
5. Syntax/AST compile of changed src/tests Python paths via
   python -B handoff/t08-sync-static-check.py; no bytecode generation.
   Earlier run: 43 paths, zero syntax failures; inherited unchanged embeddings
   setter/property duplicate-name warnings are not merge-introduced functions.
6. git -c core.whitespace=cr-at-eol diff --check b0779fc8 -- src tests:
   PASS after EOF reconciliation. No full release suite, service deployment,
   browser acceptance, model calls or release verification performed.

## Unfinished behavior — deliberately committed

Latest reconciled batch has five remaining functional failures after the two
fixture failures passed their focused rerun. No broad green-suite claim:

- test_http_memory_delete_requires_verified_worktree_scope: DID NOT RAISE
  urllib.error.HTTPError; expected 403 retained. Root reports the same failure.
- test_http_context_ignores_client_coordination_identity: HTTP 400 instead of 404.
- test_memory_delete_route_passes_verified_repository_identity: HTTP 404 instead
  of 200; deleted=false, record not found.
- test_sse_stream_replays_all_pages_and_advances_cursor: replay uses 100-row
  bounded T03 pages (after_seq 0,100,200...) rather than old expected 0,1000.
- test_sse_stream_surfaces_retention_gap_before_kind_filtered_replay: expected
  gap event missing. Do not relax these expectations merely to make tests green.

Earlier batch failures not rerun after final reconciliation and therefore still
outstanding/unverified:

- test_stale_source_invalidation_uses_physical_worktree_root: unscoped get returns
  None under scoped identity policy; status access raises AttributeError.
- test_context_identity_streams_full_legacy_payload: old streaming JSONEncoder
  expectation conflicts with master's optimized json.dumps identity behavior.
- test_corrupt_record_and_deadline_fail_open_with_warning: expected
  memory_lookup_deadline_exceeded, got memory_context_unavailable.
- test_command_receipt_is_durable_and_allows_task_completion: publication_calls
  zero instead of one.
- test_receipt_persistence_failure_warns_without_overwriting_command_result,
  evidence and receipt variants: verification_receipt_warning missing.

Command cache filename/durable provenance split (.sqlite3 master versus original
producer .sqlite) needs integrator review. Archived test matrices and all other
unfinished snapshots are preserved, not executed or certified. Source safety
contracts inherited from pinned master do not prove current runtime acceptance.

Exact changes against pinned master are in t08-sync-changed-files-20261006.txt;
runtime preservation inventory is in t08-sync-runtime-preserved-20261006.txt.
