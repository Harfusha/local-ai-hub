# Wave 6 Implementation Plan: Hardware, Models & Multimodal UI

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide browser headless UI inspection, local visual diffing via Qwen-VL, non-blocking GPU telemetry, and VRAM lifecycle management.

**Architecture:** Modifies `browser_bridge.py`, `frontend_review.py`, `vram_balancer.py`, `ollama.py`, `commands.py`, `tokens.py`, `services.py`, `sqlite_support.py`, `debug_traces.py`, `deterministic.py`, `reranker.py`, and `mcp_server.py`. Exposes CDP DOM snapshotting, ephemeral mock server binding, idle model unloading, and calibrated token estimation.

**Tech Stack:** Python 3.11, CDP / Chrome Headless, Qwen-VL, Pytest.

---

### Task 79: Expose `browser_bridge` Headless Inspection in MCP (#41)

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:2330-2360`
- Modify: `mcp/local-ai/local_ai_task.json`
- Test: `tests/unit/test_mcp_browser_bridge.py`

- [ ] **Step 1: Write test verifying `local_ai_task(action="browser", url="http://localhost:3000")` calls `browser_bridge`**

```python
# tests/unit/test_mcp_browser_bridge.py
def test_mcp_browser_bridge_action(monkeypatch):
    class DummyBrowser:
        def capture(self, url, **kwargs):
            return {"success": True, "title": "Test Page", "dom_snapshot": "<html>...</html>"}
    monkeypatch.setattr("local_ai_hub.browser_bridge.BrowserBridge", lambda *a: DummyBrowser())
```

- [ ] **Step 2: Implement fix**
Add `action="browser"` or `action="browser_snapshot"` to `local_ai_task` or `local_ai_repo`. Connect to `BrowserBridge.capture_page()`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(mcp): expose browser_bridge DOM snapshot and screenshot in local_ai_task"`

---

### Task 80: Local Visual Diffing via Qwen-VL (#42)

**Files:**
- Modify: `src/local_ai_hub/frontend_review.py:280-340`
- Test: `tests/unit/test_frontend_visual_diff.py`

- [ ] **Step 1: Write test comparing baseline vs candidate screenshots**
- [ ] **Step 2: Implement visual diff**
Implement `compare_screens(baseline_png: bytes, current_png: bytes) -> dict[str, Any]` in `frontend_review.py`. Uses Qwen-VL to detect visual shifts.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(vision): implement local visual regression diffing via Qwen-VL"`

---

### Task 81: Ephemeral Port Bind for `mock_server` (#43, #45)

**Files:**
- Modify: `src/local_ai_hub/commands.py:10100-10150`
- Test: `tests/unit/test_mock_server_ephemeral_port.py`

- [ ] **Step 1: Write test binding mock server on port=0 and verifying assigned port is returned**
- [ ] **Step 2: Implement fix**
When `port` is 0 or omitted, bind socket to port 0 (`sock.bind(('127.0.0.1', 0))`) and return assigned ephemeral port. Sanitize `Authorization` and `Cookie` headers during `record_mock`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(mock): support ephemeral port binding and header sanitization in mock server"`

---

### Task 82: Non-Blocking GPU Telemetry in `VRAMBalancer` (#53, #97)

**Files:**
- Modify: `src/local_ai_hub/vram_balancer.py:50-95`
- Test: `tests/unit/test_vram_balancer_non_blocking.py`

- [ ] **Step 1: Write test verifying `vram_balancer.status()` returns immediately without waiting for `nvidia-smi`**
- [ ] **Step 2: Implement fix**
Maintain a single background daemon thread with periodic polling. `vram_balancer.status()` always returns the cached snapshot in memory (<0.1 ms).
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(vram): make GPU telemetry non-blocking via background sampling worker"`

---

### Task 83: Idle Unload Timer for Local Models in VRAM (#54)

**Files:**
- Modify: `src/local_ai_hub/ollama.py:180-220`
- Test: `tests/unit/test_model_idle_unload.py`

- [ ] **Step 1: Write test verifying model unload request is dispatched after configured idle duration**
- [ ] **Step 2: Implement fix**
Add `idle_timeout_seconds` (default 300s). When timer expires, call Ollama API with `keep_alive=0` to free GPU VRAM for the user's IDE.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(models): add idle unload timer to release GPU VRAM when local models are inactive"`

---

### Task 84: Calibrated Token Counter for Code (#40)

**Files:**
- Modify: `src/local_ai_hub/tokens.py:40-80`
- Test: `tests/unit/test_calibrated_tokenizer.py`

- [ ] **Step 1: Write test verifying code token count is accurate within 5% of BPE tokenizers**
- [ ] **Step 2: Implement fix**
Replace naive `len(text) // 4` with regex-aware subword estimator splitting identifiers on CamelCase and snake_case.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(tokens): calibrate code token estimator to eliminate budget truncation errors"`

---

### Task 85: Compact Schema Guide Cards `local_ai_status detail="guide"` (#12)

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:1675-1710`
- Test: `tests/unit/test_guide_cards_status.py`

- [ ] **Step 1: Write test verifying `local_ai_status(detail="guide")` returns compact per-tool cards**
- [ ] **Step 2: Implement guide cards**
Provide concise required parameters, action examples, and token tips for each tool, reducing schema prompting overhead by 70%.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(mcp): add compact guide cards to local_ai_status to save 70% schema tokens"`

---

### Task 86: Predictive Cache Warmup after `task_create` (#18)

**Files:**
- Modify: `src/local_ai_hub/services.py:4180-4220`
- Test: `tests/unit/test_predictive_cache_warmup.py`

- [ ] **Step 1: Write test verifying context cache begins background warmup upon task creation**
- [ ] **Step 2: Implement fix**
When `task_create` is executed with criteria or changed paths, dispatch asynchronous background context compilation so the subsequent `context` call hits L1 cache.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(services): trigger predictive background context warmup on task_create"`

---

### Task 87: Dynamic Request Matchers in Mock Server (#44)

**Files:**
- Modify: `src/local_ai_hub/commands.py:10150-10190`
- Test: `tests/unit/test_mock_server_regex_matcher.py`

- [ ] **Step 1: Write test verifying mock server matches requests with dynamic URL paths or query params**
- [ ] **Step 2: Implement regex matcher**
Support regex URL matching and query parameter wildcards in cassette definitions.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(mock): add regex and query parameter matchers to mock server"`

---

### Task 88: Dynamic Timeout and Retry in `sqlite_support.py` (#51)

**Files:**
- Modify: `src/local_ai_hub/sqlite_support.py:70-110`
- Test: `tests/unit/test_sqlite_dynamic_retry.py`

- [ ] **Step 1: Write test verifying busy timeout backs off exponentially under concurrency**
- [ ] **Step 2: Implement fix**
Implement `connect_with_retry` with exponential jitter backoff on `sqlite3.BusyError`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(sqlite): implement exponential backoff retry for SQLite busy timeouts"`

---

### Task 89: Async Job Progress Callbacks in `async_jobs.py` (#52)

**Files:**
- Modify: `src/local_ai_hub/async_jobs.py:100-140`
- Test: `tests/unit/test_async_jobs_progress.py`

- [ ] **Step 1: Write test verifying async job reports percent completion and stage message**
- [ ] **Step 2: Implement fix**
Add `progress_percent: float` and `current_stage: str` to job state record.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(jobs): add progress percentage and stage callback to async jobs"`

---

### Task 90: Local LLM OOM Fallback & VRAM Context Scaling (#55)

**Files:**
- Modify: `src/local_ai_hub/ollama.py:220-260`
- Test: `tests/unit/test_llm_oom_fallback.py`

- [ ] **Step 1: Write test simulating context OOM and verifying automatic context truncation and retry**
- [ ] **Step 2: Implement fix**
Catch `CUDA out of memory` / `model load failed`. Automatically reduce `num_ctx` by 50% or fall back to CPU offload.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(ollama): automatically scale context window down on VRAM OOM error"`

---

### Task 91: In-Process `speculative_lint` with Daemon Mode (#56)

**Files:**
- Modify: `src/local_ai_hub/speculative_lint.py:40-90`
- Test: `tests/unit/test_speculative_lint_daemon.py`

- [ ] **Step 1: Write test verifying `speculative_lint` executes in daemon mode**
- [ ] **Step 2: Implement fix**
Run Ruff / Biome via long-running daemon with persistent IPC pipe rather than spawning a fresh process for each line change.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(lint): run speculative linting via persistent background daemon"`

---

### Task 92: Traces Search MCP Action for Self-Debugging (#57)

**Files:**
- Modify: `src/local_ai_hub/debug_traces.py:110-150`
- Modify: `src/local_ai_hub/mcp_server.py:1680-1700`
- Test: `tests/unit/test_debug_traces_search.py`

- [ ] **Step 1: Write test querying slow traces (`duration_ms > 1000`) via MCP**
- [ ] **Step 2: Implement action**
Add `action="traces"` to `local_ai_status`. Queries `debug_traces.sqlite3` with filters for `min_duration_ms` and `action`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(telemetry): expose trace search in local_ai_status for agent self-debugging"`

---

### Task 93: Database Schema Migration Drift Detection (#59)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:6380-6430`
- Test: `tests/unit/test_migration_drift_detection.py`

- [ ] **Step 1: Write test detecting schema discrepancy between SQLite dump and model definitions**
- [ ] **Step 2: Implement drift detector**
Compare table columns in live SQLite vs SQL migration files, reporting added or missing columns.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(deterministic): detect database migration drift between live DB and migration files"`

---

### Task 94: Micro-Batching with Lock Yield in Reranker (#88)

**Files:**
- Modify: `src/local_ai_hub/reranker.py:240-280`
- Test: `tests/unit/test_reranker_micro_batching.py`

- [ ] **Step 1: Write test verifying concurrent threads can interleave inference requests**
- [ ] **Step 2: Implement fix**
Chunk reranking pairs into micro-batches of 2 pairs. Release and re-acquire `_predict_lock` between micro-batches to allow concurrent threads to proceed.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(reranker): use micro-batching with lock yield to prevent thread starvation during inference"`
