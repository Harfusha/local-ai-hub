# Priority untracked stash reconciliation — 2026-10-06

Status: COMMITTED CANDIDATE / PARTIAL INTEGRATION. Not E2E acceptance. No assertion that all stashes are integrated.

## Ownership and immutable inputs

- Sole writable checkout: C:/Users/Adam/.codex/worktrees/hub-audit-repairs/.local-ai-hub.
- Existing branch: codex/sync-hub-audit-repairs-20261006. No new task, chat, branch, or worktree.
- Start/audit commit: ee12a4f41e3af06d24df803c9bf9cb4f39b12c6d. Owner packet 0e4c62c296d59bdd318342a094ebf0d64f2efe76 remains immutable.
- Master pinned exactly once: 47a1f32f44f0ab23a17b5d6cc21c16dfc2549a1a. Do not chase subsequent master changes.
- Clean no-conflict merge committed as 6b237f6fb507152a81a9fb338d2b3b10804daeed before candidate edits.
- refs/checkpoints/priority-untracked-original-20261006 -> ee12a4f41e3af06d24df803c9bf9cb4f39b12c6d.
- refs/checkpoints/priority-untracked-master-20261006 -> 47a1f32f44f0ab23a17b5d6cc21c16dfc2549a1a. Existing preservation refs were not changed.
- User supplied prior terminal Hub failure/native fallback authorization. No Hub retries/polls, model calls, stash mutation, root checkout edits, push, or full release suite.
- Native read-only Git inventory was followed by explicitly authorized scoped test/document edits and candidate commit; this entire workflow is not represented as a read-only audit.
- Subagent attempt failed at agent thread limit; no agent/task was created. Native review performed locally.

## Actual counts, not coverage assumptions

- 22 immutable untracked original variants; 3 exact pinned-master matches (T13, untouched); 19 mismatches/absences reviewed.
- 10 variants have an exact blob witness in captured checkpoint ancestry. This is preservation, NOT current integration. 12 have no exact path/blob witness in the searched checkpoint history.
- 85 existing-file current-master-to-original diff hunks individually dispositioned below; the 2 absent T09 files were separately integrated.
- 6 priority files changed/added: durable contracts, tenant-context isolation, HTTP memory identity, T09 completion matrix, real broker test, production-backed T09 config fixture.
- Durable additions: 49 top-level definitions = 47 historical test functions plus 2 helpers (corrects earlier approximate 48-def commentary). Includes the original cursor test also present in a separate T18 file; that file/source was not edited.
- All 45 stash entries unchanged byte-for-byte in git stash list format %gd<TAB>%H<TAB>%P<TAB>%s; captured preservation refs all unchanged.

## Integrated candidate

- Restored original real broker positive project receipt, private environment digest, configured command binding, --help no-receipt, and generic replay rejection. Assertions retained; real project configuration and broker used. Temporary fencing wrapper was removed after proving it mishandled CommandInvocation; the final real broker needs no fixture bypass.
- Restored T09 fixture interface using production ProjectConfigError/resolve_project_context. Historical sys.modules replacement, fake ProjectSettings and manufactured config digest are not used.
- Restored all missing durable functions separately after hunk review: schema backups/WAL, event-page snapshot/gaps/replay, blackboard CAS, memory/task/receipt rollback, swarm CAS/idempotency, pubsub retention/overflow, legacy database preservation, and lease migration contracts.
- Adapted only current event-page serialization (dict seq), empty-new-stream sentinel 0 versus retained/error None, length-prefixed memory stream identity and scoped memory lookup. Sequence, gap, projection, rollback and tombstone assertions remain exact.
- Cancellation replay repeats the same expected_version; a changed request explicitly must report idempotency_conflict. This retains original retry intent without weakening master CAS request binding.
- Tenant context tests now exercise BOTH public record seeding and original projection seeding. Original foreign-tenant exclusion and unscoped-global assertions retained; no guard disabled.
- HTTP original rootless/root-bound versus unowned-global distinctions, canonical race injection, foreign delete denial, matching-tenant delete and foreign promote/quarantine negative branches restored. Master forged promotion and deleted-record replay guards retained.
- T09 completion matrix read-only validate_completion/state/events checks and configured receipt/environment preflight restored; repository revision checkpoint and structured configured-command hash adapted to production config. Synthetic artifacts still do not establish actual command execution provenance.

## Actual validation

Final frozen-source command (no cache provider; PYTHONDONTWRITEBYTECODE=1):

~~~text
python -B -m pytest -q -p no:cacheprovider tests/test_t09_t06_v6_real_broker.py tests/test_agent_t08_durable_contract.py tests/test_agent_memory_context_tenant_isolation.py tests/test_agent_memory_http_identity.py tests/test_t09_http_task_completion_matrix.py --disable-warnings --tb=short
~~~

Result: **19 failed, 67 passed in 134.38s**, exit 1. Breakdown: broker 1 passed; durable 60 passed/2 failed; tenant context 6 passed/1 failed; HTTP memory 5 failed; T09 matrix 11 failed.

Standalone real broker also passed: 1 passed in 17.02s. Earlier diagnostic durable run: 53 passed/9 failed. Intermediate combined run: 55 passed/23 failed in 95.84s; files changed during that diagnostic run, so its line references are not final-source evidence. Final command above ran without target-source edits until completion. Final EOF-only whitespace cleanup has no executable effect.

Runtime databases, subprocess smoke project and pytest temporary state were created under C:/Users/Adam/AppData/Local/Temp/pytest-of-Adam, not committed. Pre-existing .sync-checks and handoff runtime artifacts stayed untouched/untracked. No model/benchmark/release command executed. No tests run for retained-only/T13 paths; equivalence dispositions there are source evidence, not runtime acceptance.

## Explicit missing integration / owned blockers

1. AgentOS memory writer: test_memory_append_result_error_rolls_back_projection fails at agent_memory.py:909 -> publish([appended.event]) with AppendResult(error) and event=None; raises AttributeError instead of rejecting append before projection/publication. Caller/source is outside the 22 paths. Do not patch it here. Original rollback assertion remains active.
2. AgentOS/lease schema owner: test_scope_leases_migrate_into_versioned_agent_state_database fails closed at agent_events.py:554 for table lease_waits after ScopeLeaseStore migration. Historical preservation fixture and current component schema need owner reconciliation. Neither lease nor T18 source edited.
3. Memory retrieval owner: test_find_for_context_without_tenant_returns_only_tenantless_global returns additional repository/task tenantless records. Exact original singleton expectation retained. Query-memory-scope/root unknown writer not touched.
4. T05/T13 trusted HTTP fixture integration remains incomplete: all 5 HTTP tests receive 403 before legacy route expectations. Current master derives root tenant from trusted principal/allowed roots and rejects spoofed header/body tenant (see unchanged shared runtime security tests); historical arbitrary X-LocalAI-Tenant/payload identities cannot become authority. Missing work is a trusted principal/root-bound fixture and corresponding original isolation cases, not removal of auth guards. Newly restored foreign promote/quarantine branches are present but not reached before earlier failure. Historical successful payload approver=user promotion is intentionally incompatible with master forged-approval guard.
5. T09 matrix fixture integration remains incomplete: 2 nominally valid memory cases fail validate_completion; 3 memory-only cases fail command receipt preflight (test/lint unsatisfied); 6 receipt-negative cases receive trusted-transport 403 instead of expected receipt-gate 400. Need broker execution provenance plus trusted principal/root fixture; never fabricate a trusted execution record or alter expected_success to get green. Positive direct real broker path passed, but does not prove HTTP completion.
6. verification_rules original literal current_revision=revision forwarding cannot be inserted: current TaskStore.complete signature has no such keyword. Existing project rules checkpoint repository_revision before completion and real broker test demonstrates that route. Exact original API forwarding needs owner TaskStore decision outside allowed edits; no unsupported keyword or removal of memory audit/empty-criteria path was added.

No E2E receipt, shared-runtime lifecycle acceptance, or complete stash integration claimed. These are committed unfinished tests/fixtures under explicit user policy; failures are not xfailed, skipped or hidden.

## Immutable blob and checkpoint-history evidence

Method: git ls-tree -r -z pinned master; git cat-file blob original OID; git diff --unified=3 masterBlob originalBlob. For each path git log --format=%H across the captured unique preservation checkpoint tips, then rev-parse commit:path and blob comparison. A witness commit was verified ancestor of its listed captured ref. Absence means no exact witness in this bounded captured ancestry inventory, not obsolescence. Current integration is judged separately by hunks/tests.

| Priority path | Original blob | Pinned master blob | Exact original checkpoint-history witness |
| --- | --- | --- | --- |
| tests/test_http_code_find_symbol_include_body.py | c0ab390b999ff0aff5c0a97cd1e2a60761633aab | c0ab390b999ff0aff5c0a97cd1e2a60761633aab | 38967ac0cea211113927bb7584cf9271a7412a48 @ refs/checkpoints/priority-untracked-master-20261006 |
| tests/test_shared_runtime_security_lifecycle.py | 8a7f697a0fb2409af9abd78284f4798190e4340c | 8a7f697a0fb2409af9abd78284f4798190e4340c | 38967ac0cea211113927bb7584cf9271a7412a48 @ refs/checkpoints/priority-untracked-master-20261006 |
| tools/resolve_hub_pids.py | b7f86a3bcaaaec2c0c04fffe995ce765940e6709 | b7f86a3bcaaaec2c0c04fffe995ce765940e6709 | 38967ac0cea211113927bb7584cf9271a7412a48 @ refs/checkpoints/priority-untracked-master-20261006 |
| src/local_ai_hub/verification_rules.py | e510187ba595aeec524a9ed7da39414035579e84 | fe87ca5eed1d98997cee842df18d29a7a7d813c8 | none found |
| tests/t09_project_config_test_fixture.py | 2ab857e51e4af3dc617b22f4e9a7a00a9b58ea0c | ABSENT | none found |
| tests/test_agent_t08_crash_after_commit.py | 2169a202ac97b5af036ce71b9d9f0a257a82ffae | a66cb7db9b073aa494e18382f2ad649e58db1bb2 | none found |
| tests/test_agent_t08_durable_contract.py | 9dd0826ed4b8c5acc903854ac8069c121ef9d819 | 5d0947642aca8f8759a8673713ea02180848128e | none found |
| tests/test_agent_t08_live_order.py | 683ce7bc0e6057263a93c8ceca3b04448cdb61a6 | 462e3877fe28d45e13709ebeb0bc783ede897e79 | none found |
| tests/test_project_memory_audit_completion.py | 2b9fbb7e1b0f1a945ba0b1e4b55782970f35ffc8 | 526b3f63ce88c962207467ac66b5ef066fd1759c | none found |
| tests/test_t09_http_task_completion_matrix.py | f9e3532f214fe0ba63f28107b8ee680026b656de | 47c5029a056a7b78ff7635a9d820b9672778de45 | none found |
| tests/test_t09_http_task_completion_persisted_receipts.py | 1a54d3c5e1e43a7f2bdcac1f1778e59c1d51fb0f | eab57884f63e7a5094843fdc305963b4cf0825b1 | none found |
| tests/test_t09_t06_v6_real_broker.py | 36a1c68a5c8293340b16b8d0ca0da33d4e671d41 | ABSENT | none found |
| tests/test_agent_memory_context_tenant_isolation.py | f1ad7866d9a7ea217fb69d89b34a93b94e985047 | 9dddfb6d48bbbf8217cbe951fa0701d701099b33 | df9850131a79191c5a860a1d231d3acd867869db @ refs/checkpoints/hub-audit-repairs-pinned-master-20261006 |
| tests/test_agent_memory_http_identity.py | a1479b01dc906adf4e4ba51801dffc4990247c3e | 45f7dc6cbfb5775e307b09dc369d0043f9febe8c | df9850131a79191c5a860a1d231d3acd867869db @ refs/checkpoints/hub-audit-repairs-pinned-master-20261006 |
| tests/test_t05_agent_state_migrations.py | e0628cb18078eb692e38ad7439e99c50c41aeabe | eeb7b150a183bfda7856867835c478667c4de8ca | df9850131a79191c5a860a1d231d3acd867869db @ refs/checkpoints/hub-audit-repairs-pinned-master-20261006 |
| tests/test_t05_memory_delete_artifacts.py | e017133351ef4f47122c1aa074861f41fbaacca0 | 5d6c2f8e234969dc1ee83749bea312ddc4fa5bb1 | df9850131a79191c5a860a1d231d3acd867869db @ refs/checkpoints/hub-audit-repairs-pinned-master-20261006 |
| tests/test_t05_memory_fts_atomicity.py | 4b5dc725d14af6889603e45ec3945a1ccfcda8b2 | df3d46b9620d106bfeb8000f0ad1532a87b769d8 | df9850131a79191c5a860a1d231d3acd867869db @ refs/checkpoints/hub-audit-repairs-pinned-master-20261006 |
| tests/test_http_route_operation_acceptance.py | 09789024dbe196f2e5110558ec7a1e8cadc9767e | d70e89817a5546f7704d4b9105ce935359c7950f | none found |
| tests/test_mcp_command_operation_acceptance.py | ad5c9104e687971a7d46fe04fd4f03970fb1d887 | 1cd5b7e17f1a91c833447093ab13292550b3f97c | none found |
| tests/test_rag_work_operation_acceptance.py | e61c8afc45fe1103891343b3688cbaf2bdeaaf3a | 464cc300ef85307a525d41d0269ce808707bcf5f | none found |
| tests/test_ollama_gaming_mode.py | 5e4fe2d0bb8894fe4ee6767b7842bb295c868086 | fc77416e98d78001342299cb05effea884a00a37 | 6ab3f97cb36ee9d22419a9b42a5243f46651121a @ refs/checkpoints/hub-audit-repairs-pinned-master-20261006 |
| tests/test_t12_llama_model_inventory.py | 6b41d2b5246b65b6d1aa2bb125e5fb5b287dc070 | fce8147f68e079bc46dc49d87e6b6b350048237f | 6ab3f97cb36ee9d22419a9b42a5243f46651121a @ refs/checkpoints/hub-audit-repairs-pinned-master-20261006 |

## Per-hunk dispositions

Hunk coordinates below are **pinned master -> original stash**, not the candidate diff. RETAIN/EQUIVALENT means inspected current behavior/test intent is already present or stronger, not that checkpoint existence proves integration. MIXED/BLOCKED identifies unresolved pieces; original expectations are recoverable using listed immutable blob/U-parent, and incompatible fragments are archived below.

### tests/test_http_code_find_symbol_include_body.py

Original stash 75a8ff394d29fb0ad76cd6e73ab2111956b9658d; untracked parent eab68c48b6f90c1b404919d137ca0b92db19701c; blob c0ab390b999ff0aff5c0a97cd1e2a60761633aab.

EXACT CURRENT MASTER: untouched T13 integration, not merely preservation.

### tests/test_shared_runtime_security_lifecycle.py

Original stash 75a8ff394d29fb0ad76cd6e73ab2111956b9658d; untracked parent eab68c48b6f90c1b404919d137ca0b92db19701c; blob 8a7f697a0fb2409af9abd78284f4798190e4340c.

EXACT CURRENT MASTER: untouched T13 integration, not merely preservation.

### tools/resolve_hub_pids.py

Original stash 75a8ff394d29fb0ad76cd6e73ab2111956b9658d; untracked parent eab68c48b6f90c1b404919d137ca0b92db19701c; blob b7f86a3bcaaaec2c0c04fffe995ce765940e6709.

EXACT CURRENT MASTER: untouched T13 integration, not merely preservation.

### src/local_ai_hub/verification_rules.py

Original stash 16269603f281615ba125f5c80cc38c04a7acca98; untracked parent b1c61ebb03082b189d4647b1c62602575a9e598c; blob e510187ba595aeec524a9ed7da39414035579e84.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -9,7 +9,6 @@ from typing import Protocol | RETAIN: ProjectSettings typing/import remains; deleting it adds no stash behavior. |
| @@ -256,9 +255,6 @@ def complete_task_with_project_rules( | REJECT: deleting the pre-mutation memory audit weakens completion safety. |
| @@ -278,32 +274,6 @@ def complete_task_with_project_rules( | RETAIN: current empty-criteria completion context path; removing it loses newer master behavior. |
| @@ -355,4 +325,5 @@ def complete_task_with_project_rules( | BLOCKED-EXACT: TaskStore.complete has no current_revision keyword. Current rules checkpoint repository_revision before complete; broker regression exercises this path. Direct original forwarding needs owner TaskStore API reconciliation, outside this scope. |

### tests/t09_project_config_test_fixture.py

Original stash 16269603f281615ba125f5c80cc38c04a7acca98; untracked parent b1c61ebb03082b189d4647b1c62602575a9e598c; blob 2ab857e51e4af3dc617b22f4e9a7a00a9b58ea0c.

ABSENT -> ADAPTED: original public fixture functions restored against production module. Unsafe synthetic config/module internals archived below.

### tests/test_agent_t08_crash_after_commit.py

Original stash 16269603f281615ba125f5c80cc38c04a7acca98; untracked parent b1c61ebb03082b189d4647b1c62602575a9e598c; blob 2169a202ac97b5af036ce71b9d9f0a257a82ffae.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -1,17 +1,11 @@ | RETAIN: current receipt crash helpers/imports and dict/dataclass event adapter. |
| @@ -42,8 +36,8 @@ os._exit(74) | ADAPTED-IN-MASTER: event kind assertions use _event_field; identical crash durability intent. |
| @@ -112,129 +106,6 @@ os._exit(74) | REJECT: original deletes newer receipt projection/task/event hard-crash atomicity coverage. |

### tests/test_agent_t08_durable_contract.py

Original stash 16269603f281615ba125f5c80cc38c04a7acca98; untracked parent b1c61ebb03082b189d4647b1c62602575a9e598c; blob 9dd0826ed4b8c5acc903854ac8069c121ef9d819.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -1,10 +1,11 @@ | RETAIN: Path/receipt artifact imports from master; historical formatting is inert. |
| @@ -31,6 +32,343 @@ from local_ai_hub.services import LocalAIServices | INTEGRATED: schema preservation, quarantine and six event-page tests restored; dict event serialization/current empty cursor sentinel adapted without relaxing sequence/gap assertions. |
| @@ -51,6 +389,8 @@ def test_event_insert_failure_does_not_advance_cursor_or_survive_restart(tmp_pat | RETAIN: formatting-only whitespace addition. |
| @@ -107,54 +447,11 @@ def test_append_in_transaction_preserves_caller_rollback_and_strict_replay(tmp_p | REJECT: deletion of newer rollback/publication checks is not missing behavior. |
| @@ -173,29 +470,8 @@ def test_append_in_transaction_rejects_connection_without_caller_transaction(tmp | REJECT: deletion of newer caller-transaction coverage is not missing behavior. |
| @@ -224,6 +500,8 @@ def test_ordered_event_publication_rejects_uncommitted_and_rolled_back_events(tm | RETAIN: formatting-only whitespace addition. |
| @@ -263,6 +541,159 @@ def test_duplicate_replay_rebuilds_cursor_from_stream_high_water(tmp_path): | INTEGRATED: blackboard CAS/idempotency, database mismatch and projection rollback functions restored; current task tests retained. |
| @@ -287,6 +718,8 @@ def test_task_transition_append_result_error_rolls_back_projection(tmp_path, mon | RETAIN: formatting-only whitespace addition. |
| @@ -341,6 +774,8 @@ def test_task_transition_cas_has_one_winner_and_one_conflict(tmp_path, monkeypat | RETAIN: formatting-only whitespace addition. |
| @@ -352,8 +787,7 @@ def test_verification_append_result_error_rolls_back_receipt_projection(tmp_path | REJECT: original removes trusted artifact fixture from receipt fault injection; keep current receipt validation. |
| @@ -371,6 +805,28 @@ def test_verification_append_result_error_rolls_back_receipt_projection(tmp_path | INTEGRATED: blackboard retry/idempotency collision test restored. |
| @@ -382,8 +838,7 @@ def test_verification_receipt_task_projection_and_events_rollback_together(tmp_p | REJECT: original removes trusted artifact fixture from joint receipt/task rollback; keep current guard. |
| @@ -421,14 +876,15 @@ def test_verification_receipt_task_projection_and_events_rollback_together(tmp_p | MIXED: keep master's trusted task and artifact setup, preserving receipt/task rollback and unknown-task rejection. |
| @@ -447,28 +903,778 @@ def test_passed_receipt_for_unknown_task_persists_without_task_projection(tmp_pa | INTEGRATED/MIXED: all remaining original missing pubsub, memory, swarm, database preservation and lease tests restored, plus helpers. Retain master's unknown-task receipt guard. CAS replay now repeats identical expected_version and explicitly rejects a changed request. |

### tests/test_agent_t08_live_order.py

Original stash 16269603f281615ba125f5c80cc38c04a7acca98; untracked parent b1c61ebb03082b189d4647b1c62602575a9e598c; blob 683ce7bc0e6057263a93c8ceca3b04448cdb61a6.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -1,24 +1,12 @@ | RETAIN: newer blackboard/memory/swarm imports, event adapter and publication helpers. |
| @@ -96,14 +84,14 @@ def test_concurrent_event_appends_publish_in_committed_sequence_order(tmp_path, | REJECT: original removes receipt writer case from task ordering parametrization. |
| @@ -123,15 +111,6 @@ def test_task_event_commits_share_append_publish_order_lock(tmp_path, monkeypatc | REJECT: original removes ordered_event_publication tracking. |
| @@ -171,7 +150,7 @@ def test_task_event_commits_share_append_publish_order_lock(tmp_path, monkeypatc | ADAPTED-IN-MASTER: dict/dataclass payload adapter preserves observed committed event values. |
| @@ -179,8 +158,6 @@ def test_task_event_commits_share_append_publish_order_lock(tmp_path, monkeypatc | REJECT: original removes receipt writer branch. |
| @@ -203,7 +180,6 @@ def test_task_event_commits_share_append_publish_order_lock(tmp_path, monkeypatc | REJECT: original removes publication-order invocation assertion. |
| @@ -294,189 +270,3 @@ def test_ordered_event_publication_serializes_caller_owned_batch(tmp_path, monke | REJECT: original deletes newer memory/blackboard/swarm ordering and forged/duplicate/out-of-order publication guards. |

### tests/test_project_memory_audit_completion.py

Original stash 16269603f281615ba125f5c80cc38c04a7acca98; untracked parent b1c61ebb03082b189d4647b1c62602575a9e598c; blob 2b9fbb7e1b0f1a945ba0b1e4b55782970f35ffc8.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -5,7 +5,6 @@ from pathlib import Path | RETAIN: MemoryKind required by actual memory fixture. |
| @@ -31,16 +30,6 @@ def test_project_completion_rejects_skipped_memory_without_not_used_reason( | RETAIN: actual stale memory creation supplies stronger end-to-end input than synthetic state. |
| @@ -52,17 +41,17 @@ def test_project_completion_rejects_skipped_memory_without_not_used_reason( | RETAIN: current generated memory context and warning assertion; do not replace immutable context with synthetic checkpoint. |

### tests/test_t09_http_task_completion_matrix.py

Original stash 16269603f281615ba125f5c80cc38c04a7acca98; untracked parent b1c61ebb03082b189d4647b1c62602575a9e598c; blob f9e3532f214fe0ba63f28107b8ee680026b656de.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -11,10 +11,11 @@ import pytest | INTEGRATED: CompletionGateError/environment binding imports; retain real production config resolver. |
| @@ -151,6 +152,7 @@ def test_task_completion_http_receipt_and_memory_matrix( | ADAPTED: real fixture interface now exists, but no module replacement is necessary here. |
| @@ -170,7 +172,8 @@ def test_task_completion_http_receipt_and_memory_matrix( | INTEGRATED: retain full resolved project_context for configured receipt preflight. |
| @@ -181,6 +184,7 @@ def test_task_completion_http_receipt_and_memory_matrix( | REJECT: raising=False could hide a missing memory-adoption API; current required monkeypatch remains strict. |
| @@ -201,11 +205,15 @@ def test_task_completion_http_receipt_and_memory_matrix( | INTEGRATED/MIXED: repository revision is checkpointed, memory audit retained; immutable creation-time memory_context is not rewritten. |
| @@ -250,6 +258,48 @@ def test_task_completion_http_receipt_and_memory_matrix( | INTEGRATED: read-only completion/state/event assertions and configured receipt preflight restored. Structured configured-command digest reconciled with production resolver. Current execution-provenance/trusted transport remain required; failing cases are not waived. |

### tests/test_t09_http_task_completion_persisted_receipts.py

Original stash 16269603f281615ba125f5c80cc38c04a7acca98; untracked parent b1c61ebb03082b189d4647b1c62602575a9e598c; blob 1a54d3c5e1e43a7f2bdcac1f1778e59c1d51fb0f.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -1,28 +1,29 @@ | RETAIN: actual broker-based receipt fixture and real project config, not historical replacement module. |
| @@ -49,38 +50,63 @@ def test_http_task_complete_uses_persisted_tenant_scoped_receipts( | RETAIN: actual project command executes and persisted receipt supplies revision; historical synthetic receipt would bypass broker provenance. |
| @@ -169,6 +195,7 @@ def test_http_task_complete_uses_persisted_tenant_scoped_receipts( | REJECT: replacement project-config module remains unnecessary and omits production guards. |

### tests/test_t09_t06_v6_real_broker.py

Original stash 16269603f281615ba125f5c80cc38c04a7acca98; untracked parent b1c61ebb03082b189d4647b1c62602575a9e598c; blob 36a1c68a5c8293340b16b8d0ca0da33d4e671d41.

ABSENT -> INTEGRATED: original complete test body retained; only production fixture interface import/invocation added. Final real broker passes.

### tests/test_agent_memory_context_tenant_isolation.py

Original stash 4948724725da96c9141da6d7ae83d9fbf1d9536c; untracked parent 875b6da8ad28a2121488f5a91a8e1d2c7a98466e; blob f1ad7866d9a7ea217fb69d89b34a93b94e985047.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -61,8 +61,7 @@ def test_find_for_context_filters_explicit_foreign_tenant_for_repository_and_glo | INTEGRATED: both original direct projection seed and master public record path parametrized; exact foreign-tenant exclusion assertions retained. |
| @@ -107,8 +106,7 @@ def test_context_compiler_filters_foreign_tenant_before_returning_memory(tmp_pat | INTEGRATED: both seed modes exercised for context compiler; foreign filtering and unscoped exclusion unchanged. |
| @@ -157,8 +155,7 @@ def test_task_create_and_resume_exclude_same_root_foreign_tenant_memory(tmp_path | INTEGRATED: both seed modes exercised for task create/resume; cross-tenant memory assertions unchanged. |

### tests/test_agent_memory_http_identity.py

Original stash 4948724725da96c9141da6d7ae83d9fbf1d9536c; untracked parent 875b6da8ad28a2121488f5a91a8e1d2c7a98466e; blob a1479b01dc906adf4e4ba51801dffc4990247c3e.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -12,8 +12,6 @@ from contextlib import closing | RETAIN: pytest import needed by newer tombstone rejection test. |
| @@ -46,10 +44,17 @@ def test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope(tm | INTEGRATED: distinguish root-bound global record from unowned shared global. |
| @@ -101,8 +106,17 @@ def test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope(tm | INTEGRATED: rootless lookup denial and unowned shared lookup assertions. |
| @@ -157,7 +171,7 @@ def test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope(tm | INTEGRATED: canonical path comparison for identity-race injection. |
| @@ -175,13 +189,13 @@ def test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope(tm | INTEGRATED: inspect preserved projection identity after rejected stale delete rather than unauthorized public lookup. |
| @@ -191,7 +205,166 @@ def test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope(tm | MIXED: scoped tombstone lookup integrated; moved unscoped functions already exist. Reject original successful payload-forged promotion and replay success; keep current 403 and deleted-record ValueError assertions. |
| @@ -279,14 +452,32 @@ def test_http_memory_get_and_mutations_bind_transport_tenant_and_project_identit | MIXED: scope-selectable test seed restored; positive promote/quarantine stand-in methods are not needed for current real store. Positive payload approver=user cannot establish trusted approval. |
| @@ -472,13 +663,18 @@ def test_http_memory_get_and_mutations_bind_transport_tenant_and_project_identit | RETAIN/BLOCKED: historical direct SQL retention check could not replace current caller contract without trusted-identity fixture review. Existing assertion retained, not made permissive. |
| @@ -490,10 +686,81 @@ def test_http_memory_get_and_mutations_bind_transport_tenant_and_project_identit | MIXED: original foreign promote/quarantine negative assertions restored. Historical successful payload-based promotion/quarantine requires trusted principal fixture reconciliation; do not relax current trusted approval. Positive caller delete still needs protocol integration. |
| @@ -582,16 +849,8 @@ def test_http_memory_public_identity_blocks_spoofed_origin_and_foreign_queries(t | REJECT: deleting master promotion_candidate loses spoofed approval regression. |
| @@ -620,28 +879,6 @@ def test_http_memory_public_identity_blocks_spoofed_origin_and_foreign_queries(t | REJECT: deleting explicit forged-promotion 403 guard weakens security. |
| @@ -778,12 +1015,17 @@ def test_http_memory_public_identity_blocks_spoofed_origin_and_foreign_queries(t | RETAIN/BLOCKED: current preserved record assertion remains; trusted scoped lookup fixture must be reconciled before changing it. |
| @@ -794,165 +1036,31 @@ def test_http_memory_public_identity_blocks_spoofed_origin_and_foreign_queries(t | MIXED: foreign transport delete denial and matching tenant delete restored. Moved existing unscoped tests retained with master trusted-approval/tombstone guards. |

### tests/test_t05_agent_state_migrations.py

Original stash 4948724725da96c9141da6d7ae83d9fbf1d9536c; untracked parent 875b6da8ad28a2121488f5a91a8e1d2c7a98466e; blob e0628cb18078eb692e38ad7439e99c50c41aeabe.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -1,7 +1,6 @@ | RETAIN: hashlib used by newer incident schema variant tests. |
| @@ -20,36 +19,12 @@ from local_ai_hub.agent_context import ContextCompiler | REJECT: original deletes trusted receipt artifact helper and leases import/newer component tests. |
| @@ -79,15 +54,12 @@ def _seed_state(db_path): | RETAIN: trusted artifact backed migration receipt; provenance formatting is equivalent. |
| @@ -137,7 +109,7 @@ def _assert_state_survives(db_path, task, event, memory): | RETAIN: trusted artifact required to prove durable receipt still verifies after migration. |
| @@ -161,7 +133,7 @@ def _make_historical_v0(db_path, event): | EQUIVALENT: adjacent Python string literals produce identical ALTER TABLE SQL. |
| @@ -209,7 +181,7 @@ def test_unversioned_current_schema_migrates_with_verified_backup_and_restart(tm | EQUIVALENT: adjacent Python string literals produce identical DROP COLUMN SQL. |
| @@ -254,9 +226,6 @@ def test_historical_schema_version_migrates_and_preserves_legacy_event_versions( | REJECT: removing sparse event version row-count assertion weakens migration preservation proof. |
| @@ -342,99 +311,18 @@ def test_unsupported_newer_schema_version_fails_closed_byte_for_byte(tmp_path, u | RETAIN: read-only preflight, verified recovery backup, shm/component/sparse metadata tests are stronger than historical replacement. |
| @@ -518,7 +406,7 @@ def test_missing_required_projection_schema_fails_closed_and_preserves_wal_and_s | RETAIN: current explicit no-migration-applied message; both variants assert fail-closed, file retention and valid backup. |
| @@ -651,8 +539,8 @@ def test_migration_backup_timeout_fails_closed_before_database_mutation(tmp_path | EQUIVALENT: split ALTER TABLE literals compile to identical schema changes. |
| @@ -749,119 +637,3 @@ def test_backup_timeout_bounds_sqlite_busy_wait(tmp_path, monkeypatch): | REJECT: original deletes newer ignored-column and scope-column incident migration coverage. |

### tests/test_t05_memory_delete_artifacts.py

Original stash 4948724725da96c9141da6d7ae83d9fbf1d9536c; untracked parent 875b6da8ad28a2121488f5a91a8e1d2c7a98466e; blob e017133351ef4f47122c1aa074861f41fbaacca0.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -14,19 +14,16 @@ def test_scoped_delete_purges_fts_and_embedding_artifacts(tmp_path): | RETAIN: public record creates event and searchable projection; original private seed bypasses writer integration. |
| @@ -98,8 +95,8 @@ def test_replaying_record_after_delete_does_not_restore_memory_or_fts(tmp_path): | REJECT: successful replay after deletion contradicts current fail-closed tombstone; retained non-restoration and explicit ValueError guard. |
| @@ -134,30 +131,26 @@ def test_delete_cleanup_failure_rolls_back_memory_and_search_state(tmp_path, mon | RETAIN: public record-based rollback fixture verifies writer/search integration, not private projection bypass. |
| @@ -170,7 +163,7 @@ def test_delete_cleanup_failure_rolls_back_memory_and_search_state(tmp_path, mon | ADAPTED-IN-MASTER: cursor 2 includes recorded event plus marker; cursor 1 assumed private seeding. Atomic rollback assertion retained. |

### tests/test_t05_memory_fts_atomicity.py

Original stash 4948724725da96c9141da6d7ae83d9fbf1d9536c; untracked parent 875b6da8ad28a2121488f5a91a8e1d2c7a98466e; blob 4b5dc725d14af6889603e45ec3945a1ccfcda8b2.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -51,7 +51,6 @@ def test_record_update_fts_write_failure_rolls_back_durable_record_and_preserves | EQUIVALENT: blank line only. |
| @@ -66,14 +65,6 @@ def test_record_update_fts_write_failure_rolls_back_durable_record_and_preserves | RETAIN: master additionally snapshots event cursor; original removal adds no FTS rollback behavior. |

### tests/test_http_route_operation_acceptance.py

Original stash a9d199006a82f2448f348cc5ec5717257e58ee91; untracked parent 4021e040601d6aa2350137fe0254190045b2a7f0; blob 09789024dbe196f2e5110558ec7a1e8cadc9767e.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -85,21 +85,11 @@ def test_http_get_agent_state_events_forwards_stream_cursor_and_limit( | ADAPTED-IN-MASTER: paginated event_page dict carries cursor/gap metadata instead of legacy events-only stub. |
| @@ -113,7 +103,7 @@ def test_http_get_agent_state_events_forwards_stream_cursor_and_limit( | ADAPTED-IN-MASTER: success/events equality preserves original payload intent while allowing required page metadata. |
| @@ -124,8 +114,8 @@ def test_http_get_agent_state_tasks_forwards_filters_and_serializes(running_http | ADAPTED-IN-MASTER: current list_tasks forwards query alongside original filters. |
| @@ -141,7 +131,7 @@ def test_http_get_agent_state_tasks_forwards_filters_and_serializes(running_http | ADAPTED-IN-MASTER: expected call includes query; other original filter values retained. |

### tests/test_mcp_command_operation_acceptance.py

Original stash a9d199006a82f2448f348cc5ec5717257e58ee91; untracked parent 4021e040601d6aa2350137fe0254190045b2a7f0; blob ad5c9104e687971a7d46fe04fd4f03970fb1d887.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -80,28 +80,22 @@ def test_mcp_command_auto_fix_forwards_bounded_repair_policy(monkeypatch: Any, t | RETAIN: master accounts second bounded telemetry call; primary repair-policy arguments remain asserted. |
| @@ -315,30 +309,6 @@ def test_mcp_command_mock_server_start_uses_dedicated_endpoint_and_port(monkeypa | EQUIVALENT: stop mock-daemon test moved, not missing. |
| @@ -371,3 +341,27 @@ def test_mcp_command_speculative_lint_submits_bounded_paths_and_job_identity( | EQUIVALENT: same stop mock-daemon definition appears at earlier location in master. |

### tests/test_rag_work_operation_acceptance.py

Original stash a9d199006a82f2448f348cc5ec5717257e58ee91; untracked parent 4021e040601d6aa2350137fe0254190045b2a7f0; blob e61c8afc45fe1103891343b3688cbaf2bdeaaf3a.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -22,7 +22,6 @@ class _Backend: | RETAIN: accounting reporter stub isolates RAG backend forwarding test; removing it restores no behavior. |
| @@ -30,7 +29,6 @@ def _enable_rag(monkeypatch: Any, backend: _Backend) -> None: | RETAIN: accounting reporter stub isolates work backend forwarding test; original backend arguments remain asserted. |

### tests/test_ollama_gaming_mode.py

Original stash 4e48862b9a0e2664e4ed1f83911b9d9feaa24e10; untracked parent 88f1297cd3be3e3796a3a181c73dc649d98b2dbb; blob 5e4fe2d0bb8894fe4ee6767b7842bb295c868086.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -174,7 +174,7 @@ def test_pause_unloads_every_loaded_model_without_loading_models( | EQUIVALENT: three identical /api/generate literals equal list multiplication; unload count/order test remains. |

### tests/test_t12_llama_model_inventory.py

Original stash 4e48862b9a0e2664e4ed1f83911b9d9feaa24e10; untracked parent 88f1297cd3be3e3796a3a181c73dc649d98b2dbb; blob 6b41d2b5246b65b6d1aa2bb125e5fb5b287dc070.

| Hunk | Decision / behavioral reason |
| --- | --- |
| @@ -4,7 +4,6 @@ from contextlib import nullcontext | RETAIN: pytest import needed by deadline regression. |
| @@ -75,23 +74,6 @@ def test_force_fresh_model_info_ignores_cached_empty_snapshot(monkeypatch) -> No | REJECT: original deletes newer no-HTTP-after-deadline test; cache/fresh inventory tests already integrated. |

## Restored durable definition provenance

Every entry below originates in blob 9dd0826ed4b8c5acc903854ac8069c121ef9d819; no new feature implementation. Existing master functions/guards remain.

| Definition | Original lines |
| --- | --- |
| test_durable_schema_mismatch_backups_and_preserves_original | 37-54 |
| test_durable_schema_mismatch_retains_original_when_backup_fails | 57-78 |
| test_durable_schema_mismatch_backup_includes_committed_wal_sidecar | 81-103 |
| test_disposable_derived_cache_quarantines_and_rebuilds | 106-120 |
| test_event_page_reports_empty_retention_gap_and_future_cursor | 123-186 |
| test_event_page_reports_gaps_inside_page_in_sequence_order | 189-217 |
| test_event_page_uses_one_snapshot_while_cleanup_commits | 220-292 |
| test_event_page_advances_cursor_past_trailing_gap_after_events | 295-318 |
| test_event_page_error_is_stable_and_preserves_input_cursor | 321-342 |
| test_event_page_replays_more_than_default_page_without_gaps | 345-369 |
| test_blackboard_expected_version_has_one_winner_and_one_conflict | 546-566 |
| test_blackboard_idempotency_key_binds_expected_version | 569-589 |
| test_swarm_rejects_state_store_on_different_database | 592-605 |
| test_blackboard_event_failure_rolls_back_projection | 608-633 |
| test_blackboard_append_result_error_rolls_back_projection | 636-650 |
| test_memory_append_result_error_rolls_back_projection | 653-675 |
| test_swarm_append_result_error_rolls_back_projection | 678-694 |
| test_blackboard_retry_is_idempotent_and_rejects_key_collision | 810-827 |
| test_schema_type_and_incomplete_group_mismatches_backup_without_repair | 907-934 |
| test_missing_memory_projection_with_durable_events_requires_recovery | 937-963 |
| test_missing_task_projection_with_durable_events_requires_recovery | 966-989 |
| test_agent_event_queue_overflow_emits_replayable_gap_marker | 992-1008 |
| test_pubsub_replays_after_restart_and_rejects_idempotency_collision | 1011-1041 |
| test_durable_pubsub_poll_preserves_event_page_failure | 1044-1055 |
| test_pubsub_live_overflow_sends_gap_marker | 1058-1067 |
| test_services_pubsub_uses_app_owned_durable_store | 1070-1083 |
| test_verification_change_and_outcome_rows_rollback_with_events | 1086-1114 |
| test_expired_memory_delete_and_event_are_atomic | 1117-1149 |
| test_blackboard_delete_projection_and_event_share_transaction | 1152-1175 |
| test_swarm_expected_version_allows_one_parallel_step | 1178-1207 |
| test_swarm_verification_failure_rolls_back_step_without_receipt | 1210-1245 |
| test_swarm_cancel_is_atomic_cas_and_idempotent | 1248-1275 |
| test_duplicate_swarm_cancel_retries_pending_lease_release | 1278-1295 |
| test_relation_event_failure_rolls_back_relation_projection | 1298-1314 |
| test_compaction_event_failure_rolls_back_digest_sources_and_relations | 1317-1361 |
| _seed_legacy_agent_state | 1364-1373 |
| _durable_rows | 1376-1386 |
| test_agent_state_filename_migration_backs_up_and_preserves_durable_records | 1389-1403 |
| test_agent_state_filename_migration_preserves_committed_wal_records | 1406-1430 |
| test_agent_state_filename_migration_interrupted_copy_keeps_source_and_backup | 1433-1454 |
| test_agent_state_filename_migration_is_idempotent_when_files_match | 1457-1468 |
| test_agent_state_filename_migration_adopts_legacy_data_over_empty_target | 1471-1484 |
| test_agent_state_filename_migration_conflict_preserves_both_histories | 1487-1510 |
| test_agent_state_filename_migration_detects_legacy_writer_after_cutover | 1513-1531 |
| test_agent_blackboard_legacy_database_merges_and_retries_idempotently | 1534-1565 |
| test_agent_blackboard_migration_rejects_legacy_writer_after_cutover | 1568-1601 |
| test_cache_rebuild_does_not_erase_agent_state_records | 1604-1616 |
| test_scope_leases_migrate_into_versioned_agent_state_database | 1619-1663 |
| test_scope_lease_schema_mismatch_keeps_legacy_and_verified_backup | 1666-1680 |

## Nonintegrable original fragments (documentation, NEVER apply wholesale)

Only incompatible/retained safety hunks are copied here for precise recovery; this is not a substitute for the integrated tests above. Original full bytes remain reachable at Uparent:path and blob OIDs, and all stashes remain intact. Reasons are per hunk immediately above.

### Archived src/local_ai_hub/verification_rules.py hunk 1

RETAIN: ProjectSettings typing/import remains; deleting it adds no stash behavior.

~~~diff
@@ -9,7 +9,6 @@ from typing import Protocol

 from .agent_tasks import CompletionGateError, TaskCheckpoint, TaskState, TaskStore
 from .agent_verification import CompletionResult
-from .project_config import ProjectSettings


 class CompletionReceiptStore(Protocol):
~~~

### Archived src/local_ai_hub/verification_rules.py hunk 2

REJECT: deleting the pre-mutation memory audit weakens completion safety.

~~~diff
@@ -256,9 +255,6 @@ def complete_task_with_project_rules(
     task_root = _task_project_root(before, initial_state_data)
     if task_root is None:
         raise CompletionGateError("task project root is unavailable")
-    memory_audit_validator = getattr(task_store, "_validate_memory_audit", None)
-    if callable(memory_audit_validator):
-        memory_audit_validator(before)
     try:
         from .project_config import ProjectConfigError, resolve_project_context
     except ImportError as exc:
~~~

### Archived src/local_ai_hub/verification_rules.py hunk 3

RETAIN: current empty-criteria completion context path; removing it loses newer master behavior.

~~~diff
@@ -278,32 +274,6 @@ def complete_task_with_project_rules(
         raise CompletionGateError("project configuration could not be resolved") from exc
     if project.resolution.error_codes:
         raise CompletionGateError("project configuration is invalid")
-    if not before.contract.acceptance_criteria:
-        state_data = dict(before.checkpoint.state_data)
-        state_data["repo_root"] = str(project.root)
-        state_data["repository_revision"] = revision
-        if state_data != dict(before.checkpoint.state_data):
-            checkpoint = TaskCheckpoint(
-                phase=before.checkpoint.phase,
-                next_action=before.checkpoint.next_action,
-                affected_paths=before.checkpoint.affected_paths,
-                evidence_ids=before.checkpoint.evidence_ids,
-                blockers=before.checkpoint.blockers,
-                state_data=state_data,
-            )
-            suffix = "_project_completion_context"
-            task_store.checkpoint(
-                task_key,
-                checkpoint,
-                actor=actor,
-                idempotency_key=f"{idempotency_key}{suffix}" if idempotency_key else "",
-            )
-        return task_store.complete(
-            task_key,
-            reason=reason,
-            actor=actor,
-            idempotency_key=idempotency_key,
-        )
     before_generation = before.checkpoint.state_data.get("mutation_generation", 0)
     result = evaluate_project_completion(
         verification_store,
~~~

### Archived src/local_ai_hub/verification_rules.py hunk 4

BLOCKED-EXACT: TaskStore.complete has no current_revision keyword. Current rules checkpoint repository_revision before complete; broker regression exercises this path. Direct original forwarding needs owner TaskStore API reconciliation, outside this scope.

~~~diff
@@ -355,4 +325,5 @@ def complete_task_with_project_rules(
         reason=reason,
         actor=actor,
         idempotency_key=idempotency_key,
+        current_revision=revision,
     )
~~~

### Archived tests/test_agent_t08_crash_after_commit.py hunk 1

RETAIN: current receipt crash helpers/imports and dict/dataclass event adapter.

~~~diff
@@ -1,17 +1,11 @@
-import sqlite3
 import subprocess
 import sys
-from contextlib import closing
 from pathlib import Path

 from local_ai_hub.agent_events import AgentStateStore
 from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStatus, TaskStore
-from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
 import pytest

-def _event_field(event, name):
-    return event[name] if isinstance(event, dict) else getattr(event, name)
-

 def test_process_exit_after_commit_before_publish_recovers_event(tmp_path):
     db_path = tmp_path / "agent_state.sqlite3"
~~~

### Archived tests/test_agent_t08_crash_after_commit.py hunk 3

REJECT: original deletes newer receipt projection/task/event hard-crash atomicity coverage.

~~~diff
@@ -112,129 +106,6 @@ os._exit(74)
     expected_kinds = ["task.created"]
     if operation == "transition":
         expected_kinds.append("task.transitioned")
-    assert [_event_field(event, "kind") for event in page["events"]] == expected_kinds
-    assert [_event_field(event, "seq") for event in page["events"]] == list(range(1, len(expected_kinds) + 1))
+    assert [event.kind for event in page["events"]] == expected_kinds
+    assert [event.seq for event in page["events"]] == list(range(1, len(expected_kinds) + 1))
     assert page["last_seq"] == page["next_seq"] == len(expected_kinds)
-
-
-@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
-def test_process_exit_during_receipt_write_recovers_atomically(tmp_path, phase):
-    db_path = tmp_path / "agent_state.sqlite3"
-    repo_root = Path(__file__).resolve().parents[1]
-    task_id = f"task-receipt-hard-crash-{phase}"
-    TaskStore(AgentStateStore(db_path)).create(
-        GoalContract(
-            goal="recover receipt write after process exit",
-            acceptance_criteria=("tests",),
-        ),
-        ScopeContext(task_id=task_id),
-        task_id=task_id,
-    )
-
-    script = """
-import inspect
-import os
-import sys
-from pathlib import Path
-sys.path.insert(0, sys.argv[3])
-from local_ai_hub.artifacts import ArtifactStore
-from local_ai_hub.agent_events import AgentStateStore
-from local_ai_hub.agent_tasks import TaskStore
-from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
-
-store = AgentStateStore(sys.argv[1])
-task_store = TaskStore(store)
-task = task_store.get(sys.argv[4])
-owner = task.owner
-command_id = "cmd-hard-exit-tests"
-repository_revision = sys.argv[5]
-proof = {
-    "kind": "work_command_verification",
-    "passed": True,
-    "task_id": sys.argv[4],
-    "owner": owner,
-    "criterion": "tests",
-    "command_id": command_id,
-    "exit_code": 0,
-    "repository_revision": repository_revision,
-    "mutation_generation": 0,
-    "result": {"success": True, "exit_code": 0},
-}
-artifacts = ArtifactStore(Path(sys.argv[1]).parent)
-evidence_id = artifacts.put_json(proof, owner, "command_verification")
-if sys.argv[2] == "before_commit":
-    original = VerificationStore.record_in_transaction
-    def exit_before_commit(self, con, receipt, **kwargs):
-        result = original(self, con, receipt, **kwargs)
-        os._exit(73)
-    VerificationStore.record_in_transaction = exit_before_commit
-else:
-    store._publish = lambda _event: os._exit(73)
-
-receipt_kwargs = {
-    "command_id": command_id,
-    "repository_revision": repository_revision,
-}
-if "owner" in VerificationReceipt.__dataclass_fields__:
-    receipt_kwargs.update(owner=owner, mutation_generation=0, evidence_type="test")
-receipt = VerificationReceipt.create(
-    sys.argv[4], "tests", passed=True, evidence_id=evidence_id, **receipt_kwargs
-)
-verification_kwargs = {"task_store": task_store}
-if "artifact_store" in inspect.signature(VerificationStore).parameters:
-    verification_kwargs["artifact_store"] = artifacts
-VerificationStore(store, **verification_kwargs).record(receipt)
-os._exit(74)
-"""
-    child = subprocess.run(
-        [
-            sys.executable,
-            "-B",
-            "-c",
-            script,
-            str(db_path),
-            phase,
-            str(repo_root / "src"),
-            task_id,
-            subprocess.run(
-                ["git", "rev-parse", "HEAD"],
-                cwd=repo_root,
-                check=True,
-                text=True,
-                capture_output=True,
-            ).stdout.strip(),
-        ],
-        cwd=repo_root,
-        capture_output=True,
-        text=True,
-        timeout=15,
-        check=False,
-    )
-
-    assert child.returncode == 73, child.stderr
-    recovered_store = AgentStateStore(db_path)
-    recovered_task = TaskStore(recovered_store).get(task_id)
-    assert recovered_task is not None
-    with closing(sqlite3.connect(db_path)) as con:
-        receipt_rows = con.execute(
-            "SELECT receipt_id FROM agent_verification_receipts WHERE task_id=?",
-            (task_id,),
-        ).fetchall()
-
-    if phase == "before_commit":
-        assert recovered_task.verification_receipts == {}
-        assert receipt_rows == []
-        assert recovered_store.events(f"verification:{task_id}") == []
-        assert not any(
-            event.kind == "task.verified"
-            for event in recovered_store.events(f"task:{task_id}")
-        )
-    else:
-        receipt_id = recovered_task.verification_receipts["tests"]
-        assert receipt_rows == [(receipt_id,)]
-        assert [event.kind for event in recovered_store.events(f"verification:{task_id}")].count(
-            "verification.receipt_recorded"
-        ) == 1
-        assert [event.kind for event in recovered_store.events(f"task:{task_id}")].count(
-            "task.verified"
-        ) == 1
~~~

### Archived tests/test_agent_t08_durable_contract.py hunk 1

RETAIN: Path/receipt artifact imports from master; historical formatting is inert.

~~~diff
@@ -1,10 +1,11 @@
 import sqlite3
 from contextlib import closing
-from pathlib import Path
 import threading
 import time
 from concurrent.futures import ThreadPoolExecutor
+
 import pytest
+
 from local_ai_hub.cache import SQLiteCache
 from local_ai_hub.agent_blackboard import BlackboardStore
 from local_ai_hub.agent_events import AppendResult, AgentEvent, AgentStateStore, SwarmPubSub
~~~

### Archived tests/test_agent_t08_durable_contract.py hunk 3

RETAIN: formatting-only whitespace addition.

~~~diff
@@ -51,6 +389,8 @@ def test_event_insert_failure_does_not_advance_cursor_or_survive_restart(tmp_pat
     recovered = restarted.append(AgentEvent.create("task:fault", "task.ok", {"x": 2}))
     assert recovered.seq == 1
     assert restarted.event_page("task:fault")["last_seq"] == 1
+
+
 def test_append_in_transaction_preserves_caller_rollback_and_strict_replay(tmp_path):
     db_path = tmp_path / "agent_state.sqlite3"
     store = AgentStateStore(db_path)
~~~

### Archived tests/test_agent_t08_durable_contract.py hunk 4

REJECT: deletion of newer rollback/publication checks is not missing behavior.

~~~diff
@@ -107,54 +447,11 @@ def test_append_in_transaction_preserves_caller_rollback_and_strict_replay(tmp_p
         con.close()

     persisted = store.event_page(stream_id)
-    page_events = [
-        event.to_dict() if isinstance(event, AgentEvent) else event
-        for event in persisted["events"]
-    ]
-    committed_event = (
-        committed.event.to_dict()
-        if isinstance(committed.event, AgentEvent)
-        else committed.event
-    )
-    assert page_events == [committed_event]
+    assert persisted["events"] == [committed.event]
     assert persisted["last_seq"] == committed.seq == 1
     store.unsubscribe(subscriber)
-@pytest.mark.parametrize(
-    ("field", "conflicting_value"),
-    (("actor", "worker-b"), ("correlation_id", "trace-b")),
-)
-def test_append_in_transaction_strict_replay_binds_actor_and_correlation(
-    tmp_path, field, conflicting_value
-):
-    db_path = tmp_path / "agent_state.sqlite3"
-    store = AgentStateStore(db_path)
-    store._ensure_schema()
-    original = AgentEvent.create(
-        "task:strict-identity",
-        "test.appended",
-        {"value": 1},
-        idempotency_key="same-key",
-        actor="worker-a",
-        correlation_id="trace-a",
-    )
-    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
-        con.execute("BEGIN IMMEDIATE")
-        store.append_in_transaction(con, original, strict_idempotency=True)
-        con.execute("COMMIT")

-    conflicting = AgentEvent.create(
-        original.stream_id,
-        original.kind,
-        original.payload,
-        idempotency_key=original.idempotency_key,
-        actor=conflicting_value if field == "actor" else original.actor,
-        correlation_id=conflicting_value if field == "correlation_id" else original.correlation_id,
-    )
-    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
-        con.execute("BEGIN IMMEDIATE")
-        with pytest.raises(ValueError, match="idempotency key was already used"):
-            store.append_in_transaction(con, conflicting, strict_idempotency=True)
-        con.execute("ROLLBACK")
+
 def test_append_in_transaction_rejects_connection_without_caller_transaction(tmp_path):
     db_path = tmp_path / "agent_state.sqlite3"
     store = AgentStateStore(db_path)
~~~

### Archived tests/test_agent_t08_durable_contract.py hunk 5

REJECT: deletion of newer caller-transaction coverage is not missing behavior.

~~~diff
@@ -173,29 +470,8 @@ def test_append_in_transaction_rejects_connection_without_caller_transaction(tmp
     recovered = store.event_page(event.stream_id)
     assert recovered["events"] == []
     assert recovered["last_seq"] == recovered["next_seq"] == 0
-def test_task_receipt_projection_rejects_connection_without_caller_transaction(tmp_path):
-    db_path = tmp_path / "agent_state.sqlite3"
-    state_store = AgentStateStore(db_path)
-    tasks = TaskStore(state_store)
-    task = tasks.create(
-        GoalContract(goal="receipt transaction", acceptance_criteria=("tests",)),
-        ScopeContext(task_id="task-receipt-transaction"),
-        task_id="task-receipt-transaction",
-    )

-    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
-        with pytest.raises(RuntimeError, match="caller-owned transaction"):
-            tasks.add_verification_receipt_in_transaction(
-                con, task.task_id, "tests", "receipt-without-transaction"
-            )

-    saved = tasks.get(task.task_id)
-    assert saved is not None
-    assert saved.verification_receipts == {}
-    assert all(
-        event.kind != "task.verified"
-        for event in state_store.events(f"task:{task.task_id}")
-    )
 def test_ordered_event_publication_rejects_uncommitted_and_rolled_back_events(tmp_path):
     db_path = tmp_path / "agent_state.sqlite3"
     store = AgentStateStore(db_path)
~~~

### Archived tests/test_agent_t08_durable_contract.py hunk 6

RETAIN: formatting-only whitespace addition.

~~~diff
@@ -224,6 +500,8 @@ def test_ordered_event_publication_rejects_uncommitted_and_rolled_back_events(tm
     assert page["events"] == []
     assert page["last_seq"] == page["next_seq"] == 0
     store.unsubscribe(subscriber)
+
+
 def test_duplicate_replay_rebuilds_cursor_from_stream_high_water(tmp_path):
     db_path = tmp_path / "agent_state.sqlite3"
     store = AgentStateStore(db_path)
~~~

### Archived tests/test_agent_t08_durable_contract.py hunk 8

RETAIN: formatting-only whitespace addition.

~~~diff
@@ -287,6 +718,8 @@ def test_task_transition_append_result_error_rolls_back_projection(tmp_path, mon

     assert tasks.get(task.task_id).status.value == "active"
     assert state_store.events(f"task:{task.task_id}")[-1].payload["to_status"] == "active"
+
+
 def test_task_transition_cas_has_one_winner_and_one_conflict(tmp_path, monkeypatch):
     state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
     tasks = TaskStore(state_store)
~~~

### Archived tests/test_agent_t08_durable_contract.py hunk 9

RETAIN: formatting-only whitespace addition.

~~~diff
@@ -341,6 +774,8 @@ def test_task_transition_cas_has_one_winner_and_one_conflict(tmp_path, monkeypat
     ]
     assert len(transitions) == 1
     assert transitions[0].payload["to_status"] == committed.status.value
+
+
 def test_verification_append_result_error_rolls_back_receipt_projection(tmp_path, monkeypatch):
     db_path = tmp_path / "agent_state.sqlite3"
     state_store = AgentStateStore(db_path)
~~~

### Archived tests/test_agent_t08_durable_contract.py hunk 10

REJECT: original removes trusted artifact fixture from receipt fault injection; keep current receipt validation.

~~~diff
@@ -352,8 +787,7 @@ def test_verification_append_result_error_rolls_back_receipt_projection(tmp_path
     )
     verifications = VerificationStore(state_store, task_store=tasks)
     receipt = VerificationReceipt.create(
-        "task-append-error", "tests", passed=True, evidence_id="evidence-tests",
-        command_id="cmd-append-error",
+        "task-append-error", "tests", passed=True, evidence_id="evidence-tests"
     )
     monkeypatch.setattr(
         state_store,
~~~

### Archived tests/test_agent_t08_durable_contract.py hunk 12

REJECT: original removes trusted artifact fixture from joint receipt/task rollback; keep current guard.

~~~diff
@@ -382,8 +838,7 @@ def test_verification_receipt_task_projection_and_events_rollback_together(tmp_p
         task_id="task-atomic-receipt",
     )
     receipt = VerificationReceipt.create(
-        "task-atomic-receipt", "tests", passed=True, evidence_id="evidence-tests",
-        command_id="cmd-atomic-receipt",
+        "task-atomic-receipt", "tests", passed=True, evidence_id="evidence-tests"
     )
     with closing(sqlite3.connect(db_path)) as con, con:
         con.execute(
~~~

### Archived tests/test_agent_t08_live_order.py hunk 1

RETAIN: newer blackboard/memory/swarm imports, event adapter and publication helpers.

~~~diff
@@ -1,24 +1,12 @@
 from contextlib import closing
-from dataclasses import replace
 import threading
 import time

 import pytest

 from local_ai_hub.agent_events import AgentEvent, AgentStateStore
-from local_ai_hub.agent_blackboard import BlackboardStore
-from local_ai_hub import agent_memory as agent_memory_module
-from local_ai_hub.agent_memory import AgentScope, MemoryKind, MemoryRecord, MemoryStore
 from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStatus, TaskStore
 from local_ai_hub.sqlite_support import connect_sqlite
-from local_ai_hub.swarm import SwarmCoordinator
-
-
-def _memory_stream_id(scope: AgentScope, scope_id: str, key: str) -> str:
-    builder = getattr(agent_memory_module, "_memory_event_stream_id", None)
-    if callable(builder):
-        return builder(scope, scope_id, key)
-    return f"memory:{scope.value}:{key}"


 def test_concurrent_event_appends_publish_in_committed_sequence_order(tmp_path, monkeypatch):
~~~

### Archived tests/test_agent_t08_live_order.py hunk 2

REJECT: original removes receipt writer case from task ordering parametrization.

~~~diff
@@ -96,14 +84,14 @@ def test_concurrent_event_appends_publish_in_committed_sequence_order(tmp_path,
     assert [subscriber.get_nowait().seq, subscriber.get_nowait().seq] == [1, 2]


-@pytest.mark.parametrize("task_writer", ["create", "update", "receipt"])
+@pytest.mark.parametrize("task_writer", ["create", "update"])
 def test_task_event_commits_share_append_publish_order_lock(tmp_path, monkeypatch, task_writer):
     db_path = tmp_path / "agent_state.sqlite3"
     state_store = AgentStateStore(db_path)
     tasks = TaskStore(state_store)
     task_id = f"task-live-order-{task_writer}"
     stream_id = f"task:{task_id}"
-    if task_writer in {"update", "receipt"}:
+    if task_writer == "update":
         tasks.create(
             GoalContract(goal="preserve event order"),
             ScopeContext(task_id=task_id),
~~~

### Archived tests/test_agent_t08_live_order.py hunk 3

REJECT: original removes ordered_event_publication tracking.

~~~diff
@@ -123,15 +111,6 @@ def test_task_event_commits_share_append_publish_order_lock(tmp_path, monkeypatc
     publish = state_store._publish
     append_publish_lock = state_store._append_publish_lock
     task_thread = None
-    publication_calls = []
-    ordered_publication = state_store.ordered_event_publication
-
-    def track_ordered_publication(con):
-        if threading.current_thread() is task_thread:
-            publication_calls.append(True)
-        return ordered_publication(con)
-
-    monkeypatch.setattr(state_store, "ordered_event_publication", track_ordered_publication)

     class ObservedAppendPublishLock:
         def __enter__(self):
~~~

### Archived tests/test_agent_t08_live_order.py hunk 5

REJECT: original removes receipt writer branch.

~~~diff
@@ -179,8 +158,6 @@ def test_task_event_commits_share_append_publish_order_lock(tmp_path, monkeypatc
                     actor="test",
                     idempotency_key="task-live-order-update",
                 )
-            else:
-                tasks.add_verification_receipt(task_id, "live-order", "receipt-1")
         except BaseException as exc:
             errors.append(exc)
~~~

### Archived tests/test_agent_t08_live_order.py hunk 6

REJECT: original removes publication-order invocation assertion.

~~~diff
@@ -203,7 +180,6 @@ def test_task_event_commits_share_append_publish_order_lock(tmp_path, monkeypatc
     assert not task_thread.is_alive()
     assert errors == []
     assert lock_was_used
-    assert publication_calls == [True]
     assert task_published_before_release == []
     published = [subscriber.get_nowait(), subscriber.get_nowait()]
     assert [event.seq for event in published] == [first_seq, first_seq + 1]
~~~

### Archived tests/test_agent_t08_live_order.py hunk 7

REJECT: original deletes newer memory/blackboard/swarm ordering and forged/duplicate/out-of-order publication guards.

~~~diff
@@ -294,189 +270,3 @@ def test_ordered_event_publication_serializes_caller_owned_batch(tmp_path, monke
     assert second_publish_entered.is_set()
     assert second_published_early == []
     assert [subscriber.get_nowait().seq, subscriber.get_nowait().seq] == [1, 2]
-
-
-@pytest.mark.parametrize("writer", ["memory", "blackboard", "swarm"])
-def test_t08_store_writers_publish_same_stream_in_commit_order(tmp_path, monkeypatch, writer):
-    db_path = tmp_path / "agent_state.sqlite3"
-    state_store = AgentStateStore(db_path)
-    if writer == "memory":
-        memory = MemoryStore(state_store)
-        stream_id = _memory_stream_id(AgentScope.REPOSITORY, "repo", "ordered")
-
-        def write(value):
-            memory.record(
-                MemoryRecord.create(
-                    kind=MemoryKind.FINDING,
-                    scope=AgentScope.REPOSITORY,
-                    scope_id="repo",
-                    key="ordered",
-                    value={"value": value},
-                    evidence_ids=(f"evidence-{value}",),
-                ),
-                idempotency_key=f"ordered-{value}",
-            )
-    elif writer == "blackboard":
-        board = BlackboardStore(db_path, state_store=state_store)
-        stream_id = "blackboard:ordered:section"
-
-        def write(value):
-            return board.update("ordered", "section", {"value": value}, author="agent")
-    else:
-        coordinator = SwarmCoordinator(db_path, state_store=state_store)
-        dispatched = coordinator.dispatch("ordered publication", root=str(tmp_path))
-        assert dispatched["success"] is True
-        stream_id = f"swarm:{dispatched['swarm_id']}"
-
-        def write(value):
-            if value == 1:
-                return coordinator.step(
-                    dispatched["swarm_id"], "Coder", "submit_patch", {"value": value}
-                )
-            return coordinator.step(
-                dispatched["swarm_id"], "Tester", "submit_result", {"passed": True}
-            )
-
-    initial_seq = state_store.event_page(stream_id)["last_seq"]
-    subscriber = state_store.subscribe()
-    first_publish_entered = threading.Event()
-    release_first_publish = threading.Event()
-    second_started = threading.Event()
-    second_lock_attempted = threading.Event()
-    second_publish_entered = threading.Event()
-    second_published_before_release = []
-    publish = state_store._publish
-    append_publish_lock = state_store._append_publish_lock
-    second_thread = None
-
-    class ObservedAppendPublishLock:
-        def __enter__(self):
-            if threading.current_thread() is second_thread:
-                second_lock_attempted.set()
-            append_publish_lock.acquire()
-
-        def __exit__(self, *_args):
-            append_publish_lock.release()
-
-    monkeypatch.setattr(state_store, "_append_publish_lock", ObservedAppendPublishLock())
-
-    def delay_first_publish(event):
-        if event.stream_id == stream_id and event.seq == initial_seq + 1:
-            first_publish_entered.set()
-            assert release_first_publish.wait(timeout=5)
-        elif event.stream_id == stream_id and event.seq > initial_seq + 1:
-            second_publish_entered.set()
-            if not release_first_publish.is_set():
-                second_published_before_release.append(event.seq)
-        publish(event)
-
-    monkeypatch.setattr(state_store, "_publish", delay_first_publish)
-    errors = []
-
-    def run_write(value, started=None):
-        if started is not None:
-            started.set()
-        try:
-            result = write(value)
-            if isinstance(result, dict) and result.get("success") is False:
-                errors.append(result)
-        except BaseException as exc:
-            errors.append(exc)
-
-    first_thread = threading.Thread(target=run_write, args=(1,))
-    first_thread.start()
-    assert first_publish_entered.wait(timeout=5)
-    second_thread = threading.Thread(target=run_write, args=(2, second_started))
-    second_thread.start()
-    assert second_started.wait(timeout=5)
-    deadline = time.monotonic() + 3
-    while not second_lock_attempted.is_set() and not second_publish_entered.is_set():
-        if time.monotonic() >= deadline:
-            break
-        threading.Event().wait(0.001)
-    lock_was_attempted = second_lock_attempted.is_set()
-    release_first_publish.set()
-    first_thread.join(timeout=5)
-    second_thread.join(timeout=5)
-
-    assert not first_thread.is_alive()
-    assert not second_thread.is_alive()
-    assert errors == []
-    assert lock_was_attempted
-    assert second_published_before_release == []
-    published = []
-    while not subscriber.empty():
-        event = subscriber.get_nowait()
-        if event.stream_id == stream_id:
-            published.append(event)
-    seqs = [event.seq for event in published]
-    assert seqs == sorted(seqs)
-    assert len(seqs) >= 2
-    state_store.unsubscribe(subscriber)
-
-def test_ordered_event_publication_rejects_committed_row_content_mismatch(tmp_path):
-    db_path = tmp_path / "agent_state.sqlite3"
-    state_store = AgentStateStore(db_path)
-    state_store._ensure_schema()
-    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
-        con.execute("BEGIN IMMEDIATE")
-        result = state_store.append_in_transaction(
-            con, AgentEvent.create("task:publication-row", "task.created", {"n": 1})
-        )
-        con.execute("COMMIT")
-    subscriber = state_store.subscribe()
-    forged = replace(result.event, payload={"n": 2})
-
-    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
-        with state_store.ordered_event_publication(con) as publish_committed:
-            with pytest.raises(RuntimeError, match="event is not committed"):
-                publish_committed([forged])
-
-    assert subscriber.empty()
-    state_store.unsubscribe(subscriber)
-
-@pytest.mark.parametrize("batch_kind", ("duplicate", "out_of_order"))
-def test_ordered_event_publication_rejects_duplicate_or_out_of_order_batch(
-    tmp_path, batch_kind
-):
-    db_path = tmp_path / "agent_state.sqlite3"
-    state_store = AgentStateStore(db_path)
-    state_store._ensure_schema()
-    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
-        con.execute("BEGIN IMMEDIATE")
-        first = state_store.append_in_transaction(
-            con, AgentEvent.create("task:publication-validation", "task.one", {"n": 1})
-        )
-        second = state_store.append_in_transaction(
-            con, AgentEvent.create("task:publication-validation", "task.two", {"n": 2})
-        )
-        con.execute("COMMIT")
-    subscriber = state_store.subscribe()
-
-    events = [first.event, first.event] if batch_kind == "duplicate" else [second.event, first.event]
-    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
-        with state_store.ordered_event_publication(con) as publish_committed:
-            with pytest.raises(ValueError, match="stream sequence order"):
-                publish_committed(events)
-
-    assert subscriber.empty()
-    state_store.unsubscribe(subscriber)
-
-def test_ordered_event_publication_rejects_publish_after_scope_closes(tmp_path):
-    db_path = tmp_path / "agent_state.sqlite3"
-    state_store = AgentStateStore(db_path)
-    state_store._ensure_schema()
-    subscriber = state_store.subscribe()
-    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
-        with state_store.ordered_event_publication(con) as publish_committed:
-            con.execute("BEGIN IMMEDIATE")
-            result = state_store.append_in_transaction(
-                con, AgentEvent.create("task:closed-publication", "task.created", {})
-            )
-            con.execute("COMMIT")
-
-        with pytest.raises(RuntimeError, match="scope is closed"):
-            publish_committed([result.event])
-
-    assert subscriber.empty()
-    state_store.unsubscribe(subscriber)
~~~

### Archived tests/test_project_memory_audit_completion.py hunk 1

RETAIN: MemoryKind required by actual memory fixture.

~~~diff
@@ -5,7 +5,6 @@ from pathlib import Path
 import pytest

 from local_ai_hub.agent_identity import ScopeContext
-from local_ai_hub.agent_memory import AgentScope, MemoryKind, MemoryRecord, MemoryStatus
 from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, TaskCheckpoint
 from local_ai_hub.agent_verification import VerificationReceipt
 from local_ai_hub.app import LocalAIApp
~~~

### Archived tests/test_project_memory_audit_completion.py hunk 2

RETAIN: actual stale memory creation supplies stronger end-to-end input than synthetic state.

~~~diff
@@ -31,16 +30,6 @@ def test_project_completion_rejects_skipped_memory_without_not_used_reason(
         encoding="utf-8",
     )
     app = LocalAIApp(str(config_path))
-    app.agent_memory.record(
-        MemoryRecord.create(
-            kind=MemoryKind.FACT,
-            scope=AgentScope.REPOSITORY,
-            key="stale-project-memory",
-            value="stale evidence",
-            status=MemoryStatus.STALE,
-            provenance={"root": str(project_root)},
-        )
-    )
     task_id = "project-completion-skipped-memory"
     app.agent_tasks.create(
         GoalContract(
~~~

### Archived tests/test_project_memory_audit_completion.py hunk 3

RETAIN: current generated memory context and warning assertion; do not replace immutable context with synthetic checkpoint.

~~~diff
@@ -52,17 +41,17 @@ def test_project_completion_rejects_skipped_memory_without_not_used_reason(
         actor="agent",
         repo_root=str(project_root),
     )
-    task = app.agent_tasks.get(task_id)
-    assert task is not None
-    assert any(
-        warning["code"] == "memory_stale_skipped"
-        for warning in task.checkpoint.state_data["memory_context"]["warnings"]
-    )
     app.agent_tasks.checkpoint(
         task_id,
         TaskCheckpoint(
             phase="work",
-            state_data={"memory_audit": {"used_ids": []}},
+            state_data={
+                "memory_context": {
+                    "items": [],
+                    "warnings": [{"code": "memory_stale_skipped"}],
+                },
+                "memory_audit": {"used_ids": []},
+            },
         ),
         actor="agent",
     )
~~~

### Archived tests/test_t09_http_task_completion_matrix.py hunk 4

REJECT: raising=False could hide a missing memory-adoption API; current required monkeypatch remains strict.

~~~diff
@@ -181,6 +184,7 @@ def test_task_completion_http_receipt_and_memory_matrix(
             app.agent_tasks,
             "_task_memory_context",
             lambda _task_id, _contract, _context, **_kwargs: memory_context,
+            raising=False,
         )
     app.agent_tasks.create(
         GoalContract(
~~~

### Archived tests/test_t09_http_task_completion_persisted_receipts.py hunk 1

RETAIN: actual broker-based receipt fixture and real project config, not historical replacement module.

~~~diff
@@ -1,28 +1,29 @@
 from __future__ import annotations

+import json
+import hashlib
 from pathlib import Path
 import threading

-from local_ai_hub import http_server, mcp_server
+from local_ai_hub import http_server
+from local_ai_hub import mcp_server
 from local_ai_hub.agent_identity import ScopeContext
-from local_ai_hub.agent_tasks import GoalContract, TaskCheckpoint
+from local_ai_hub.agent_tasks import GoalContract
+from local_ai_hub.agent_verification import VerificationReceipt
 from local_ai_hub.app import LocalAIApp
 from local_ai_hub.client import HubClient
+from t09_project_config_test_fixture import install_t09_project_config_test_fixture


 def test_http_task_complete_uses_persisted_tenant_scoped_receipts(
     tmp_path: Path, monkeypatch
 ) -> None:
+    project_config = install_t09_project_config_test_fixture(monkeypatch)
     tenant_id = "agent-t09"
     task_id = "task-t09-http-receipts"
+    repository_revision = "rev-t09-http-acceptance"
     project_root = tmp_path / "repo"
     project_root.mkdir()
-    test_dir = project_root / "tests"
-    test_dir.mkdir()
-    (test_dir / "test_project_rules.py").write_text(
-        "def test_project_command():\n    assert 1 + 1 == 2\n",
-        encoding="utf-8",
-    )
     (project_root / ".local-ai.toml").write_text(
         '[commands]\ntest = "python -m pytest -q tests/test_project_rules.py"\n'
         '[verification_rules]\nrequired_commands = ["test"]\n',
~~~

### Archived tests/test_t09_http_task_completion_persisted_receipts.py hunk 2

RETAIN: actual project command executes and persisted receipt supplies revision; historical synthetic receipt would bypass broker provenance.

~~~diff
@@ -49,38 +50,63 @@ def test_http_task_complete_uses_persisted_tenant_scoped_receipts(
         actor=tenant_id,
         repo_root=str(project_root),
     )
-    command_result = app.commands.run_project_command(
-        "test",
-        str(project_root),
-        tenant=tenant_id,
-        task_id=task_id,
-        criterion="test",
-        timeout=60,
-        force=True,
+    project_config_digest = project_config.resolve_project_context(project_root, state_dir).config_digest
+    command_text = "python -m pytest -q tests/test_project_rules.py"
+    command_sha256 = hashlib.sha256(command_text.encode("utf-8")).hexdigest()
+    project_environment_sha256 = hashlib.sha256(b"{}").hexdigest()
+    configured_command_sha256 = command_sha256
+    caller_arguments_sha256 = hashlib.sha256(b"[]").hexdigest()
+    execution_binding = hashlib.sha256(
+        json.dumps(
+            {
+                "project_alias": "test",
+                "project_config_digest": project_config_digest,
+                "configured_command_sha256": configured_command_sha256,
+                "caller_arguments_sha256": caller_arguments_sha256,
+                "command_sha256": command_sha256,
+                "project_environment_sha256": project_environment_sha256,
+            },
+            sort_keys=True,
+            separators=(",", ":"),
+        ).encode("utf-8")
+    ).hexdigest()
+
+    command_evidence = app.artifacts.put_json(
+        {
+            "kind": "work_command_verification",
+            "passed": True,
+            "task_id": task_id,
+            "owner": tenant_id,
+            "repository_revision": repository_revision,
+            "mutation_generation": 0,
+            "criterion": "test",
+            "command_id": "cmd-t09-http-test",
+            "command_classification": "test",
+            "command": command_text,
+            "project_alias": "test",
+            "project_config_digest": project_config_digest,
+            "project_environment_sha256": project_environment_sha256,
+            "configured_command_sha256": configured_command_sha256,
+            "caller_arguments_sha256": caller_arguments_sha256,
+            "project_execution_binding_sha256": execution_binding,
+            "command_sha256": command_sha256,
+            "exit_code": 0,
+            "result": {"success": True, "exit_code": 0},
+        },
+        tenant_id,
+        "command_verification",
     )
-    assert command_result.get("success") is True, command_result
-    receipt = command_result.get("verification_receipt")
-    assert isinstance(receipt, dict), command_result
-    command_evidence = str(command_result.get("verification_evidence_id") or "")
-    assert command_evidence
-    repository_revision = str(receipt.get("repository_revision") or "")
-    assert repository_revision
-    task_state = app.agent_tasks.get(task_id)
-    assert task_state is not None
-    state_data = dict(task_state.checkpoint.state_data)
-    state_data["repository_revision"] = repository_revision
-    app.agent_tasks.checkpoint(
-        task_id,
-        TaskCheckpoint(
-            phase=task_state.checkpoint.phase,
-            next_action=task_state.checkpoint.next_action,
-            affected_paths=task_state.checkpoint.affected_paths,
-            evidence_ids=task_state.checkpoint.evidence_ids,
-            blockers=task_state.checkpoint.blockers,
-            state_data=state_data,
-        ),
-        actor=tenant_id,
-        idempotency_key="t09-broker-revision",
+    app.agent_verification.record(
+        VerificationReceipt.create(
+            task_id,
+            "test",
+            evidence_id=command_evidence,
+            command_id="cmd-t09-http-test",
+            owner=tenant_id,
+            repository_revision=repository_revision,
+            mutation_generation=0,
+            evidence_type="test",
+        )
     )
     preflight = app.agent_verification.completion(
         task_id, current_revision=repository_revision, current_mutation_generation=0
~~~

### Archived tests/test_t09_http_task_completion_persisted_receipts.py hunk 3

REJECT: replacement project-config module remains unnecessary and omits production guards.

~~~diff
@@ -169,6 +195,7 @@ def test_http_task_complete_uses_persisted_tenant_scoped_receipts(
         server.server_close()
         thread.join(timeout=2)
         http_server.APP = previous_app
+
     assert payload["success"] is True, payload
     assert payload["task"]["task_id"] == task_id
     assert payload["task"]["status"] == "completed"
~~~

### Archived tests/test_agent_memory_http_identity.py hunk 1

RETAIN: pytest import needed by newer tombstone rejection test.

~~~diff
@@ -12,8 +12,6 @@ from contextlib import closing
 from pathlib import Path
 from urllib.parse import urlencode

-import pytest
-
 from local_ai_hub import http_server
 from local_ai_hub.agent_identity import AgentScope
 from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus
~~~

### Archived tests/test_agent_memory_http_identity.py hunk 10

REJECT: deleting master promotion_candidate loses spoofed approval regression.

~~~diff
@@ -582,16 +849,8 @@ def test_http_memory_public_identity_blocks_spoofed_origin_and_foreign_queries(t
         value="tenant-owned record",
         provenance={"root": str(repo_a.resolve()), "repository_id": repo_a_id, "tenant": "tenant-a"},
     )
-    promotion_candidate = MemoryRecord.create(
-        kind=MemoryKind.FACT,
-        scope=AgentScope.REPOSITORY,
-        key="http-promotion-requires-trusted-approval",
-        value="repository-scoped fact",
-        provenance={"root": str(repo_a.resolve()), "repository_id": repo_a_id, "tenant": "tenant-a"},
-    )
     app.agent_memory.record(legacy, actor="user")
     app.agent_memory.record(tenant_owned, actor="user")
-    app.agent_memory.record(promotion_candidate, actor="agent")

     previous_app = http_server.APP
     http_server.APP = app
~~~

### Archived tests/test_agent_memory_http_identity.py hunk 11

REJECT: deleting explicit forged-promotion 403 guard weakens security.

~~~diff
@@ -620,28 +879,6 @@ def test_http_memory_public_identity_blocks_spoofed_origin_and_foreign_queries(t
             return exc.code, json.loads(exc.read().decode("utf-8"))

     try:
-        status, forged_promotion = request(
-            "POST",
-            payload={
-                "action": "promote",
-                "record_id": promotion_candidate.record_id,
-                "target_scope": "global",
-                "approver": "user",
-                "root": str(repo_a),
-                "repository_id": repo_a_id,
-            },
-        )
-        assert status == 403
-        assert forged_promotion["success"] is False
-        still_scoped = app.agent_memory.get(
-            promotion_candidate.record_id,
-            root=str(repo_a),
-            repository_id=repo_a_id,
-            tenant="tenant-a",
-        )
-        assert still_scoped is not None
-        assert still_scoped.scope is AgentScope.REPOSITORY
-
         status, hidden_by_tenant = request(
             "GET",
             params={
~~~

### Archived tests/test_t05_agent_state_migrations.py hunk 1

RETAIN: hashlib used by newer incident schema variant tests.

~~~diff
@@ -1,7 +1,6 @@
 from __future__ import annotations

 from contextlib import closing
-import hashlib
 import json
 import os
 import sqlite3
~~~

### Archived tests/test_t05_agent_state_migrations.py hunk 2

REJECT: original deletes trusted receipt artifact helper and leases import/newer component tests.

~~~diff
@@ -20,36 +19,12 @@ from local_ai_hub.agent_context import ContextCompiler
 from local_ai_hub.agent_identity import AgentScope
 from local_ai_hub.agent_incidents import IncidentStore
 from local_ai_hub.agent_learning import LearningStore
-from local_ai_hub.leases import ScopeLeaseStore
 from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
 from local_ai_hub.agent_policy import PolicyEngine
 from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStore
 from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore


-class _MigrationArtifactStore:
-    def __init__(self, task):
-        self.task = task
-
-    def get(self, artifact_id, *, max_chars, tenant):
-        proof = {
-            "passed": True,
-            "kind": "work_source_review",
-            "criteria": ["migration"],
-            "task_id": self.task.task_id,
-            "owner": tenant,
-            "repository_revision": "",
-            "mutation_generation": 0,
-        }
-        return {
-            "success": True,
-            "artifact_id": artifact_id,
-            "kind": "source_review",
-            "next_offset": None,
-            "text": json.dumps(proof),
-        }
-
-
 def _seed_state(db_path):
     state = AgentStateStore(db_path)
     tasks = TaskStore(state)
~~~

### Archived tests/test_t05_agent_state_migrations.py hunk 3

RETAIN: trusted artifact backed migration receipt; provenance formatting is equivalent.

~~~diff
@@ -79,15 +54,12 @@ def _seed_state(db_path):
         key="migration-memory",
         value="durable memory",
         source="test",
-        provenance={
-            "root": str(db_path.parent / "memory-repo"),
-            "tenant": "migration-tenant",
-        },
+        provenance={"root": str(db_path.parent / "memory-repo"), "tenant": "migration-tenant"},
     )
     # Seed durable projection directly; event-writer integration belongs to T08.
     MemoryStore(state)._save_record(memory)

-    verifications = VerificationStore(state, task_store=tasks, artifact_store=_MigrationArtifactStore(task))
+    verifications = VerificationStore(state, task_store=tasks)
     receipt = VerificationReceipt.create(
         task_id=task.task_id,
         criterion="migration",
~~~

### Archived tests/test_t05_agent_state_migrations.py hunk 4

RETAIN: trusted artifact required to prove durable receipt still verifies after migration.

~~~diff
@@ -137,7 +109,7 @@ def _assert_state_survives(db_path, task, event, memory):
         root=memory.provenance["root"],
         tenant=memory.provenance["tenant"],
     ).value == "durable memory"
-    assert VerificationStore(state, task_store=tasks, artifact_store=_MigrationArtifactStore(task)).completion(task.task_id).complete is True
+    assert VerificationStore(state, task_store=tasks).completion(task.task_id).complete is True


 def _backup_for(db_path):
~~~

### Archived tests/test_t05_agent_state_migrations.py hunk 7

REJECT: removing sparse event version row-count assertion weakens migration preservation proof.

~~~diff
@@ -254,9 +226,6 @@ def test_historical_schema_version_migrates_and_preserves_legacy_event_versions(
             "SELECT schema_version FROM agent_event_schema_versions WHERE stream_id=? AND seq=1",
             (event.stream_id,),
         ).fetchone()[0] == 7
-        assert connection.execute(
-            "SELECT COUNT(*) FROM agent_event_schema_versions"
-        ).fetchone()[0] == 1
         assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
     _assert_state_survives(db_path, task, event, memory)
~~~

### Archived tests/test_t05_agent_state_migrations.py hunk 8

RETAIN: read-only preflight, verified recovery backup, shm/component/sparse metadata tests are stronger than historical replacement.

~~~diff
@@ -342,99 +311,18 @@ def test_unsupported_newer_schema_version_fails_closed_byte_for_byte(tmp_path, u
         connection.commit()
     before = _sqlite_file_snapshot(db_path)

-    with pytest.raises(RuntimeError, match="schema version") as caught:
-        AgentStateStore(db_path)._preflight_schema_read_only()
+    with pytest.raises(RuntimeError, match="schema version"):
+        AgentStateStore(db_path).events(event.stream_id)

-    assert caught.value.recovery_required is True
-    assert caught.value.backup_path is not None and caught.value.backup_path.is_file()
-    with closing(sqlite3.connect(caught.value.backup_path)) as backup:
-        assert backup.execute("PRAGMA quick_check").fetchone()[0] == "ok"
-        assert backup.execute("PRAGMA user_version").fetchone()[0] == unsupported_version
-        assert backup.execute(
-            "SELECT event_id FROM agent_events WHERE event_id=?", (event.event_id,)
-        ).fetchone() == (event.event_id,)
     assert db_path.is_file()
     assert _sqlite_file_snapshot(db_path) == before


-def test_preflight_ignores_transient_shm_metadata_change(tmp_path, monkeypatch):
-    db_path = tmp_path / "agent_state.sqlite3"
-    _seed_state(db_path)
-    shm_path = Path(f"{db_path}-shm")
-    shm_path.write_bytes(b"transient sqlite shared-memory state")
-    original_classify = AgentStateStore._classify_schema.__func__
-
-    def touch_shm_during_snapshot_classification(cls, connection):
-        result = original_classify(cls, connection)
-        stat = shm_path.stat()
-        os.utime(shm_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
-        return result
-
-    monkeypatch.setattr(
-        AgentStateStore,
-        "_classify_schema",
-        classmethod(touch_shm_during_snapshot_classification),
-    )
-    AgentStateStore(db_path)._preflight_schema_read_only()
-
-
-def test_component_schema_version_is_independent_of_database_version(tmp_path):
-    db_path = tmp_path / "agent_state.sqlite"
-    _seed_state(db_path)
-    ScopeLeaseStore(tmp_path)
-    with closing(sqlite3.connect(db_path)) as connection:
-        connection.execute("DROP TABLE agent_event_schema_versions")
-        connection.execute("PRAGMA user_version=0")
-        connection.commit()
-
-    AgentStateStore(db_path)._ensure_schema()
-
-    with closing(sqlite3.connect(db_path)) as connection:
-        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
-        assert connection.execute(
-            "SELECT version FROM agent_state_schema_versions WHERE component='leases'"
-        ).fetchone() == (1,)
-
-
-def test_legacy_event_version_metadata_is_sparse_and_pruned_with_event(tmp_path):
-    db_path = tmp_path / "agent_state.sqlite3"
-    _, event, _ = _seed_state(db_path)
-    with closing(sqlite3.connect(db_path)) as connection:
-        assert connection.execute(
-            "SELECT schema_version FROM agent_event_schema_versions WHERE stream_id=? AND seq=?",
-            (event.stream_id, 1),
-        ).fetchone() is None
-        connection.execute(
-            "INSERT INTO agent_event_schema_versions(stream_id, seq, schema_version) "
-            "VALUES (?, ?, 7)",
-            (event.stream_id, 1),
-        )
-        connection.execute(
-            "UPDATE agent_events SET created_at=? WHERE stream_id=? AND seq=?",
-            (time.time() - (2 * 86400), event.stream_id, 1),
-        )
-        connection.commit()
-
-    result = AgentStateStore(db_path).cleanup(retention_days=1)
-
-    assert result["success"] is True
-    assert result["deleted_events"] >= 1
-    with closing(sqlite3.connect(db_path)) as connection:
-        assert connection.execute(
-            "SELECT 1 FROM agent_events WHERE stream_id=? AND seq=?",
-            (event.stream_id, 1),
-        ).fetchone() is None
-        assert connection.execute(
-            "SELECT 1 FROM agent_event_schema_versions WHERE stream_id=? AND seq=?",
-            (event.stream_id, 1),
-        ).fetchone() is None
-
-
 def test_unknown_legacy_layout_fails_closed_without_changing_database_bytes(tmp_path):
     db_path = tmp_path / "agent_state.sqlite3"
     _, event, _ = _seed_state(db_path)
     with closing(sqlite3.connect(db_path)) as connection:
-        connection.execute("ALTER " "TABLE agent_events ADD COLUMN unknown_future_data TEXT")
+        connection.execute("ALTER TABLE agent_events ADD COLUMN unknown_future_data TEXT")
         connection.execute("DROP TABLE agent_event_schema_versions")
         connection.execute("PRAGMA user_version=0")
         connection.commit()
~~~

### Archived tests/test_t05_agent_state_migrations.py hunk 9

RETAIN: current explicit no-migration-applied message; both variants assert fail-closed, file retention and valid backup.

~~~diff
@@ -518,7 +406,7 @@ def test_missing_required_projection_schema_fails_closed_and_preserves_wal_and_s
         backups = list(tmp_path.glob("agent_state.sqlite.schema-mismatch-*.sqlite3"))
         assert len(backups) == 1
         assert str(backups[0]) in str(exc_info.value)
-        assert "no migration applied" in str(exc_info.value).casefold()
+        assert "preserve the original database files" in str(exc_info.value).casefold()
         with closing(sqlite3.connect(backups[0])) as backup:
             assert backup.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
             assert backup.execute("PRAGMA user_version").fetchone()[0] == 0
~~~

### Archived tests/test_t05_agent_state_migrations.py hunk 11

REJECT: original deletes newer ignored-column and scope-column incident migration coverage.

~~~diff
@@ -749,119 +637,3 @@ def test_backup_timeout_bounds_sqlite_busy_wait(tmp_path, monkeypatch):
         source.close()
         locker.rollback()
         locker.close()
-
-
-def test_preflight_accepts_incident_store_ignored_column_migration_variant(tmp_path):
-    db_path = tmp_path / "agent_state.sqlite3"
-    _seed_state(db_path)
-
-    with closing(sqlite3.connect(db_path)) as connection:
-        connection.execute("DROP TABLE agent_incidents")
-        incident_ddl = """CREATE TABLE agent_incidents (
-                                incident_id TEXT PRIMARY KEY,
-                                operation_class TEXT NOT NULL,
-                                error_class TEXT NOT NULL,
-                                signature_hash TEXT NOT NULL,
-                                redacted_message TEXT NOT NULL,
-                                state_revision TEXT NOT NULL,
-                                attempts INTEGER NOT NULL,
-                                evidence_ids TEXT NOT NULL,
-                                root_cause TEXT,
-                                verified_fix TEXT,
-                                confidence REAL NOT NULL,
-                                resolved INTEGER NOT NULL,
-                                created_at REAL NOT NULL,
-                                updated_at REAL NOT NULL,
-                                expires_at REAL,
-                                affected_paths TEXT NOT NULL DEFAULT '[]'
-                            , ignored INTEGER NOT NULL DEFAULT 0)"""
-        connection.execute(incident_ddl)
-        connection.executescript(
-            """
-            CREATE INDEX idx_agent_incidents_fp
-                ON agent_incidents (error_class, operation_class, signature_hash, state_revision);
-            CREATE INDEX idx_agent_incidents_lookup
-                ON agent_incidents (operation_class, signature_hash, state_revision, updated_at DESC);
-            CREATE INDEX idx_agent_incidents_recent
-                ON agent_incidents (operation_class, signature_hash, updated_at DESC);
-            """
-        )
-        connection.execute(
-            "INSERT INTO agent_incidents (incident_id, operation_class, error_class, "
-            "signature_hash, redacted_message, state_revision, attempts, evidence_ids, "
-            "confidence, resolved, created_at, updated_at, affected_paths) "
-            "VALUES ('legacy-incident', 'command', '', '', '', '', 0, '[]', 0, 0, 1, 1, '[]')"
-        )
-        connection.commit()
-        incident_sql = connection.execute(
-            "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_incidents'"
-        ).fetchone()[0]
-
-    incident_hash = hashlib.sha256(
-        " ".join(str(incident_sql).split()).casefold().encode("utf-8")
-    ).hexdigest()
-    assert incident_hash == "43c461c1906a1c11a5558889e2c49478942b940c3e98d0a926848ead3010a63e", repr(incident_sql)
-
-    before = _sqlite_file_snapshot(db_path)
-    state = AgentStateStore(db_path)
-    state._preflight_schema_read_only()
-    assert _sqlite_file_snapshot(db_path) == before
-    IncidentStore(state)
-    backups = list(tmp_path.glob("agent_state.sqlite3.migration-v0-v1-*.bak"))
-    assert len(backups) == 1
-    with closing(sqlite3.connect(backups[0])) as backup:
-        assert backup.execute(
-            "SELECT incident_id FROM agent_incidents WHERE incident_id='legacy-incident'"
-        ).fetchone() == ("legacy-incident",)
-        backup_sql = backup.execute(
-            "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_incidents'"
-        ).fetchone()[0]
-        assert hashlib.sha256(
-            " ".join(str(backup_sql).split()).casefold().encode("utf-8")
-        ).hexdigest() == incident_hash
-    with closing(sqlite3.connect(db_path)) as migrated:
-        columns = {str(row[1]) for row in migrated.execute("PRAGMA table_info(agent_incidents)")}
-        assert {"ignored", "repository_key", "tenant_key"}.issubset(columns)
-        assert migrated.execute(
-            "SELECT incident_id FROM agent_incidents WHERE incident_id='legacy-incident'"
-        ).fetchone() == ("legacy-incident",)
-
-
-def test_preflight_accepts_incident_store_scope_columns_variant(tmp_path):
-    db_path = tmp_path / "agent_state.sqlite3"
-    _seed_state(db_path)
-
-    with closing(sqlite3.connect(db_path)) as connection:
-        connection.execute("DROP TABLE agent_incidents")
-        connection.execute(
-            """CREATE TABLE agent_incidents (
-                incident_id TEXT PRIMARY KEY,
-                operation_class TEXT NOT NULL,
-                error_class TEXT NOT NULL,
-                signature_hash TEXT NOT NULL,
-                redacted_message TEXT NOT NULL,
-                state_revision TEXT NOT NULL,
-                attempts INTEGER NOT NULL,
-                evidence_ids TEXT NOT NULL,
-                root_cause TEXT,
-                verified_fix TEXT,
-                confidence REAL NOT NULL,
-                resolved INTEGER NOT NULL,
-                created_at REAL NOT NULL,
-                updated_at REAL NOT NULL,
-                expires_at REAL,
-                affected_paths TEXT NOT NULL DEFAULT '[]'
-            , ignored INTEGER NOT NULL DEFAULT 0, repository_key TEXT NOT NULL DEFAULT '', tenant_key TEXT NOT NULL DEFAULT '')"""
-        )
-        connection.commit()
-        incident_sql = connection.execute(
-            "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_incidents'"
-        ).fetchone()[0]
-    incident_hash = hashlib.sha256(
-        " ".join(str(incident_sql).split()).casefold().encode("utf-8")
-    ).hexdigest()
-    assert incident_hash == "b3f8fa5c1723ab3addf421e28c3e9e07d232a7734cc95c247aed04224f3856b0"
-
-    before = _sqlite_file_snapshot(db_path)
-    AgentStateStore(db_path)._preflight_schema_read_only()
-    assert _sqlite_file_snapshot(db_path) == before
~~~

### Archived tests/test_t05_memory_delete_artifacts.py hunk 1

RETAIN: public record creates event and searchable projection; original private seed bypasses writer integration.

~~~diff
@@ -14,19 +14,16 @@ def test_scoped_delete_purges_fts_and_embedding_artifacts(tmp_path):
     root = tmp_path / "repo"
     root.mkdir()
     store = MemoryStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
-    record = store.record(
-        MemoryRecord.create(
-            kind=MemoryKind.FACT,
-            scope=AgentScope.REPOSITORY,
-            scope_id=str(root),
-            key="delete-search-artifacts",
-            value="sensitive searchable memory",
-            source="user",
-            provenance={"root": str(root), "tenant": "tenant-a"},
-        ),
-        actor="user",
-        idempotency_key="delete-search-artifacts",
+    record = MemoryRecord.create(
+        kind=MemoryKind.FACT,
+        scope=AgentScope.REPOSITORY,
+        scope_id=str(root),
+        key="delete-search-artifacts",
+        value="sensitive searchable memory",
+        source="user",
+        provenance={"root": str(root), "tenant": "tenant-a"},
     )
+    store._save_record(record)
     assert store.set_embedding(record.record_id, [0.25, 0.75])
     with closing(connect_sqlite(store.state_store.db_path)) as con:
         fts_exists = con.execute(
~~~

### Archived tests/test_t05_memory_delete_artifacts.py hunk 2

REJECT: successful replay after deletion contradicts current fail-closed tombstone; retained non-restoration and explicit ValueError guard.

~~~diff
@@ -98,8 +95,8 @@ def test_replaying_record_after_delete_does_not_restore_memory_or_fts(tmp_path):
         tenant="tenant-a",
     )

-    with pytest.raises(ValueError, match="memory record was deleted and cannot be replayed"):
-        store.record(record, actor="user", idempotency_key="delete-replay-record")
+    replayed = store.record(record, actor="user", idempotency_key="delete-replay-record")
+    assert replayed.record_id == record.record_id
     assert store.get(
         record.record_id,
         scope=AgentScope.REPOSITORY,
~~~

### Archived tests/test_t05_memory_delete_artifacts.py hunk 3

RETAIN: public record-based rollback fixture verifies writer/search integration, not private projection bypass.

~~~diff
@@ -134,30 +131,26 @@ def test_delete_cleanup_failure_rolls_back_memory_and_search_state(tmp_path, mon
     root.mkdir()
     db_path = tmp_path / "agent_state.sqlite3"
     store = MemoryStore(AgentStateStore(db_path))
-    record = store.record(
-        MemoryRecord.create(
-            kind=MemoryKind.FACT,
-            scope=AgentScope.REPOSITORY,
-            scope_id=str(root),
-            key="rollback-delete-primary",
-            value="retain after failed deletion",
-            source="user",
-            provenance={"root": str(root), "tenant": "tenant-a"},
-        ),
-        actor="user",
+    record = MemoryRecord.create(
+        kind=MemoryKind.FACT,
+        scope=AgentScope.REPOSITORY,
+        scope_id=str(root),
+        key="rollback-delete-primary",
+        value="retain after failed deletion",
+        source="user",
+        provenance={"root": str(root), "tenant": "tenant-a"},
     )
-    related = store.record(
-        MemoryRecord.create(
-            kind=MemoryKind.FACT,
-            scope=AgentScope.REPOSITORY,
-            scope_id=str(root),
-            key="rollback-delete-related",
-            value="retain relation",
-            source="user",
-            provenance={"root": str(root), "tenant": "tenant-a"},
-        ),
-        actor="user",
+    related = MemoryRecord.create(
+        kind=MemoryKind.FACT,
+        scope=AgentScope.REPOSITORY,
+        scope_id=str(root),
+        key="rollback-delete-related",
+        value="retain relation",
+        source="user",
+        provenance={"root": str(root), "tenant": "tenant-a"},
     )
+    store._save_record(record)
+    store._save_record(related)
     store.record_relation(record.record_id, "related_to", related.record_id)
     assert store.set_embedding(record.record_id, [0.5, 0.5])
     with closing(connect_sqlite(db_path)) as con:
~~~

### Archived tests/test_t05_memory_fts_atomicity.py hunk 2

RETAIN: master additionally snapshots event cursor; original removal adds no FTS rollback behavior.

~~~diff
@@ -66,14 +65,6 @@ def test_record_update_fts_write_failure_rolls_back_durable_record_and_preserves
             "SELECT COUNT(*) FROM agent_events WHERE idempotency_key = ?",
             ("failed-update",),
         ).fetchone()[0]
-        stream_id = con.execute(
-            "SELECT stream_id FROM agent_events WHERE idempotency_key = ?",
-            ("before-update",),
-        ).fetchone()[0]
-        cursor = con.execute(
-            "SELECT last_seq FROM agent_event_cursors WHERE stream_id = ?",
-            (stream_id,),
-        ).fetchone()
     finally:
         con.close()
~~~

### Archived tests/test_mcp_command_operation_acceptance.py hunk 1

RETAIN: master accounts second bounded telemetry call; primary repair-policy arguments remain asserted.

~~~diff
@@ -80,28 +80,22 @@ def test_mcp_command_auto_fix_forwards_bounded_repair_policy(monkeypatch: Any, t
         auto_rollback=False,
     )

-    assert len(backend.calls) == 2
-    command_call, accounting_call = backend.calls
-    assert command_call == (
-        "/api/command",
-        _expected_payload(
-            "auto_fix",
-            root,
-            "pytest tests/test_parser.py",
-            task_id="task-1",
-            criterion="parser regression passes",
-            auto_fix=True,
-            max_attempts=2,
-            auto_rollback=False,
-        ),
-        {"timeout": 77.0},
-    )
-    accounting_path, accounting_payload, accounting_options = accounting_call
-    assert accounting_path == "/api/telemetry/tool-accounting"
-    assert isinstance(accounting_payload.get("batch_id"), str)
-    assert accounting_payload["batch_id"]
-    assert accounting_payload["events"] == []
-    assert accounting_options == {"timeout": 0.25}
+    assert backend.calls == [
+        (
+            "/api/command",
+            _expected_payload(
+                "auto_fix",
+                root,
+                "pytest tests/test_parser.py",
+                task_id="task-1",
+                criterion="parser regression passes",
+                auto_fix=True,
+                max_attempts=2,
+                auto_rollback=False,
+            ),
+            {"timeout": 77.0},
+        )
+    ]
     _assert_response_fields(result, response)
     assert result["success"] is True
~~~

### Archived tests/test_rag_work_operation_acceptance.py hunk 1

RETAIN: accounting reporter stub isolates RAG backend forwarding test; removing it restores no behavior.

~~~diff
@@ -22,7 +22,6 @@ class _Backend:

 def _enable_rag(monkeypatch: Any, backend: _Backend) -> None:
     monkeypatch.setattr(mcp_server, "CLIENT", backend)
-    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
     monkeypatch.setattr(mcp_server.FEATURES, "rag", True)
     monkeypatch.setattr(mcp_server.FEATURES, "tasks", False)
     monkeypatch.setattr(mcp_server, "_timeout", lambda kind: {"quick": 11.0, "long": 77.0}[kind])
~~~

### Archived tests/test_rag_work_operation_acceptance.py hunk 2

RETAIN: accounting reporter stub isolates work backend forwarding test; original backend arguments remain asserted.

~~~diff
@@ -30,7 +29,6 @@ def _enable_rag(monkeypatch: Any, backend: _Backend) -> None:

 def _enable_work(monkeypatch: Any, backend: _Backend) -> None:
     monkeypatch.setattr(mcp_server, "CLIENT", backend)
-    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
     monkeypatch.setattr(mcp_server.FEATURES, "work_orchestrator", True)
     monkeypatch.setattr(mcp_server.FEATURES, "tasks", False)
     monkeypatch.setattr(mcp_server, "_timeout", lambda kind: {"quick": 11.0, "long": 77.0}[kind])
~~~

### Archived tests/test_t12_llama_model_inventory.py hunk 1

RETAIN: pytest import needed by deadline regression.

~~~diff
@@ -4,7 +4,6 @@ from contextlib import nullcontext
 from pathlib import Path
 import json
 import time
-import pytest

 import local_ai_hub.llama_cpp as llama_cpp_module
 from local_ai_hub.llama_cpp import LlamaCppRouter
~~~

### Archived tests/test_t12_llama_model_inventory.py hunk 2

REJECT: original deletes newer no-HTTP-after-deadline test; cache/fresh inventory tests already integrated.

~~~diff
@@ -75,23 +74,6 @@ def test_force_fresh_model_info_ignores_cached_empty_snapshot(monkeypatch) -> No
     assert models["fresh-served-id"]["status"]["value"] == "loaded"


-def test_strict_model_inventory_raises_when_deadline_expires_before_http(monkeypatch) -> None:
-    url = "http://127.0.0.1:12438"
-    router = LlamaCppRouter(
-        {"llama_cpp": {"mode": "auto", "models": {"model": {"url": url}}}}
-    )
-    clock_values = iter((50.0, 51.0))
-    monkeypatch.setattr(llama_cpp_module.time, "monotonic", lambda: next(clock_values))
-    monkeypatch.setattr(
-        llama_cpp_module,
-        "_open_interruptible_response",
-        lambda *_args, **_kwargs: pytest.fail("expired inventory must not start HTTP"),
-    )
-
-    with pytest.raises(TimeoutError, match="inventory deadline expired"):
-        router._model_info(url, force_refresh=True, strict=True, deadline=50.5)
-
-
 def test_unload_model_routes_unmapped_served_id_to_its_configured_endpoint(monkeypatch) -> None:
     url = "http://127.0.0.1:12438"
     router = LlamaCppRouter(
~~~

### Historical fake configuration implementation

Nonintegrable exact internals: constructing SimpleNamespace instead of production ProjectSettings, mutating parsed verification_rules, inventing a digest, and replacing sys.modules omits current owner validation. The fixture public interface is actively restored using the real owner; original module is retained here only to recover its historical intent.

~~~python
from __future__ import annotations

import hashlib
import importlib
import json
import sys
import tomllib
import types
from pathlib import Path
from types import SimpleNamespace


class ProjectConfigError(ValueError):
    pass


def resolve_project_context(project_root: str | Path, _state_dir: str | Path):
    root = Path(project_root).resolve()
    config_path = root / ".local-ai.toml"
    try:
        raw = config_path.read_bytes()
        parsed = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ProjectConfigError("invalid test project config") from exc
    commands = parsed.get("commands", {})
    rules = parsed.get("verification_rules", {})
    if not isinstance(commands, dict) or not isinstance(rules, dict):
        raise ProjectConfigError("test project config sections must be tables")
    required = rules.pop("required_commands", ())
    if not isinstance(required, (list, tuple)):
        raise ProjectConfigError("required_commands must be an array")
    for name in required:
        if not isinstance(name, str):
            raise ProjectConfigError("required command names must be strings")
        rules.setdefault(name, (name,))
    settings = SimpleNamespace(
        commands=commands,
        verification_rules={
            name: tuple(value) if isinstance(value, list) else value
            for name, value in rules.items()
        },
        env=parsed.get("env", {}),
        env_references={},
    )
    digest = hashlib.sha256(
        json.dumps(
            {"root": str(root), "config": parsed},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return SimpleNamespace(
        root=root,
        settings=settings,
        config_digest=digest,
        resolution=SimpleNamespace(error_codes=()),
    )


def install_t09_project_config_test_fixture(monkeypatch):
    """Provide the T21-owned project-config interface for T09 contract tests only."""
    module = types.ModuleType("local_ai_hub.project_config")
    module.ProjectConfigError = ProjectConfigError
    module.resolve_project_context = resolve_project_context
    monkeypatch.setitem(sys.modules, module.__name__, module)
    package = importlib.import_module("local_ai_hub")
    monkeypatch.setattr(package, "project_config", module, raising=False)
    return module
~~~

## Handoff boundary

Candidate commit is a child of merge 6b237f6f on the existing branch. Resolve its SHA with git log -1 --format=%H -- this note. Master pin and original/audit pin refs above remain stable. No unmerged index entries expected; final handoff records actual post-commit checks. No stash disposal is authorized by this document.
