# T21 root-current path-hints packet — 2026-10-04

Status: PARTIAL / owner-gated. T21 source patch apply-check passes against current dirty root. Public response metadata remains blocked on T16; T03 has no safe root-current adapter patch. Root untouched; no root tests.

## Pinned checkout

- T21 candidate: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`, branch `codex/t21-project-config`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- Root current: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.

## T21 root-current source patch

`T21-path-hints-t21-owned-root-current-20261004.patch` SHA-256 `97E325D27FFC32BC5350BAFD6B4602E6F95BF4BA1BB5793DD323AB01CCD25926`. Includes T21 project config/privacy projection, `/api/search`-only client hint serialization, Python fallback sentinel, and T21 project/client tests. Does not include MCP adapter, HTTP route, or service result projection.

Root `git apply --check`: exit 0; no application. `git apply --stat`: 5 paths, 46 insertions, 5 deletions.

Root preimage SHA-256: `project_config.py` `00E80B1342E5E70A66FA8955D95553127E913F56EC693CF527B6AC96053BDBDE`; `client.py` `2A546D0B5C74FABA304242843F5AED53ED77F3FD5978A7AD38E0332F1F996FEE`; `repo_tools.py` `360734CEB316A8A9FC698C19C1098D88FC591170DBBF5F3B67DB6608CD3A6A36`; `tests/test_project_path_hints.py` `92EC33C9BB69D75F50ACB9EFBC501C541574D877128112444458CD11576AA5C7`; `tests/test_client_path_hints.py` `2D4F101AD392365C96CB3E1419415E1CB361764D4535B7752280BB964C35329F`.

## Owner matrix and blockers

- T21 owns project path resolution, `PathHintUsage`, search use, search-only client serialization, fallback completeness, and its tests. Telemetry projection fields: `hint_used: bool`, `fallback_used: bool`, `hint_helped: bool | None`; no paths/identifiers.
- T03 owns MCP/schema adapters. T03 approved a separately owner-labeled candidate packet, but reports no safe root-current patch: root `operation_contracts.py` is untracked and broader than search; root `mcp_server.py` is dirty. T03 candidate only: HEAD `ad622f8a90a81e349e94d3402f297f2995e733b2`, `operation_contracts.py` SHA `F84FD40A594A34B0E73C53CF28D98614200E142334FDE632ECDBAC5BA0A0DFFF`, `mcp_server.py` SHA `3B36A3313DC04388F49A29741FACAF29BE2D4CFCF8964E9A905FC006F3F9B24`; 110 candidate tests passed in 22.02s. These are not root pins.
- T06 owns `/api/search`. Candidate and root route blocks compare exactly equal (9 lines): both pass `payload.path_hints` to `APP.services.repo_search` and return the result. No route hunk needed; no T06 release recorded. `/api/context/pack` untouched.
- T16 owns service result semantics. Root service consumes hints but lacks `path_hint_usage` output projection. Candidate has it. No T16 patch/source edit included.
- T09/T14 report no current PathHintUsage dependency and release no paths. T19 protected and untouched.

## T21-owned route test hunk

`T21-api-search-path-hint-e2e-test-root-current-20261004.patch` SHA-256 `5AA575EA78E7271B0FAC2D54A01F6D3D514F44F14964EBC92DED5D2A2DACD738`; root preimage apply-check passed. This test-only hunk asserts public `/api/search` returns exactly `{"hint_used": true, "fallback_used": false, "hint_helped": null}` and requires T16 service projection. It is not in the source patch; do not integrate as complete until T16 releases that seam.

## Exact candidate receipt

Run once in T21 candidate: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_path_hints.py::test_post_forwards_path_hints_to_search_only tests/test_client_path_hints.py::test_search_sends_exact_typed_path_hints_request_body tests/test_client_path_hints.py::test_post_caps_path_hints_and_drops_unlisted_fields tests/test_mcp_repo_path_hints.py::test_repo_search_forwards_known_path_as_scoped_path_hint tests/test_mcp_repo_path_hints.py::test_registered_local_ai_repo_passes_public_path_hints tests/test_mcp_repo_path_hints.py::test_api_search_forwards_path_hints_to_repo_search tests/test_mcp_repo_path_hints.py::test_api_search_route_consumes_t03_hint_and_returns_repository_hit tests/test_project_config_service_integration.py::test_repo_search_prioritizes_verified_project_path_hint_without_narrowing tests/test_project_config_service_integration.py::test_repo_search_uses_explicit_request_hint_for_unindexed_file tests/test_project_config_service_integration.py::test_repo_search_hint_hit_does_not_skip_broader_results tests/test_project_path_hints.py::test_path_hint_telemetry_metadata_excludes_candidate_paths tests/test_project_path_hints.py::test_path_hint_telemetry_metadata_normalizes_malformed_runtime_values tests/test_t21_project_config_preprocess.py::test_python_fallback_truncation_requires_omitted_candidate_sentinel`.

Result: 14 passed in 3.55s, exit 0. Candidate-only; no root tests.

Superseded: do not apply `T21-root-current-project-path-search.patch` or rely on `T21-root-current-owner-packet-20261004.md`; they combine T03 MCP hunks and record an earlier T06 release.