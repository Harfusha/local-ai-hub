# T03 root-current search seam reconciliation

Checked 2026-10-01. Candidate HEAD: `d68ee694c6d3f75db5c1ab2f63497226880e5010`. Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a` (T20-owned, dirty). No root edits or root tests by T03.

## Result

No root-current patch is needed for the released T03 search seam: root already contains the public schema, MCP dispatch and HTTP forwarding. A generated forward patch would duplicate current dirty root content. The earlier candidate patch `T03-root-path-hints.patch`, SHA-256 `44ED6619E8B16ABF882E0F8FBF836DC2231A645258CD8D8BB0F71CE7C7908A00`, is stale against root and should not be applied.

Root evidence:

- `src/local_ai_hub/operation_contracts.py:175-224`: `path_hints` is scoped to repo `search`; nested schema requires `path`, `purpose`, and `scope`, caps 64 items/1024 path chars, and rejects extra properties. Runtime/action validation at `482-551,1048-1098`.
- `src/local_ai_hub/mcp_server.py:144-195`: normalize and root-confine hints. Search wrapper signature at `1916`, forward at `1981-1989`; action validation/normalization at `2385-2400`.
- `src/local_ai_hub/http_server.py:3930-3938`: `/api/search` forwards `payload.path_hints` to `repo_search`.
- `src/local_ai_hub/services.py` is T21-owned for this adapter. Root currently has `repo_search(..., path_hints=...)`; T03 did not edit this service implementation.

T20 reported **30 root path-hints tests passed**. T03 candidate focused selectors previously passed **9 tests in 2.87s**:

```text
tests/test_operation_contracts.py::test_repo_path_hints_schema_is_bounded_and_search_only
tests/test_operation_contracts.py::test_local_ai_repo_path_hints_forward_only_when_consumer_supports_them
tests/test_operation_contracts.py::test_local_ai_repo_search_normalizes_windows_path_hints_within_root
tests/test_operation_contracts.py::test_local_ai_repo_search_rejects_path_hints_outside_root_before_dispatch
tests/test_operation_contracts.py::test_local_ai_repo_search_rejects_backslash_traversal_for_posix_root
tests/test_mcp_compact_transport.py::test_local_ai_repo_non_context_actions_ignore_guard_fields
```

## Omit from any T20 cherry-pick/integration

- `operation_contracts.py`: receipt, pipeline and unrelated action-schema hunks.
- `mcp_server.py`: tool catalog/status/transport changes, receipt gate/schema, and every non-search action hunk. Its current diff also contains unrelated shared changes; do not replace the whole file.
- `http_server.py`: all routes other than `/api/search`, including `/api/context/pack`, operational-mode/gaming, SSE/request-id and task cleanup hunks. Do not replace the whole file.
- `services.py`: all T03 write-set dispatch changes; the search adapter is T21-owned and already present in root.
- `generator.py` receipt schema and unrelated test/doc changes.

No patch was emitted because the released path-hints seam is already present in root. Root remains T20-owned; T21 service/config ownership is unchanged.
