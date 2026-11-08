# MCP action input-contract index

Generated 2026-11-08 from the then-current action inventory and declared contracts in src/local_ai_hub/operation_contracts.py. This is a source-contract snapshot, not a live MCP inventory; use mcp-action-coverage.md for this session's exposed actions.

This is source/schema evidence, not runtime acceptance. The live MCP schema controls exposure. Actions present only in this snapshot are unavailable unless the live schema exposes them; runtime permissions, root authorization, consent and cleanup must still be verified by the matching prompt.

## Tool-level gates

| Tool | Selector | Feature gate / requirements | Timeout / effect defaults |
|---|---|---|---|
| local_ai_status | detail | status | quick: 180 seconds by default; configured MCP timeout applies / read_only |
| local_ai_artifact | action | artifacts | HubClient.post default 360 seconds; capped by configured max_request_timeout_seconds / read_only |
| local_ai_repo | action | repo | action-specific: search max 120s, other quick 180s, context 600s, model 1800s, long 2400s / read_only |
| local_ai_task | action | tasks, has_any_model | model 1800 seconds or long 2400 seconds; HubClient cap applies / read_only |
| local_ai_rag | action | rag | action-specific MCP timeout; HubClient cap applies / read_only |
| local_ai_coord | action | coord | action-specific coordination budget; HubClient cap applies / read_only |
| local_ai_work | action | work_orchestrator | work-order timeout is bounded by its request budget / read_only |

## Tool-level input properties

The table lists every declared property and its schema-level type/default/constraints. Action rows below apply each action allowlist, required/non-empty set, feature requirement, effect and action-scoped fields on top of this shared tool schema.

| Tool | Field | Schema | Action-scoped to |
|---|---|---|---|
| local_ai_status | max_response_tokens | ['integer', 'null']; minimum=128; default=null | shared/handler-defined |
| local_ai_status | response_profile | string; enum=["minimal","compact","standard","debug","delta","dense"]; default="compact" | shared/handler-defined |
| local_ai_status | reuse_key | string; default="" | shared/handler-defined |
| local_ai_status | detail | string; default="brief" | shared/handler-defined |
| local_ai_status | extra_fields | array; items(string) | shared/handler-defined |
| local_ai_artifact | max_response_tokens | ['integer', 'null']; minimum=128; default=null | shared/handler-defined |
| local_ai_artifact | response_profile | string; enum=["minimal","compact","standard","debug","delta","dense"]; default="compact" | shared/handler-defined |
| local_ai_artifact | reuse_key | string; default="" | shared/handler-defined |
| local_ai_artifact | action | string; default="get" | shared/handler-defined |
| local_ai_artifact | artifact_id | string; default="" | shared/handler-defined |
| local_ai_artifact | file | string; maxLength=32768; default="" | shared/handler-defined |
| local_ai_artifact | root | string; default="." | shared/handler-defined |
| local_ai_artifact | workspace | string; default="" | shared/handler-defined |
| local_ai_artifact | path | string; maxLength=32768; default="" | shared/handler-defined |
| local_ai_artifact | expected_file_sha256 | string; maxLength=64; default="" | shared/handler-defined |
| local_ai_artifact | line_start | integer; minimum=1; maximum=2147483647; default=1 | shared/handler-defined |
| local_ai_artifact | line_end | integer; minimum=0; maximum=2147483647; default=0 | shared/handler-defined |
| local_ai_artifact | start_line | integer; minimum=1; maximum=2147483647; default=1 | shared/handler-defined |
| local_ai_artifact | end_line | integer; minimum=0; maximum=2147483647; default=0 | shared/handler-defined |
| local_ai_artifact | section | string; maxLength=512; default="" | shared/handler-defined |
| local_ai_artifact | offset | integer; minimum=0; default=0 | shared/handler-defined |
| local_ai_artifact | max_chars | integer; minimum=1; maximum=50000; default=4000 | shared/handler-defined |
| local_ai_artifact | extra_fields | array; items(string) | shared/handler-defined |
| local_ai_artifact | binary | boolean; default=false | shared/handler-defined |
| local_ai_artifact | slices | array; minItems=1; maxItems=16; items(object;required=offset,max_chars;fields=offset,max_chars;additionalProperties=false) | shared/handler-defined |
| local_ai_repo | max_response_tokens | ['integer', 'null']; minimum=128; default=null | shared/handler-defined |
| local_ai_repo | response_profile | string; enum=["minimal","compact","standard","debug","delta","dense"]; default="compact" | shared/handler-defined |
| local_ai_repo | reuse_key | string; default="" | shared/handler-defined |
| local_ai_repo | action | string | shared/handler-defined |
| local_ai_repo | id | string; default="" | shared/handler-defined |
| local_ai_repo | goal | string; default="" | shared/handler-defined |
| local_ai_repo | prompt | string; default="" | shared/handler-defined |
| local_ai_repo | workspace | string; default="" | shared/handler-defined |
| local_ai_repo | root | string; default="." | shared/handler-defined |
| local_ai_repo | query | string; default="" | shared/handler-defined |
| local_ai_repo | max_commits | integer; minimum=1; maximum=100; default=50 | git_log, git_history_search |
| local_ai_repo | author | string; maxLength=256; pattern="^[^\\x00-\\x1F\\x7F]*$"; default="" | git_log, git_history_search |
| local_ai_repo | since | string; maxLength=64; pattern="^(?:\\d{4}-\\d{2}-\\d{2}\|\\d{4}-\\d{2}-\\d{2}[Tt]\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:[Zz]\|[+-]\\d{2}:\\d{2}))?$"; default="" | git_log, git_history_search |
| local_ai_repo | until | string; maxLength=64; pattern="^(?:\\d{4}-\\d{2}-\\d{2}\|\\d{4}-\\d{2}-\\d{2}[Tt]\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:[Zz]\|[+-]\\d{2}:\\d{2}))?$"; default="" | git_log, git_history_search |
| local_ai_repo | old_symbol | string; maxLength=512 | ast_refactor |
| local_ai_repo | new_symbol | string; maxLength=512 | ast_refactor |
| local_ai_repo | base | string; maxLength=512; default="HEAD" | solve, diff, git_diff, context |
| local_ai_repo | head | string; maxLength=512; default="" | diff, git_diff |
| local_ai_repo | start_line | integer; minimum=1; default=1 | read_file, source |
| local_ai_repo | end_line | integer; minimum=0; default=0 | read_file, source |
| local_ai_repo | line_start | integer; minimum=1; default=1 | read_file, source |
| local_ai_repo | line_end | integer; minimum=0; default=0 | read_file, source |
| local_ai_repo | max_chars | integer; minimum=1; maximum=50000; default=4000 | read_file, source |
| local_ai_repo | old_code | ['string', 'null']; maxLength=1048576; default=null | semantic_diff, patch |
| local_ai_repo | new_code | ['string', 'null']; maxLength=1048576; default=null | semantic_diff, patch |
| local_ai_repo | rev1 | ['string', 'null']; maxLength=512; default=null | diff, git_diff |
| local_ai_repo | rev2 | ['string', 'null']; maxLength=512; default=null | diff, git_diff |
| local_ai_repo | path | string; maxLength=4096; default="" | shared/handler-defined |
| local_ai_repo | file | string; maxLength=4096; default="" | git_diff, stat, read_file, type_stubs, source, file_info, generate_tests, generate_tests_for_diff, mutation_test, diff |
| local_ai_repo | task | string; default="" | shared/handler-defined |
| local_ai_repo | task_id | string; default="" | shared/handler-defined |
| local_ai_repo | include_code | boolean; default=false | shared/handler-defined |
| local_ai_repo | search_mode | string; enum=["lexical","rag","hybrid"] | search |
| local_ai_repo | limit | integer; minimum=1; maximum=200; default=24 | git_log, find_files, hotspots, code_index, implementations, callers, glob, callees, call_graph, search |
| local_ai_repo | days | integer; minimum=1; maximum=3650; default=30 | hotspots |
| local_ai_repo | depth | integer; minimum=1; maximum=5; default=1 | call_graph |
| local_ai_repo | offset | integer; minimum=0; maximum=2047; default=0 | callees, find_files, search, code_index, implementations, callers, glob |
| local_ai_repo | include_diagnostics | boolean; default=false | context |
| local_ai_repo | clone_id | string; default="" | context |
| local_ai_repo | worktree_id | string; default="" | context |
| local_ai_repo | branch | string; default="" | context |
| local_ai_repo | repository_id | string; default="" | context |
| local_ai_repo | session_id | string; default="" | context |
| local_ai_repo | repository_revision | string; default="" | context |
| local_ai_repo | steps | array; items(object) | pipeline |
| local_ai_repo | is_worktree | boolean; default=false | preprocess |
| local_ai_repo | parent_root | string; default="" | preprocess |
| local_ai_repo | path_hints | array; maxItems=64; items(object;required=path,purpose,scope;fields=path,purpose,scope,evidence_id,provenance,repository_revision,config_digest,expires_at;additionalProperties=false) | search, context |
| local_ai_repo | directory_hints | array; maxItems=64; items(string;minLength=1) | context |
| local_ai_repo | exclude_paths | array; maxItems=64; items(string;minLength=1) | context |
| local_ai_repo | force_include_paths | array; maxItems=64; items(string;minLength=1) | context |
| local_ai_repo | include_tests | boolean; default=false | shared/handler-defined |
| local_ai_repo | phase | string; default="" | shared/handler-defined |
| local_ai_repo | focus | array; items(string) | shared/handler-defined |
| local_ai_repo | preload_profile | string; default="" | shared/handler-defined |
| local_ai_repo | guarded | boolean; default=false | shared/handler-defined |
| local_ai_repo | changed_paths | array; items(string) | generate_tests_for_diff, context |
| local_ai_repo | since_hash | string; default="" | shared/handler-defined |
| local_ai_repo | approval | ['boolean', 'string']; default="" | shared/handler-defined |
| local_ai_repo | override_reason | string; default="" | shared/handler-defined |
| local_ai_repo | staged | boolean; default=false | shared/handler-defined |
| local_ai_repo | mode | string; default="adaptive" | shared/handler-defined |
| local_ai_repo | language | string; default="auto" | circular_dependencies, resolve_imports |
| local_ai_repo | relation | string; default="" | shared/handler-defined |
| local_ai_repo | profile | string; default="" | shared/handler-defined |
| local_ai_repo | max_tokens | integer; default=0 | shared/handler-defined |
| local_ai_repo | token_budget | integer; default=0 | shared/handler-defined |
| local_ai_repo | diff | string; default="" | shared/handler-defined |
| local_ai_repo | name | string; default="" | shared/handler-defined |
| local_ai_repo | text | string; default="" | shared/handler-defined |
| local_ai_repo | evidence | array; items(object) | shared/handler-defined |
| local_ai_repo | pattern | string; default="*" | structural_search, find_files, glob |
| local_ai_repo | target | string; default="" | patch |
| local_ai_repo | replacement | string; default="" | patch |
| local_ai_repo | extra_fields | array; items(string) | shared/handler-defined |
| local_ai_task | max_response_tokens | ['integer', 'null']; minimum=128; default=null | shared/handler-defined |
| local_ai_task | response_profile | string; enum=["minimal","compact","standard","debug","delta","dense"]; default="compact" | shared/handler-defined |
| local_ai_task | reuse_key | string; default="" | shared/handler-defined |
| local_ai_task | automation | object; additionalProperties=false | automation |
| local_ai_task | action | string | shared/handler-defined |
| local_ai_task | url | string; maxLength=4096 | browser |
| local_ai_task | delivery | string; enum=["sync","async","auto"]; default="sync" | shared/handler-defined |
| local_ai_task | phase | string; default="" | second_opinion, delegate, reason, explore, review, compress |
| local_ai_task | focus | array; items(string) | second_opinion, delegate, reason, explore, review, compress |
| local_ai_task | preload_profile | string; default="" | second_opinion, delegate, reason, explore, review, compress |
| local_ai_task | repository_revision | string; default="" | second_opinion, delegate, reason, explore, review, compress |
| local_ai_task | changed_paths | array; items(string) | second_opinion, delegate, reason, explore, review, compress |
| local_ai_task | task | string; default="" | shared/handler-defined |
| local_ai_task | context | string; default="" | shared/handler-defined |
| local_ai_task | root | string; default="" | shared/handler-defined |
| local_ai_task | profile | string; default="" | shared/handler-defined |
| local_ai_task | conversation_id | string; default="" | shared/handler-defined |
| local_ai_task | prompt | string; default="" | shared/handler-defined |
| local_ai_task | model | string; default="" | shared/handler-defined |
| local_ai_task | candidate | string; default="" | shared/handler-defined |
| local_ai_task | code | string; default="" | review, code_review |
| local_ai_task | diff | string; default="" | review, code_review |
| local_ai_task | problem | string; default="" | reason |
| local_ai_task | query | string; default="" | delegate, explore, reason |
| local_ai_task | question | string; default="" | second_opinion |
| local_ai_task | text | string; default="" | compress |
| local_ai_task | image_artifact_id | string; default="" | shared/handler-defined |
| local_ai_task | screenshot_artifact_id | string; default="" | shared/handler-defined |
| local_ai_task | baseline_screenshot_artifact_id | string; default="" | shared/handler-defined |
| local_ai_task | bundle_artifact_id | string; default="" | shared/handler-defined |
| local_ai_task | dom_artifact_id | string; default="" | shared/handler-defined |
| local_ai_task | accessibility_artifact_id | string; default="" | shared/handler-defined |
| local_ai_task | computed_styles_artifact_id | string; default="" | shared/handler-defined |
| local_ai_task | runtime_artifact_id | string; default="" | shared/handler-defined |
| local_ai_task | network_artifact_id | string; default="" | shared/handler-defined |
| local_ai_task | source | string; default="" | shared/handler-defined |
| local_ai_task | job_id | string; default="" | shared/handler-defined |
| local_ai_task | evaluation_task_id | string; default="" | shared/handler-defined |
| local_ai_task | evaluation_cohort | string; default="" | shared/handler-defined |
| local_ai_task | workspace | string; default="" | shared/handler-defined |
| local_ai_task | approver | string; default="" | shared/handler-defined |
| local_ai_task | task_id | string; default="" | shared/handler-defined |
| local_ai_task | language | string; default="" | shared/handler-defined |
| local_ai_task | request_id | string; default="" | submit |
| local_ai_task | complexity | string; default="auto" | shared/handler-defined |
| local_ai_task | job_action | string; default="reason" | shared/handler-defined |
| local_ai_task | max_tokens | integer; default=0 | shared/handler-defined |
| local_ai_task | evaluation_days | integer; default=30 | shared/handler-defined |
| local_ai_task | latency_budget_ms | number; default=0 | shared/handler-defined |
| local_ai_task | timeout_seconds | number; default=90 | shared/handler-defined |
| local_ai_task | evaluation_duration_ms | number; default=0 | shared/handler-defined |
| local_ai_task | conversation | boolean; default=false | shared/handler-defined |
| local_ai_task | cloud_fallback | boolean; default=false | shared/handler-defined |
| local_ai_task | quality_pass | ['boolean', 'null'] | shared/handler-defined |
| local_ai_task | test_pass | ['boolean', 'null'] | shared/handler-defined |
| local_ai_task | dom | ['string', 'object'] | shared/handler-defined |
| local_ai_task | accessibility | ['string', 'object'] | shared/handler-defined |
| local_ai_task | computed_styles | ['string', 'object'] | shared/handler-defined |
| local_ai_task | runtime | ['string', 'object'] | shared/handler-defined |
| local_ai_task | bundle | ['string', 'object'] | shared/handler-defined |
| local_ai_task | accessibility_snapshot | ['string', 'object'] | shared/handler-defined |
| local_ai_task | computed_style_data | ['string', 'object'] | shared/handler-defined |
| local_ai_task | runtime_context | ['string', 'object'] | shared/handler-defined |
| local_ai_task | html | string | shared/handler-defined |
| local_ai_task | viewport | object | shared/handler-defined |
| local_ai_task | page | object | shared/handler-defined |
| local_ai_task | candidate_data | object | shared/handler-defined |
| local_ai_task | json_schema | object | shared/handler-defined |
| local_ai_task | tasks | array; items(object) | shared/handler-defined |
| local_ai_task | items | array; items(object) | batch |
| local_ai_task | cases | array; minItems=1; maxItems=32; items(object;fields=id,input,expected,max_words,include_response_text,allowed_citations,required_citations,forbidden_phrases;additionalProperties=false) | shared/handler-defined |
| local_ai_task | format | ['string', 'object'] | shared/handler-defined |
| local_ai_task | extra_fields | array; items(string) | shared/handler-defined |
| local_ai_rag | max_response_tokens | ['integer', 'null']; minimum=128; default=null | shared/handler-defined |
| local_ai_rag | response_profile | string; enum=["minimal","compact","standard","debug","delta","dense"]; default="compact" | shared/handler-defined |
| local_ai_rag | reuse_key | string; default="" | shared/handler-defined |
| local_ai_rag | action | string | shared/handler-defined |
| local_ai_rag | query | string; default="" | shared/handler-defined |
| local_ai_rag | root | string | shared/handler-defined |
| local_ai_rag | top_k | integer; default=6 | shared/handler-defined |
| local_ai_rag | limit | integer; default=6 | shared/handler-defined |
| local_ai_rag | task | string; default="" | shared/handler-defined |
| local_ai_rag | workspace | string; default="" | shared/handler-defined |
| local_ai_rag | content | string; default="" | shared/handler-defined |
| local_ai_rag | title | string; default="" | shared/handler-defined |
| local_ai_rag | metadata | object | shared/handler-defined |
| local_ai_rag | image_path | string; default="" | shared/handler-defined |
| local_ai_rag | caption | string; default="" | shared/handler-defined |
| local_ai_rag | path | string; default="" | shared/handler-defined |
| local_ai_rag | file | string; default="" | shared/handler-defined |
| local_ai_rag | extra_fields | array; items(string) | shared/handler-defined |
| local_ai_coord | max_response_tokens | ['integer', 'null']; minimum=128; default=null | shared/handler-defined |
| local_ai_coord | response_profile | string; enum=["minimal","compact","standard","debug","delta","dense"]; default="compact" | shared/handler-defined |
| local_ai_coord | reuse_key | string; default="" | shared/handler-defined |
| local_ai_coord | action | string | shared/handler-defined |
| local_ai_coord | root | string; default="." | shared/handler-defined |
| local_ai_coord | paths | array; items(string) | shared/handler-defined |
| local_ai_coord | path | string; default="" | release, task_update, task_checkpoint, task_create, claim, renew |
| local_ai_coord | file | string; default="" | release, task_update, task_checkpoint, task_create, claim, renew |
| local_ai_coord | next_action | string; default="" | task_checkpoint, task_update |
| local_ai_coord | blockers | array; items(string) | task_checkpoint, task_update |
| local_ai_coord | evidence_ids | array; items(string) | task_checkpoint, task_update |
| local_ai_coord | summary | string; default="" | task_fail, record_native_receipt, plan_reconcile_steering, task_complete |
| local_ai_coord | result | string; default="" | task_fail, record_native_receipt, task_complete |
| local_ai_coord | timeout_seconds | number; minimum=0.0; default=0.0 | wait_for_event, semaphore_acquire |
| local_ai_coord | id | string; default="" | task_resume, task_cleanup_worktree, board_item_update, task_get, board_item_get, task_zombie_reap, board_item_delete |
| local_ai_coord | lease_id | string; default="" | shared/handler-defined |
| local_ai_coord | task_id | string; default="" | shared/handler-defined |
| local_ai_coord | key | string; default="" | shared/handler-defined |
| local_ai_coord | value | string; default="" | shared/handler-defined |
| local_ai_coord | query | string; default="" | shared/handler-defined |
| local_ai_coord | command | string; default="" | shared/handler-defined |
| local_ai_coord | command_id | string; default="" | record_native_receipt |
| local_ai_coord | task | string; default="" | shared/handler-defined |
| local_ai_coord | status | string; default="" | shared/handler-defined |
| local_ai_coord | reason | string; default="" | shared/handler-defined |
| local_ai_coord | record_id | string; default="" | memory_delete, memory_promote, memory_get |
| local_ai_coord | target_scope | string; default="" | memory_promote |
| local_ai_coord | approver | string; default="" | shared/handler-defined |
| local_ai_coord | criterion | string; default="" | shared/handler-defined |
| local_ai_coord | board_id | string; default="" | shared/handler-defined |
| local_ai_coord | section | string; default="" | shared/handler-defined |
| local_ai_coord | scope | string; default="" | shared/handler-defined |
| local_ai_coord | scope_id | string; default="" | shared/handler-defined |
| local_ai_coord | clone_id | string; default="" | shared/handler-defined |
| local_ai_coord | worktree_id | string; default="" | shared/handler-defined |
| local_ai_coord | branch | string; default="" | shared/handler-defined |
| local_ai_coord | repository_id | string; default="" | shared/handler-defined |
| local_ai_coord | session_id | string; maxLength=256; default="" | shared/handler-defined |
| local_ai_coord | repository_revision | string; default="" | shared/handler-defined |
| local_ai_coord | phase | string; default="" | shared/handler-defined |
| local_ai_coord | preload_profile | string; default="" | shared/handler-defined |
| local_ai_coord | since_hash | string; default="" | context_compile |
| local_ai_coord | question_id | string; maxLength=80; default="" | shared/handler-defined |
| local_ai_coord | question | string; maxLength=16384; default="" | shared/handler-defined |
| local_ai_coord | answer | string; maxLength=16384; default="" | shared/handler-defined |
| local_ai_coord | state_revision | string; default="" | shared/handler-defined |
| local_ai_coord | generation | string; default="" | shared/handler-defined |
| local_ai_coord | audit_reason | string; default="" | shared/handler-defined |
| local_ai_coord | name | string; default="" | shared/handler-defined |
| local_ai_coord | item_id | string; default="" | shared/handler-defined |
| local_ai_coord | title | string; default="" | shared/handler-defined |
| local_ai_coord | priority | string; default="" | shared/handler-defined |
| local_ai_coord | assignee | string; default="" | shared/handler-defined |
| local_ai_coord | milestone | string; default="" | shared/handler-defined |
| local_ai_coord | linked_task_id | string; default="" | shared/handler-defined |
| local_ai_coord | target_date | string; default="" | shared/handler-defined |
| local_ai_coord | description | string; default="" | shared/handler-defined |
| local_ai_coord | purpose | string; default="" | shared/handler-defined |
| local_ai_coord | owner | string; default="" | shared/handler-defined |
| local_ai_coord | resource | string; default="" | semaphore_status, semaphore_acquire, semaphore_release |
| local_ai_coord | notes | string; default="" | task_checkpoint, task_update |
| local_ai_coord | plan_id | string; default="" | shared/handler-defined |
| local_ai_coord | idempotency_key | string; default="" | shared/handler-defined |
| local_ai_coord | plan_task_id | string; default="" | shared/handler-defined |
| local_ai_coord | steering_id | string; default="" | shared/handler-defined |
| local_ai_coord | spec_rel_path | string; default="" | shared/handler-defined |
| local_ai_coord | spec_content | string; default="" | shared/handler-defined |
| local_ai_coord | expected_spec_revision | string; default="" | shared/handler-defined |
| local_ai_coord | accountable_role | string; default="" | shared/handler-defined |
| local_ai_coord | consent | boolean; default=false | shared/handler-defined |
| local_ai_coord | expected_revision | string; minLength=1 | shared/handler-defined |
| local_ai_coord | lifecycle | string; enum=["draft","active","paused","completed","cancelled","archived"] | shared/handler-defined |
| local_ai_coord | default_target_ref | ['string', 'null'] | shared/handler-defined |
| local_ai_coord | spec_refs | array; items(object) | shared/handler-defined |
| local_ai_coord | task_data | object | shared/handler-defined |
| local_ai_coord | tasks | ['object', 'null'] | shared/handler-defined |
| local_ai_coord | confidence | ['number', 'null']; minimum=0; maximum=1; default=null | shared/handler-defined |
| local_ai_coord | output_summary | string; default="" | shared/handler-defined |
| local_ai_coord | acceptance_criteria | array; items(string) | task_update, plan_reconcile_steering, task_create |
| local_ai_coord | criteria | array; items(string) | task_update, task_create |
| local_ai_coord | error | string; default="" | task_fail |
| local_ai_coord | kind | string; default="" | memory_record, memory_list, memory_find, memory_get |
| local_ai_coord | allow_adopt | boolean; default=false | shared/handler-defined |
| local_ai_coord | passed | boolean; default=true | shared/handler-defined |
| local_ai_coord | format | ['string', 'null']; default=null | curate_dataset, verify_export |
| local_ai_coord | state_data | ['object', 'null'] | task_checkpoint, task_update |
| local_ai_coord | budget | object; additionalProperties=false | task_budget_increase |
| local_ai_coord | goal | string; default="" | task_update, swarm_dispatch, task_create |
| local_ai_coord | target_paths | ['array', 'null']; items(string) | swarm_dispatch |
| local_ai_coord | test_command | string; default="" | swarm_dispatch |
| local_ai_coord | author | string; default="agent" | blackboard_update, swarm_dispatch |
| local_ai_coord | swarm_id | string; default="" | swarm_status, swarm_cancel, swarm_step |
| local_ai_coord | role | string; default="Coder" | swarm_step |
| local_ai_coord | swarm_action | string; default="submit_patch" | swarm_step |
| local_ai_coord | payload | ['object', 'null'] | swarm_step |
| local_ai_coord | state | string; default="" | swarm_list, task_list |
| local_ai_coord | source_branch | string; default="" | simulate_merge |
| local_ai_coord | target_branch | string; default="HEAD" | simulate_merge |
| local_ai_coord | worktree_path | string; default="" | worktree_release |
| local_ai_coord | delete_branch | boolean; default=true | worktree_release |
| local_ai_coord | output_path | string; default="training_dataset.jsonl" | curate_dataset |
| local_ai_coord | min_receipts | integer; default=1 | curate_dataset |
| local_ai_coord | content | any | blackboard_update |
| local_ai_coord | remote_sections | object | blackboard_merge |
| local_ai_coord | expected_version | integer; minimum=0 | blackboard_update |
| local_ai_coord | message | any | task_fail, pubsub_publish |
| local_ai_coord | publisher | string; default="agent" | pubsub_publish |
| local_ai_coord | topic | string; default="default" | pubsub_publish, wait_for_event, pubsub_poll |
| local_ai_coord | after_ts | number; minimum=0; maximum=1000000000000 | pubsub_poll |
| local_ai_coord | ttl_seconds | ['integer', 'number'] | shared/handler-defined |
| local_ai_coord | max_tokens | integer; default=0 | shared/handler-defined |
| local_ai_coord | receipt | object | verify_receipt |
| local_ai_coord | sync_action | string; enum=["export","import"]; default="export" | task_sync |
| local_ai_coord | stream_id | string; default="" | task_sync |
| local_ai_coord | events | array; items(object) | task_sync |
| local_ai_coord | limit | integer; minimum=1; maximum=1000; default=1000 | pubsub_poll, negative_knowledge_find, board_item_list, plan_list, task_sync, memory_find |
| local_ai_coord | contract | object | shared/handler-defined |
| local_ai_coord | checkpoint | object | shared/handler-defined |
| local_ai_coord | record | object | negative_knowledge_record |
| local_ai_coord | fingerprint | object; additionalProperties=false | shared/handler-defined |
| local_ai_coord | tool_outcome | object | shared/handler-defined |
| local_ai_coord | focus | array; items(string) | shared/handler-defined |
| local_ai_coord | include_diagnostics | boolean; default=false | shared/handler-defined |
| local_ai_coord | base | string; default="HEAD" | shared/handler-defined |
| local_ai_coord | after_seq | integer; minimum=0; maximum=9223372036854775807; default=0 | task_sync, pubsub_poll |
| local_ai_coord | include_stale | boolean; default=false | shared/handler-defined |
| local_ai_coord | capacity | integer; minimum=1; default=1 | shared/handler-defined |
| local_ai_coord | timeout | number; minimum=0; default=0 | shared/handler-defined |
| local_ai_coord | labels | array; items(string) | shared/handler-defined |
| local_ai_coord | details | object | shared/handler-defined |
| local_ai_coord | filter | object | shared/handler-defined |
| local_ai_coord | filter_payload | object | shared/handler-defined |
| local_ai_coord | include | array; items(string) | shared/handler-defined |
| local_ai_coord | extra_fields | array; items(string) | shared/handler-defined |
| local_ai_work | max_response_tokens | ['integer', 'null']; minimum=128; default=null | shared/handler-defined |
| local_ai_work | response_profile | string; enum=["minimal","compact","standard","debug","delta","dense"]; default="compact" | shared/handler-defined |
| local_ai_work | reuse_key | string; default="" | shared/handler-defined |
| local_ai_work | action | string | shared/handler-defined |
| local_ai_work | root | string; default="" | shared/handler-defined |
| local_ai_work | task | string; default="" | shared/handler-defined |
| local_ai_work | work_id | string; default="" | shared/handler-defined |
| local_ai_work | task_id | string; default="" | shared/handler-defined |
| local_ai_work | acceptance_criteria | array; items(string) | shared/handler-defined |
| local_ai_work | constraints | array; items(string) | shared/handler-defined |
| local_ai_work | mode | string; enum=["execute","bounded","plan","plan_only","dry_run"]; default="bounded" | shared/handler-defined |
| local_ai_work | allowed_paths | array; minItems=1; maxItems=8; items(string) | shared/handler-defined |
| local_ai_work | approved_commands | array; minItems=1; maxItems=8; items(string) | shared/handler-defined |
| local_ai_work | permissions | object | shared/handler-defined |
| local_ai_work | budget | object | shared/handler-defined |
| local_ai_work | timeout_seconds | number; default=90 | shared/handler-defined |
| local_ai_work | answer | string; default="" | shared/handler-defined |
| local_ai_work | return_fields | array; items(string) | shared/handler-defined |
| local_ai_work | extra_fields | array; items(string) | shared/handler-defined |
| local_ai_work | max_output_tokens | integer; default=0 | shared/handler-defined |
| local_ai_work | keep_failed_workspace | boolean; default=false | shared/handler-defined |

## Per-action contract

Fields use action metadata: required, non-empty, allowed (if explicitly restricted), feature requirements, effect, retry safety, idempotency, and important declared output flags. Field type/bounds are included when the JSON Schema declares them. For an action without an explicit allowlist, the action-scoped fields column names fields conditionally bound by the shared validator; other shared parameters remain handler-defined.

| Tool/action | Required | Non-empty | Allowed fields or action-scoped fields | Type/bound notes | Feature gate | Effect; retry-safe; idempotent | Declared output fields |
|---|---|---|---|---|---|---|---|
| local_ai_status.brief | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_artifact.get | artifact_id | artifact_id | artifact_id, offset, max_chars, section, binary, slices, root, workspace | max_chars:integer minimum=1 maximum=50000 default=4000; section:string maxLength=512; slices:array minItems=1 maxItems=16 items(object); root:string default=. | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_artifact.slice | artifact_id | artifact_id | artifact_id, offset, max_chars, section, binary, slices, root, workspace | max_chars:integer minimum=1 maximum=50000 default=4000; section:string maxLength=512; slices:array minItems=1 maxItems=16 items(object); root:string default=. | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_artifact.list | none | none | selector/common only |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_artifact.source | path | path | path, file, line_start, line_end, start_line, end_line, max_chars, offset, expected_file_sha256, slices, root, workspace | path:string maxLength=32768; file:string maxLength=32768; line_start:integer minimum=1 maximum=2147483647 default=1; line_end:integer maximum=2147483647; start_line:integer minimum=1 maximum=2147483647 default=1; end_line:integer maximum=2147483647; max_chars:integer minimum=1 maximum=50000 default=4000; expected_file_sha256:string maxLength=64; slices:array minItems=1 maxItems=16 items(object); root:string default=. | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.profile | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.search | none | none | root, query, path, include_code, path_hints, limit, offset, summarize_results, search_mode | root:string default=.; path:string maxLength=4096; path_hints:array maxItems=64 items(object); limit:integer minimum=1 maximum=200 default=24; offset:integer maximum=2047; search_mode:string enum=['lexical', 'rag', 'hybrid'] | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.map | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.code_index | none | none | root, query, limit, offset, include_code | root:string default=.; limit:integer minimum=1 maximum=200 default=24; offset:integer maximum=2047 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.deterministic | none | none | root, query | root:string default=. | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.context | query | query | root, query, workspace, mode, max_tokens, token_budget, task_id, session_id, phase, focus, preload_profile, repository_revision, changed_paths, base, staged, guarded, since_hash, approval, override_reason, clone_id, worktree_id, branch, repository_id, include_diagnostics, path_hints, directory_hints, exclude_paths, force_include_paths | root:string default=.; mode:string default=adaptive; max_tokens:integer maximum=100000; token_budget:integer maximum=100000; phase:string enum=['', 'plan', 'edit', 'review', 'test', 'handoff']; focus:array items(string); changed_paths:array items(string); base:string maxLength=512 default=HEAD; path_hints:array maxItems=64 items(object); directory_hints:array maxItems=64 items(string,minLength=1); exclude_paths:array maxItems=64 items(string,minLength=1); force_include_paths:array maxItems=64 items(string,minLength=1) | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.route | path | path | root, query, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.delegate | task | task | root, task, workspace, profile, max_tokens | root:string default=.; max_tokens:integer maximum=100000 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.solve | task | task | root, task, workspace, mode, max_tokens, base, staged | root:string default=.; mode:string default=adaptive; max_tokens:integer maximum=100000; base:string maxLength=512 default=HEAD | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.review_diff | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.impact | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.refactor_impact | path | path | root, query, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.resolve_imports | query | query | root, query, language, extra_fields | root:string default=.; language:string default=auto; extra_fields:array items(string) | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.audit_dependencies | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.ast_outline | path | path | root, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.git_status | none | none | root, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.repo_state | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.verify | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.affected_tests | none | none | root, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.topology | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.callers | none | none | shared schema; scoped: limit, offset, symbol | limit:integer minimum=1 maximum=200 default=24; offset:integer maximum=2047 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.callees | none | none | shared schema; scoped: limit, offset, symbol | limit:integer minimum=1 maximum=200 default=24; offset:integer maximum=2047 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.implementations | none | none | shared schema; scoped: limit, offset, symbol | limit:integer minimum=1 maximum=200 default=24; offset:integer maximum=2047 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.declaration | query | query | root, query, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.profile_digest | path | path | root, path, max_tokens | root:string default=.; path:string maxLength=4096; max_tokens:integer maximum=100000 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.schema_inspect | none | none | root, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.explain_query | query | query | root, query, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.env_compat | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.circular_dependencies | none | none | root, language | root:string default=.; language:string default=auto | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.dependency_slice | query | query | root, query, path, max_tokens | root:string default=.; path:string maxLength=4096; max_tokens:integer maximum=100000 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.structural_search | query | query | root, query, path, max_tokens, pattern | root:string default=.; path:string maxLength=4096; max_tokens:integer maximum=100000; pattern:string default=* | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.context_budget | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.git_diff | none | none | root, path, staged, max_tokens, rev1, rev2, base, head | root:string default=.; path:string maxLength=4096; max_tokens:integer maximum=100000; rev1:['string', 'null'] maxLength=512; rev2:['string', 'null'] maxLength=512; base:string maxLength=512 default=HEAD; head:string maxLength=512 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.diff | none | none | root, path, staged, max_tokens, rev1, rev2, base, head | root:string default=.; path:string maxLength=4096; max_tokens:integer maximum=100000; rev1:['string', 'null'] maxLength=512; rev2:['string', 'null'] maxLength=512; base:string maxLength=512 default=HEAD; head:string maxLength=512 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.git_history_search | none | query | root, query, max_commits, author, since, until, path | root:string default=.; max_commits:integer minimum=1 maximum=100 default=50; author:string maxLength=256 pattern=^[^\x00-\x1F\x7F]*$; since:string maxLength=64 pattern=^(?:\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2}))?$; until:string maxLength=64 pattern=^(?:\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2}))?$; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.hotspots | none | none | root, days, limit | root:string default=.; days:integer minimum=1 maximum=3650 default=30; limit:integer minimum=1 maximum=200 default=24 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.cross_repo_contract | path | path | root, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.skeletonize | none | none | root, query, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.investigate | none | none | root, query, path, include_code | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.diagnose | query | query | root, query | root:string default=. | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.briefing | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.semantic | none | none | root, query, path, relation | root:string default=.; path:string maxLength=4096 | serena | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.intelligence | none | none | root, query, path, relation | root:string default=.; path:string maxLength=4096 | has_semantic | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.pipeline | none | none | shared schema; scoped: steps | steps:array items(object) | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.call_graph | query | query | root, query, path, limit, depth | root:string default=.; path:string maxLength=4096; limit:integer minimum=1 maximum=200 default=24; depth:integer minimum=1 maximum=5 default=1 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.call_graph_diff | none | none | shared schema; scoped: none declared |  | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.semantic_diff | none | none | shared schema; scoped: old_code, new_code | old_code:['string', 'null'] maxLength=1048576; new_code:['string', 'null'] maxLength=1048576 | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.cross_project_graph | none | none | shared schema; scoped: none declared |  | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.cross_project_symbols | none | none | root, query | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.cross_project_impact | query | query | root, query | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.find_files | none | none | root, query, pattern, limit, offset | root:string default=.; pattern:string default=*; limit:integer minimum=1 maximum=200 default=24; offset:integer maximum=2047 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.glob | none | none | root, query, pattern, limit, offset | root:string default=.; pattern:string default=*; limit:integer minimum=1 maximum=200 default=24; offset:integer maximum=2047 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.git_log | none | none | root, query, max_commits, author, since, until, path, limit | root:string default=.; max_commits:integer minimum=1 maximum=100 default=50; author:string maxLength=256 pattern=^[^\x00-\x1F\x7F]*$; since:string maxLength=64 pattern=^(?:\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2}))?$; until:string maxLength=64 pattern=^(?:\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2}))?$; path:string maxLength=4096; limit:integer minimum=1 maximum=200 default=24 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.file_info | none | none | root, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.stat | none | none | root, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.read_file | none | none | root, path, line_start, line_end, start_line, end_line, max_chars | root:string default=.; path:string maxLength=4096; line_start:integer minimum=1 default=1; start_line:integer minimum=1 default=1; max_chars:integer minimum=1 maximum=50000 default=4000 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.source | none | none | root, path, line_start, line_end, start_line, end_line, max_chars | root:string default=.; path:string maxLength=4096; line_start:integer minimum=1 default=1; start_line:integer minimum=1 default=1; max_chars:integer minimum=1 maximum=50000 default=4000 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.definition | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.references | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.find_references | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.find_symbol | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.generate_tests | none | none | root, query, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.validate_patch | query | query | root, query | root:string default=. | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.test_matrix | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.security_audit | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.dead_code | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.secret_scan | none | none | root, path, staged | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.reachability_dead_code | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.mutation_test | none | none | root, path, diff | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.complexity | none | none | root, path, max_tokens, include_tests | root:string default=.; path:string maxLength=4096; max_tokens:integer maximum=100000 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.api_spec | none | none | root, query | root:string default=. | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.migration_drift | none | none | root, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.package_audit | none | none | root, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.synthesize_commit | none | task_id | root, query, task_id | root:string default=. | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.ast_refactor | old_symbol, new_symbol | old_symbol, new_symbol | root, path, old_symbol, new_symbol, staged | root:string default=.; path:string maxLength=4096; old_symbol:string maxLength=512; new_symbol:string maxLength=512 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.generate_mocks | query, path | query, path | root, query, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.split_changes | none | none | root, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.synthesize_rules | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.code_invariants | none | none | root, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.generate_dataset | query | query | root, query, max_tokens, relation | root:string default=.; max_tokens:integer maximum=100000 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.generate_types | path | path | root, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.type_stubs | path | path | root, path | root:string default=.; path:string maxLength=4096 | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.generate_tests_for_diff | none | none | root, diff, path, changed_paths | root:string default=.; path:string maxLength=4096; changed_paths:array items(string) | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.preprocess | none | none | shared schema; scoped: is_worktree, parent_root |  | preprocessing | repository_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.preprocess_status | none | none | shared schema; scoped: none declared |  | preprocessing | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.preprocess_refresh | none | none | shared schema; scoped: none declared |  | preprocessing | repository_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.preprocess_pause | none | none | shared schema; scoped: none declared |  | preprocessing | repository_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.preprocess_resume | none | none | shared schema; scoped: none declared |  | preprocessing | repository_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.preprocess_cancel | none | none | shared schema; scoped: none declared |  | preprocessing | repository_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.preprocess_unregister | none | none | shared schema; scoped: none declared |  | preprocessing | repository_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.patch | path | path | root, path, old_code, new_code, target, replacement | root:string default=.; path:string maxLength=4096; old_code:['string', 'null'] maxLength=1048576; new_code:['string', 'null'] maxLength=1048576 | none in operation contract | repository_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_repo.revert | path | none | root, path | root:string default=.; path:string maxLength=4096 | none in operation contract | repository_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |

**local_ai_repo source-only actions absent from the active MCP schema:** batch_replace. Do not count these as active coverage.

| local_ai_task.delegate | none | none | shared schema; scoped: query, phase, focus, preload_profile, repository_revision, changed_paths | focus:array items(string); changed_paths:array items(string) | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.explore | none | none | shared schema; scoped: query, phase, focus, preload_profile, repository_revision, changed_paths | focus:array items(string); changed_paths:array items(string) | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.reason | none | none | shared schema; scoped: problem, query, phase, focus, preload_profile, repository_revision, changed_paths | focus:array items(string); changed_paths:array items(string) | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.continue | none | none | shared schema; scoped: none declared |  | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.review | none | none | shared schema; scoped: code, diff, phase, focus, preload_profile, repository_revision, changed_paths | focus:array items(string); changed_paths:array items(string) | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.second_opinion | none | none | shared schema; scoped: question, phase, focus, preload_profile, repository_revision, changed_paths | focus:array items(string); changed_paths:array items(string) | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.compress | none | none | shared schema; scoped: text, phase, focus, preload_profile, repository_revision, changed_paths | focus:array items(string); changed_paths:array items(string) | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.route | none | none | shared schema; scoped: none declared |  | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.batch | none | none | shared schema; scoped: items | items:array items(object) | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.benchmark | none | none | selector/common only |  | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.hardware_benchmark | none | none | model, prompt, max_tokens |  | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.evaluation_record | none | none | shared schema; scoped: none declared |  | has_any_model | evaluation_store; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.evaluation_report | none | none | shared schema; scoped: none declared |  | has_any_model | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.eval_suite | none | none | task, model, cases | cases:array minItems=1 maxItems=32 items(object) | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.prompt_eval | none | none | prompt, candidate_data |  | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.eval_drift | none | none | task |  | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.submit | task | task | job_action, task, context, candidate, complexity, max_tokens, tasks, profile, root, workspace, timeout_seconds, request_id | job_action:string default=reason; complexity:string default=auto; tasks:array items(object); timeout_seconds:number default=90 | has_any_model | durable_job; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.status | none | none | shared schema; scoped: none declared |  | has_any_model | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.wait | none | none | shared schema; scoped: none declared |  | has_any_model | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.result | none | none | shared schema; scoped: none declared |  | has_any_model | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.cancel | none | none | shared schema; scoped: none declared |  | has_any_model | durable_job; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.candidate_create | candidate_data | none | candidate_data |  | has_any_model | candidate_store; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.candidate_promote | candidate, approver | candidate, approver | candidate, approver |  | has_any_model | candidate_store; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.speculative_draft | none | none | task, candidate, context, root |  | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.complete_code | none | none | prompt, candidate, max_tokens |  | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.scaffold | none | none | prompt, context, language, max_tokens, model |  | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.automation | root, task_id, automation | root, task_id | root, task_id, automation |  | has_any_model | browser_desktop_mutation; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, outcome_unknown, evidence_ids |
| local_ai_task.browser | none | none | shared schema; scoped: url | url:string maxLength=4096 | has_any_model | browser_capture; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.vision | none | none | prompt, candidate, model, image_artifact_id, screenshot_artifact_id, baseline_screenshot_artifact_id, bundle_artifact_id, dom_artifact_id, accessibility_artifact_id, computed_styles_artifact_id, runtime_artifact_id, network_artifact_id, source, cloud_fallback, root, dom, accessibility, computed_styles, runtime, viewport, page, bundle, html, accessibility_snapshot, computed_style_data, runtime_context, json_schema |  | has_any_model, vision | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_task.transcribe | none | none | candidate, model, language |  | has_any_model | local_model_execution; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_rag.index | none | none | shared schema; scoped: none declared |  | none in operation contract | index_store; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_rag.search | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_rag.list | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_rag.docset_index | none | none | shared schema; scoped: none declared |  | none in operation contract | index_store; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_rag.docset_search | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_rag.ingest_document | none | none | shared schema; scoped: none declared |  | none in operation contract | index_store; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_rag.ingest_diagram | none | none | shared schema; scoped: none declared |  | none in operation contract | index_store; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_budget_increase | root, task_id, reason, budget | root, task_id, reason | root, task_id, reason, budget | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_checkpoint | none | none | shared schema; scoped: notes, state_data, changed_paths, path, file, next_action, blockers, evidence_ids | blockers:array items(string); evidence_ids:array items(string) | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_claim | task_id | task_id | root, task_id, owner | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_cleanup_worktree | task_id | task_id | root, task_id | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_complete | none | none | shared schema; scoped: summary, result |  | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_create | none | none | root, task_id, goal, task, paths, contract, scope, acceptance_criteria, criteria, title, description, path, file | root:string default=.; paths:array items(string); acceptance_criteria:array items(string); criteria:array items(string) | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_fail | none | none | root, task_id, reason, error, message | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_get | none | none | shared schema; scoped: id |  | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_heartbeat | none | none | shared schema; scoped: none declared |  | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_list | none | none | root, query, status, owner, limit, offset, include_stale | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_repair_session | none | none | shared schema; scoped: none declared |  | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_resume | none | none | shared schema; scoped: id |  | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_rollback | none | none | shared schema; scoped: none declared |  | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_sync | none | none | root, sync_action, stream_id, after_seq, limit, events | root:string default=.; sync_action:string enum=['export', 'import'] default=export; after_seq:integer maximum=9223372036854775807; limit:integer minimum=1 maximum=1000 default=1000; events:array items(object) | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_transition | none | none | shared schema; scoped: none declared |  | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.task_zombie_reap | task_id | task_id | root, task_id | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.context_compile | task_id | task_id | root, task_id, since_hash, max_tokens, paths, include_diagnostics, clone_id, worktree_id, branch, repository_id, session_id, repository_revision, phase, focus, preload_profile | root:string default=.; max_tokens:integer maximum=100000 default=4000; paths:array items(string); session_id:string maxLength=256; focus:array items(string) | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.memory_delete | root, scope, record_id | root, scope, record_id | root, scope, record_id, scope_id, task_id, session_id, clone_id, worktree_id, branch | root:string default=.; session_id:string maxLength=256 | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.memory_find | none | none | root, scope, query, limit, kind, key, status, session_id | root:string default=.; limit:integer minimum=1 maximum=1000 default=1000; session_id:string maxLength=256 | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.memory_get | none | none | shared schema; scoped: kind, record_id |  | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.memory_promote | root, scope, record_id, target_scope | root, scope, record_id, target_scope | root, scope, record_id, target_scope, scope_id, task_id, session_id, clone_id, worktree_id, branch | root:string default=.; session_id:string maxLength=256 | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.memory_record | root, scope, key, value | root, scope, key | root, scope, key, value, kind, status, confidence, ttl_seconds, session_id | root:string default=.; confidence:['number', 'null'] maximum=1; session_id:string maxLength=256 | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.negative_knowledge_find | root, query | root, query | root, query, limit | root:string default=.; limit:integer minimum=1 maximum=1000 default=1000 | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.negative_knowledge_record | root, record | root | root, record | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.record_native_receipt | task_id, criterion, command_id | task_id, criterion, command_id | root, task_id, criterion, command_id | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.session_briefing | none | none | root, session_id, include | root:string default=.; session_id:string maxLength=256; include:array items(string) | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.verify_completion | task_id | task_id | root, task_id, repository_revision | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.verify_export | task_id | task_id | root, task_id, format | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.verify_receipt | receipt | none | root, receipt | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.board_item_create | title | title | root, title, status, priority, labels, assignee, milestone, linked_task_id, details, name, description, task_id | root:string default=.; labels:array items(string) | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.board_item_delete | item_id | item_id | root, item_id | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.board_item_get | item_id | item_id | root, item_id | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.board_item_list | none | none | root, status, priority, milestone, assignee, limit | root:string default=.; limit:integer minimum=1 maximum=1000 default=1000 | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.board_item_update | item_id | item_id | root, item_id, title, status, priority, labels, assignee, milestone, linked_task_id, details, name, description, id, task_id | root:string default=.; labels:array items(string) | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.board_summary | none | none | root | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.milestone_create | name | name | root, name, target_date, description | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.milestone_status | name | name | root, name | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.plan_adopt_legacy_board | none | root, plan_id | root, plan_id, title, owner, idempotency_key | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.plan_archive | none | root, plan_id, expected_revision | root, plan_id, expected_revision, idempotency_key, owner | root:string default=.; expected_revision:string minLength=1 | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.plan_bind_task | none | root, task_id, plan_id, plan_task_id | root, task_id, plan_id, plan_task_id, expected_revision, session_id | root:string default=.; expected_revision:string minLength=1; session_id:string maxLength=256 | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.plan_board_view | none | root | root, plan_id, query, worktree_id | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.plan_create | none | root, plan_id, title | root, plan_id, title, description, lifecycle, default_target_ref, spec_refs, tasks, accountable_role, owner, idempotency_key | root:string default=.; lifecycle:string enum=['draft', 'active', 'paused', 'completed', 'cancelled', 'archived']; spec_refs:array items(object) | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.plan_get | none | root, plan_id | root, plan_id | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.plan_init | none | root | root | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.plan_list | none | root | root, query, lifecycle, limit | root:string default=.; lifecycle:string enum=['draft', 'active', 'paused', 'completed', 'cancelled', 'archived']; limit:integer minimum=1 maximum=1000 default=1000 | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.plan_reconcile_steering | none | root, task_id, steering_id, spec_rel_path, spec_content, acceptance_criteria, expected_revision, expected_spec_revision | root, task_id, steering_id, spec_rel_path, spec_content, acceptance_criteria, expected_revision, expected_spec_revision, summary | root:string default=.; acceptance_criteria:array items(string); expected_revision:string minLength=1 | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.plan_task_delete | none | root, plan_id, task_id, expected_revision | root, plan_id, expected_revision, task_id, idempotency_key, owner | root:string default=.; expected_revision:string minLength=1 | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.plan_task_edit | none | root, plan_id, task_id, task_data, expected_revision | root, plan_id, expected_revision, task_id, task_data, idempotency_key, owner | root:string default=.; expected_revision:string minLength=1 | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.plan_update | none | root, plan_id, expected_revision | root, plan_id, expected_revision, title, description, lifecycle, default_target_ref, spec_refs, accountable_role, owner, idempotency_key | root:string default=.; expected_revision:string minLength=1; lifecycle:string enum=['draft', 'active', 'paused', 'completed', 'cancelled', 'archived']; spec_refs:array items(object) | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.plan_validate | none | root, plan_id | root, plan_id | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.answer | root, question_id, answer | root, question_id, answer | root, question_id, answer, task_id | root:string default=.; question_id:string maxLength=80; answer:string maxLength=16384 | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.ask | root, session_id | root, session_id | root, session_id, question_id, question, task_id | root:string default=.; session_id:string maxLength=256; question_id:string maxLength=80; question:string maxLength=16384 | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.blackboard_delete | none | none | root, task_id, board_id, section | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.blackboard_get | none | none | root, task_id, board_id, section | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.blackboard_list | none | none | root, task_id | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.blackboard_merge | remote_sections | none | root, task_id, board_id, remote_sections | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.blackboard_update | content | none | root, task_id, board_id, section, content, author, expected_version | root:string default=.; author:string default=agent | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.claim | none | none | shared schema; scoped: changed_paths, path, file |  | none in operation contract | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.leases | none | none | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.pubsub_poll | none | none | root, topic, after_seq, limit, after_ts | root:string default=.; topic:string default=default; after_seq:integer maximum=9223372036854775807; limit:integer minimum=1 maximum=1000 default=1000; after_ts:number maximum=1000000000000 | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.pubsub_publish | message | none | root, topic, message, publisher | root:string default=.; topic:string default=default; publisher:string default=agent | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.release | none | none | shared schema; scoped: changed_paths, path, file |  | none in operation contract | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.renew | none | none | shared schema; scoped: path, file |  | none in operation contract | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.semaphore_acquire | name | name | root, name, capacity, timeout, ttl_seconds, purpose, owner | root:string default=.; capacity:integer minimum=1 default=1 | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.semaphore_release | name, lease_id | name, lease_id | root, name, lease_id, owner | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.semaphore_status | none | none | root, name | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.wait_for_event | topic | topic | root, topic, timeout, filter, filter_payload | root:string default=.; topic:string default=default | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.simulate_merge | source_branch | source_branch | root, source_branch, target_branch | root:string default=.; target_branch:string default=HEAD | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.swarm_cancel | swarm_id | swarm_id | root, swarm_id, reason | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.swarm_dispatch | goal | goal | root, goal, target_paths, test_command, author | root:string default=.; target_paths:['array', 'null'] items(string); author:string default=agent | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.swarm_list | none | none | root, state | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.swarm_status | swarm_id | swarm_id | root, swarm_id | root:string default=. | agent_os | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.swarm_step | swarm_id | swarm_id | root, swarm_id, role, swarm_action, payload | root:string default=.; role:string default=Coder; swarm_action:string default=submit_patch | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.worktree_lease | none | none | root, branch | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.worktree_release | none | none | root, worktree_path, worktree_id, delete_branch, branch | root:string default=.; delete_branch:boolean default=True | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.curate_dataset | root | root | root, output_path, min_receipts, format | root:string default=.; output_path:string default=training_dataset.jsonl; min_receipts:integer default=1 | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.gpu_reservation_release | generation, consent, audit_reason | generation, audit_reason | generation, consent, audit_reason |  | none in operation contract | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.gpu_reservation_release_authorized | consent, audit_reason | audit_reason | consent, audit_reason |  | none in operation contract | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.gpu_reservation_status | none | none | selector/common only |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_coord.incident_decision | root, fingerprint | root, fingerprint | root, fingerprint, state_revision | root:string default=. | agent_os | coordination_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_work.status | work_id | work_id | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_work.wait | work_id | work_id | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_work.get | work_id | work_id | shared schema; scoped: none declared |  | none in operation contract | read_only; retry=True; idem=True; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |
| local_ai_work.cancel | work_id | work_id | shared schema; scoped: none declared |  | none in operation contract | work_order_state; retry=False; idem=False; replay=False | success, error, terminal, retryable, degraded, stale, cancelled, evidence_ids |

Round 129 recorded `local_ai_work.submit` and `local_ai_work.continue` in one GPT-6 Luna Medium session; that observation is session-bound, not a current or universal exposure guarantee. This source-contract snapshot has no per-action rows for them. Case 134 distinguishes their source contract and gates from each session's live enum; case 129 remains the input/output contract audit.


## Shared validation branches

- Action must be in the feature-filtered action set; unknown actions reject with the currently supported enum.
- local_ai_status has no public action selector; the internal brief entry above denotes the one supported detail value, detail=brief.
- Unknown arguments and arguments scoped to another action reject. Required and non-empty fields are checked before dispatch; booleans do not pass integer checks; non-finite numbers, wrong JSON types, enum/range and array-size violations reject.
- local_ai_status bypass adoption requires both supported target_tool and target_action; target fields reject unless adoption_signal=bypassed.
- local_ai_repo context path hints/directories/exclusions require adaptive mode; search/code_index/callers/callees/implementations enforce pagination bounds; hotspots enforces days 1..3650 and limit 1..50; nested path hints validate their own schema.
- For local_ai_repo search, `path` is normalized into a `path_hints` ranking signal; it does not confine results. `path_hints` likewise are hints, not authorization boundaries. Fixture-isolated search must use the fixture itself as `root` and verify every returned path stays beneath it.
- local_ai_coord memory record/delete/promote require explicit absolute root and canonical scope; record validates non-empty key and string value; delete/promote require record ID; promote requires canonical target scope.
- local_ai_coord plans require canonical repository root; plan_list limit is 1..1000; supplied expected_revision must be a non-empty trimmed revision. task_sync export/import fields are mutually exclusive; limit is 1..1000.
- local_ai_coord negative_knowledge_find requires canonical non-empty root/query and limit 1..100; nested incident/negative-knowledge records validate their schemas; ask requires question or question_id; verify_receipt requires a schema-valid receipt object.
- local_ai_artifact source max_chars is 512..12000; get/slice offsets and slice batches have separate bounds.
- Record output states separately: success, partial/degraded, truncated/output_truncated, terminal/retryable, in_progress/waiting/timed_out/cancelled/outcome_unknown, approval/override, mutation_applied, receipt_status, task_status and cleanup confirmation when exposed. Never convert unknown or incomplete output into PASS.

## Inventory reconciliation

Rows above describe the source-contract snapshot and do not establish current MCP exposure. Use the live action inventory in mcp-action-coverage.md. Cases 114-133 provide action scenarios; case 129 audits field-level contracts, and case 134 separates source-supported `local_ai_work` actions from per-session exposure and gating.

Source-contract action rows emitted: 218. This generated index omits per-action rows for `local_ai_work.submit` and `.continue` even though `operation_contracts.py` declares both; live exposure remains session-specific. Case 134 verifies the exact source declaration separately.
