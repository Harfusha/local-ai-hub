# T21 project config core handoff — 2026-10-02

## Scope and provenance

Single-file core delta from T21 candidate `codex/t21-project-config`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. No root, adapter, or `/api/context/pack` changes are included.

| Path | Owner | Base SHA-256 | Target SHA-256 |
|---|---|---|---|
| `src/local_ai_hub/project_config.py` | T21 core | `03145095FAC22F7A69454069D0C41B5206AC2C78A0508CF6C924339D0FD26D5E` | `FFD425B1260B285F25B1D121A7C6BCD585C618B5C7E26415E2AD0A7014196B0B` |

Base Git blob: `ff7bf849ce6948d7f54876fe4ea779dfd45b0f6c`.

Patch: `T21-project-config-module-20261002.patch`  
Patch SHA-256: `BA6B7DAB963534DC5E137CDB4CC552DB1E85F0C57B4795D27F682C3B987EC49C`.

Apply only when target file matches the base SHA-256/blob. T08 checkout base was not inspected; compatibility there is unconfirmed. Patch is a diff for an existing file, not an add-file export.

## API contract

```python
from local_ai_hub.project_config import PathHint, resolve_project_context

resolve_project_context(
    root: str | os.PathLike[str],
    state_dir: str | os.PathLike[str],
) -> ProjectContext
```

`ProjectContext` exposes `root`, `resolution`, `settings`, `config_digest`, and `coordination_id`. `resolution` contains `settings`, `active_sources`, `error_codes`, and `config_digest`.

`PathHint` required fields: `path`, `purpose`, `scope`. Optional fields: `evidence_id`, `provenance`, `repository_revision`, `config_digest`, `expires_at`.

For `/api/search`, consumer tuple is `purpose="repository_search"`, `scope="repo_search"`. Request schema permits at most 64 closed hint objects. Public MCP schema/dispatch belongs to T03; HTTP/client transport belongs to T04. Core owns runtime validation. T09 may consume only `hint_used`, `fallback_used`, `hint_helped`; never paths. T14 owns context consumers; `/api/context/pack` is excluded.

## Freshness and path safety

- Normalize slash variants and outer whitespace; reject absolute paths, `.`/`..`, glob syntax, non-printable values, and paths over 1024 characters.
- Require exact purpose/scope. Resolve canonical target under canonical root; require existing target. Reject symlink escape.
- If supplied, repository revision and config digest must match current values. Expired timestamps reject.
- Learned hints require evidence ID, provenance, repository revision, and config digest. Request hints may omit evidence metadata.
- Invalid hints are discarded. Search fallback stays bounded to canonical root and project path policy; hints do not widen root or narrow normal search results.

## Targeted selectors

Run only after T20 releases the validation slot:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py::test_repo_path_hints_schema_is_bounded_and_scoped
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_t21_candidate_path_hint_worktree_e2e.py::test_registered_search_path_hints_use_candidate_worktree_config tests/test_t21_search_policy_consumers.py tests/test_project_config_service_integration.py::test_repo_search_hint_hit_does_not_skip_broader_results
```

The second selector set previously reported 7 passed in the T21 candidate. No tests run for this manifest; T20 G remains UNKNOWN.


## Resolver precedence review (static, no tests run)

Static review of `_resolve_project_config` confirms overlay order: defaults, primary worktree `.local-ai.toml`, current worktree/repository `.local-ai.toml`, Git-common `info/local-ai.toml`, then current `.local-ai.worktree.toml`. Later valid values override earlier values; additive mapping fields retain unrelated entries. Any invalid layer returns safe defaults with an error code, so a valid worktree layer cannot hide an invalid lower layer. `config_digest` hashes normalized effective settings. `resolve_project_context` exposes that digest to path-hint freshness checks.

Relevant selectors, pending T20 validation-slot release:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py::test_linked_worktree_inherits_primary_repository_project_config tests/test_project_config.py::test_project_config_precedence_covers_primary_linked_common_and_worktree_layers tests/test_project_config.py::test_invalid_lower_layer_cannot_be_hidden_by_valid_worktree_override
```


## Root-source fixture handoff

T21-owned `tests/test_t21_root_path_hint_worktree_chain.py` resolves `ROOT_SOURCE` as `Path(__file__).resolve().parents[1] / "src"`; no personal absolute checkout path remains in the inspected fixture. Current file SHA-256: `3D93E23DBCE47855A9DC1CB1CD012EF51E5DB61D809290D614ABE0AEAAFA6355`.

T20 previously reported selector `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t21_root_path_hint_worktree_chain.py` passed 1 test in 5.49s. This is a T20 receipt, not a rerun by T21. No root write occurred here.


## T03 public-schema release report

T03 reports that its e809 public `local_ai_repo(action="search")` schema now includes optional `path_hints` and pins `purpose="repository_search"`, `scope="repo_search"`; INSTALL/UPDATE prompt docs are synced. This release covers the public contract only. T03 reports service-side freshness validation remains absent in e809; it does not release overlapping `services.py` ownership. T21 has made no adapter or service edit; T20/root hunk reconciliation remains required.


## T20 integration inventory (read-only)

Candidate branch/HEAD last verified: `codex/t21-project-config` / `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. Root revision was not re-read. T20/T01 relay reports root `project_config.py` SHA-256 `4238B6A6DE1DE00F55F4679CE0DF7D431522EC1BAFABFA272258C1662F13F713`; treat as broker evidence, not T21 direct verification.

| T21/core candidate path | Current SHA-256 | Ownership note |
|---|---|---|
| `src/local_ai_hub/project_config.py` | `FFD425B1260B285F25B1D121A7C6BCD585C618B5C7E26415E2AD0A7014196B0B` | T21 core resolver/schema |
| `tests/test_project_path_hints.py` | `52E6369CD3562935F2B2602901B00A34483C941EBC22AF412E2C2C538AA88E47` | T21 core/privacy/path tests |
| `tests/test_t21_root_path_hint_worktree_chain.py` | `3D93E23DBCE47855A9DC1CB1CD012EF51E5DB61D809290D614ABE0AEAAFA6355` | T21 E2E fixture; path derived from `__file__` |
| `src/local_ai_hub/services.py` | `24A01432EA4288BA0CF4AA27AAF6FA4A769CF8167F56FDE70714EE78967939CF` | T21 candidate hunk overlaps T03 owner |

T03 e809 service candidate SHA reported earlier: `1BDA56D89BD7540C4AE89F36B2BD13A4BEA7471BEEA35AE7E14336D2E6F55EC2`; it differs from T21 `services.py`. No safe whole-file patch. T21 hunk contract: `LocalAIServices.repo_search` resolves `ProjectContext`, gets `config_digest`, gets current non-stale/non-degraded cache fingerprint for revision, validates saved/request/configured hints at purpose `repository_search` + scope `repo_search`, gathers bounded root-contained hinted candidates, then retains full-search fallback. Approximate candidate anchors: revision/context `services.py:2610–2645`; validation and inventory `:2690–2745`; fallback `:2780–2860` (line anchors may move with owner integration).

Owner map: T21 owns resolver and T21 tests; T03 owns public MCP schema/dispatch and overlapping service candidate; T04 owns HTTP/client serialization; T09 owns telemetry projection consumer; T14 owns context/pack. Only T03 public schema release is reported. No service/client/HTTP integration release. Do not overlay files; T20 must reconcile owner hunks against its root preimage.

Suggested selectors after T20 serial GO:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_path_hints.py tests/test_t21_search_policy_consumers.py
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_t21_candidate_path_hint_worktree_e2e.py::test_registered_search_path_hints_use_candidate_worktree_config tests/test_t21_search_policy_consumers.py tests/test_project_config_service_integration.py::test_repo_search_hint_hit_does_not_skip_broader_results
```

Prior candidate receipts reported 28 and 7 passed respectively; no duplicate run. Current core-only patch `git apply --check`/`git diff --check` were not run. No root write/test performed.


## T20 slot preflight: three config selectors

Candidate status for `tests/test_project_config.py`: modified (`M`); SHA-256 `0196D8FA417DD2B56BFC0D143217D25E2986E1B1B1DF6CEFFADD3C0EEB9FBCEA`.

Exact selectors pending GO:
- `tests/test_project_config.py::test_linked_worktree_inherits_primary_repository_project_config`
- `tests/test_project_config.py::test_project_config_precedence_covers_primary_linked_common_and_worktree_layers`
- `tests/test_project_config.py::test_invalid_lower_layer_cannot_be_hidden_by_valid_worktree_override`

These are distinct from prior 28-pass, 7-pass, and 1-pass receipts: none of those command selectors included `tests/test_project_config.py`. Exact-selector process scan found no matching `python.exe`/`pytest.exe` process. Do not infer test result.

Command to run only after explicit T20 GO:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py::test_linked_worktree_inherits_primary_repository_project_config tests/test_project_config.py::test_project_config_precedence_covers_primary_linked_common_and_worktree_layers tests/test_project_config.py::test_invalid_lower_layer_cannot_be_hidden_by_valid_worktree_override
```

`local_ai_command` tool is available, but no broker call was made: the single bounded Hub failure has already occurred and policy forbids retries. No native `git diff --check` run; no receipt available. No test run.


## T20 slot T receipt

One broker run, exact command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py::test_linked_worktree_inherits_primary_repository_project_config tests/test_project_config.py::test_project_config_precedence_covers_primary_linked_common_and_worktree_layers tests/test_project_config.py::test_invalid_lower_layer_cannot_be_hidden_by_valid_worktree_override
```

`local_ai_command` action `run`; request ID `req_be44e8a841b4`; execution ID `05a38a4cd3604372972f6ad803c13c37`; success `true`; exit code `0`; duration `1010.1 ms`; stdout `3 passed in 0.31s`; broker repository_revision `8ed9c070ffbad7ea8b5002e8a96fb3500e98f3b563250b7bf50ad6dd3b22edda`; response was not reused. Response did not include `terminal`, `retryable`, or `outcome_unknown`; do not infer missing fields. No retry or native fallback.

Before/after SHA-256 unchanged:
- `src/local_ai_hub/project_config.py`: `FFD425B1260B285F25B1D121A7C6BCD585C618B5C7E26415E2AD0A7014196B0B`.
- `tests/test_project_config.py`: `0196D8FA417DD2B56BFC0D143217D25E2986E1B1B1DF6CEFFADD3C0EEB9FBCEA`.
- Git HEAD remained `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.


## T03 latest public-contract report

T03 reports its public search contract as optional `path_hints`, max 64 closed objects; each requires `path` (max 1024 chars), `purpose="repository_search"`, `scope="repo_search"`; unknown keys reject. MCP normalizes separators/root-relative paths, rejects canonical-root escapes, forwards valid hints, and returns 501 for unsupported consumer. `operation_contracts.py` restricts the field to `search`. T03 says INSTALL/UPDATE prompt docs already match; its source-only `git diff --check` passed; tests remain unrun under T20 gate. These are T03 reports, not T21 verification.

T03-reported SHA-256: `mcp_server.py` `5E4D7EFD00611A6D32217AA8D8B46A1E03872F6C9B68BFDE4D8484875D64AD5E`; `operation_contracts.py` `ADCE4B200D7FB4AB2669AC79DAD30AC7FC8A1D976269FBEBE8F93378901254A7`; `tests/test_mcp_compact_transport.py` `7D92AEC6D7577C4A9CC2AA1A9941092CDFD94A9198D9828F90AD29A383660D31`.


## Chronology correction

Earlier sections saying “no tests run” / “T20 G remains UNKNOWN” describe the handoff state before T20 issued GO for the three config selectors. The later `T20 slot T receipt` section is authoritative for that run: 3 passed, exit 0. This does not change the separate status: path-hint suites (28/7 receipts are prior reports), root-copy acceptance, consumer integration, and `git diff --check` were not run/verified by this update.


## T20 release-matrix snapshot (read-only)

On the latest read of T20 thread, T04 batch was still pending an exact receipt; T20 noted a reported 40/40 result as candidate-only. T20 issued GO #6 to T08 for a bounded corrected root-current batch. No T21 GO/slot was present in this snapshot. This is a point-in-time T20 report; no test or root action taken by T21.


## Root-current test-only handoff

Artifact: `T21-root-current-20261002.patch`, SHA-256 `FB6E815847A7523EE9A50CE28783B37891B93E3A4E40B79EC2FAB2DAFD9E0CE4`.

Exactly one changed path: `tests/test_project_path_hints.py`; adds one T21 regression test that rejects a 1025-character hint. No production source or consumer hunk. Root test-file preimage SHA-256 recorded when generated: `2DBA6145040EB2C20FF74788C88A66BF5A4BD4F6F210E292A2032B925DF20DAB`; patch index abbreviated base blob `3e71071`, target blob `f2101d0`. T21 candidate target test SHA-256 `52E6369CD3562935F2B2602901B00A34483C941EBC22AF412E2C2C538AA88E47`.

Historical receipt: root `git apply --check --binary` passed against the recorded preimage. Candidate selector `python -m pytest -q --tb=short tests/test_project_path_hints.py::test_path_hint_rejects_paths_over_t03_contract_limit` reported 1 passed. Root test was not run; root HEAD/current preimage were not rechecked in this continuation. T20 owns root integration. Do not apply if the current root test-file hash differs from the pinned preimage.


## T03 root-current schema discrepancy report

T03 reports current root `operation_contracts.py:193` scopes `path_hints` to both `search` and `context`; `tests/test_operation_contracts.py:428-479` reportedly allow context hints only for `mode="adaptive"` and reject `fast`/`full`/custom modes. This differs from T03 e809 search-only candidate schema. T21 consumes hints only for repository search; this does not authorize T21 context consumer work. `/api/context/pack` remains outside T21 scope and unchanged. Treat line/test details as T03 report; T21 did not inspect root or run those tests. Do not transplant e809 schema patch wholesale over root-current adaptive context behavior.


## T03 contract handoff refresh — 2026-10-03

T03 reports e809 HEAD `d68ee694c6d3f75db5c1ab2f63497226880e5010`. Its MCP live/generated schema exposes `path_hints` only for `local_ai_repo(action="search")`: array max 64, closed item fields, required `path`, `purpose="repository_search"`, `scope="repo_search"`; other actions reject the field. T03 identifies `src/local_ai_hub/operation_contracts.py` (`REPO_ACTION_FIELDS`, `repo_path_hints_schema`) and tests `test_repo_path_hints_schema_is_bounded_and_scoped` plus `test_repo_path_hints_search.py`. Report says contract ready for T21 integration. This is T03-provided candidate evidence; T21 did not inspect e809 or rerun tests.


## Serial gate and adapter ownership — latest status check (2026-10-03)

Current Codex thread listing showed T20 idle and T04 active. T20's latest completed message states the T08 receipt predates current `agent_events.py` hash, slot remains closed, release **NO-GO**. T20 idle is not a T21 GO. No T21 test run. T04 transport ownership remains active; no client/HTTP adapter release was observed. T21 remains limited to its resolver/schema/test paths and handoff.


## Candidate path-hints propagation audit — 2026-10-03 (read-only)

Candidate HEAD remains `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. Static call path present in this candidate:

1. `client.py` preserves validated `path_hints` only when route is `/api/search` (SHA-256 `1E28197A3C9FF920A4C71FC5189A3CB425B79189CA5F5F001416D175A9E6A79D`).
2. `mcp_server.py` validates/normalizes root-relative hints and forwards them through HubClient search dispatch (SHA-256 `436985F193EDABE896A8A7A3F002601F9307D576DB669EA006C4599060393838`; T03-owned dirty candidate).
3. `http_server.py` `/api/search` dispatch passes payload `path_hints` to `LocalAIServices.repo_search` (SHA-256 `0206929817D58D5D6192C8D082DA201F399D06A60679CE5A934EDA8F93199AF0`; T04/shared owner candidate).
4. T21 candidate `services.py` resolves project context and validates using exact tuple/freshness before bounded candidate search and broader fallback (SHA-256 `24A01432EA4288BA0CF4AA27AAF6FA4A769CF8167F56FDE70714EE78967939CF`; service hunk overlaps T03/T20 ownership).
5. T21 core `project_config.py` SHA remains `FFD425B1260B285F25B1D121A7C6BCD585C618B5C7E26415E2AD0A7014196B0B`.

This proves static candidate presence only, not a root integration receipt. Hashes pin dirty candidate files; they do not identify authorship of every hunk. T04 latest final reports 40 transport selectors passed, but does not explicitly release `client.py` path-hint hunks. T03 reports public schema contract ready; overlapping MCP/service hunks still require owner reconciliation. T20 latest observed thread was active/in-progress on readiness; no fresh T21 GO observed. No tests, edits, root reads, or patch applies occurred in this audit. `/api/context/pack` was not inspected or changed.


## Scoped core diff-check receipt — 2026-10-03

`local_ai_command` action `run`; exact command `git diff --check -- src/local_ai_hub/project_config.py tests/test_project_config.py tests/test_project_path_hints.py`; request `req_01f9a4c17d12`; execution `29acc0ff092a44fd9e93e0f30684ac01`; success `true`; exit `0`; duration `120.7 ms`; repository_revision `5c7628c7bd5b21e1e9f579295597757367fb7a348e925f00a64259bd67da1b5e`; no payload reuse. The broker did not return `terminal` or `retryable`; do not infer. This check covers tracked core/test hunks only, not untracked fixture/handoff or consumer/root files. No test run.


## Acceptance coverage refresh — 2026-10-03

Current candidate HEAD remains `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`; tracked T21 core/test dirty paths remain modified, consumer files remain dirty/shared. Existing verified broker receipt is the three config selectors (3 passed); earlier candidate receipts 28/7/1 remain prior reports, not reruns.

Static selector inventory found `tests/test_t21_candidate_path_hint_worktree_e2e.py::test_registered_search_path_hints_use_candidate_worktree_config`, covering MCP `local_ai_repo` through client `/api/search`; prior 7-pass command included this selector. Candidate files `tests/test_client_path_hints.py` and `tests/test_mcp_repo_path_hints.py` contain route/transport cases for `/api/search`, `/api/command`, context isolation, root containment, and forwarding, but are untracked in this worktree snapshot and path ownership is unproven. Do not edit or run them until owners/T20 confirm ownership and serial GO.

Latest T20 `read_thread` call returned thread turn status `failed` with `systemError`; no explicit T21 GO was present. No test run. T21 scope remains core/config/path tests; consumer integration acceptance remains open pending T03/T04 ownership reconciliation and T20 slot.


## Typed path-hint adapter contract and current owner matrix — 2026-10-03

Core contract: `PathHint` carries `path: str`, `purpose: str`, `scope: str`, and optional `evidence_id`, `provenance`, `repository_revision`, `config_digest`, and `expires_at`. Repository search accepts only `purpose="repository_search"` and `scope="repo_search"`; at most 64 closed request items, with path bounded to 1024 characters. Core validates canonical root containment and freshness before prioritizing candidates; full-search fallback remains available.

Telemetry contract: `PathHintUsage.telemetry_metadata() -> dict[str, bool | None]` returns exactly `hint_used`, `fallback_used`, and `hint_helped`. Values normalize to booleans or `None`; `hint_helped` remains `None` because outcome attribution is unavailable. Candidate paths and evidence/provenance/revision/config fields never enter this projection. Privacy tests pin both path exclusion and malformed-value normalization.

| Path or seam | Owner | Boundary |
| --- | --- | --- |
| `src/local_ai_hub/project_config.py`; `tests/test_project_config.py`; `tests/test_project_path_hints.py`; `tests/test_t21_root_path_hint_worktree_chain.py` | T21 | Core resolver/schema and T21-owned tests only. |
| `src/local_ai_hub/operation_contracts.py`; `src/local_ai_hub/mcp_server.py` public search schema/dispatch hunks | T03 | Consumer-owned; T03 released the candidate input contract dependency below. No adapter patch transferred. |
| `src/local_ai_hub/client.py`; `src/local_ai_hub/http_server.py` `/api/search` transport hunks | T06 | Consumer-owned; no T21 edits or release inferred. |
| `src/local_ai_hub/services.py` telemetry projection/consumer hunks | T09 | Consumer-owned; path strings remain excluded. |
| `src/local_ai_hub/services.py` repository-search adapter hunks | T16 | Consumer-owned; overlaps shared candidate hunks. |
| `/api/context/pack` route/consumer hunks in `src/local_ai_hub/mcp_server.py` and `src/local_ai_hub/http_server.py` | T19 | Explicitly untouched and outside T21 contract. |

This matrix records current ownership boundaries supplied for the continuation, not proof of release or authorship of every dirty hunk. Mixed files require owner-level hunk reconciliation before integration. T14/T15 have no verified task IDs; do not message pending clientThreadIds or create replacement tasks. T20 has issued no fresh T21 validation GO. No adapter edits or test runs occurred in this update.


## T03 path-hints dependency release — 2026-10-03

T03 explicitly released its candidate `local_ai_repo(action="search")` input contract as a T21 dependency. Source receipt: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub\handoff\T03-action-output-schemas-20261002.receipt.md`, SHA-256 `FC4F3509C9C46989BC32892F134D6C5F5B54782BA886937D484DE6B694D28F5B`. It records optional `path_hints`, maximum 64 entries, and required `path`, `purpose`, `scope`; T03 reports 28 focused schema/dispatch tests passed. This is candidate evidence and contract release only; it does not authorize T21 root integration or changes to T03/T06/T09/T16/T19 consumer files.

T21 core already carries matching bounds: `_MAX_REQUEST_PATH_HINTS = 64` and `_MAX_RELATIVE_PATH = 1024` in `project_config.py`; `PathHint` requires `path`, `purpose`, and `scope`. T21 did not change core source for this receipt. `/api/context/pack` remains untouched. T20 has no fresh T21 validation GO, so no T21 tests ran.


## T21 candidate MCP-to-search E2E receipt — 2026-10-03

The user explicitly authorized the T21 MCP/client `/api/search` scope and requested E2E coverage, with no root write and no `/api/context/pack` change. One isolated candidate selector ran in `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub` at HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t21_candidate_path_hint_worktree_e2e.py::test_registered_search_path_hints_use_candidate_worktree_config
```

Result: exit `0`, `1 passed in 4.88s`. The test calls registered MCP `local_ai_repo(action="search")`, captures the client `/api/search` payload, dispatches through the candidate HTTP handler and service, then asserts worktree config, ignored/private/hard-denied paths, accepted hint and traversal rejection. It uses a temporary local HTTP server and temporary Git fixture; it does not prove live daemon or root integration.

Test SHA-256: `F9E1DA649FED113D3EAA234129BFFF952F5CF27E406FE4B73614F805947CFF54`. Candidate input hashes at the run: `mcp_server.py` `436985F193EDABE896A8A7A3F002601F9307D576DB669EA006C4599060393838`; `client.py` `1E28197A3C9FF920A4C71FC5189A3CB425B79189CA5F5F001416D175A9E6A79D`; `http_server.py` `0206929817D58D5D6192C8D082DA201F399D06A60679CE5A934EDA8F93199AF0`; `services.py` `24A01432EA4288BA0CF4AA27AAF6FA4A769CF8167F56FDE70714EE78967939CF`. These identify shared dirty candidate inputs, not sole authorship of every hunk. No adapter edits, root writes, or additional test runs occurred in this step. T20's broader serial release remains NO-GO; this receipt is the single explicitly requested isolated T21 selector.


## T03 current acceptance receipt — 2026-10-03

Verified T03 handoff: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub\handoff\T03-acceptance-current.md`, SHA-256 `DA1108BD383EE0A59C0D28309480E3A08E4FB4A2DA2E074402C2BE98FCA3FD94`. It pins T03 candidate HEAD `ad622f8a90a81e349e94d3402f297f2995e733b2`, exact suite `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py tests/test_recovery_journal_contract.py tests/test_mcp_live_wire_schema.py`, result `108 passed in 23.62s`, exit `0`, and adds `test_mcp_repo_search_forwards_path_hints_to_http_payload`. T03 reports T04 confirmed its client-to-HTTP selector for the next hop.

T03 says it will not copy T21/T06/T16 hunks; its receipt leaves combined real route/service acceptance with T20. This confirms the public contract and MCP wrapper hop only. It does not release T06 HTTP or T16 service hunks, authorize root writes, or change the `/api/context/pack` exclusion. T21 candidate E2E receipt above remains separate evidence.


## Root-current search-only scope check — 2026-10-03

Read-only root inspected at `C:\Users\Adam\.local-ai-hub`, branch `master`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; several target files are already dirty and `operation_contracts.py` is untracked. No root files were written.

Root static path confirms MCP normalizes and forwards hints to `/api/search`; root `http_server.py` passes `payload.path_hints` to `repo_search`; root `services.py::repo_search` accepts `path_hints`. Root `client.py` SHA-256 `393791DFC87F64247DB675B1E76C86DF6B4C666B937B70CAD2A55FC7BE44502C` currently gates on both `/api/search` and `/api/command`, and its untracked `tests/test_client_path_hints.py::test_post_forwards_path_hints_to_search_and_command` asserts forwarding for both. That fails the approved search-only scope. The T21 candidate client is search-only and its MCP-to-search E2E selector passed above.

Root blocker: client correction and its expectation belong to the dirty/shared root owner state; root write is prohibited here. No root tests ran. T20 remains `systemError`/NO-GO. Preserve root dirty hunks, request/receive T06 integration ownership before applying the T21 search-only client behavior. `/api/context/pack` stayed untouched by T21.

## T21 root-current core/schema receipt — 2026-10-03

- Approved PathHintUsage.telemetry_metadata() projects exactly hint_used, fallback_used, and hint_helped; it excludes paths and extra fields. Targeted T21 candidate privacy/normalization selectors: 2 passed in 0.12s.
- T21 candidate ConsistencyRequest.project_config_digest accepts only a normalized 64-character lowercase hexadecimal digest; malformed values become empty. Targeted candidate schema selectors previously passed: 2 passed in 0.20s. T14 route must pass the server-resolved resolve_project_context(...).config_digest, never client text.
- Prepared root-current add-only patch: handoff/T21-root-current-core-patch-20261003.patch, SHA-256 DC6571E422CEB5026339A41956D70025A85C83688A2132AF6AEA58D9638B18AA. It adds the digest field/normalization/serialization and tests, plus the non-PathHint runtime guard and seven missing T21 containment/normalization tests. git apply --check against current root C:\Users\Adam\.local-ai-hub succeeded (exit 0); patch remains unapplied.
- The add-only patch carries the T21 validate_path_hint type guard; root already has PathHintUsage projection and privacy tests, so it intentionally does not duplicate them. Root remained read-only. No consumer adapter or /api/context/pack files are in this patch.

### Path-to-owner handoff

| Path or seam | Owner | Handoff |
|---|---|---|
| project_config.py, services.py::repo_search, repo_tools.py::search_paths, /api/search, core resolver/schema tests | T21 | T21 candidate work; root-current patch only, unapplied |
| MCP public schema/dispatch and wrapper acceptance | T03 | T03 handoff/receipt verified; route forwards search hints |
| client transport and retry behavior | T04 | T04 handoff verified; root client change awaits T04 release; adapters remain untouched |
| /api/context/pack route forwarding and route contract test | T14 | T14 owns route/test only; T21 owns the digest field contract |
| other consumer adapters | T06, T09, T16, T19 | untouched pending owner release |
| /api/context/pack implementation outside T14's assigned route/test | T14 | excluded from T21 edits |

No T21 write to root, no adapter edit, and no /api/context/pack edit. T20 serial acceptance remains NO-GO; root runtime acceptance is unverified.


## Post-integration acceptance handoff — 2026-10-03

Orchestrator reports the exact core patch `DC6571E4…63B18AA` integrated into root `project_config.py`, `agent_consistency.py`, and the two scoped tests. Reverse-apply check and scoped diff check pass. Root validation remains blocked on T02 shared test-window release; T21 ran no root tests.

Exact T21 root-core command after T02 release:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_path_hints.py tests/test_agent_consistency.py tests/test_project_config_service_integration.py tests/test_t21_root_path_hint_worktree_chain.py
```

Acceptance gaps: this root command has not run; no fresh combined MCP → client → `/api/search` → `repo_search` root receipt exists; T03/T04/T14 owner-owned acceptance remains separate; `/api/context/pack` stays T14-owned; no live Hub/runtime acceptance is claimed. Keep T21 task open until T02 releases the slot and fresh root receipts exist.

## T14 fixture diagnosis from root acceptance — 2026-10-03

Orchestrator reported integrated batch: 198 passed, 2 failed in 72.82s. T21-related failure is `tests/test_context_delivery.py::test_adaptive_context_uses_project_weights_and_invalidates_config_identity`: test fixture's `SimpleNamespace(retrieval_weights=...)` reaches `resolve_pinned_context`, which correctly reads `settings.pinned_context`.

Contract evidence: `ProjectSettings.pinned_context` defaults to empty tuple. The test double is incomplete; production resolver semantics remain unchanged. Prepared owner-only one-line fixture patch `handoff/T14-context-fixture-default.patch`, SHA-256 `86C1C94EEA2D83038774743E7EF137E9BCF5935F02F01ACFA7E1C80A340891E1`; `git apply --check` against root passed (exit 0). Patch is unapplied, root test file untouched by T21. Sent patch and diagnosis to T14.

After T02 releases the test window, T14 should apply/validate its owned fixture patch and rerun:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_context_delivery.py::test_adaptive_context_uses_project_weights_and_invalidates_config_identity
```

Acceptance remains open pending T02 test-slot release and fresh receipt.

## Validation slot update — 2026-10-03

T04 currently owns the validation slot. T21 will not run root or candidate tests until T04 releases it. The only pending action is the unapplied one-line T14 fixture patch above; no production change and no additional test run. T04 received this hold notice.

## Combined post-release acceptance command

Run once only after T04 releases the validation slot and T14 integrates the fixture patch:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_path_hints.py tests/test_agent_consistency.py tests/test_project_config_service_integration.py tests/test_t21_root_path_hint_worktree_chain.py tests/test_context_delivery.py::test_adaptive_context_uses_project_weights_and_invalidates_config_identity
```

Patch pins: T21 core `DC6571E422CEB5026339A41956D70025A85C83688A2132AF6AEA58D9638B18AA` (integrated per orchestrator); T14 fixture `5F00AD52D353397753887A88D1D3A91B8ADC6316FDEA496C7D495E1AB5C63998` (prepared, unapplied). No tests run while T04 owns the slot.

## Post-T04 slot root validation — 2026-10-03

T04 released the validation slot. Ran the recorded combined root selector once:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_path_hints.py tests/test_agent_consistency.py tests/test_project_config_service_integration.py tests/test_t21_root_path_hint_worktree_chain.py tests/test_context_delivery.py::test_adaptive_context_uses_project_weights_and_invalidates_config_identity
165 passed, 1 failed in 46.73s
```

All 165 passing tests include T21 project/worktree precedence, path-hint freshness/containment, shared Git-common/namespace scoping, service fallback, digest identity, and root worktree chain selectors. Remaining failure is T14-owned test fixture only: adding `pinned_context=()` exposed next missing settings contract `entry_points`; production `ProjectSettings` defines both defaults. Correct fixture should use `project_config.ProjectSettings(retrieval_weights={"lexical": weight})`.

Updated replacement guidance artifact `handoff/T14-context-fixture-default.patch`, SHA-256 `86C1C94EEA2D83038774743E7EF137E9BCF5935F02F01ACFA7E1C80A340891E1`. T14's dirty root test already contains the intermediate pinned_context fixture hunk; `git apply --check` against that dirty mixed-line-ending file fails. Do not force-apply. T14 received instruction to update its owned checkout and rerun only `tests/test_context_delivery.py::test_adaptive_context_uses_project_weights_and_invalidates_config_identity`. T21 did not write root.

The original orchestrator batch reported 198 passed/2 failed; this T21 focused batch accounts for one failure only. The other failure remains outside T21's exact selector and needs its owning task's receipt. Keep acceptance open until T14 selector and remaining owner failure are resolved.

T14 latest selector iteration exposed one more incomplete test-double field: `_project_context_hint_groups` invokes `project_context.path_hints(purpose, scope, repository_revision)`. T14 was notified to provide a local `path_hints` callable returning `()` along with `ProjectSettings`; keep production resolver unchanged. This selector has not yet passed.

## Current status after T14 fixture contract update — 2026-10-03

Read-only root inspection now shows the T14 fixture with valid `ProjectSettings(retrieval_weights=...)` and `path_hints=lambda **_kwargs: ()`. T21 made no root edit; T14 was notified to confirm ownership and run its selector only after slot release.

Exact replacement guidance patch `handoff/T14-context-fixture-default.patch`, SHA-256 `C2E18932533722A5B721BF8EF158D738AC25BBC4FD2037EFE02F2E251FE9DEBC`, documents replacing the partial fixture with the full protocol. It is a handoff artifact, not for reapplication if root already contains those lines.

T04 latest status remains active and waiting for T01 release after `outcome_unknown`. No tests run in this turn. After slot release, rerun the same combined selector shown above; keep `/api/context/pack` T14-owned.

## Final T21 owner receipt — root pins and remaining integrations — 2026-10-03

Root is `C:\Users\Adam\.local-ai-hub`, branch `master`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`. Core patch `DC6571E422CEB5026339A41956D70025A85C83688A2132AF6AEA58D9638B18AA` is already integrated; `git apply --reverse --check` passes. No T21 root edits.

Exact root working-tree preimages used when the core add-only patch was prepared:

| Path | Preimage SHA-256 |
|---|---|
| `src/local_ai_hub/project_config.py` | `4238B6A6DE1DE00F55F4679CE0DF7D431522EC1BAFABFA272258C1662F13F713` |
| `src/local_ai_hub/agent_consistency.py` | `86D4E5B0433EA09379CF7F55E9A2B158F0A45861791D1D6418BE2BCBA4FF7B7B` |
| `tests/test_agent_consistency.py` | `3AE5572B6A59ECCBA18201BF6974F05B0DA9BF30CC49A98A7D51B1CD96062679` |
| `tests/test_project_path_hints.py` | `07D00BBA1E0963645DDB3C5970E1C9FC9763D90F969725C0211E14A83EB8ADC4` |

Current root target hashes at this receipt:

| Path | Current SHA-256 |
|---|---|
| `src/local_ai_hub/project_config.py` | `00E80B1342E5E70A66FA8955D95553127E913F56EC693CF527B6AC96053BDBDE` |
| `src/local_ai_hub/agent_consistency.py` | `F97ED584351BC9F8BA9C9AB5509CBB8DA8FC335C0DFDF9DB9D91B0C37F3E3DD3` |
| `src/local_ai_hub/services.py` | `525565A42B626A7ED2A66ADE57C6878D1802B430F2D1BD5A2818B7ADA68D3179` |
| `src/local_ai_hub/repo_tools.py` | `360734CEB316A8A9FC698C19C1098D88FC591170DBBF5F3B67DB6608CD3A6A36` |
| `src/local_ai_hub/http_server.py` | `7CE0E3D38979220917443CBF1FC24FFACCA8254ACD9E878E456FBB97C7A936EE` |
| `src/local_ai_hub/client.py` | `C2CDC6EF131D9134D39251B7597DE84200DCD093118C9A2EC1CE863CB440D50D` |
| `src/local_ai_hub/mcp_server.py` | `C61467CF7B8E3DFF4E105EE39B22742D488BC78791FFD05DBDAE5AB53B27E0ED` |
| `tests/test_project_config.py` | `90A66B610B84FADDF178147321362DB91139FFCE0FDC680E01AAD9FBD1866270` |
| `tests/test_project_path_hints.py` | `92EC33C9BB69D75F50ACB9EFBC501C541574D877128112444458CD11576AA5C7` |
| `tests/test_agent_consistency.py` | `501EA4999F7D7483122C39093DD6045A52CFE0E49F7A0599A3F9ECDE5A7365D3` |
| `tests/test_context_delivery.py` | `73C99145EAF0658ED2194BE08E70271D196EA99A02B74B824E3EA6DF4E8234A0` |

Root selectors after serialized slot release:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_path_hints.py tests/test_agent_consistency.py tests/test_project_config_service_integration.py tests/test_t21_root_path_hint_worktree_chain.py tests/test_mcp_repo_path_hints.py tests/test_api_search_path_hints.py tests/test_context_delivery.py::test_adaptive_context_uses_project_weights_and_invalidates_config_identity
```

Previously observed focused result remains `165 passed, 1 failed in 46.73s`; T14 fixture then lacked ProjectSettings fields/provider. Current root fixture now visibly uses `ProjectSettings(retrieval_weights=...)` and `path_hints=lambda **_kwargs: ()`; selector has not been rerun.

Unresolved owner integrations: T04 client currently forwards `path_hints` on both `/api/search` and `/api/command`; `tests/test_client_path_hints.py::test_post_forwards_path_hints_to_search_and_command` still encodes that broader route set. T04 owns that gate/test seam. T09 telemetry consumer, T06/T16/T19 consumers have no release receipt in this handoff. T14 owns `/api/context/pack`; current root has T14 route changes, but its selector receipt remains pending. T03 public MCP search wrapper files are present; fresh integrated end-to-end root acceptance remains pending. T04 latest status waits for T01 serial slot release after `outcome_unknown`; no test run in this receipt.

## Serialized validation slot latest — 2026-10-03

T04 explicitly reports the shared slot is not released and T21 is waiting in queue. T04 candidate work only; no test run in this turn. T21 will run no root/candidate tests until explicit release.

T21-only acceptance selector after release:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_path_hints.py tests/test_agent_consistency.py tests/test_project_config_service_integration.py tests/test_t21_root_path_hint_worktree_chain.py
```

## Caller-chain and dependency receipt — 2026-10-03

### Root caller chain (read-only)

1. MCP `local_ai_repo(action="search")` converts legacy `path` into a `PathHint` with purpose `repository_search` and scope `repo_search`, appends up to 64 typed request hints, normalizes each path against root, rejects invalid/outside-root hints, then calls `_local_ai_repo_impl`.
2. `_local_ai_repo_impl` sends `CLIENT.post("/api/search", ..., path_hints=...)`.
3. `HubClient.post` serializes only allowed hint fields, caps at 64, rejects malformed required/optional field types, and removes hints when explicit `path` is supplied. Current root gate still permits both `/api/search` and `/api/command`; `tests/test_client_path_hints.py::test_post_forwards_path_hints_to_search_and_command` also asserts both. This remains T04-owned scope gap.
4. HTTP `/api/search` passes payload hints to `LocalAIServices.repo_search`.
5. `repo_search` resolves `ProjectContext` using the configured state directory with `create=False`; checks purpose/scope, repository revision, config digest, freshness, root containment and policy; hinted files/directories are bounded candidates.
6. T10 full search runs regardless; targeted hinted search is merged with `full_result`, so hints prioritize/add candidates without narrowing recall. `repo_tools.search_paths` independently validates root containment, exclusions, extension and project policy.

### Owner/dependency map

| Seam | Owner | Boundary/status |
|---|---|---|
| project/worktree config resolver, path-hint schema/validation, `/api/search` service candidate selection, T21 core tests | T21 | Core patch integrated; no duplicate edits |
| MCP public search contract, dispatch, hint normalization/wrapper tests | T03 | Owner files; selector listed below |
| client serialization and route gate | T04 | Current root gate still includes `/api/command`; T04 owns correction/release |
| full search/retrieval ranking and fallback | T10 | Preserve full-result execution and union; no retrieval implementation edits by T21 |
| hint telemetry consumer | T09 | Only booleans `hint_used`, `fallback_used`, `hint_helped`; no path values |
| context consumer and `/api/context/pack` | T14 | T14-owned; T21 does not edit route or adapter |
| remaining consumers | T06, T16, T19 | Owner release required; untouched |

### Exact selector inventory (not run in this receipt)

| Owner | Selector/module |
|---|---|
| T21 core | `tests/test_project_config.py`, `tests/test_project_path_hints.py`, `tests/test_agent_consistency.py`, `tests/test_project_config_service_integration.py`, `tests/test_t21_root_path_hint_worktree_chain.py` |
| T10 retrieval boundary | `tests/test_t10_repo_search_path_hints.py` |
| T03 MCP/API | `tests/test_mcp_repo_path_hints.py`, `tests/test_api_search_path_hints.py` |
| T04 transport | `tests/test_client_path_hints.py`, `tests/test_t04_root_path_hint_chain.py` |
| T14 context regression | `tests/test_context_delivery.py::test_adaptive_context_uses_project_weights_and_invalidates_config_identity` |

Combined serialized command is recorded in the prior section. T04 currently owns/waits for the serial validation slot; no test was run for this receipt. Root fixture now has valid `ProjectSettings`, `path_hints` provider, and config identity. `/api/context/pack` and T10 retrieval behavior remain unmodified by T21.

Root current source pins at this receipt: `mcp_server.py` `C61467CF7B8E3DFF4E105EE39B22742D488BC78791FFD05DBDAE5AB53B27E0ED`; `client.py` `7D0EF3BE7A95152318FAE1B7E7B8376BFAAE065EEAD4C5CC4F2A37C1DF06DEA2`; `http_server.py` `7CE0E3D38979220917443CBF1FC24FFACCA8254ACD9E878E456FBB97C7A936EE`; `services.py` `58908C5C718A520463171B7890C0B8E1E7F7CC54D5EF62F9809BE707EFC173FE`; `repo_tools.py` `360734CEB316A8A9FC698C19C1098D88FC591170DBBF5F3B67DB6608CD3A6A36`; `project_config.py` `00E80B1342E5E70A66FA8955D95553127E913F56EC693CF527B6AC96053BDBDE`.

## Full caller-chain acceptance command after owner releases

Run only after T04 releases the serial slot and T04 updates its route-scope test; this command intentionally spans owners but edits none:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_path_hints.py tests/test_agent_consistency.py tests/test_project_config_service_integration.py tests/test_t21_root_path_hint_worktree_chain.py tests/test_t10_repo_search_path_hints.py tests/test_operation_contracts.py::test_repo_path_hints_schema_is_bounded_and_scoped tests/test_mcp_repo_path_hints.py tests/test_api_search_path_hints.py tests/test_client_path_hints.py tests/test_t04_root_path_hint_chain.py tests/test_context_delivery.py::test_adaptive_context_uses_project_weights_and_invalidates_config_identity
```

Pre-release receipts: T21 core combined run `165 passed, 1 failed in 46.73s` before the T14 fixture reached its current complete shape. T04 prior focused transport receipt `54 passed / 6.17s` belongs to its candidate/current owner state, not an integrated root receipt. No fresh combined command result exists.

## T14 fixture reconciliation — exact failing preimage and current root state

Original failing fixture preimage used `SimpleNamespace(retrieval_weights=...)` plus `config_digest`; that omitted valid `ProjectSettings.pinned_context`/`entry_points` defaults and `ProjectContext.path_hints` provider. The exact replacement receipt is `handoff/T14-context-fixture-contract-repair-from-failing-preimage.patch`, SHA-256 `D88759B59D8BFFD6DAD6A63D7A6889CA4D14B5CCB7582F13AB036223939AE652`. It replaces settings with `project_config.ProjectSettings(retrieval_weights=...)`, supplies `root=ROOT`, and adds `path_hints=lambda **_kwargs: ()`.

Root-current applicability: patch is already integrated in the dirty root test file; do not apply again. Current `tests/test_context_delivery.py` SHA-256 `63FAEC10ADF77C24D1D4973208ECCB7298CC0E40FACC6131507DF5D0F5925416`; lines 818-823 show the complete fixture. No root write by T21. No production change.

Exact acceptance selector remains `tests/test_context_delivery.py::test_adaptive_context_uses_project_weights_and_invalidates_config_identity`. Do not run before T20 releases its test slot. Prior `165 passed, 1 failed in 46.73s` predates this complete fixture; current selector result is unknown.

## Existing T21 worktree recovery and dirty ownership — 2026-10-03

Current T21 thread `01a0d7b9-04b9-7da1-906e-393693d07f65` reports cwd `C:\Users\Adam\.codex\worktrees\4294\.local-ai-hub`, but that path has no `.git` or source tree. `list_artifacts` returned none. The repository's `git worktree list --porcelain` confirms the existing valid checkout `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`, branch `codex/t21-project-config`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. No replacement worktree/task created.

Dirty checkout has many unrelated/overlapping changes; preserve them. T21-authorized paths for this continuation: `src/local_ai_hub/project_config.py`, `src/local_ai_hub/agent_consistency.py`, and the T21 project/path-hint tests. `services.py::repo_search` and `repo_tools.py::search_paths` are shared/overlapping hunks; no new edit made because root already carries their path-hint behavior and no per-hunk release arrived.

Protected dirty owner surfaces: `mcp_server.py` and HTTP search contract/tests (T03); `client.py` and transport tests (T04); full retrieval/fallback work in `preprocess.py`/`rag.py` (T10); `/api/context/pack` region and context consumer tests (T14); telemetry/other adapters (T06/T09/T16/T19); remaining project-policy/verification files outside this exact scope. No hunks were reset or overlaid.

Root caller-chain pins and route details are recorded above. Current client still accepts hints on `/api/command`; T04 was sent the exact seam and selectors. T03 was sent the HTTP/MCP route evidence and owned selectors. No owner patch/release receipt has arrived in this turn.

Root-current T21 patch pin remains `DC6571E422CEB5026339A41956D70025A85C83688A2132AF6AEA58D9638B18AA`; reverse-apply check exit 0. The previously recorded T21 candidate receipts remain limited to named selectors (path-hint E2E 1 passed; digest 2 passed; telemetry 2 passed; type guard 1 passed). Root combined run remains `165 passed, 1 failed` before T14 fixture correction; current context selector not rerun.

Exact root selectors after owner release: T21 core `tests/test_project_config.py tests/test_project_path_hints.py tests/test_agent_consistency.py tests/test_project_config_service_integration.py tests/test_t21_root_path_hint_worktree_chain.py`; T10 boundary `tests/test_t10_repo_search_path_hints.py`; T03 `tests/test_operation_contracts.py::test_repo_path_hints_schema_is_bounded_and_scoped tests/test_mcp_repo_path_hints.py tests/test_api_search_path_hints.py`; T04 `tests/test_client_path_hints.py tests/test_t04_root_path_hint_chain.py`; T14 regression `tests/test_context_delivery.py::test_adaptive_context_uses_project_weights_and_invalidates_config_identity`.

No tests run in this continuation. T04 has not confirmed the serialized slot is released. End-to-end acceptance remains blocked on T04 route-scope owner fix/release and a fresh combined root receipt; `/api/context/pack` and T10 retrieval boundary remain intact.

## T03 contract dependency receipt — 2026-10-03

T03 reports its existing `e809` worktree has public `local_ai_repo(action="search")` `path_hints` schema and bounded/scoped validation in `operation_contracts.py` and `tests/test_operation_contracts.py`; MCP normalizes and forwards the hints. Its HTTP `/api/search` adapter forwards them to `repo_search` only when that method signature supports the keyword; otherwise T03 returns 501. Current root `LocalAIServices.repo_search` accepts `path_hints`.

T03 also corrected a stale MCP transport factory AST assertion to TENANT/CONFIG_PATH; no production client edit. Exact T03 selector inventory: `tests/test_operation_contracts.py::test_repo_path_hints_schema_is_bounded_and_scoped`, `tests/test_mcp_repo_path_hints.py`, and `tests/test_api_search_path_hints.py`.

This is dependency/owner-scope evidence only; T03 ran no tests, claims no release, and T20 serialized validation slot remains UNKNOWN. T21 did not edit T03 files or root.

## T21-approved search-only client seam patch — 2026-10-03

User authorized T21 continuation to prepare the `/api/search` client adapter patch; root remains read-only. Candidate `client.py` already gates path hints to `/api/search`. Root-current patch artifact `handoff/T21-search-only-client-root-current.patch`, SHA-256 `8B7ACE3677F369AF13101A137202108992FFC3415656985FD0B9E3B6278EEA79`, changes only the client route gate and the matching existing test expectation. Root `git apply --check` passed, exit 0; patch unapplied.

Exact preimages: root `src/local_ai_hub/client.py` SHA-256 `7D0EF3BE7A95152318FAE1B7E7B8376BFAAE065EEAD4C5CC4F2A37C1DF06DEA2`; root `tests/test_client_path_hints.py` SHA-256 `2D4F101AD392365C96CB3E1419415E1CB361764D4535B7752280BB964C35329F`. Updated selector: `tests/test_client_path_hints.py::test_post_forwards_path_hints_to_search_only`. T04 has the scoped patch and review request; no test run pending T20 GO.

MCP/API path is already present in root; T03 confirms its owner contract. Exact selectors: `tests/test_operation_contracts.py::test_repo_path_hints_schema_is_bounded_and_scoped`, `tests/test_mcp_repo_path_hints.py`, `tests/test_api_search_path_hints.py::test_api_search_forwards_path_hints_to_repo_search`. No T03 source edit or overlay.

Combined search-chain selectors after serialized T20 GO: `tests/test_operation_contracts.py::test_repo_path_hints_schema_is_bounded_and_scoped tests/test_mcp_repo_path_hints.py tests/test_api_search_path_hints.py::test_api_search_forwards_path_hints_to_repo_search tests/test_client_path_hints.py::test_post_forwards_path_hints_to_search_only tests/test_t04_root_path_hint_chain.py::test_registered_repo_search_forwards_hints_over_real_root_http tests/test_t21_root_path_hint_worktree_chain.py::test_registered_search_honors_worktree_hint_and_path_policy`. Keep T10 retrieval tests in the broader combined acceptance command above.

## T20 slot status — 2026-10-03

Read-only latest T20 receipt remains NO-GO/unknown: probable Hub dispatch defect drops or renames `worktree_id`; release helper receives empty value and rejects. T16 is tracing read-only; parent was informed. No further release attempts or tests were reported. Therefore all selectors above remain prepared only, not accepted.

## Non-overlapping T21 config completion patch — 2026-10-03

Static symbol comparison confirms root and T21 candidate match for `ProjectSettings`, `ProjectConfigResolution`, `ProjectContext`, `PathHint`, `PathHintUsage`, `resolve_project_context`, `validate_path_hint`, `prioritize_paths_with_hints`, `resolve_pinned_context`, and `resolve_entry_points`. No production core delta remains.

Root is missing candidate-owned regression `test_project_config_precedence_covers_primary_linked_common_and_worktree_layers`, which covers ordered inheritance defaults → primary worktree project → linked repository project → Git-common config → worktree override. Prepared add-only patch `handoff/T21-worktree-precedence-root-current-tests.patch`, SHA-256 `E9902AE3A475DE2D6F8E5F0E887959A0CE953C9A81008332D7BC7015310AA37C`; exact root test preimage SHA-256 `90A66B610B84FADDF178147321362DB91139FFCE0FDC680E01AAD9FBD1866270`. Root `git apply --check` passed (exit 0); patch remains unapplied, no root write.

Exact selector after T20 GO: `tests/test_project_config.py::test_project_config_precedence_covers_primary_linked_common_and_worktree_layers`. No test run.

Client handoff remains `handoff/T21-search-only-client-root-current.patch`, SHA-256 `8B7ACE3677F369AF13101A137202108992FFC3415656985FD0B9E3B6278EEA79`; it contains only route gate `/api/search` and its test expectation. It does not include T16 cleanup ID forwarding, request-ID, tenant, retry, or transport hunks. T04's broader overlapping client transport seam remains independently owned and unchanged by T21. `/api/context/pack` and T10 retrieval/fallback untouched.

## Separate T16 cleanup blocker (excluded from T21 patch) — 2026-10-03

Latest T20 receipt relays T16's confirmed root cause: `worktree_id` drops across `mcp_server.py` → `client.py` → `http_server.py` → `services.py`; `process_utils.py` requires it and rejects empty. Ownership across those five modules is unclear; no coordinated owner, no safe fix, no tests. This is separate from T21 search-path forwarding. T21 client patch does not alter cleanup-ID forwarding, request IDs, tenant hints, retries, or other transport behavior.

## T21 project-config consumer coverage patch — 2026-10-03

Prepared disjoint add-only test patch `handoff/T21-worktree-search-preprocess-consumer-root-current.patch`, SHA-256 `9198AB105CA1471C0C1FD5575479156F8D0C11B56A2E9B8391CB3A4A7ACF2A7F`. Root `git apply --check` passed, exit 0. Patch touches only:

- `tests/test_project_config.py`: add `test_project_config_precedence_covers_primary_linked_common_and_worktree_layers`; root preimage SHA-256 `90A66B610B84FADDF178147321362DB91139FFCE0FDC680E01AAD9FBD1866270`.
- `tests/test_t21_project_config_preprocess.py`: new file, root preimage absent. Five T21 consumer selectors.
- `tests/test_t21_search_policy_consumers.py`: new file, root preimage absent. Three project-policy-to-search consumer selectors.

No production path, MCP/client adapter, T10 retrieval implementation, T14 context-pack route, or T16 cleanup identity hunk is included. Existing root command consumer coverage is selected separately; no duplicate command implementation.

Post-T20-GO consumer command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py::test_project_config_precedence_covers_primary_linked_common_and_worktree_layers tests/test_t21_project_config_preprocess.py tests/test_t21_search_policy_consumers.py tests/test_project_config_service_integration.py::test_run_affected_applies_project_mapping_and_path_hints_safely tests/test_project_config.py::test_verification_rules_reject_undefined_command_aliases tests/test_agent_verification.py::test_verification_store_forwards_project_rules_to_completion_evaluator tests/test_agent_verification.py::test_project_lint_command_receipt_binds_runner_to_configured_alias
```

Coverage intent: inherited config precedence + freshness, preprocessor exclusion/entry-point/recheck behavior, search extension/gitignore/binary policy, existing run-affected mapping, configured verification and lint command aliases. The T21 search tests exercise config consumption only; T10 retrieval/full-search behavior remains unchanged. Tests not run; T20 GO remains absent.
