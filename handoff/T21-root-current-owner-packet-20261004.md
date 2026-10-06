# T21 root-current owner packet — 2026-10-04

Status: candidate handoff only. No root edits or root tests. Root integration waits for T20 slot and owner coordination. `/api/context/pack`, T03 MCP contract, and orchestrator-owned `/api/search` remain excluded.

## Root identity

- Candidate checkout: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`
- Candidate HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`
- Root checkout: `C:\Users\Adam\.local-ai-hub`
- Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`

## Root-ready T21 core delta

Patch: [T21-path-hint-partial-metadata-root-current.patch](T21-path-hint-partial-metadata-root-current.patch), SHA-256 `3615028C88E1824D0AD07045B2AE9DA801FE3B38E646CFE00B0AEC7E07AE6157`. It changes only `src/local_ai_hub/project_config.py` and `tests/test_project_path_hints.py` (10 source lines changed; 31 test lines added). This accepts independently optional provenance fields on request hints while learned persisted hints still require complete provenance.

| Path | Candidate before → after SHA-256 | Current root preimage SHA-256 |
|---|---|---|
| `src/local_ai_hub/project_config.py` | `FFD425B1260B285F25B1D121A7C6BCD585C618B5C7E26415E2AD0A7014196B0B` → `088B8AFDF05A331E51C74925884B2B7984DF8BD5E3AD227C82DBDBEEB19289A1` | `00E80B1342E5E70A66FA8955D95553127E913F56EC693CF527B6AC96053BDBDE` |
| `tests/test_project_path_hints.py` | `43E3612144E38CC6C82EDAABF00E424478308FDF51E189878105186D64D4B606` → `22484A490FACED3D02FF1BB2F041F52831598A6F75573F00EBAC41BDD3539D81` | `92EC33C9BB69D75F50ACB9EFBC501C541574D877128112444458CD11576AA5C7` |

Read-only `git apply --check` against current root: exit 0. Nothing applied.

## Exact candidate receipts

- `tests/test_project_path_hints.py`: **25 passed in 0.74 s**, exit 0. Includes CakePHP `/templates/element` routing, full-result retention, path policy, freshness, and scope cases.
- `test_request_path_hint_accepts_partial_optional_metadata` and `test_project_config_precedence_covers_primary_linked_common_and_worktree_layers`: **2 passed in 0.32 s**, exit 0.
- Telemetry privacy selectors `test_path_hint_telemetry_metadata_excludes_candidate_paths` and `test_path_hint_telemetry_metadata_normalizes_malformed_runtime_values`: **2 passed in 0.48 s**, exit 0.
- Fresh behavior selectors `test_project_context_never_reads_hub_state_as_configuration` and parameterized `test_search_honors_forced_gitignored_directory`: **3 passed in 0.66 s**, exit 0. The project resolver uses `.local-ai.toml` under the repository and leaves the same-named Hub-state file unchanged. Search returns the visible file and explicitly forced `node_modules/@my-org/button.php` with both explicit-hint settings.
- `test_search_honors_project_custom_text_extensions` asserts both visible and configured `.shader` files with and without an explicit request hint. Its earlier broad-run output was not retained, so no isolated passing receipt is claimed. Consumer `LocalAIServices.repo_search` only; no MCP, client, or HTTP route acceptance claim.

## Failed cross-worktree lease selector — evidence only

Candidate-only test file: `tests/test_t21_coordination_namespace_bridge.py`, SHA-256 `AE847F92E0F5AF92D3724BBB99FC16B5FE0B29BAA087A7A5F942FCE0AECBDD45`; exact test-only patch [T21-namespace-wrapper-tests-AE847F92E0F5.patch](T21-namespace-wrapper-tests-AE847F92E0F5.patch), SHA-256 `A3D0F585A011956FAB870ACC2247496E3A19741A8CE80AA46BC8FAB3FE8EE71F`. The root preimage is **MISSING**. Do not add this file to the root-ready core patch: its relevant selector currently fails.

Exact candidate command selectors:

```text
tests/test_t21_coordination_namespace_bridge.py::test_client_cannot_override_namespace_or_tenant_for_memory_find
tests/test_t21_coordination_namespace_bridge.py::test_overlapping_lease_from_same_namespace_conflicts_across_worktrees
tests/test_t21_coordination_namespace_bridge.py::test_lease_renew_and_release_require_the_owner
```

Receipt: **2 passed, 1 failed in 14.44 s**, exit 1. Failure at test line 247: `conflicting["success"]` was `True`, expected `False`. The client tenant override and lease-owner checks passed.

### Failure trace and owner boundary

Both worktree contexts produce the same `ProjectContext.coordination_id`. T03-owned `mcp_server.local_ai_coord` accepts/sends the concrete `root`; claim dispatch sends no coordination ID. T06-owned HTTP lease route passes that root to `ScopeLeaseStore`. `ScopeLeaseStore._root` hashes the canonical root path, so separate worktree paths get separate lease domains.

| File | Candidate working SHA-256 | Current root working SHA-256 | Owner / use |
|---|---|---|---|
| `src/local_ai_hub/mcp_server.py` | `436985F193EDABE896A8A7A3F002601F9307D576DB669EA006C4599060393838` | `FDFDD51B35054A1C80A8B5DF0DD751D6745E0CF0C888AE6CF18A47D7B386EA73` | T03; claim forwards root only |
| `src/local_ai_hub/http_server.py` | `0206929817D58D5D6192C8D082DA201F399D06A60679CE5A934EDA8F93199AF0` | `C97AA26A4D84BE35FE7BFA1A18FDBB5AE9A5BA393F73D541D38E3F2DCB33D93D` | T06/lease route dispatch |
| `src/local_ai_hub/leases.py` | `BF56E69ABC46DCF1B9CC4B4778251618FD1EA243329D58E48BEFE833DB1AF1CB` | `446959227D37E706BFA1511CEE304C6D84FDD91DA0EBFEF5FBB88AFAEEAFD6AE` | Lease owner; hashes canonical root |

These owner files are evidence inputs only. No adapter fix or root test belongs in this packet. T03/T06 coordination and an explicit T20 slot are required before testing an integrated root change.

## Search-only owner correction and acceptance (2026-10-04)

The user's latest scope explicitly assigns T21 search-specific `local_ai_repo` path hints, `HubClient.post` search serialization, and `/api/search` route forwarding. It excludes T03 generic transport/request-ID/client-contract symbols and excludes `/api/context/pack`. T03 confirmed it will leave those search path-hint symbols to T21; T06 confirmed T21 owns `/api/search` and no T06 overlap was identified. T21 stayed out of general client request/retry/auth symbols and all non-search HTTP routes.

### Root-current owner packet patch

Combined candidate patch: [T21-root-current-project-path-search.patch](T21-root-current-project-path-search.patch), SHA-256 `EC58A87F2C98EB6455A6F3CBDC8A90A7F1A558D440BEEA1114333AFA12C4A581`, 6,263 bytes. It combines:

- Core partial-metadata patch SHA `3615028C88E1824D0AD07045B2AE9DA801FE3B38E646CFE00B0AEC7E07AE6157`.
- Client search-only eligibility patch SHA `8B7ACE3677F369AF13101A137202108992FFC3415656985FD0B9E3B6278EEA79` (only `/api/search` retains hint forwarding; `/api/command` drops it; request IDs/retry/auth untouched).
- MCP search-only validation/forwarding patch SHA `3CACF85B932EC374F91085620BA26FBEB87EF9183FD1B15663F122DDD814D60C` (25 changed lines in `_normalize_repo_search_path_hints` and search dispatch; preserves current root's cross-platform Windows path resolver).

Combined patch paths: `project_config.py`, `test_project_path_hints.py`, `client.py`, `test_client_path_hints.py`, `mcp_server.py`. `git apply --check` against current root worktree returned **0**; nothing was applied. This preflight targets current dirty root files, not clean root HEAD. Current root already contains uncommitted HTTP search-hint code. Its `/api/search` handler block is text-identical to candidate block, SHA-256 `B5D054BEB08D6A09E0E67E75B8E7F72F9D3744011FF538237322AE06D5E43DEF`; no HTTP route hunk needed. Root's MCP helper differs from candidate; the included patch adds strict required/optional-field validation and terminal input errors while retaining root resolver behavior.

Candidate / root-current whole-file SHA-256:

| Path | T21 candidate | Root current working file |
|---|---|---|
| `src/local_ai_hub/project_config.py` | `088B8AFDF05A331E51C74925884B2B7984DF8BD5E3AD227C82DBDBEEB19289A1` | `00E80B1342E5E70A66FA8955D95553127E913F56EC693CF527B6AC96053BDBDE` |
| `src/local_ai_hub/mcp_server.py` | `436985F193EDABE896A8A7A3F002601F9307D576DB669EA006C4599060393838` | `FDFDD51B35054A1C80A8B5DF0DD751D6745E0CF0C888AE6CF18A47D7B386EA73` |
| `src/local_ai_hub/client.py` | `1E28197A3C9FF920A4C71FC5189A3CB425B79189CA5F5F001416D175A9E6A79D` | `4E250AD3496E665F428FAC5B0E231238AE71017ED9078C2682513932797CA632` |
| `src/local_ai_hub/http_server.py` | `0206929817D58D5D6192C8D082DA201F399D06A60679CE5A934EDA8F93199AF0` | `589C578EA5EB78C3192D3531FB776BF93FD703D9EFAB85B358B04A30891EFF24` |

### Exact T21 candidate validation

One focused command ran against T21 candidate only:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_path_hints.py tests/test_client_path_hints.py tests/test_mcp_repo_path_hints.py tests/test_t21_search_policy_consumers.py tests/test_t21_candidate_path_hint_worktree_e2e.py
```

Receipt: **120 passed in 17.46 s**, exit 0. Coverage includes config precedence and linked/worktree inheritance; project-vs-Hub-state separation; traversal/symlink security; same-common-dir isolation; evidence/revision/config-digest binding; stale-row fairness and expiry; custom text extensions, force-include and binary policy; CakePHP `/templates/element` ranking; worktree E2E; registered MCP validation/forwarding; `/api/search` forwarding/repository-hit selector; client exact body, cap and route filtering; and an explicit `/api/context/pack` non-forwarding assertion.

No root tests ran. Search-only consumer ownership was not expanded to T03 generic request IDs, T04 retry/auth/replay, unrelated service methods, or `/api/context/pack`.
