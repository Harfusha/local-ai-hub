# T21 root-current handoff

Date: 2026-10-01

## Scope and current result

T21 core scope is project/worktree configuration, path-hint schema/resolution, privacy-safe usage projection, and T21-owned tests. No root/master files were edited by this handoff. `/api/context/pack` remains outside scope.

Registered T21 checkout: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`, branch `codex/t21-project-config`, `HEAD 824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.

Earlier T21 candidate patch: `T21-stash0-core-reconcile.patch`, SHA-256 `AF066F1B1C2A942C4091F7B19C9C2B9B29EA543654AF4DEB42E21CFAE4DF8218`. Scope: `docs/PROJECT_CONFIGURATION.md`, `src/local_ai_hub/project_config.py`, `tests/test_project_config.py`, `tests/test_project_path_hints.py`.

Current root is dirty and has advanced overlapping changes. Against current root, `git apply --reverse --check` fails on these four paths; `git apply --check --3way` also fails because current index/worktree differs. Treat old patch as historical evidence only; do not apply it to current root. No replacement code patch is safe or needed based on the current source audit below.

## Core contract

`PathHintUsage` keeps candidate `paths` as control data. Its telemetry projection contains only `hint_used: bool`, `fallback_used: bool`, and `hint_helped: None`. It normalizes the two usage flags and never emits paths. Consumers must not log the dataclass or candidate paths. `hint_helped` remains unknown until a consumer measures usefulness. A request hint may carry any subset of optional provenance fields; persisted learned hints still require complete provenance.

Path hints reorder candidate paths only. They never narrow a complete result set, authorize reads, or bypass path policy. Consumers must continue to enforce `path_is_allowed(...)` and `may_descend(...)`; broader fallback remains required when the prioritized pass has no useful result.

The persisted-hint read uses an existing-database read-only connection. A removed/missing database or table yields no hints without recreating state; unrelated SQLite operational errors still surface. Expired hints remain excluded.

## Root-current source evidence (read-only)

- `src/local_ai_hub/project_config.py:267-278`: typed `PathHintUsage` and path-free telemetry fields.
- `src/local_ai_hub/project_config.py:1353-1364,1486-1489`: read-only existing database connection and missing-database race handling.
- `tests/test_project_path_hints.py:338-394`: expired persisted hint and deletion-after-existence-check regression cases.
- `tests/test_project_path_hints.py:17-45`: telemetry projection excludes paths and normalizes malformed values.
- `tests/test_project_config.py:104-156`: linked-worktree config inheritance and primary-worktree discovery.

These are source-presence checks only; no root tests were rerun during this continuation.

## T21 validation receipts

- Existing T21 focused config/path-hint/preprocess receipt: **116 passed in 8.32 s**.
- Fresh current T21 worktree run, Oct 1 2026:
  `$env:PYTHONPATH="C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\src"; python -B -m pytest -q -p no:cacheprovider --tb=short "C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_project_config.py" "C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_project_path_hints.py" "C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_project_config_service_integration.py" "C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_t21_project_config_preprocess.py"`
  Result: **116 passed in 9.99 s**, exit 0. Ran only inside registered T21 worktree; no root tests.
- Verification-rules contract suite after T09 API handoff: prior receipt **6 passed in 3.79 s**, not rerun; same-path `verification_rules.py` ownership remains T09-gated.
- Completion adapter/handler candidate E2E, Oct 1 2026: standalone `tests/test_verification_rules.py` **6 passed in 5.16 s**, exit 0. Combined with all T21 core selectors, the command below passed **122 in 16.32 s**, exit 0:
  `$env:PYTHONPATH="C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\src"; python -B -m pytest -q -p no:cacheprovider --tb=short "C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_project_config.py" "C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_project_path_hints.py" "C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_project_config_service_integration.py" "C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_t21_project_config_preprocess.py" "C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_verification_rules.py"`
- This candidate suite covers completion-rule evaluation, failed-receipt non-mutation, HTTP completion hook, MCP completion hook, and invalid project configuration. It ran only in the T21 worktree. T09-owned `agent_tasks.py`/`agent_verification.py` were not edited; no root acceptance is implied.
- The first race regression failed before the fix with missing-table `sqlite3.OperationalError`; after the fix, race plus expired-hint pair passed: **2 passed in 0.18 s**.
- T21 core patch reverse-check and core `git diff --check` pass in T21 worktree. Current-root reverse-check is **FAIL**, as recorded above.

## Patch queue audit (T21 worktree only; no patch applied)

| Artifact | SHA-256 | Paths | Disposition |
|---|---|---|---|
| `T21-stash0-core-reconcile.patch` | `AF066F1B1C2A942C4091F7B19C9C2B9B29EA543654AF4DEB42E21CFAE4DF8218` | `docs/PROJECT_CONFIGURATION.md`; `src/local_ai_hub/project_config.py`; `tests/test_project_config.py`; `tests/test_project_path_hints.py` | T21 core. Reverse-check passes in T21 worktree; old patch does not apply/reverse-check against current root. Keep as owner handoff evidence; root integration belongs to T20. |
| `T21-root.patch`; `t21-path-hints-consumer.patch` | `6FFC67C866527C9751475D853F8AF314DABBA00CFDDD3582F151E45F8BE9B1AF` | `tests/test_mcp_repo_path_hints.py` | Consumer integration test; outside current T21 core/test scope. Keep unapplied pending owning consumer integration. |
| `T21-root-hint-candidates.patch` | `9F48207762F7596A0F020073FAE366253140EB493FC8A27E2778D4108B660D77` | `src/local_ai_hub/services.py` | Consumer adapter; owner boundary closed. Keep unapplied. |
| `T21-root-imports-fix.patch` | `419DA63992D1741F7578FB0C6D72DA5446416E2A4D3779EFD7818698F0F976C0` | `tests/test_mcp_repo_path_hints.py` | Consumer integration test; outside current scope. Keep unapplied. |
| `T21-root-journal-fixture.patch` | `FA7BAB8C11EB4F267EED769584C7DC2E1C422A90A619CC2AADA3DA8CAB1DE61A` | `tests/test_mcp_repo_path_hints.py` | Consumer integration fixture; outside current scope. Keep unapplied. |
| `T21-root-search-scope.patch` | `1FF2EA563B23D00EA684B43D0E611BC089A26B7F8F2413113F1172EB2F642D02` | `src/local_ai_hub/services.py` | Consumer adapter; owner boundary closed. Keep unapplied. |

The two equal-SHA consumer patch names are duplicate artifacts, not separate work. T03's release covers only its own `local_ai_repo(search)` contract/forwarding hunks; it does not transfer T21 `services.repo_search` adapter ownership. T04 asked for a boundary/release for a `services.repo_search` consumer hunk; current user scope keeps adapters untouched, so T21 grants no release here. `/api/context/pack` excluded.

## T20 root-current patch review (read-only, 2026-10-01)

Observed root `C:\Users\Adam\.local-ai-hub`, branch `master`, `HEAD 98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Root already has T21-era path normalization in `_relative_pattern`, read-only persisted-hint reads/race handling, the project config limit check, and several matching tests. Do not reapply those hunks.

Minimal current-root delta: [T21-root-current-core-minimal.patch](T21-root-current-core-minimal.patch), SHA-256 `62BC6605B14A1506DC6EA792D7D2DB6971F93D3A3B76A544064A473BDDCA1134`. It changes only `src/local_ai_hub/project_config.py`: `_safe_config_file` captures device/inode identity; `_read_layer` opens no-follow/nonblocking, verifies regular file and opened identity before parsing, retains byte cap, and safely closes descriptors. Read-only `git apply --check` against observed root `HEAD` passed; patch was not applied. It does not alter path-hint validator: candidate variant permits contained absolute paths, while current root contract rejects absolute paths. Keep root contract; do not transplant that validator hunk.

Suggested serial root selector set after T20 applies/reviews this delta (not run by T21):

```powershell
$env:PYTHONPATH='C:\Users\Adam\.local-ai-hub'
python -B -m pytest -q -p no:cacheprovider --import-mode=importlib --tb=short -c 'C:\Users\Adam\.local-ai-hub\pyproject.toml' 'C:\Users\Adam\.local-ai-hub\tests\test_project_config.py' 'C:\Users\Adam\.local-ai-hub\tests\test_project_path_hints.py' 'C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_project_config.py::test_config_loader_rejects_file_replaced_after_containment_check' 'C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_project_config.py::test_config_loader_rejects_unavailable_file_identity' 'C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_project_config.py::test_config_loader_rejects_unavailable_open_file_identity' 'C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_project_config.py::test_config_loader_survives_descriptor_cleanup_failure'
```

Root may still be changing under T20, so re-check patch applicability in its serialized integration slot before applying. Candidate-only completion E2E receipt remains **122 passed in 16.32 s**; `agent_tasks.py`/`agent_verification.py` stayed unedited. Root completion-adapter selectors require T20/T09 reconciliation of their `verification_rules.py` variants first.

## Remaining root E2E seam (read-only review, 2026-10-01)

Root task-complete HTTP action at `src/local_ai_hub/http_server.py:2658-2665` calls `APP.agent_tasks.complete(...)` without using request `payload.root`. Root `_verify_completion` resolves config from task checkpoint `worktree.repo_root`, checkpoint `repo_root`, then an existing `task.context.repository_id`. T21 candidate HTTP handler at `http_server.py:2300-2347` explicitly selects request `root` (fallback task context), obtains current revision, calls `complete_task_with_project_rules(...)` with that root and verification-store `state_dir`, then mutates task only after receipt evaluation. Therefore, when completion request supplies `root` absent from task context/checkpoint, root handler does not bind project verification rules to that request root. This is the concrete completion E2E gap to reconcile with T09; T21 did not edit the T09-owned evaluator, HTTP handler, or root.

No missing core path-hint route/service behavior was found in the read-only root scan: `LocalAIServices.repo_search` accepts hints, resolves project context and ranks/falls back through path policy; `/api/search` forwards the field; MCP private repo-search dispatch forwards it through `HubClient.post`. Root already has path-hint tests in `tests/test_api_search_path_hints.py`, `tests/test_client_path_hints.py`, `tests/test_mcp_repo_path_hints.py`, `tests/test_repo_tools_path_hints.py`, `tests/test_t10_repo_search_path_hints.py`, plus config-service tests. T20 should run these in its serialized root slot after owner review.

Recommended additional completion selectors for T20 after T09 reconciliation (not run by T21): root `tests/test_agent_tasks.py::test_completed_forwards_project_rules_to_compatible_verifier`, root `tests/test_project_verification_rules.py::test_project_completion_forwards_config_and_task_generation_to_t09_store`, and candidate `tests/test_verification_rules.py::test_http_task_completion_uses_project_verification_rules`, `::test_completion_handler_does_not_mutate_task_when_receipts_fail`, `::test_completion_handler_uses_persisted_receipts_and_completes_task`. Root currently calls task completion through `TaskStore`; candidate handler selectors specifically verify explicit request-root propagation and must not be called root PASS until the T09/T21 handler seam is reconciled.

Targeted candidate verification, 2026-10-01: `$env:PYTHONPATH="C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\src"; python -B -m pytest -q -p no:cacheprovider --tb=short "C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_verification_rules.py::test_http_task_completion_uses_project_verification_rules"` => **1 passed in 2.57 s**, exit 0. This verifies candidate HTTP handler selects `payload.root` and forwards resolved project `verification_rules` and configured command criteria to receipt evaluation. Candidate-only; root was not tested.

## Master-plan acceptance status

- T21 master-plan items 395-399 and 401-403 are checked in the existing plan; current core suite receipt above covers resolver, typed schema, path safety, telemetry privacy, hint reuse, linked-worktree config and T06 candidate service seam.
- Item 400 remains unchecked: optional `path_hints` exposure across all eligible owner schemas/routes is not T21 core work and cannot be completed while T03/T14/T15/T16/T19 consumer files remain owner-gated. T03's exact narrow release is recorded above; it does not release other adapters.
- Item 404 remains unchecked in the shared plan. T21-owned core tests pass; broader consumer/schema/route/install-update documentation acceptance still needs owner releases and T20 root integration receipts. Candidate worktree tests do not establish root acceptance.
- Root integration remains T20-owned. No root file or root test was touched during this continuation.

## Path-to-owner dependency matrix

| Path(s) | Owner / boundary | T21 action |
|---|---|---|
| `src/local_ai_hub/project_config.py`; `docs/PROJECT_CONFIGURATION.md`; `tests/test_project_config.py`; `tests/test_project_path_hints.py` | T21 core | Owned core only; keep changes isolated to registered T21 checkout. |
| `src/local_ai_hub/operation_contracts.py` general contract; non-search `mcp_server.py` | T03 | Generic contract/dispatch stays T03. T21 owns only search-specific path-hint normalization and forwarding symbols. |
| `src/local_ai_hub/http_server.py` (`/api/search`) | T21 search-only; T06 all other routes | T21 may edit only `/api/search` hint forwarding; `/api/context/pack` and other handlers excluded. |
| `src/local_ai_hub/client.py` (`HubClient.post` `/api/search` hint branch) | T21 search-only; T04 general request/transport | T21 may edit path-hint filtering for `/api/search`; preserve T04 request IDs, auth, retry/replay, and transport symbols. |
| `src/local_ai_hub/agent_events.py`; `src/local_ai_hub/agent_tasks.py`; `src/local_ai_hub/agent_verification.py`; `src/local_ai_hub/verification_rules.py` | T09 | Receipt/evaluator owner; no T21 edits. T09 confirms no path-hint overlap and releases only `tests/test_project_path_hints.py` from T09 ownership. |
| `src/local_ai_hub/services.py` (`LocalAIServices.repo_search` path-hint hunk); `work_orchestrator.py`; `repository_test_impact.py`; remaining service symbols | T21 path-hint hunk; T16 remaining service/orchestration | T21 search-path-hint behavior only; no unrelated service edits. |
| `src/local_ai_hub/context_identity.py`; `src/local_ai_hub/task_context.py`; named T14 identity/settings/memory hunks in `agent_context.py` and `context_ledger.py` | T14 | Consumer identity work remains T14-owned; T14 released no path to T21. |
| `src/local_ai_hub/preprocess.py`; `src/local_ai_hub/rag.py`; `src/local_ai_hub/repo_tools.py` | T06/T19 consumer ownership | Frozen; require exact owner release before editing. |
| `src/local_ai_hub/agent_events.py`; `src/local_ai_hub/agent_tasks.py`; `src/local_ai_hub/agent_verification.py`; `src/local_ai_hub/verification_rules.py` | T09; T09 reports no release for the current untracked `verification_rules.py` variant | No T21 edits. |
| `/api/context/pack` route and behavior | Agent 2 owner | Explicitly excluded; do not change. |

The latest user boundary overrides any earlier adapter-release note. Existing dirty consumer changes in T21 checkout are preserved and not treated as permission to edit or integrate them.

## Owner status requests

Current task IDs were checked with `list_threads`. T03 confirmed T21 owns all search path-hint symbols; T03 keeps generic contract and transport scope. T06 confirmed `/api/search` is T21-owned and has no identified overlap; T06 keeps other routes. T04 received a scoped notice for only `HubClient.post` search hint filtering; general request contract remains excluded. T16 received notice for only `LocalAIServices.repo_search` path-hint behavior. T09 previously released `tests/test_project_path_hints.py` from T09 ownership. T14 owns `/api/context/pack`, still excluded. Root remains unmodified by T21.

### Typed adapter contract for owner handoff

`PathHint` is the typed resolver input: `path`, `purpose`, and `scope` are required; `evidence_id`, `provenance`, `repository_revision`, `config_digest`, and `expires_at` are independently optional on request hints. Search accepts at most 64 request hints. Hints can reorder candidates but cannot narrow results or bypass path policy. Persisted learned hints require their full provenance/freshness tuple. Consumers may emit only `PathHintUsage.telemetry_metadata()` (`hint_used`, `fallback_used`, `hint_helped`); never serialize the dataclass or candidate paths. This is an interface contract only and grants no consumer edit permission.

## Read-only stash preservation audit (2026-10-04)

Stash `stash@{0}` is commit `20a15030ecee4f76f4327ef884f4cb15e97752c6`, based on `22fe09c3daedaa7eb594db2dac2b124fbcc8a4c4`, with untracked parent `c165c60d1b2abbf588fb178e80ae44544aef2323`. Exact snapshot patch: [T21-stash0-orchestrator-preserve.snapshot.patch](T21-stash0-orchestrator-preserve.snapshot.patch), SHA-256 `6F02E2A7FB00E478A82E626C7F9A92FBF74C5BBB5D60C2CA5D4AD0465C20FB12`, 85,424 bytes. Patch has seven paths; no apply, pop, or drop performed.

Hunk comparison used the shared merge base `22fe09c3daedaa7eb594db2dac2b124fbcc8a4c4` for stash, candidate HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`, and root HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`. It normalized CRLF to LF and compared base-range plus replacement-line edits. “Exact duplicate” means same edit at the same base range; “overlap” means a different edit touches the same base range; “stash-only” means no exact or overlapping edit was found. Overlaps need owner review; counts do not assert semantic equivalence.

| Stash path | Owner | Stash edits | Candidate comparison | Root comparison |
|---|---|---:|---|---|
| `docs/PROJECT_CONFIGURATION.md` | T21 handoff | 6 | 0 exact, 4 overlapping, 2 stash-only | 4 exact, 2 overlapping |
| `docs/superpowers/specs/2026-09-25-t21-adapter-handoff.md` | T21 handoff | 11 | 0 exact, 6 overlapping, 5 stash-only | 9 exact, 2 overlapping |
| `src/local_ai_hub/project_config.py` | T21 core | 3 | 0 exact, 2 overlapping, 1 stash-only | 3 exact |
| `tests/test_project_config.py` | T21 core | 3 | 0 exact, 3 stash-only | 2 exact, 1 stash-only |
| `tests/test_project_path_hints.py` | T21 core | 3 | 0 exact, 3 stash-only | 3 exact |
| `src/local_ai_hub/verification_rules.py` | T09 boundary | 1 | 1 overlapping, different | 1 overlapping, different |
| `tests/test_project_verification_rules.py` | T09 boundary | 1 | absent from candidate | 1 overlapping, different |

The root already contains exact stash hunks for all three `project_config.py` edits and all three `test_project_path_hints.py` edits. `test_project_config.py` has two exact root duplicates and one stash-only edit. Handoff docs diverged in overlapping hunks. Do not transplant T09 verification-rule variants through T21; candidate file is untracked and owner release is absent. Root integration remains T20-owned.

## Consumer and isolation evidence (2026-10-04)

T21-owned core receipts remain candidate-only: `tests/test_project_path_hints.py` **25 passed in 0.74 s** (includes the CakePHP `/templates/element` routing and repository/worktree-scoped hint cases); config precedence selector **2 passed in 0.32 s**; telemetry privacy selectors **2 passed in 0.48 s**. These prove core hint ordering, full result retention, freshness/scope checks, config inheritance/override, and path-free telemetry in this candidate.

Fresh candidate selectors `test_project_context_never_reads_hub_state_as_configuration` and parameterized `test_search_honors_forced_gitignored_directory` returned **3 passed in 0.66 s**. They prove project-local config stays separate from Hub state and `LocalAIServices.repo_search` preserves visible plus explicitly forced gitignored results with/without request hints. This does not cover HTTP/MCP/client forwarding.

Additional candidate-only isolation selectors: `test_client_cannot_override_namespace_or_tenant_for_memory_find` and `test_lease_renew_and_release_require_the_owner` passed; `test_overlapping_lease_from_same_namespace_conflicts_across_worktrees` failed (`conflicting["success"]` was `True`, expected `False`; suite receipt **2 passed, 1 failed in 14.44 s**, exit 1). Root-cause trace: both `ProjectContext` values have the same derived `coordination_id`, but T03-owned `local_ai_coord` sends only the concrete `root` to `/api/leases/claim_batch`; T06-owned HTTP dispatch passes it to `ScopeLeaseStore`, whose `root_id` hashes the canonical root path. Separate worktree paths therefore use separate lease domains. The adapter/API has no coordination-ID field. This is a cross-owner integration gap, not a T21 core resolver fix. No adapter changed.

One earlier broad T21 selector command returned five progress dots without a captured exit/output. Process was later absent; mark that run **inconclusive**, not passing, and do not repeat it.

Owner evidence read from current task threads: T03 reports its candidate contract selections **108 + 3 passed**, while its root scratch check had **11 failed, 1 passed, 1 error**; T03 identifies a T06 `/api/search` `VAR_POSITIONAL` issue. T04 reports a root client/SSE transport patch with **32 passed in 3.60 s**; that receipt covers transport, not path-hint forwarding. T06 reports no selected checkout/lease and no current `/api/search` fix or passing receipt. T09 releases `tests/test_project_path_hints.py` from T09 ownership; its separate R7 receipt is **20 passed**, not consumer path-hint evidence. Latest T19 status supplied no path-hint consumer receipt. These are owner-reported receipts, not T21 reruns. T20 root GO remains outstanding; no root consumer tests were launched.

## Current owner-only candidate packet (2026-10-04)

T21 partial optional-metadata fix is isolated in [T21-path-hint-partial-metadata-root-current.patch](T21-path-hint-partial-metadata-root-current.patch), SHA-256 `3615028C88E1824D0AD07045B2AE9DA801FE3B38E646CFE00B0AEC7E07AE6157`. Patch stat: `src/local_ai_hub/project_config.py` (+8/-2) and `tests/test_project_path_hints.py` (+31). Candidate HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. Candidate source preimage/postimage SHA-256: `FFD425B1260B285F25B1D121A7C6BCD585C618B5C7E26415E2AD0A7014196B0B` → `088B8AFDF05A331E51C74925884B2B7984DF8BD5E3AD227C82DBDBEEB19289A1`; candidate test preimage/postimage: `43E3612144E38CC6C82EDAABF00E424478308FDF51E189878105186D64D4B606` → `22484A490FACED3D02FF1BB2F041F52831598A6F75573F00EBAC41BDD3539D81`.

Observed root HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; root preimage SHA-256 is `00E80B1342E5E70A66FA8955D95553127E913F56EC693CF527B6AC96053BDBDE` for `project_config.py` and `92EC33C9BB69D75F50ACB9EFBC501C541574D877128112444458CD11576AA5C7` for `test_project_path_hints.py`. `git apply --check` against root returned **0**. No root application occurred.

Exact candidate receipts:

- `tests/test_project_path_hints.py`: **25 passed in 0.74 s**, exit 0; includes `test_cakephp_button_hint_prioritizes_templates_without_narrowing_results` and path-policy/freshness cases.
- `test_request_path_hint_accepts_partial_optional_metadata` plus `test_project_config_precedence_covers_primary_linked_common_and_worktree_layers`: **2 passed in 0.32 s**, exit 0.
- Telemetry selectors `test_path_hint_telemetry_metadata_excludes_candidate_paths` and `test_path_hint_telemetry_metadata_normalizes_malformed_runtime_values`: **2 passed in 0.48 s**, exit 0.
- Tenant/lease isolation selectors: `test_client_cannot_override_namespace_or_tenant_for_memory_find` and `test_lease_renew_and_release_require_the_owner` passed; `test_overlapping_lease_from_same_namespace_conflicts_across_worktrees` failed as detailed above (**2 passed, 1 failed in 14.44 s**, exit 1).

Consumer packet status: T03 owner-only wrapper test patch SHA-256 `7D83E7FF93B4013B1B8C3C1BEB7B9D4AA5AA98582999E6EA73CAB387CA09CD66` changes only `tests/test_mcp_contract_dispatch.py`; its root preflight passed, while production schema/forwarding already exists in root. T03's candidate report says **108 + 3 passed**; its root scratch check reports **11 failed, 1 passed, 1 error**, so it is not root acceptance. T04's current owner report covers client/SSE transport (**32 passed in 3.60 s**) only, not path-hint serialization. T06 has no available owned checkout/lease or current `/api/search` route receipt; T03 reported a `VAR_POSITIONAL` defect in the T06 route check. No T03/T04/T06 adapter diff is part of the T21 patch. Root consumer integration remains gated on explicit owner coordination and T20 GO.

## Search-only acceptance update (2026-10-04)

Latest user correction assigns T21 the search-specific MCP/client/path-hint and `/api/search` symbols. T03 confirms it keeps generic transport/request-ID/client-contract scope; T06 confirms `/api/search` is T21-owned with no identified overlap. T04 got a scoped note for search-only filtering; its generic request/retry/auth/replay code stays excluded. T16 got a scoped search-only notice. `/api/context/pack` remains excluded.

Focused candidate command over `test_project_config.py`, `test_project_path_hints.py`, `test_client_path_hints.py`, `test_mcp_repo_path_hints.py`, `test_t21_search_policy_consumers.py`, and `test_t21_candidate_path_hint_worktree_e2e.py`: **120 passed in 17.46 s**, exit 0. Covers config precedence/worktree inheritance, Hub-state separation, traversal and symlink denial, repo/evidence/revision/config-digest scope, hint expiry, force-include/custom extension/binary policy, CakePHP `/templates/element`, worktree E2E, MCP registered dispatch, `/api/search` forwarding, client serialization/cap/route filtering, and `/api/context/pack` non-forwarding.

Root-current combined patch [T21-root-current-project-path-search.patch](T21-root-current-project-path-search.patch), SHA-256 `EC58A87F2C98EB6455A6F3CBDC8A90A7F1A558D440BEEA1114333AFA12C4A581`; apply-check against dirty root worktree returned 0, no application. Includes core partial-metadata, client search-only route filter, and MCP search-only validation/forwarding. Root HTTP `/api/search` block already matches candidate exactly (slice SHA `B5D054BEB08D6A09E0E67E75B8E7F72F9D3744011FF538237322AE06D5E43DEF`). Patch skips HTTP route hunk; root current files are dirty, so this is not a clean-HEAD integration receipt. See [owner packet](T21-root-current-owner-packet-20261004.md) for exact file preimages/postimages and patch breakdown. No root writes/tests.
