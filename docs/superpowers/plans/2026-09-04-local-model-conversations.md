# Local Model Conversations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded process-local continuation for synchronous `local_ai_task` model exchanges.

**Architecture:** A dedicated in-memory store owns opaque tenant-bound transcripts and active-turn reservations. `LocalAIServices` keeps route/model/system settings from the first request and invokes the existing generation path with persistent caches disabled. The compact MCP tool gains `conversation`, `conversation_id`, and `continue` while retaining seven tools.

**Tech Stack:** Python 3.11, FastMCP, pytest, existing Local AI Hub scheduler/runtime.

---

### Task 1: Conversation state

**Files:**
- Create: `src/local_ai_hub/conversations.py`
- Test: `tests/test_conversations.py`

- [x] Write failing tests for tenant isolation, active-turn rejection, expired IDs and successful commit.
- [x] Run focused tests and observe missing-module failure.
- [x] Implement only the bounded in-memory store and rerun focused tests.

### Task 2: Service continuation

**Files:**
- Modify: `src/local_ai_hub/services.py`
- Test: `tests/test_conversations.py`

- [x] Write failing service tests for first-turn route pinning, transcript inclusion, failure rollback and cache bypass.
- [x] Run focused tests and observe missing-service behavior.
- [x] Add `conversation=true` start and `continue_conversation`; rerun focused tests.

### Task 3: MCP and HTTP transport

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/http_server.py`
- Modify: `tests/test_mcp_agent_routing.py`

- [x] Write failing forwarding/schema tests for `continue` and conversation fields.
- [x] Run focused tests and observe action/schema failure.
- [x] Add the action and HTTP route; rerun focused tests.

### Task 4: Documentation and validation

**Files:**
- Modify: `docs/MCP_AND_AGENTS.md`
- Modify: `docs/HTTP_API.md`

- [x] Document process lifetime, bounds and unsupported async/profile modes.
- [x] Run focused pytest, `python -m compileall -q src mcp tools tests`, full pytest and `python tools/selftest.py`.
