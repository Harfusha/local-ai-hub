"""Static delivery and lifecycle contract text for the MCP tool surface."""

from __future__ import annotations


def semantic_handoff_contract(enabled: bool, status_enabled: bool = True) -> str:
    if not enabled:
        return " Semantic delegation actions are unavailable under the active profile, feature gates, or local-inference configuration."
    return (
        " Semantic delegation is on-demand under the active schema and quality gates. After deterministic/indexed evidence,"
        " use the matching exposed `local_ai_task` action by default for bounded review of non-trivial edits, reasoning"
        " on uncertain decisions, semantic exploration, independent second opinions, or evidence/log compression."
        " Check backend and model quality; inference stays advisory. Cloud reasoning and planning"
        " are never blocked by mandatory local handoffs. Deterministic/indexed tools remain authoritative"
        " for exact facts, symbols, diff and tests."
    )


def async_job_lifecycle_contract(*, include_mcp_tool: bool = True) -> str:
    contract = (
        " Async status, wait, result, and cancel work with model execution disabled; wait defaults to 90 seconds and is capped by async_jobs.wait_max_seconds and the client transport budget. A timed-out wait returns current state with wait_timeout_seconds and does not cancel the job; call result after completion instead of polling."
        " Compact lifecycle responses preserve job_id, state, artifact_id (empty until available), and expires_at (Unix timestamp seconds). Terminal job state expires at expires_at; async_jobs.result_ttl_seconds defaults to 259,200 seconds (72 hours), and artifact-store TTL must cover it."
        " Queued cancellation immediately returns terminal cancelled. Running cancellation returns running with cancel_requested=true as acknowledgement; worker completion supplies final state."
        " Direct HTTP lifecycle requests use `POST /api/async-jobs`: submit sends action=submit, job_action, and optional stable request_id; controls send action=status|wait|result|cancel with job_id, and wait also sends timeout_seconds."
    )
    if include_mcp_tool:
        contract += (
            " MCP exposes `local_ai_task(action=submit|status|wait|result|cancel, ...)`;"
            " `HubClient.submit_async_job`, `async_job_status`, `wait_async_job`, `async_job_result`, and `cancel_async_job` call the same HTTP path."
        )
    else:
        contract += (
            " MCP and HubClient retain status, wait, result, and cancel controls when model execution is disabled."
        )
    return contract + (
        " Recovery may replay only explicitly replay-safe actions with a stable request_id and remaining attempts;"
        " command-backed and unclassified actions become terminal `outcome_unknown`."
    )


def task_delivery_contract() -> str:
    return (
        " Delivery: `sync` is default except HTTP `/api/rag/index`, which defaults to `auto` with a 30-second latency budget; explicit `delivery=sync` stays inline. `async` submits immediately on mapped HTTP routes; `auto` needs a positive `latency_budget_ms` and at least ten endpoint observations with p95 above budget, while sparse history stays inline except RAG indexing, which submits async below ten samples."
        " HTTP delivery maps `/api/delegate`, `/api/reason`, `/api/review`, `/api/review/diff`, `/api/second-opinion`, `/api/compress`, `/api/route`, `/api/delegate/batch`, and `/api/rag/index` to durable actions. MCP RAG indexing uses a 30-second budget; cold start submits with reason `cold_start_rag_index`. Inspect returned `job_id` with status, wait, or result."
        " For `delivery=auto` on `/api/review/diff`, a positive `review.max_queue_age_ms` exceeded by queue age returns a terminal 503 before cold-start handling; otherwise positive budget with fewer than five samples selects async as `cold_start_review_diff`."
        " Direct `submit` job_action accepts `batch`, `compress`, `delegate`, `rag_index`, `reason`, `review`, `review_diff`, `route`, `second_opinion`, or `speculative_lint`; body `request_id` is the job idempotency key and `X-LocalAI-Request-ID` is separate journal correlation. Retryable async queue rejection maps to HTTP 429 and returns `status_code` in the body."
        f"{async_job_lifecycle_contract()}"
        " Start synchronously with HTTP POST `/api/delegate` or `/api/reason` or MCP `local_ai_task(action=delegate|explore|reason, conversation=true, delivery=sync)`; continue via HTTP `POST /api/conversations/continue` (`conversation_id`, `task`, optional `context`) or MCP `local_ai_task(action=continue, conversation_id=..., task=..., context=...)`."
        " `HubClient` has no dedicated start helper; use `HubClient.post` for `/api/delegate` or `/api/reason`. `HubClient.continue_conversation(conversation_id, prompt, context=...)` sends `conversation_id`, maps `prompt` to `task`, and includes optional `context`."
        " Conversation IDs identify reservations in this installation; model settings stay pinned and only one turn runs at a time. Defaults: 12 turns, prompt limit from `model_conversations.max_prompt_tokens` (fallback `token_saving.max_local_input_tokens`, default 56,000), idle/active TTLs of 900/1,800 seconds, and capacity 1,000. State is process-memory only and lost on restart."
    )
