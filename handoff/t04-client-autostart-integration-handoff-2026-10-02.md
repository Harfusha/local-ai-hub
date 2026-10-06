# T04 client/autostart integration handoff — 2026-10-02

## Revisions and ownership

- Candidate worktree: C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub
- Candidate HEAD: 3658d5056354849ddf17883ed04f807f16cc44c1; parent: f305ec6a8f4200b1fd9a2bde5048f43bd508db19.
- Merge base with root HEAD: 2b33602adef0d030fea66cdcc04ca742c60b2e32.
- Root HEAD: 01df56605ccf484ebfe2808ac60d696c4e81dffc.
- Root was not edited during this handoff. Existing root files are dirty/untracked from shared work; findings below distinguish presence from authorship.

## Current T04 candidate paths and hashes

- src/local_ai_hub/client.py: 007A7D932C54FBA78D411B9EC622B70FEDC35666DFCCA275311444F26C05002B (candidate includes tenant binding, request deadline/cancellation, retry classification and readiness waiting).
- tests/test_client_tenant_override.py: C34DA8FA8C740FA1711F20C213D0CCA978515C89DD101302166F01275B05F1EF.
- tests/test_client_transport.py: FE3F90240CCA4DAE7F3B2B0DD3CAFEA8A0AA29916AC7CC1A35A9EB364C1BF242.
- tests/test_t04_public_api_contracts.py: F95730F0D77B51C1D9163BA1B5F95B47967A981CE278128D305A2EF4C925C002 (fixture now supplies root/principal scope).

## Root-current patches and preimage checks

| Patch | SHA-256 | Forward check on root HEAD + dirty worktree | Reverse check | Interpretation |
|---|---|---|---|---|
| handoff/t04-root-current-autostart-only.patch | DD6A767D4B6087D8BA8148FC6ACDB05E07C0207DEF804381144FDB52F34AFC2D | Fails at client.py:356 | Pass | Wait-until-ready hunk is already present in current root client.py; no patch needed for that hunk. |
| handoff/t04-root-current-service-autostart-test.patch | ACEAB4F9B2F0FEA1532261FEAABAA9487BFC9EBCD1029682AC22712050BD23C5 | Fails: new file already exists | Pass | Test content is already present in root worktree as untracked file. It is not committed at root HEAD. |
| handoff/t04-root-current-tenant-deadline-combined.patch | FBED6CF6CD42699A81F1B6128FF046105835A0E303EF4B5B25951E4D1B01F007 | Pass | Not needed | Combined current-client patch for tenant binding + HTTP deadline/cancellation/classification. |
| handoff/t04-root-current-tenant-contract-test.patch | BBA355321A566E4C9EC44D68591B7118719048AA95E9B7D1ECB2A91F4E796BD2 | Pass | Not needed | Adds tests/test_t04_root_tenant_binding.py only. |

Root current src/local_ai_hub/client.py hash is 75B07C21735B881ED58C03BFC80B450410C3778C248D662A7C8E675549180D4F; root current autostart test hash is 858C528B86E5048CD0A11C3F5A2B43CB0D4E5AF2B2984233E02A3ED5ED5C7FB4. The autostart patch's client hunk is already integrated in the dirty root file. The new test file is present but untracked. Do not reapply either patch blindly.

## Existing candidate test receipt

Exact API/conversation batch:

python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_public_api_contracts.py tests/test_conversations.py tests/test_conversation_continue_route_contract.py::test_hub_client_continues_through_production_route_and_preserves_transcript tests/test_conversation_continue_route_contract.py::test_expired_conversation_is_terminal_through_production_route tests/test_conversation_continue_route_contract.py::test_competing_continuation_is_retryable_in_progress_through_production_route tests/test_mcp_agent_routing.py::test_local_ai_task_forwards_continue_with_opaque_conversation_id tests/test_mcp_agent_routing.py::test_local_ai_repo_investigate_preserves_include_code tests/test_mcp_agent_routing.py::test_repo_review_diff_returns_foreground_result_by_default tests/test_agent_tasks.py::test_task_query_bounds_rows_scanned tests/test_agent_tasks.py::test_task_query_scan_window_is_bounded_before_stale_filter tests/test_agent_tasks.py::test_task_query_skips_stale_candidate_before_page_limit tests/test_surface_inventory.py::test_inventory_extracts_surfaces_and_resolves_dynamic_route_registry

Historical result: 40 passed in 47.55s, exit 0, in candidate worktree. Command text SHA-256: 0B75E141227590A36D6E97AAA3057C2FAB60A9D57089244D87C0F942AAFCA7EC. No source/test edits followed this receipt run; only handoff documentation changed.

No T20 serial GO is recorded for that 40-selector batch. It remains candidate-only. The run was already in progress when T20 said it could finish; available coordination evidence does not establish that it overlapped another test runner. Do not claim either overlap or a T20 GO.

The separate 16 transport selectors passed in two groups of 8 after a connect-timeout classification fix. User authorized those tests, but a separate T20 GO was not recorded. Those results are candidate-only as well.

## Autostart evidence limits

The existing test_thirty_cold_clients_share_service_start_and_readiness in tests/test_t04_root_current_service_autostart.py creates 30 clients, but mocks _online, subprocess.run, listener/PID discovery, and _pooled_open. It proves the mocked shared-lock/readiness coordination path and one mocked service-start call, not real child creation, supervisor ownership, daemon readiness, or HTTP search. A separate 2-thread test in tests/test_client_transport.py tests identical-request singleflight and does not prove two-client autostart/process behavior. No claim of a real two-client process test is supported by these receipts.

## T03 tenant-header dependency

T03's proxy builder passes tenant="". This is safe only with the T04 constructor change: current root constructor still falls back to agent-{pid} when tenant is falsey, while T04 candidate makes the default empty and omits that generated header. Root-scoped candidate requests derive the root HMAC tenant; if sent as X-LocalAI-Tenant, it is a deterministic matching consistency hint, never body-selected scope. Integrate T04 tenant semantics before treating T03's tenant="" as suppressing the PID header. T13 requires the server to derive scope from authenticated principal plus canonical allowed root.

## Outcome-unknown boundary

- ConnectionRefusedError before send is classified as definitely not sent.
- Generic connect timeout and failures after write begins remain outcome-unknown; callers must not infer non-delivery.
- Safe replay is endpoint/operation allowlisted and request-ID based. Unsafe mutations are not replayed after an ambiguous send.
- The listed evidence is mocked/local test evidence. No live daemon, adapter runtime, or actual child-process acceptance is established here.

## Root-cleanliness statement

No root write or test run occurred for this handoff. No duplicate tests were run.

