# T21 search path hints owner packet — 2026-10-06

Status: **ACTIVE / acceptance incomplete**. Owner: T21. Exact checkout: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`.

## History and sync

- Task branch: `codex/sync-t21-project-config-20261006`.
- Base SHA: `90e6f2957489b272f03cd0f3550149907f24bbf7`.
- T21 implementation commit: `eaefb387652861fa5bf91033594db92bf738968b`.
- Master synchronized from: `9de8a2ad44cafd333f56154771afe7f6f65401c7`.
- Final HEAD: `85b2d464477564162b4df7217ff7b809c6d72030` (merge commit, parents T21 commit and master).
- `git merge-base --is-ancestor refs/heads/master HEAD`: exit 0. Branch ahead/behind after sync: `0 2` (`git rev-list --left-right --count refs/heads/master...HEAD`).
- Worktree was clean before attribution and clean after merge; implementation commit touched exactly the three paths below. Master merge had no conflicts.

## Owned implementation paths and blobs

| Path | Base blob / SHA-256 | T21 commit blob / SHA-256 |
|---|---|---|
| `src/local_ai_hub/repo_tools.py` | `0624be3f187a3c90d7fd0c2d8e7f8ce4a5f14d7f` / `D8257D16CC9E051FDC1E79D68BEF07767ABEC68562D63ED614F5F1EAD69C4119` | `07c057a13162820ce9d9f80cc81c08eda908a7f6` / `BC5C908633CB734E9351F2E0D5C41A5B738A4B6852D78763C26D88251BE98A9A` |
| `src/local_ai_hub/services.py` (`LocalAIServices.repo_search` only) | `8e343f9d4752879158ec48aef8baf8c0a5493d98` / `193591C5183C1F869B6D996B9E1F11BE26D110CFE4A44DDB5C739F437B1EB7EF` | `9b48e4172d40271bc78b045f1c16c4c4260c844e` / `0430D8EF489ED608607EA7A95564A90759F3075D5CE037FFD197DD3AD9B12B20` |
| `tests/test_project_config_service_integration.py` | `5ed4c2c987a9e224d661a878a26da2a57fbd8eb6` / `1717CAF4BB21FF0B54FB8687C15C2D23E3F264CE0617DE25A084723C44BBC480` | `84f54f4a46478f61dfb5e200cc4e3a3c3efd4d89` / `522821CFAC15B16D5D6DEBB0D09198B156C0AC0EA4DEBABEC48E4000E7C120F8` |

T21 changes: consume saved and request hints in bounded candidate search; bind hint set into cache digest; fail closed for invalid project policy or unavailable Git inventory; path-free `path_hint_usage` projection (`hint_used`, `fallback_used`, `hint_helped`); pass one preloaded inventory through bounded full and targeted search; bounded Python fallback cap/sentinel metrics. Test doubles accept actual `search_paths` keyword arguments; inventory count assertion now verifies one shared inventory load.

Patch: `handoff/T21-search-path-hints-20261006.patch`, 12,955 bytes, SHA-256 `024CB14FC8BD09F80189F83FFD9AFFEF26661BE6ABF8768269B184920B083606`. Patch is exact binary diff for implementation commit against base, limited to the three paths.

## Validation receipts

T21-owned search/fallback selectors:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config_service_integration.py::test_repo_search_hints_respect_gitignore_and_searchable_file_rules tests/test_project_config_service_integration.py::test_repo_search_prioritizes_verified_project_path_hint_without_narrowing tests/test_project_config_service_integration.py::test_repo_search_uses_explicit_request_hint_for_unindexed_file tests/test_project_config_service_integration.py::test_repo_search_keeps_full_original_candidate_window_when_adding_hints tests/test_project_config_service_integration.py::test_repo_search_hint_hit_does_not_skip_broader_results tests/test_project_config_service_integration.py::test_repo_search_propagates_unavailable_git_inventory tests/test_project_config_service_integration.py::test_repo_search_fails_closed_when_project_policy_cannot_load tests/test_project_config_service_integration.py::test_repo_search_fails_closed_for_invalid_policy_without_index_candidates tests/test_t21_project_config_preprocess.py::test_python_search_fallback_has_independent_file_cap_and_metric tests/test_t21_project_config_preprocess.py::test_python_fallback_truncation_requires_omitted_candidate_sentinel
```

Result: **11 passed in 3.51s**, exit 0.

Full focused candidate after master sync:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_config_worktrees.py tests/test_project_config_service_integration.py tests/test_t21_project_config_preprocess.py tests/test_project_path_hints.py tests/test_mcp_repo_path_hints.py tests/test_client_path_hints.py
```

Result: **142 passed, 5 failed in 9.99s**, exit 1. Remaining selectors are cross-owner blockers: two `run_affected` behavior tests (T16); `test_api_search_forwards_path_hints_to_repo_search` (`http_server.py` `/api/search` route; T06); two `client.py` route/sanitization tests (T04). No T21-owned selector failed.

`git diff --check -- src/local_ai_hub/repo_tools.py src/local_ai_hub/services.py tests/test_project_config_service_integration.py`: exit 0.

## Ownership and remaining acceptance

- T21 owns the three implementation paths above and bounded repository-search behavior.
- T03 schema/dispatch contract is separately released; T04 owns HTTP client forwarding/sanitization; T06 owns the HTTP `/api/search` route; T16 owns `run_affected` orchestration behavior.
- T21 did not edit `operation_contracts.py`, `mcp_server.py`, `client.py`, `http_server.py`, T16 methods, or `/api/context/pack`.
- Full end-to-end acceptance remains blocked on T04/T06/T16 owner changes/releases and a subsequent focused rerun. Do not mark done.