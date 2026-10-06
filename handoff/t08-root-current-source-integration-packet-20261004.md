# T08 Root-Current Source Integration Packet — 2026-10-04

## Scope

- Candidate: `C:\Users\Adam\.codex\worktrees\t08-agent-os\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- Root-current: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Source-only. No root writes; no tests started while preparing this packet.
- Three stale test preimages excluded. No test hunk or test path is in the attached patch.

## Independently owned T08 source hunk

Only source patch: `handoff/t08-blackboard-trust-source-only-root-current-20261004.patch`, SHA-256 `ab36ae6548ec7d5a901fc7fdf0af3019604864a1d530ccd43dee4655babd3105`. Patch contains exactly `src/local_ai_hub/agent_context.py` blackboard trust labeling/provenance hunk. It adds unverified-note wording, lowers confidence to `0.25`, records board/section/author/version, sets `trust_level="unverified"`. No `coordination_id` hunk.

| Path | Root HEAD base SHA-256 | Source-only patch post SHA-256 | Current root working SHA-256 | Candidate working SHA-256 |
|---|---|---|---|---|
| `src/local_ai_hub/agent_context.py` | `07a7b30b31621cdff5b1aec6a899f3e158c2f542228d80a6c815eb0478ba4811` | `ba5a992d175e4f79ffd4b023cd9988545696acfa26ce1fc873988061b85b73fb` | `24781a491cafa5483b2dd09f7a233e9f3365152b4cddfca8f31cedb55655fa0b` | `fee97b4d16388337d046d0c0c4d04f3ec34b087011eeee0363a6f0dbf7099317` |

Base/post were measured from root HEAD in an isolated temporary copy with `core.autocrlf=false`; apply and reverse round-trip restored exact base SHA. Current root working tree already contains this hunk: root-current apply-check fails as already present; reverse-check passes. Root working file also contains unrelated dirty hunks; do not replace it with candidate file. Hunk origin is T08 user-approved blackboard trust change, recorded by `artifacts/t08-blackboard-trust-label-root-current.patch` and the 2026-10-02 selector receipt. This task did not write root.

## T08 event/task source preserved; no patch needed

Current candidate and root source bodies match for these independently owned hunks. Block SHA is identical on both sides; no whole-file transplant:

| Path / hunk | Root current file SHA-256 | Candidate file SHA-256 | Root hunk SHA-256 | Candidate hunk SHA-256 | Disposition |
|---|---|---|---|---|---|
| `agent_events.py` / `AgentStateStore.append_in_transaction` | `1b8e63a5ff329090801cd7f19e7df7a95e42ac0034465ac5fa06d566b279ccf4` | `2102bcb71bb5521034355b3bad6d88d08003cc7509e7e39ce6c1580ca1055056` | `f8b679de39b400c77a3905e2cea34587ef55057cd52c575ed96ae6e89d54319c` | same | Already identical. |
| `agent_events.py` / `AgentStateStore.ordered_event_publication` | same | same | `2855d98951ab922f4b308da51bfba5ea3e25bc0881b98c51704ba88798502d0e` | same | Already identical; publication rejection behavior preserved. |
| `agent_tasks.py` / `TaskStore.add_verification_receipt_in_transaction` | `599812f8cd345ffa0087581cae60e073ae34c6914a344efd989baa937e3a1b0c` | `a86ff3b368c18eccead725cf30ed4bf793489324e209fe4a7ebf38820665c7ca` | `600376eab89b7fa189954c6409fddd538bb3275a535773c744587754620a069d` | same | Already identical; T09 verification store untouched. |
| `agent_tasks.py` / `TaskStore.transition` | same | same | `7972c5aff97335543755d9687de503e584b52d1be2369176765692af259f5f1c` | same | Already identical. |
| `agent_incidents.py` / `IncidentStore.capture` | `899092ff78a0297e2000fb3286de81d8b36cd6d3cb7b39f6ef5636aae39ef647` | `1ade1aa5b63f008ff9b7a930db06725054dda740f78279d1459e1ff3249c2a07` | `7b631ff27892e7a2ce466bee6211e8ce32e4aab3df143823dfc74ed098bf9817` | same | Root provenance capture already matches. |

Root `event_page()` is newer than candidate (`dict` events plus `through_seq` bound); do not transplant candidate implementation. `TaskStore._commit_update` differs due root task-search-index work; exclude. `IncidentStore.find_negative_knowledge` differs; keep root fail-closed scope behavior. The authorized `repository_root=cwd, tenant=tenant` command-capture hunk is already present in root; no caller patch. These exclusions avoid overwriting root-current work or weakening ordered-write/publication rejection behavior.

## Ownership exclusions and dependencies

- T05-owned: `agent_memory.py`, `sqlite_support.py`, incident schema/allowlist migration, memory identity contract and migration fault matrix. No T05 hunk included. Cache test assertion patch remains separate pending T05 reconciliation. Separate allowlist patch `handoff/t08-root-current-incident-schema-allowlist-20261004.patch` SHA-256 `403a2b3543943d13c19205f5ba336bd9a0b2823de4daade5556fbb95af25dcd5`: current-root apply-check PASS, reverse-check FAIL (not applied); T05 review remains required.
- T09-owned: `agent_verification.py` and T09 receipt-store paths. No T09 hunk included.
- Incident-memory lookup remains fail-closed until root/tenant-scoped `find_negative_knowledge` caller contract is available.
- No test paths or stale test preimages included. Existing test patches/receipts remain separate artifacts.

## Receipts, kept separate by workspace

### Candidate worktree

Exact nine-file T08 suite: **52 passed in 19.65s**, exit `0`, candidate HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`. Exact command, test hashes, and inherited-dirty inventory: [candidate receipt](t08-assigned-worktree-suite-receipt-20261004.md), receipt SHA-256 `3a1dea6fba9127aeb39a2d35d3f4ca70313f3e304b9bc4acade1e64c03aaa77a`.

Previously authorized blackboard selector: `tests/test_agent_task_memory_adoption.py::test_unscoped_blackboard_is_unverified_and_cannot_bypass_task_memory_scope`, candidate result `1 passed in 1.43s`; see `artifacts/t08-blackboard-trust-overlay-selector-receipt-20261002-r2.json`. Historical candidate receipt only.

### Root-current isolated validation copy

No root test was run for this packet. Existing isolated-copy receipts remain separate:

- Event recovery/page: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_t08_crash_after_commit.py::test_process_exit_after_commit_before_publish_recovers_event tests/test_agent_t08_crash_after_commit.py::test_process_exit_after_task_commit_before_publish_recovers_projection_and_cursor tests/test_agent_t08_event_page_snapshot.py::test_event_page_through_seq_excludes_events_appended_between_pages` — `4 passed in 0.85s`.
- Cache isolation: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_t08_cache_isolation.py` — `2 passed in 0.83s`.
- Incident migration: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_t08_migration_recovery.py::test_legacy_incident_schema_is_allowlisted_and_preserved_on_migration` — `1 passed in 0.25s`. This selector used a separate T05-overlap allowlist hunk in the isolated copy; not part of this source patch.


