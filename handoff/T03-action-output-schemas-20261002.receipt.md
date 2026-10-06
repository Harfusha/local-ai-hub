# T03 action output schema handoff

## Scope

- Worktree: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`.
- Root checkout and `/api/context/pack` were not touched.
- T04 `client.py` and `inprocess_transport.py` were not touched; no transport wiring was added.
- Preserved inherited dirty changes in `mcp_server.py`, `operation_contracts.py`, and `tests/test_mcp_contract_dispatch.py`.

## Change

- `operation_output_schema` now closes each action's top-level output properties and labels its branch with `x-operation-action`, including status and artifact actions.
- `operation_tool_output_schema` emits one branch per currently enabled action without deduplicating action identity. FastMCP registration publishes this feature-filtered union.
- Runtime output validation rejects undeclared top-level fields in addition to validating types; dispatch returns the existing bounded output-contract error instead of returning a forbidden field.
- Added live catalog, disabled-feature, and dispatch regression tests. Updated action contract tests to expect closed schemas and keep the nested non-finite number check on an allowed results path.
- The `local_ai_repo(action="search")` input contract includes optional validated `path_hints` (maximum 64 entries; required `path`, `purpose`, and `scope`). Announced to T21 thread `01a0d7b9-04b9-7da1-906e-393693d07f65` with candidate/integration status.

## Validation

- Exact focused command completed: **28 passed in 3.12s**.
- The first attempted command referenced a nonexistent test selector and ran no tests. The corrected command was:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short
  tests/test_mcp_contract_dispatch.py::test_live_mcp_schema_publishes_action_conditions_and_output_schema
  tests/test_mcp_contract_dispatch.py::test_live_output_schemas_expose_action_specific_variants
  tests/test_mcp_contract_dispatch.py::test_live_mcp_schemas_match_registry_for_every_public_tool
  tests/test_mcp_contract_dispatch.py::test_live_output_schema_has_closed_branch_for_every_enabled_action
  tests/test_mcp_contract_dispatch.py::test_mcp_dispatch_rejects_action_forbidden_output_fields
  tests/test_mcp_contract_dispatch.py::test_output_schema_omits_disabled_actions_and_their_payload_fields
  tests/test_mcp_contract_dispatch.py::test_enabled_batch_replacement_schema_publishes_edit_arguments
  tests/test_operation_contracts.py::test_action_metadata_exposes_consistent_input_and_output_schemas
  tests/test_operation_contracts.py::test_primary_tool_outputs_publish_distinct_action_shapes
  tests/test_operation_contracts.py::test_every_primary_action_publishes_typed_payload_fields
  tests/test_operation_contracts.py::test_action_output_contracts_type_specialized_dispatch_results
  tests/test_operation_contracts.py::test_action_input_contracts_filter_tool_wide_fields_and_runtime_arguments
  tests/test_operation_contracts.py::test_live_repo_action_literal_respects_batch_replacement_feature
  tests/test_operation_contracts.py::test_non_finite_numbers_are_rejected_in_untyped_nested_output_fields
  tests/test_operation_contracts.py::test_all_public_tool_payload_fields_are_runtime_validated
  tests/test_operation_contracts.py::test_output_contract_rejects_non_object_and_non_finite_declared_values
  tests/test_operation_contracts.py::test_artifact_list_schema_rejects_fields_used_only_by_get_and_slice
```

- `git diff --check` emitted no whitespace errors. Git warned that the four modified source/test files use LF and may be rewritten as CRLF on a future Git touch; no normalization was run.
- No tests are running now; the exclusive test slot is free for T04.

## Hashes

Initial observed hashes for inherited dirty files:

- `src/local_ai_hub/mcp_server.py`: `B83ADBDFEF3C77070FD8611DCF9AD2F400419BE3E070A4EE298177E855EEA4D8`
- `src/local_ai_hub/operation_contracts.py`: `D676494561F1B6581121CD74FB0ED6CDE6D6843796040070F1C7363729614BBA`
- `tests/test_mcp_contract_dispatch.py`: `1DC7B8F7677BC207E35189B28111140F7CF139CBB45428D7094B24D121291AF0`

Current post-change hashes:

- `src/local_ai_hub/mcp_server.py`: `C9100717BA0FC8899A033BFBE2EB9935C2892B87E79D1E91B36C5CC86CEC66D9`
- `src/local_ai_hub/operation_contracts.py`: `F84FD40A594A34B0E73C53CF28D98614200E142334FDE632ECDBAC5BA0A0DFFF`
- `tests/test_mcp_contract_dispatch.py`: `B25DF3581068A5CC948AFBD07715C5BD21C3CDE69361D1896B3D807C5636773E`
- `tests/test_operation_contracts.py`: `8B4270F4761AEDBEB98A751F5D048C1EE8B27608D896F2DEC6139E8A455CF242`

`tests/test_operation_contracts.py` was not included in the initial preimage hash capture; do not transfer it as a whole-file overlay. Preserve its existing changes and reconcile the two output-contract test hunks.

## Integration binding

- Candidate worktree `HEAD`: `ad622f8a90a81e349e94d3402f297f2995e733b2`.
- The initial observed preimage hashes above bind three inherited dirty files. Initial preimage hash for `tests/test_operation_contracts.py` was not captured.
- Exact SHA-256 of each file at candidate `HEAD` (Git blob OID follows):
  - `src/local_ai_hub/mcp_server.py`: `229b62a68305f3236be4c4782fe17be1efe36f557e48b0fdfe1875a31f838848`; blob `6b4317b3457bfcf5995da1758a3ae229d4a00ba8`.
  - `src/local_ai_hub/operation_contracts.py`: `d2120b614852de7ab7006f65b8ae30d5b6eee474ebcad69cb2605d37ec119329`; blob `2ef2b0a3e574e3f88d040cb332059e4deccfa933`.
  - `tests/test_mcp_contract_dispatch.py`: `1bba650f154e835f961a7fa72494c0db3c6a806d72f7dd8465f3e86d41606b81`; blob `6367c3d59f95f5f846a893dd86d816b216f530b1`.
  - `tests/test_operation_contracts.py`: `6c388ced440d8eda35dee2c39762a1289412892c447ebf91ba08d3c0e8bc2bf5`; blob `ace40835d33cb3c556633817b6c7a490fc9945f4`.
- SHA-256 of `git diff --binary HEAD --` over those four paths: `3475c1e4353c75a769c188aa4be2b5f75d71d7826c31bd92e499b69bbdbba7ca` (100,221 bytes). This HEAD-relative patch includes inherited dirty hunks; it is not a T03-only patch digest.
- T03 output-schema edits are scoped to those four source/test paths. Full worktree is not limited to four files: it already contains many unrelated modified and untracked T03 artifacts. Do not transfer or overlay whole-worktree status.
- All edits in this handoff were issued under the candidate worktree path above. No root-checkout writes were issued. Root cleanliness before this work was not independently fingerprinted.
- Exact T03-only patch digest cannot be reconstructed from available evidence: three starting files have only recorded hashes, and the fourth starting hash is missing. Reconcile targeted hunks; preserve the rest.

## T04 in-process MCP wiring

- T04 contract SHA-256: `2AC552ED0ED8AACD0638F27C4E68E532E23F08A2AB992B4388DA2FF8D65A9733`.
- T04 reported separate candidate files: `client.py` SHA-256 `338A2C40C982E2A079B99F2A9C7044630F70788082B6219AA6174F1EAAB82098`; `inprocess_transport.py` `A5567CF4F86D848CA9034ECE886E497E3DB4AAFEFCA7EC81ABD772F64AEB5C75`. T04 reported its focused client/transport suite passed 37 tests; T03 did not edit those files or rerun that suite.
- T03 wiring now constructs MCP's `HubClient` with `LOCAL_AI_CONFIG`, `TENANT`, and lazy `InProcessTransport` when T04's module is present. Without that module, existing HTTP/autostart client path stays available. Adapter preserves `HubClient.post()` payload/replay handling, sends policy metadata through its request path, and sends it directly through GET/status paths. Client close is registered at process exit.
- `_classify_mcp_operation` marks repo `map`/`code_index`, artifact actions, and status `brief`/`cache`/`telemetry` as lightweight; repo `search` and status `agent_state` remain heavy. `_instrumented_tool` carries action metadata in a context variable and applies its mode gate before dispatch; lightweight status remains available.
- T03-focused exact command:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_contract_dispatch.py::test_mcp_transport_selection_injects_lazy_transport_with_same_config_and_tenant tests/test_mcp_contract_dispatch.py::test_mcp_transport_metadata_keeps_deterministic_reads_light tests/test_mcp_contract_dispatch.py::test_mcp_client_adapter_forwards_semantic_metadata_to_hub_client_request tests/test_mcp_contract_dispatch.py::test_instrumented_mcp_action_reaches_inprocess_client_with_classified_metadata tests/test_mcp_contract_dispatch.py::test_instrumented_tools_classify_heavy_command_and_lightweight_repo_reads
```

- Result: **5 passed in 2.58s**. First four selectors are new MCP transport/metadata dispatch regressions; fifth is existing classification coverage. No other tests run in this slot. `git diff --check` reported no whitespace errors; only LF-to-CRLF advisories.
- Candidate `HEAD` remained `ad622f8a90a81e349e94d3402f297f2995e733b2`. Current SHA-256: `mcp_server.py` `1747691a097507e914d50999eda45668c28ef50a33bd7d96463ed51fa63c83f7`; `test_mcp_contract_dispatch.py` `0814c65e060e05be41ec42ab9e5448a65fdc7819c80c1a1235f2b19a45ebadd4`. SHA-256 of `git diff --binary HEAD --` for those two paths is `d389aac4d00eddcb33675e43fe979deae5e29d8fa45390fe856e94af01efa019`; it includes inherited hunks and is not a T03-only patch hash.
- No root-checkout writes were issued. The full candidate worktree still contains unrelated inherited dirty files/artifacts; T03's additions here touch only `mcp_server.py`, `test_mcp_contract_dispatch.py`, and this receipt.
- Serial test slot released after this run; T20 queued T02 next. No end-to-end MCP call against the combined T03+T04 candidate was run here; root integration must verify the merged import and daemon-off dispatch.

## Remaining acceptance

- This receipt proves the focused candidate selectors only. Full T03/root integration acceptance remains with T20; do not mark the overall T03 task complete from this candidate receipt alone.
