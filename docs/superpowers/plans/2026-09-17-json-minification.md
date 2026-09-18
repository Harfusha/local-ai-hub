# Minified JSON Serialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every production JSON serialization compact while preserving explicit human-readable exports, debug/artifact presentation, documentation, and test fixtures.

**Architecture:** Add a dependency-free `json_utils.dumps` wrapper using `ensure_ascii=False` and `separators=(",", ":")`, with optional keyword passthrough for `sort_keys`, `default`, and other existing callers. Replace production `json.dumps` calls through this wrapper or explicit compact separators. Keep `indent=2` only at approved human-facing boundaries. No global monkey-patch.

**Tech Stack:** Python 3.11+, stdlib `json`, pytest, existing MCP/HTTP/cache/state modules.

---

### Task 1: Add compact serializer contract

**Files:**
- Create: `src/local_ai_hub/json_utils.py`
- Test: `tests/test_json_utils.py`

- [ ] **Step 1: Write the failing tests**

```python
import json

from local_ai_hub.json_utils import dumps


def test_dumps_is_compact_and_round_trips_unicode():
    value = {"message": "žluťoučký", "items": [1, {"ok": True}]}
    encoded = dumps(value)
    assert encoded == '{"message":"žluťoučký","items":[1,{"ok":true}]}'
    assert json.loads(encoded) == value


def test_dumps_preserves_explicit_sorting_and_default():
    encoded = dumps({"b": object(), "a": 1}, sort_keys=True, default=str)
    assert encoded.startswith('{"a":1,"b":"<object object at ')
    assert " :" not in encoded
    assert ", " not in encoded
```

- [ ] **Step 2: Run the focused test and verify the expected failure**

Run: `python -m pytest -q tests/test_json_utils.py`

Expected: FAIL because `local_ai_hub.json_utils` does not exist.

- [ ] **Step 3: Implement the minimal serializer**

```python
from __future__ import annotations

import json
from typing import Any


def dumps(value: Any, **kwargs: Any) -> str:
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("separators", (",", ":"))
    return json.dumps(value, **kwargs)
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `python -m pytest -q tests/test_json_utils.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/local_ai_hub/json_utils.py tests/test_json_utils.py && git commit -m "feat: add compact JSON serializer"`

### Task 2: Convert transport and runtime JSON

**Files:**
- Modify: `src/local_ai_hub/client.py`
- Modify: `src/local_ai_hub/commands.py`
- Modify: `src/local_ai_hub/http_server.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/ollama.py`
- Modify: `src/local_ai_hub/llama_cpp.py`
- Modify: `src/local_ai_hub/embeddings.py`
- Modify: `src/local_ai_hub/response_protocol.py`
- Test: `tests/test_reliability_core.py`, `tests/test_mcp_agent_routing.py`

- [ ] **Step 1: Add regression assertions before replacements**

Extend the existing HTTP/MCP tests with a response body containing nested JSON and assert its raw body has no `, ` or `: ` separators while `json.loads` remains unchanged. Add a direct `project_response` assertion that its compact-size calculation still uses compact JSON.

- [ ] **Step 2: Run the transport tests and verify the new assertions fail on unconverted paths**

Run: `python -m pytest -q tests/test_reliability_core.py tests/test_mcp_agent_routing.py`

Expected: FAIL on at least one default `json.dumps` transport path.

- [ ] **Step 3: Replace production transport serializations**

Use `from local_ai_hub.json_utils import dumps as json_dumps` and replace only production `json.dumps(...)` calls that create request/response bodies or runtime JSON. Preserve existing `sort_keys`, `default`, and `ensure_ascii` behavior. Representative transformation:

```python
# before
body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

# after
body = json_dumps(payload).encode("utf-8")
```

For code paths already using `separators=(",", ":")`, keep behavior unchanged or route through the helper. Do not alter free-form model output, code, logs, or explicit pretty rendering.

- [ ] **Step 4: Run transport tests and verify they pass**

Run: `python -m pytest -q tests/test_reliability_core.py tests/test_mcp_agent_routing.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/local_ai_hub/client.py src/local_ai_hub/commands.py src/local_ai_hub/http_server.py src/local_ai_hub/mcp_server.py src/local_ai_hub/ollama.py src/local_ai_hub/llama_cpp.py src/local_ai_hub/embeddings.py src/local_ai_hub/response_protocol.py tests/test_reliability_core.py tests/test_mcp_agent_routing.py && git commit -m "fix: compact runtime JSON transport"`

### Task 3: Convert persisted, cached, telemetry, and orchestration JSON

**Files:**
- Modify: `src/local_ai_hub/agent_blackboard.py`
- Modify: `src/local_ai_hub/agent_context.py`
- Modify: `src/local_ai_hub/agent_incidents.py`
- Modify: `src/local_ai_hub/agent_learning.py`
- Modify: `src/local_ai_hub/agent_memory.py`
- Modify: `src/local_ai_hub/agent_tasks.py`
- Modify: `src/local_ai_hub/agent_verification.py`
- Modify: `src/local_ai_hub/autotune.py`
- Modify: `src/local_ai_hub/cache.py`
- Modify: `src/local_ai_hub/code_index.py`
- Modify: `src/local_ai_hub/debug_traces.py`
- Modify: `src/local_ai_hub/memory.py`
- Modify: `src/local_ai_hub/preprocess.py`
- Modify: `src/local_ai_hub/semantic_cache.py`
- Modify: `src/local_ai_hub/supervisor.py`
- Modify: `src/local_ai_hub/swarm.py`
- Modify: `src/local_ai_hub/telemetry.py`
- Modify: `src/local_ai_hub/work_orchestrator.py`
- Test: matching existing module tests plus `tests/test_token_accounting.py`

- [ ] **Step 1: Add a repository guard test for unapproved noncompact production calls**

Create a bounded AST/text test that scans `src/local_ai_hub` for `json.dumps(` calls and fails when a call lacks `separators` or an explicit approved `indent=2` exception. Allow the helper's internal call, and record approved human-readable files/lines in the test so future additions fail visibly.

- [ ] **Step 2: Run the guard and record the failing call sites**

Run: `python -m pytest -q tests/test_json_utils.py tests/test_json_serialization_contract.py`

Expected: FAIL with remaining production call locations.

- [ ] **Step 3: Convert persistence and orchestration calls**

Import the shared helper in each listed module. Replace direct serializations used for SQLite blobs, cache values, state snapshots, telemetry payloads, task results, prompt context, hashes, and internal files. Keep explicit `indent=2` calls in `agent_tasks.py`, `benchmark.py`, `token_economy.py`, `work_orchestrator.py`, and `artifacts.py` only where output is intentionally human-readable; if a file is machine-read, convert it instead.

- [ ] **Step 4: Run focused persistence and accounting tests**

Run: `python -m pytest -q tests/test_agent_state_transport.py tests/test_agent_state_reliability.py tests/test_agent_memory.py tests/test_cache_decision_telemetry.py tests/test_token_accounting.py tests/test_work_orchestrator.py tests/test_json_serialization_contract.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/local_ai_hub tests/test_agent_state_transport.py tests/test_agent_state_reliability.py tests/test_agent_memory.py tests/test_cache_decision_telemetry.py tests/test_token_accounting.py tests/test_work_orchestrator.py tests/test_json_serialization_contract.py && git commit -m "fix: compact persisted JSON"`

### Task 4: Preserve intentional pretty JSON and verify whole repository

**Files:**
- Modify: `tests/test_json_serialization_contract.py`
- Inspect only: `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`, `AGENTS.md`

- [ ] **Step 1: Verify exceptions are explicit**

Assert `indent=2` remains only for human-readable exports, debug/artifact views, benchmark reports, token-economy CLI output, and fixtures. Do not change docs or prompt files unless the serialization policy text is inconsistent.

- [ ] **Step 2: Run the guard and compact focused suite**

Run: `python -m pytest -q tests/test_json_serialization_contract.py tests/test_json_utils.py`

Expected: PASS with no unapproved noncompact production serialization.

- [ ] **Step 3: Run repository validation through the command broker**

Run through `local_ai_command`: `python tools/release_check.py`, `python -m compileall -q src tools tests`, `python -m pytest -q`, and `python tools/selftest.py`.

Expected: all commands pass; no new warnings.

- [ ] **Step 4: Review the final diff and status**

Run: `git diff HEAD~3..HEAD --stat`, `git status --short`, and indexed `review_diff`. Confirm the three pre-existing modified files remain present and untouched by this work.

- [ ] **Step 5: Commit any final test-only adjustment**

Run: `git add tests/test_json_serialization_contract.py && git commit -m "test: enforce compact JSON contract"` only if the final guard needed a separate change.
