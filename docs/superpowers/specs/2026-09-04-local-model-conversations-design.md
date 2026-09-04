# Local Model Conversations Design

## Goal

Allow an MCP caller to continue a synchronous `delegate` or `reason` exchange by
opaque `conversation_id`, without adding an eighth MCP tool.

## Contract

`local_ai_task(action="delegate"|"reason", conversation=true, ...)` starts an
in-memory conversation and returns `conversation_id`. `local_ai_task(action="continue",
conversation_id=..., task=...)` sends the next user message. Calls without
`conversation=true` retain their current stateless behavior.

Conversations do not support profiles, `delivery="async"`, or model/routing
overrides after their first turn. The initial route, model, system prompt and
generation settings are pinned.

## State and bounds

Conversation history exists only in the hub process. It is bound to the request
tenant, expires after idle TTL, accepts one active turn, and has turn and prompt
token limits. Expired, unknown, or foreign IDs reveal no history. A hub restart
forgets every conversation.

Conversation turns bypass persistent generation, semantic and artifact caches,
so neither a complete transcript nor individual continuation response is stored
as a cache entry. Ordinary telemetry remains metadata-only.

## Data flow

1. The MCP façade starts `delegate` or `reason` with `conversation=true`.
2. The service selects its normal route, reserves a new conversation, and runs
   the first model request.
3. On success it appends the user prompt and full assistant response in memory.
4. `continue` reserves the same conversation, constructs a bounded transcript,
   runs with its pinned settings, and commits the new pair on success.
5. Failure releases the active reservation without appending the failed turn.

## Errors and tests

The API rejects missing IDs, unknown/foreign/expired IDs, active conversations,
async/profile usage, exhausted turn limits and oversized transcript. Tests cover
MCP forwarding, tenant isolation, transcript retention, failure rollback, token
limit, and no-cache generation path.
