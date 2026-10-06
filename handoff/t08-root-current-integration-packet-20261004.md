# T08 Root-Current Integration Packet — 2026-10-04

## Scope and state

- Candidate: `C:\Users\Adam\.codex\worktrees\t08-agent-os\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- Root-current: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Packet preparation only. No root/master files changed; no tests started.
- Candidate has inherited dirty work across unrelated T tasks. Source ownership below is hunk-level; no whole-file candidate transplant proposed.

## T08 hunks already present in root

Legacy packet `handoff/t08-owner-only-root-current-20261004.patch`, SHA-256 `e13c1e84bd90cfc5d281f755342317bd21169410ca5e9c94b16927527d9f0e36`, contains three T08 test files. Current-root checks: `git apply --check --whitespace=error` fails on all three already-updated files; `git apply --reverse --check --whitespace=error` passes. Do not reapply. Exact root preimage/postimage hashes:

| Path | Original root base SHA-256 | Current root post SHA-256 | T08 delta origin |
|---|---|---|---|
| `tests/test_agent_t08_durable_contract.py` | `2b75e1fbb4ef0dcbc7b82bdfa811de688e54b90a9d23d74f0d4a29bc1a9b2725` | `83e0de2b16d9cdf6a2933712cd2f4665960869167a13d9829684411c7a5dde4e` | T08-owned caller-transaction and receipt atomicity assertions; current root already contains them. |
| `tests/test_agent_t08_live_order.py` | `23472c0021dd415622882e2942f6dc99c153632d93cca5728808aac402f17bf9` | `5eaeabe586107dfdc5a6a2b81c492857a6957fecbe72f545cecfa807e430de3e` | T08 lock-order and publication-rejection cases; current root already contains them. |
| `tests/test_agent_incident_scope.py` | `bce7949947311d44f435b266d7cb74cea22e58fa5c7dd703c5d76450011e00c0` | `c2cb9616f0f1048b0c00767b75ba18a1b4a7a5c3a25ec8b8eb62c122c7b08cc4` | T08 root/tenant incident isolation case; current root already contains it. |

Candidate-vs-root comparison shows these tests are semantically present. Remaining differences are test placement/blank lines and one equivalent query string; no integration hunk needed.

## T08 test hunks still applicable to current root

Patch: `handoff/t08-root-current-test-contracts-20261004.patch`, SHA-256 `0a68270c514a62a05b7c190bf94858bafdaf1461f3653557423aa34785de833e`.

Current root `git apply --check --whitespace=error`: PASS. Current root `git apply --reverse --check --whitespace=error`: FAIL, expected because unapplied. Isolated temporary copy of exact root preimages: `TEMP_APPLY_CHECK=PASS; TEMP_APPLY=PASS; TEMP_REVERSE_CHECK=PASS`. Root stayed unchanged.

| Path | Root-current base SHA-256 | Patch post SHA-256 | T08 hunk origin |
|---|---|---|---|
| `tests/test_agent_t08_crash_after_commit.py` | `9c949a0cb2d9fc5f58fa7264ef1e8f5def13bb657328998591d0a97918849e8f` | `29a966cb7a0484169ea3b954d8f08d8d0492100df76f600a443c72a7781d4bf5` | T08 test assertions follow root `event_page()` dictionary representation (`event["kind"]`, `event["seq"]`). |
| `tests/test_agent_t08_event_page_snapshot.py` | `32a481ed12f35d309a53e6a2203ffb278837ff6e71e432cff5ac5d582b74ed66` | `673f3f748fce4898cd3de80ac083b0009ed9511836895e80d959115ddf35fd88` | T08 snapshot-page assertions use dictionary sequence keys, matching current root API. |
| `tests/test_agent_t08_cache_isolation.py` | `c132ef4f7ca3ebd6fd072b10c4ac5835501ec6660d23d62f95690697561e8e75` | `212121d1a63d1e5d30ef0a3788d37eb644abe56499e8fb85298ce5e4e3faa8a1` | T08 persistence assertion reads exact task-scoped DB row/value; avoids identity-less lookup under T05 fail-closed memory contract. No memory source change. |

These three files are the only current T08 test patch paths. Cache assertion remains contingent on T05 confirming the memory identity contract.

## Production source comparison; no whole-file transplant

| Path | Candidate HEAD blob SHA-256 | Candidate working SHA-256 | Root-current SHA-256 | T08 provenance / disposition |
|---|---|---|---|---|
| `src/local_ai_hub/agent_events.py` | `d6000d3fe9eb4efe0d097814ce6b5ec7db7cacea46e88ab34bd31167902b5bbd` | `2102bcb71bb5521034355b3bad6d88d08003cc7509e7e39ce6c1580ca1055056` | `1b8e63a5ff329090801cd7f19e7df7a95e42ac0034465ac5fa06d566b279ccf4` | T08 `append_in_transaction` and `ordered_event_publication` bodies match root. `event_page` differs because root uses newer dict/`through_seq` contract. No source patch. Incident-schema allowlist hunk is T05-owned; excluded below. |
| `src/local_ai_hub/agent_tasks.py` | `46f0f79aa600031915e50404eebf378b9d070fef89e96fef917ab7fb112a4328` | `a86ff3b368c18eccead725cf30ed4bf793489324e209fe4a7ebf38820665c7ca` | `599812f8cd345ffa0087581cae60e073ae34c6914a344efd989baa937e3a1b0c` | T08 receipt-transaction and transition bodies already integrated. Candidate `_commit_update` includes unrelated newer search-index work; no whole-file patch. Earlier root pre-T08 SHA `5ce57d0ef0b7a17992f604ab67390e481702b0f51393c375102623475fcf280a`. |
| `src/local_ai_hub/agent_incidents.py` | `159eba8b2f440820b6cd71ef37621a8e5c69586d1d8c28a4d3f8bf6be91003c4` | `1ade1aa5b63f008ff9b7a930db06725054dda740f78279d1459e1ff3249c2a07` | `899092ff78a0297e2000fb3286de81d8b36cd6d3cb7b39f6ef5636aae39ef647` | Root/tenant incident scope and capture contract already present. Candidate query SQL differs; no transplant. |
| `src/local_ai_hub/commands.py` | `9eadd896f38bf44566947d1b31b819bd789942e9c39e217ea5d7bc7efdff9939` | `4f96f79a1fcdc72889c7aa2e305b784684f2aefc8815eebd972c52d47e827577` | `83cb8776b086167f1198f127e05c1271abc9e742ba1c0684772357a0bf28a279` | Authorized `repository_root=cwd, tenant=tenant` capture hunk is already in root. `find_negative_knowledge(query, limit=3)` remains unscoped and fails closed; no unsafe caller hunk. |

## T05 dependency and exclusions

- `agent_memory.py` and `sqlite_support.py` remain T05/T14-owned; no T08 source hunk. T05 identity and migration fault-matrix reconciliation is pending.
- `handoff/t08-root-current-incident-schema-allowlist-20261004.patch`, SHA-256 `403a2b3543943d13c19205f5ba336bd9a0b2823de4daade5556fbb95af25dcd5`, has current-root apply-check PASS and reverse-check FAIL (unapplied). Exclude: schema allowlist ownership overlaps T05; obtain T05 review first.
- Root `commands.py` intentionally keeps incident-memory retrieval fail-closed until scoped lookup contract is available.
- Legacy `handoff/t08-owner-only-root-current-20261004.md` records an earlier root preimage and is superseded here. Its old apply receipt is stale; current reverse-check above is authoritative.

## Test receipts already available

- Assigned T08 worktree exact nine-file command and hashes: [assigned-worktree receipt](t08-assigned-worktree-suite-receipt-20261004.md), `52 passed in 19.65s`, exit `0`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`. Candidate evidence only.
- Root-current isolated-copy focused event selectors, exact command from plan: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_t08_crash_after_commit.py::test_process_exit_after_commit_before_publish_recovers_event tests/test_agent_t08_crash_after_commit.py::test_process_exit_after_task_commit_before_publish_recovers_projection_and_cursor tests/test_agent_t08_event_page_snapshot.py::test_event_page_through_seq_excludes_events_appended_between_pages` — `4 passed in 0.85s`.
- Root-current isolated-copy cache selector, exact command from plan: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_t08_cache_isolation.py` — `2 passed in 0.83s`.
- Root-current isolated-copy migration selector: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_t08_migration_recovery.py::test_legacy_incident_schema_is_allowlisted_and_preserved_on_migration` — `1 passed in 0.25s`, with separate T05-overlap allowlist hunk applied only in isolated copy.
- Previous candidate `104-test` pass is recorded in the legacy packet without exact command; treat as historical summary, not reproducible receipt. No test command was run while preparing this packet.
