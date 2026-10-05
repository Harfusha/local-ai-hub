# T03 MCP schema and registered dispatch review

Date: 2026-10-01
Root: `C:\Users\Adam\.local-ai-hub`
Observed root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
Candidate: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`

## Status

Static review plus prepared patches. Root files and tests were not changed or run; T20 controls the exclusive root write/test slot. Candidate T03 has a different operation-contract and dispatch implementation, so it cannot serve as root-current source base. Source patch SHA-256 `D58F241B97CA8A10508AF0C673A882C2CAC967522EF916724280513E79F24BA0`; dispatch-test patch SHA-256 `4FA68DE24EF34982FC2EC0E8C0EDCE12ABD33E4B851F11E0966C19B42CCE3347`. Both `git apply --check --whitespace=error` checks passed against current root working tree at HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. No tests run. Local AI Hub tools were absent from this session's tool catalog; discovery used one bounded native fallback. Token-economizer setup script was unavailable at the instructed path.

## Root findings

1. Root `src/local_ai_hub/operation_contracts.py` has one registry, but several supported handler inputs are missing from public properties: RAG `content`/`image_path`; command `execution_id`/`paths`/`patch`; coord `criterion`/`board_id`; task `task_id`/`language`/`cases`.
2. `validate_operation_arguments()` rejects unknown keys against raw `contract["properties"]`. It must validate against feature-filtered `operation_parameters_schema(tool, features)["properties"]`; otherwise advertised `local_ai_repo` `batch_replace` fields `edits`/`dry_run` fail dispatch when batch replacement is enabled.
3. `validate_operation_call()` returns early when selector is omitted. Run common schema/unknown-field checks before returning, and use declared selector default for action-scoped checks when one exists.
4. `validate_operation_output()` returns success for non-dict values. Make non-object output a contract error. `_compact_mcp_call_tool()` must return its existing invalid-output envelope without reaching scalar fallback, which currently invokes the handler a second time.

## Minimal root patch scope

- Add missing supported properties/types to the existing operation registry; action-scope fields where needed.
- Derive validator properties from the same feature-filtered schema used for MCP registration.
- Validate common fields with omitted selectors; preserve declared handler defaults and existing status aliases.
- Reject non-object output at the output-contract boundary. Keep dispatch single-shot for every handler result.
- Leave `client.py` and all unrelated HTTP/Agent OS state untouched.

## Registered MCP regression coverage

Tests must enter through the registered FastMCP dispatch path, not call `validate_operation_call()`, `_compact_mcp_call_tool()`, or the underlying tool handler directly. Cover:

- valid RAG `content` / `image_path` dispatch;
- valid command cancellation input (`execution_id` and its supported action fields);
- feature-enabled `local_ai_repo(action="batch_replace", edits=..., dry_run=...)` dispatch;
- omitted selector with an unknown field rejected before handler call;
- handler returning a non-object produces a terminal invalid-output envelope and handler call count stays exactly one.

Prepared test selectors in `T03-mcp-root-current-tests.patch`:

- `test_registered_mcp_dispatch_accepts_handler_inputs` (six parameter cases)
- `test_registered_mcp_dispatch_accepts_feature_enabled_batch_replace`
- `test_registered_mcp_dispatch_validates_unknown_field_when_selector_omitted`
- `test_registered_mcp_dispatch_rejects_non_object_output_without_replaying_handler`

Root test receipt at HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`: initial assigned attempt stopped at collection (`pytest` import missing); one-line import patch SHA-256 `295082503D2A17D54B4BB5639148B950F86AD8C9F58D7D107B8D4482023D6735` passed apply-check and was applied. Corrected one-time selector run: **8 passed, 1 failed** in 2.45s; sole failure was feature-enabled `batch_replace` at the success assertion. Saved output only says `assert False is True`; response payload/error was not captured. Static diagnosis: validator/conditional property filter are feature-aware; test toggles `FEATURES` and `Tool.parameters` after module import, but when rollout is disabled during import `_hide_disabled_batch_schema()` also rewrites `local_ai_repo.__signature__` and registered FastMCP metadata. Test should create a fresh enabled registration before dispatch (or import in a subprocess with batch replacement enabled). No source patch indicated. No reruns.

Prepared test-only correction [T03-mcp-batch-test-setup.patch](T03-mcp-batch-test-setup.patch), SHA-256 `C6E8DC8D269D7B5C3E62ECA87BF2F88D2F05B22C2E54FEC586F00D9AD4A9B80F`. It constructs `FeatureSet(batch_replacement=True)` before creating a fresh FastMCP server/tool, then invokes the existing compact MCP dispatch wrapper. Root test-file blob before patch: `8e39cc392f0ba9e6048a5bcc740ea8400e2fbd1c`. `git apply --check --whitespace=error` passed at root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Test not run; awaiting T20 review/slot.

## Path hints release

T03 candidate exposes optional `local_ai_repo(action="search").path_hints`, bounded to 64 entries and excluded from other actions/pipeline steps. T21 was notified with candidate source hashes and the prior focused test receipt. Root integration remains separate.
