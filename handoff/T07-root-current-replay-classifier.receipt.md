# T07 root-current replay-safety patch receipt

Date: 2026-10-03 (Europe/Prague)

## Candidate worktree

- Path: `C:\Users\Adam\.codex\worktrees\t07-idempotence-root-current-20261003`
- Base: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` (detached worktree)
- Candidate edits: `src/local_ai_hub/commands.py` replay-safety gate; `src/local_ai_hub/http_server.py` request journal claim/replay dispatch; replay-policy tests in `tests/test_mutation_replay.py`.
- Candidate SHA-256 at receipt refresh 2026-10-04: `src/local_ai_hub/commands.py` `3A76FF0156E3DC3ECD46853F7907901EF5B54E6E0195D703E92340CAB25D655D`; `src/local_ai_hub/http_server.py` `7C680EE80924EA6E9DC8DCC79C9845290D93532BB2FC1D94133C37E1AC2A3361`; `tests/test_mutation_replay.py` `430B2310F9C2968B54B2608C1F34DD178D681A5EFFE839C907AC00EA36124A7D`.
- Candidate Git status: modified those two files only; handoff patch and receipt untracked. Base `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Focused test command was authorized once by T20 and run once; see execution receipt below.

## Root-current preimage

- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Before this task root already had dirty T07/shared files: `src/local_ai_hub/commands.py` SHA-256 `83CB8776B086167F1198F127E05C1271ABC9E742BA1C0684772357A0BF28A279`; `src/local_ai_hub/http_server.py` SHA-256 `C97AA26A4D84BE35FE7BFA1A18FDBB5AE9A5BA393F73D541D38E3F2DCB33D93D` (rechecked 2026-10-04); `tests/test_mutation_replay.py` SHA-256 `A55048B4884DC3994DBDA5D34206885188C841A51202D94541D9A9C1652856E5`.
- T06-owned dirty file `tests/test_rollback_cache_delete_failure.py` was untracked at baseline and untouched. Root files were not edited.
- Root `commands.py` already contains the replay-safety gate; candidate carries the same T07-owned hunk. Root-current patch therefore omits duplicate production code and adds only the two missing classifier regressions.
- Root-current test preimage SHA-256: `A55048B4884DC3994DBDA5D34206885188C841A51202D94541D9A9C1652856E5`.

## Contract preserved

- `validation` remains replay-safe by default; explicit classifier `replay_safe=False` blocks repair replay.
- Initial `outcome_unknown`, timeout, or in-progress state blocks replay and keeps `outcome_unknown` true.
- Request-ID dedupe, changed-payload conflict behavior, `RecoveryJournal`, bundle import, tool-accounting, and all `http_server.py` dispatch/routes are unchanged by this candidate patch.
- T06 `commands.py` and rollback-test hunks remain outside the root-current patch.

## Patch and checks

- Root-current patch: `handoff/T07-root-current-replay-classifier-tests.patch`.
- Patch SHA-256: `332B94CB6B2C6C7032A8D1BDAF8AB14371D3D7B4BA02A16EF299D2783706DE99`.
- `git apply --check --whitespace=error` against root-current passed. T20 then authorized and the exact test-only patch was applied; sole root path `tests/test_mutation_replay.py`, preimage `A55048B4884DC3994DBDA5D34206885188C841A51202D94541D9A9C1652856E5`, postimage `3979099CCE50BB8C3EADE79EF5C11933E7E90DDF90F69D57EAF68DF603478EFE`.
- Candidate `git diff --check` passed.
- T20 single-command GO: `python -m pytest -q tests/test_mutation_replay.py`.
- Execution ID: `526ae8341bd24b1aa724274575ed1e3a`; repository revision: `64ba008f98fa2f6001e8647d6de79ecfd8ea3e20a5e55dbf9c5e26bc16d684da`; exit code: `1`.
- Result: **41 passed, 14 failed**. Failures reported under `test_maintenance_get_routes_are_read_only` (first captured failure: GET must not optimize databases). No retry or second test run.
- Source diagnosis: candidate `tests/test_mutation_replay.py:591-617` expects each maintenance GET to return `405` with `Allow: POST`; `src/local_ai_hub/http_server.py:1794-1803` instead calls `optimize_databases`, `purge_stale_cache`, and `resolve_all_errors` from GET dispatch. This failure is a real mismatch in the candidate checkout, not stale test expectation and not caused by T07 replay-safety changes. Current shared root source has GET rejection guards at `http_server.py:2519-2527` and POST mutations at `:4487-4496`; candidate run therefore does not represent current root integration. HTTP route fix stays outside T07 scope. Full 14-failure list remains unavailable because execution artifact expired.
- Candidate input hashes pre/post are unchanged: `commands.py` `3A76FF0156E3DC3ECD46853F7907901EF5B54E6E0195D703E92340CAB25D655D`; `tests/test_mutation_replay.py` `430B2310F9C2968B54B2608C1F34DD178D681A5EFFE839C907AC00EA36124A7D`.
- No builds or dispatcher edits.

## Current root acceptance

- T20-authorized root command, run once: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mutation_replay.py`.
- Root: `C:\Users\Adam\.local-ai-hub`; HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; exit `0`; **75 passed in 6.01s**.
- Pre/post hashes unchanged: `commands.py` `83CB8776B086167F1198F127E05C1271ABC9E742BA1C0684772357A0BF28A279`; `http_server.py` `589C578EA5EB78C3192D3531FB776BF93FD703D9EFAB85B358B04A30891EFF24`; `tests/test_mutation_replay.py` `3979099CCE50BB8C3EADE79EF5C11933E7E90DDF90F69D57EAF68DF603478EFE`.

## Candidate targeted replay integration run

- Candidate HEAD equals root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`. Candidate is a valid Git worktree listed by `git worktree list`, but is not attached as a Codex managed artifact.
- One CPU-only command: `python -B -m pytest -q -p no:cacheprovider --tb=short` with 19 exact selectors: repair-loop default validation replay, explicit unsafe classifier, mutating-command skip, timeout/outcome-unknown skip; RecoveryJournal same-payload replay, changed-payload conflict, malformed IDs, tenant/identity/action binding, atomic claim, crash-unknown; same-request client retry, malformed client ID, coalesced timeout; HTTP changed-payload retry, malformed POST ID, five partial-publish cases; tool-accounting retry; confirmed restart non-replay.
- Exact selector set: `test_repair_loop_replays_validation_by_default`; `test_repair_loop_honors_explicit_replay_unsafe_classification`; `test_repair_loop_does_not_replay_failed_mutating_command`; `test_repair_loop_stops_after_timed_out_command_outcome_is_unknown`; `test_recovery_journal_replays_the_same_payload_after_response_loss`; `test_recovery_journal_conflicts_when_request_payload_changes`; `test_recovery_journal_rejects_invalid_request_ids_before_claim`; `test_recovery_journal_binds_id_to_tenant_identity_and_operation`; `test_recovery_journal_claim_is_atomic_across_clients`; `test_recovery_journal_process_crash_stays_explicitly_unknown`; `test_failed_partial_publish_is_replayed_without_reexecution`; `test_client_allows_explicit_retry_with_the_same_request_id`; `test_client_rejects_malformed_request_id_before_network`; `test_client_replay_safe_coalescing_timeout_returns_owner_request_id`; `test_http_retry_replays_outcome_and_rejects_changed_payload`; `test_post_rejects_malformed_request_id_before_mutation_dispatch`; `test_http_partial_publish_failure_replays_without_dispatching_twice` (5 parametrizations); `test_tool_accounting_retry_does_not_duplicate_event_batch`; `test_confirmed_restart_request_is_not_replayed`.
- Result: exit `1`, **31 passed, 9 failed in 3.22s**. Failures are `test_http_retry_replays_outcome_and_rejects_changed_payload`, `test_post_rejects_malformed_request_id_before_mutation_dispatch`, five parametrizations of `test_http_partial_publish_failure_replays_without_dispatching_twice`, `test_tool_accounting_retry_does_not_duplicate_event_batch`, and `test_confirmed_restart_request_is_not_replayed`.
- The initial candidate failure showed the missing recovery-claim dispatch: its POST path used prior lookup then dispatched, causing duplicate side effects. User authorized porting only T07-owned hunks while preserving T06 changes. Candidate now claims the request ID with tenant, identity, and payload before dispatch; validates malformed IDs; journals telemetry accounting and bundle import; and normalizes/echoes replay responses. No expectations changed.

## Candidate port and pending validation

- Added only T07 HTTP recovery/idempotency hunks in the valid linked candidate worktree. Root was not edited.
- Candidate `git diff --check -- src/local_ai_hub/http_server.py src/local_ai_hub/commands.py tests/test_mutation_replay.py` passed after the port.
- Current source/test hashes are recorded above. The full candidate selector later received a one-shot T20 GO; its incomplete broker receipt is recorded in the resume section below.

## Resume and root-current reconciliation — 2026-10-04

- Candidate Git root is a valid linked worktree at `C:\Users\Adam\.codex\worktrees\t07-idempotence-root-current-20261003`; candidate HEAD and root HEAD both remain `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`. No rebase needed.
- Candidate tracked dirty paths are only `src/local_ai_hub/commands.py`, `src/local_ai_hub/http_server.py`, and `tests/test_mutation_replay.py`; `handoff/` contains T07 receipts/patches. Root has extensive unrelated dirty paths; T07 made no root writes.
- Current candidate SHA-256: `commands.py` `3A76FF0156E3DC3ECD46853F7907901EF5B54E6E0195D703E92340CAB25D655D`; `http_server.py` `7C680EE80924EA6E9DC8DCC79C9845290D93532BB2FC1D94133C37E1AC2A3361`; `tests/test_mutation_replay.py` `430B2310F9C2968B54B2608C1F34DD178D681A5EFFE839C907AC00EA36124A7D`.
- Root-current hashes at reconciliation: `commands.py` `83CB8776B086167F1198F127E05C1271ABC9E742BA1C0684772357A0BF28A279`; `http_server.py` `5FE7F97420A1C22CEC4350F664046B70DA74333943FE14D7DA0AB02107EE0204`; `tests/test_mutation_replay.py` `3979099CCE50BB8C3EADE79EF5C11933E7E90DDF90F69D57EAF68DF603478EFE`.
- Root-current already contains `_claim_recovery`, `RecoveryJournal.validate_request_id`, bundle import fingerprinting, tool-accounting claims, and the general POST claim before dispatch. Existing root replay tests cover malformed request IDs and replay. No server patch is needed in root; applying candidate's stale whole-function delta would overlap newer shared route work. T07 therefore supplies a no-op root-current integration packet backed by source/path/hash evidence; root remains untouched.
- T16 coordination confirmed disjoint ownership: T07 does not touch `client.py` or `tests/test_client_start_lock_owner.py`.
- T20 authorized exactly one candidate command after T16 released its slot: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mutation_replay.py`. Preflight matched the three candidate hashes above. `local_ai_command(action=run)` returned only `success:false` with a truncated response envelope (`original_tokens=1157`, `requested_tokens=1200`, `returned_tokens=48`), no exit status or pytest summary. T20 then observed a live `pytest ... tests/test_mutation_replay.py` process (PID 37088, parent 22504); on immediate fresh census PID 37088 had exited, and parent 22504 was the Local AI Hub server. The command was not rerun or killed. Exact pytest result remains unavailable; do not claim pass/fail.
- `local_ai_command(action=stats)` reported `active_count=0` after the test process exited. No output artifact was recoverable through `local_ai_artifact`; that listing endpoint returned a terminal output-contract error. No retry authorized.
- `git diff --check` passed after the candidate port. Root stayed at the hashes above during this reconciliation.
- The mandated `ensure-tools.ps1` is absent from both `C:\Users\Adam\.agents\skills\token-economizer\scripts` and `C:\Users\Adam\.codex\skills\token-economizer\scripts`; no setup or PATH changes were made.
