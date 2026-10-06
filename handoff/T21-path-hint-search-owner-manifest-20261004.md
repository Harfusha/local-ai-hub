# T21 path-hint search handoff — 2026-10-04

Status: T21 core is implemented and candidate-tested. Cross-owner public integration is not released for root integration. This manifest is an evidence handoff; it grants no adapter ownership.

## Pinned worktrees

- T21 candidate: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`, branch `codex/t21-project-config`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- Root preimages: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- No root files were edited and no root tests were run.

## Typed seam contract

Core `PathHintUsage` carries ordered paths internally. Its telemetry projection is exactly:

```text
hint_used: bool
fallback_used: bool
hint_helped: bool | None
```

The projection contains no paths, hint values, or candidate identifiers. Public input is `local_ai_repo(action="search").path_hints`, a bounded list validated by T03's adapter and forwarded to `/api/search`; search meaning and ranking stay in T21 core. T03 reported these adapter candidate pins:

- `src/local_ai_hub/operation_contracts.py` SHA-256 `F84FD40A594A34B0E73C53CF28D98614200E142334FDE632ECDBAC5BA0A0DFFF`
- `src/local_ai_hub/mcp_server.py` SHA-256 `3B36A3313DC04388F49A29741FACAF29BE2D4CFCF8964E9A905FC006F3F9B24D`
- T03 selector: `test_mcp_repo_search_forwards_path_hints_to_http_payload` (T03-reported; not run in T21 checkout).

## Path-to-owner matrix

| Path / seam | Owner | T21 action and boundary |
|---|---|---|
| `src/local_ai_hub/project_config.py` — resolver, `PathHintUsage`, privacy projection | T21 | Core producer; current candidate SHA-256 `088B8AFDF05A331E51C74925884B2B7984DF8BD5E3AD227C82DBDBEEB19289A1`; root preimage `00E80B1342E5E70A66FA8955D95553127E913F56EC693CF527B6AC96053BDBDE`. |
| `src/local_ai_hub/services.py` — search use/result metadata | T21 | Search consumer; current candidate SHA-256 `24A01432EA4288BA0CF4AA27AAF6FA4A769CF8167F56FDE70714EE78967939CF`; root preimage `0FAB8C8224BA37C08F85F46210120777EEA20E14F7BA4B5C09936D79593FBD0C`. |
| `src/local_ai_hub/repo_tools.py` — bounded Python fallback completeness | T21 | Search engine reports `python_fallback_truncated` only when one extra iterator item proves omission; current candidate SHA-256 `9C4692A452A45304A246D4B9BEB7325BEA04ED8D7A1458BBB2BE9D93B9C91A0C`; root preimage `360734CEB316A8A9FC698C19C1098D88FC591170DBBF5F3B67DB6608CD3A6A36`. |
| `tests/test_project_path_hints.py`, `tests/test_t21_project_config_preprocess.py`, `tests/test_mcp_repo_path_hints.py` | T21-owned tests | Current candidate SHA-256 respectively `22484A490FACED3D02FF1BB2F041F52831598A6F75573F00EBAC41BDD3539D81`, `0391722543F054ACCDFB6C73D2FDA0803ACC193A5F50D872EAE1C484374FDF7E`, `9838B44544EEA494D6AEA3DFA469E935346106D88006F351A7574D54302CFD64`. |
| `src/local_ai_hub/operation_contracts.py`, search-specific `src/local_ai_hub/mcp_server.py` input validation/forwarding | T03 | T03 says contract is implemented in its candidate and releases the public `path_hints` input contract. T21 did not edit these adapters. |
| `src/local_ai_hub/http_server.py`, `/api/search` public response seam | T06 | No T06 release recorded for this handoff. T21 made no route edits. Candidate HTTP route was exercised by a T21-owned focused test; root route acceptance remains unverified. |
| T09 task/recovery consumers; T14 context-budget consumers | T09 / T14 | Owners report no current PathHintUsage dependency and release no paths. No edits. |
| T16/T19 consumer paths | T16 / T19 | Protected; no edits or ownership inference. |
| `/api/context/pack` | excluded | Untouched. |

## Exact candidate verification

Run in the T21 candidate only:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t21_project_config_preprocess.py::test_python_search_fallback_has_independent_file_cap_and_metric tests/test_t21_project_config_preprocess.py::test_python_fallback_truncation_requires_omitted_candidate_sentinel tests/test_mcp_repo_path_hints.py::test_api_search_route_consumes_t03_hint_and_returns_repository_hit
```

Result: **4 passed in 3.95s**, exit 0. The parametrized sentinel cases prove exact-cap exhaustion is false and a yielded omitted candidate is true. The HTTP route selector uses real Python fallback and asserts the public result carries `python_fallback_truncated=true`.

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_path_hints.py::test_path_hint_telemetry_metadata_excludes_candidate_paths tests/test_project_path_hints.py::test_path_hint_telemetry_metadata_normalizes_malformed_runtime_values
```

Result: **2 passed in 0.15s**, exit 0. Telemetry contains only the three typed fields and no candidate paths; malformed values normalize safely.

## Integration blocker

T03 input contract is available; T09/T14 report no consumer seam. T06 `/api/search` response ownership has no release receipt in this handoff. Therefore no cross-owner adapter edit, root patch application, or root test is authorized/claimed. Resume integration only after the T06 owner provides an exact route scope or immutable owner patch. Candidate receipts above are not root acceptance.
