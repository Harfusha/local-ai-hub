# T14 root-current packet — 2026-10-04

## Scope

Root checkout: `C:\Users\Adam\.local-ai-hub`; candidate: `C:\Users\Adam\.codex\worktrees\t14-context-budget-recovery\.local-ai-hub`.

Root already has the adaptive `/api/context/pack` route, integer token validation, and MCP `adaptive` forwarding. This packet carries only the missing unique evidence-ID projection and regression coverage: `src/local_ai_hub/mcp_server.py` plus new `tests/test_context_pack_budget_e2e.py`.

## Root identity and hashes

- Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Root `mcp_server.py` preimage SHA-256: `FDFDD51B35054A1C80A8B5DF0DD751D6745E0CF0C888AE6CF18A47D7B386EA73`.
- Projected postimage SHA-256 after applying the packet to an isolated copy: `04FF58CA3F82E1A8271D499585DE5F99F5A28986B4650DD0E0CCC5DBDE659B0F`.
- New E2E test preimage: absent.
- New E2E test projected SHA-256: `6AE1494740BDEFB8CA3CA7032ED2494E7FB9140C95C031466395379D4BD16B51`.
- Packet SHA-256: `0AB7EE2C93F739E4ACBB01E46247E0909B644F72EF3D7E950A42D0164B109B8F`.

Projected postimages were computed by applying this exact patch to a temporary copy. The root checkout was not modified; its actual pre/post source hash remains the preimage above. Root already has unrelated dirty files, preserved.

## Validation receipts

Candidate-only command (no root tests):

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_context_pack_budget_e2e.py tests/test_agent_context.py::test_context_etag_separates_request_scope_identity tests/test_agent_context.py::test_delta_pack_returns_unchanged_etag tests/test_agent_context.py::test_disabled_agent_state_returns_stateless_repo_context_warning tests/test_context_delivery.py::test_context_http_rejects_malformed_max_tokens_and_guard_fields tests/test_context_delivery.py::test_model_failure_returns_deterministic_degraded_pack tests/test_mcp_response_budget.py::test_context_projection_budget_rejection_keeps_bounded_identity_and_citation tests/test_mcp_compact_transport.py::test_local_ai_repo_context_returns_bounded_deterministic_projection tests/test_mcp_compact_transport.py::test_local_ai_repo_guarded_projection_drops_nested_raw_model_fields tests/test_mcp_compact_transport.py::test_local_ai_repo_context_bounds_oversized_authoritative_fields tests/test_mcp_compact_transport.py::test_local_ai_repo_context_low_budget_preserves_authoritative_envelope tests/test_mcp_compact_transport.py::test_local_ai_repo_context_forwards_guarded_pack_fields tests/test_mcp_compact_transport.py::test_local_ai_repo_context_preserves_legacy_fast_full_payload tests/test_response_budget.py
```

Result: `24 passed in 8.78s`.

Root-current `git apply --check` result: `APPLY_CHECK_PASS`. Candidate `git diff --check` exited 0; Git printed existing LF-to-CRLF working-copy notices only.

## Packet

- `T14-root-current-20261004.patch`
- Hash above is the packet integrity receipt. Keep this packet unchanged; regenerate only against a newly captured root preimage.
