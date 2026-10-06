# T01 manual master synchronization — 2026-10-06

Scope: existing T01 checkout only. No push, root-checkout edits, master-ref mutation, stash, reset, clean, or original-file deletion. Hub skipped under inherited terminal-unavailable/native-fallback authorization. Caveman/token-economizer loaded; ensure-tools PlanOnly script absent in both installed locations.

Initial master pin: `614a6a50ac2a3e4106270136cb8e584e770c3752` (commit verified).
Original HEAD: `689165fbe18101feacf5f489847a4890fc27ed1f` (detached).
Branch: `codex/sync-t01-master-20261006`.
Merged target: initial pin only. Latest master observed read-only at `9b794d7fa24abb179a17d87e14becdfa7fc8cd50`; not merged. Latest user instruction revoked moving-head follow-up unless already begun; no latest merge had begun. No repeated master chasing.

## Preservation

- Pre-merge checkpoint: `refs/checkpoints/sync-t01-master-20261006` = `f69381da76d0eba5fc5b56701979985c7db2eeee`.
- Complete original checkpoint: `refs/checkpoints/sync-t01-complete-original-20261006` = `0d2a1fa28bae21c961fa2b8dde7e721f784638e3`.
- Exact original status, six tracked-file hashes, 133 untracked-file hashes and six master collisions: [original-state manifest](T01-sync-master-20261006-original-state.json).
- First checkpoint contains all tracked dirty files and six colliding new test modules, preserving CRLF bytes using core.autocrlf=false. Complete checkpoint also archives all 127 original handoff files after parent clarified their relevance, before content reconciliation. Archival files remained untouched.
- SHA256 verification: 139/139 original tracked-dirty/untracked files match complete checkpoint blobs; 127/127 noncolliding original handoff files match original working-file hashes.
- All 127 original handoff files committed, including unfinished/historical patches and receipts. Archival evidence does not prove current acceptance; no historical patch blindly applied.
- Artificial CRLF conflicts resolved by restarting merge from clean checkpoint using -Xrenormalize, without side preference. Merged source/tests normalized to LF; original exact bytes remain checkpointed.
- Isolated verification state: `.sync-t01-runtime/`, ignored and uncommitted, including test fixtures and databases/caches. Committed test config: `handoff/T01-sync-test-config.toml`. Original ignored data not cleaned.

## Per-path semantic decisions

| Path | Retained intent / superseded content |
|---|---|
| src/local_ai_hub/mcp_server.py | T01 Use/Skip cues combined with current master descriptions, complete RAG actions and registry-derived artifact actions. Obsolete CodeGraphContext wording removed. Master task_list query forwarding retained exactly once. New context implementation preserved. |
| tools/surface_inventory.py | T01 disabled-tool schema fallback, checkout-local config selection, route availability classification and precise client target matching retained. Master action-alias detection and exact-document checks preserved. Duplicate owner helpers/constants removed. T14 supersedes stale T01 context owner and Agent-2 pending gate. |
| tests/test_surface_inventory.py | T01 owner/schema/hash/mtime/read-only CLI/operation-link assertions plus master filesystem-write guards retained. Identical duplicates deduplicated; distinct legacy GET candidate-link test retained under separate name. Stale context tests adapted to POST/T14 and existing contract fields. |
| docs/API_COVERAGE.md | Conflicting generated snapshots superseded by merged generator output (652 rows, zero drift). Original snapshots preserved in checkpoints/archives. Generation does not prove behavioral acceptance. |
| tests/test_client_operation_acceptance.py | Collision reconciled automatically under renormalization; semantic content equals initial master. Original bytes checkpointed. |
| tests/test_http_route_operation_acceptance.py | Master event_page pagination and task-list query signatures supersede stale events/list signatures. Original cleanup/swarm tests retained; relocated copies deduplicated. Response-envelope assertions remain unfinished. |
| tests/test_hubctl_unlinked_operations.py | Collision reconciled automatically; semantic content equals initial master. |
| tests/test_mcp_command_operation_acceptance.py | Master accounting side-call assertion supersedes single-call expectation; daemon test deduplicated. Speculative-lint acceptance remains unfinished. |
| tests/test_mcp_coord_operation_acceptance.py | All roughly 1000 unique T01 dispatch/action/HTTP/task test lines beyond master retained. Existing disabled-feature and accounting-side-call failures recorded below. |
| tests/test_rag_work_operation_acceptance.py | Original tests plus master accounting-reporter mock isolation retained. |
| tests/test_reliability_integration.py | Registered-MCP-description test retained instead of source-substring check. Disabled local_ai_task registration leaves acceptance incomplete. |
| tests/test_vision_artifacts.py | Keyword artifact invocation preserved; already incorporated in master. |
| .gitignore | Ignore only new isolated T01 verification state; prevent accidental runtime-data commit. |
| handoff/* | All 127 original evidence files preserved and committed unchanged. Archival scripts/patches neither executed nor applied. |

## Verification / incomplete acceptance

Commands use checkout PYTHONPATH=src, PYTHONDONTWRITEBYTECODE=1, LOCAL_AI_CONFIG=handoff/T01-sync-test-config.toml, TEMP/TMP=.sync-t01-runtime/temp. No full release suite.

`python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=.sync-t01-runtime/pytest` selected:
`tests/test_surface_inventory.py tests/test_client_operation_acceptance.py tests/test_http_route_operation_acceptance.py tests/test_hubctl_unlinked_operations.py tests/test_mcp_command_operation_acceptance.py tests/test_mcp_coord_operation_acceptance.py tests/test_rag_work_operation_acceptance.py tests/test_reliability_integration.py::test_mcp_tools_have_use_when_and_skip_when_cues tests/test_vision_artifacts.py::test_mcp_binary_artifact_response_is_metadata_only`.
Result: **821 passed, 11 failed, 89.82 seconds**. Two obsolete context-route tests subsequently corrected. First two-test follow-up exposed missing route.note field; assertions then aligned to current owner/contract fields. Final follow-up: **2 passed in 7.00 seconds**, using the same pytest flags, basetemp=.sync-t01-runtime/pytest-context-final, and selectors test_context_pack_dynamic_route_is_owned_by_t14 / test_context_pack_dynamic_route_retains_t14_owner.

Nine other failed selectors from initial run, retained and not rerun:
- HTTP: `test_http_post_agent_state_cleanup_forwards_retention_policy`, `test_http_post_agent_state_swarm_dispatch_forwards_explicit_scope`: extra response request_id.
- Command: `test_mcp_command_speculative_lint_submits_bounded_paths_and_job_identity`: no backend dispatch under current gate.
- Coord: `test_local_ai_coord_feature_disabled_rejects_valid_action_before_backend_dispatch`: unsupported field absent.
- Coord: `test_local_ai_coord_task_sync_forwards_export_and_import_payloads`, `test_local_ai_coord_blackboard_update_posts_content_and_version`, `test_local_ai_coord_context_compile_posts_scope_and_budget`, `test_local_ai_coord_verify_receipt_forwards_criterion_and_pass_state`: extra accounting call.
- Reliability: `test_mcp_tools_have_use_when_and_skip_when_cues`: local_ai_task absent from registered tools under run configuration.

`python -B tools/surface_inventory.py --root . --write-doc --task-id T01`: 652 rows, zero drift. `python -B tools/surface_inventory.py --root . --check`: coverage_matches=true, 652 rows, zero drift, exit 0.
AST parse/duplicate-function checks passed for merged MCP server, inventory generator and inventory tests. Original SHA256 verification passed (139/139).
Commit proves reconciliation and ancestry only. Runtime/release/model/backend acceptance incomplete. Failing tests and historical unfinished evidence intentionally committed per user instruction.

All 133 original untracked files are included on the final branch (127 unchanged handoff archives plus six reconciled test modules). No original untracked paths excluded. New verification files under `.sync-t01-runtime/` are preserved outside Git; exact excluded file list is recorded in `T01-sync-master-20261006-runtime-paths.json`. Final status/ancestry/hash/diff receipts: `T01-sync-master-20261006-final-receipt.json`.

Committed merge: `9780dadd79b9d6bcf06eabe7b865d98c97e85306`; parents are pre-merge checkpoint and initial pinned master. Before receipt generation, exact tracked dirty/untracked status was empty; zero unresolved entries. Receipts and this final note update are committed in a direct child. Excluded new runtime/test-temp files: 671, enumerated with SHA256 in runtime manifest. Eight code/doc paths differ from pin: 2434 insertions, 1030 deletions (separate from archival evidence additions). No full-suite or final rerun of the nine other failed selectors; acceptance remains incomplete.
