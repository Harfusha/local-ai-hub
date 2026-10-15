# Wave 6 Implementation Plan: Hardware, Models & Multimodal UI

> **Governing workflow:** Follow [Simplified Worktree and Integration Process](../specs/2026-10-07-simplified-worktree-integration.md). The primary agent implements, reviews, and integrates on current `master`. Subagents and isolated worktrees are optional for independent implementation with disjoint scope; audits and routine work remain with the primary agent. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide browser headless UI inspection, local visual diffing via Qwen-VL, non-blocking GPU telemetry, and VRAM lifecycle management.

**Architecture:** Modifies `browser_bridge.py`, `frontend_review.py`, `vram_balancer.py`, `ollama.py`, `commands.py`, `tokens.py`, `services.py`, `sqlite_support.py`, `debug_traces.py`, `deterministic.py`, `reranker.py`, and `mcp_server.py`. Exposes CDP DOM snapshotting, ephemeral mock server binding, idle model unloading, and calibrated token estimation.

**Tech Stack:** Python 3.11, CDP / Chrome Headless, Qwen-VL, Pytest.

---

### Task 79: Expose `browser_bridge` Headless Inspection in MCP (#41)

**2026-10-15 integrated source checkpoint — primary owner: Codex.** Commit `6ce835de` exposes `local_ai_task(action="browser", url=...)` through `/api/task/browser` in the shared HTTP daemon. The generated schema comes from `operation_contracts.py`; the old `mcp/local-ai/local_ai_task.json` file hint does not exist. Capture uses a bounded loopback-only proxy, two process slots, managed Windows process-tree cleanup, isolated profiles, bounded DOM/PNG output, and tenant-scoped atomic DOM/screenshot artifacts. Existing dirty T74–T78 work was preserved through selective staging.

Validation on current integrated source with the preserved dirty overlay: `python -m pytest tests/unit/test_mcp_browser_bridge.py tests/unit/test_browser_headless_capture.py tests/test_mcp_agent_routing.py tests/test_browser_artifact_atomicity.py -q --tb=short` — **89 passed**, including the opt-in installed-Chrome test with `LOCAL_AI_BROWSER_RUNTIME_TEST=1` and `LOCAL_AI_CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe`. Final narrower rerun after the accounting/cleanup edit: the two unit files — **14 passed**, same runtime environment, broker request `req_6420fc406304`. The installed Chrome test confirms actual DOM/PNG creation, blocked external subresource, artifact retrieval, and scratch cleanup using only temporary state. This proves the capture component, not deployment of a new shared daemon or final HTTP/MCP installed-runtime acceptance.

**Remaining acceptance:** the historical T18 route-inventory tests still report source/fixture drift (including `post_repo_secret_scan_1`) outside this feature. Reconcile these under API coverage rather than relabeling the immutable preimage. Full release acceptance remains open; the source index returned zero callers for the new helper despite its explicit HTTP call, so that index result is not completeness evidence.

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:2330-2360`
- Modify: `src/local_ai_hub/operation_contracts.py` (generated MCP schema source)
- Modify: `src/local_ai_hub/browser_bridge.py`
- Modify: `src/local_ai_hub/http_server.py`, `src/local_ai_hub/http_route_registry.py`
- Test: `tests/unit/test_mcp_browser_bridge.py`
- Test: `tests/unit/test_browser_headless_capture.py`

- [x] **Step 1: Write test verifying `local_ai_task(action="browser", url="http://localhost:3000")` calls `browser_bridge`**

```python
# tests/unit/test_mcp_browser_bridge.py
def test_mcp_browser_bridge_action(monkeypatch):
    class DummyBrowser:
        def capture(self, url, **kwargs):
            return {"success": True, "title": "Test Page", "dom_snapshot": "<html>...</html>"}
    monkeypatch.setattr("local_ai_hub.browser_bridge.BrowserBridge", lambda *a: DummyBrowser())
```

- [x] **Step 2: Implement fix**
Expose `local_ai_task(action="browser")` and connect to `BrowserBridge.capture_page()` through the shared HTTP daemon so adapters do not create separate browser capacity pools. Return DOM and PNG artifact references with bounded previews.
- [x] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(mcp): expose browser_bridge DOM snapshot and screenshot in local_ai_task"`

---

### Task 80: Local Visual Diffing via Qwen-VL (#42)

**2026-10-15 source integration — `88510fd8`.** `compare_screens` accepts the two PNG payloads and an explicitly injected existing vision runner; the shared `VisionService` resolves tenant-scoped baseline/candidate artifacts, invokes it, and reuses the existing model capability, cancellation, timeout, structured-output and availability handling. MCP accepts `baseline_screenshot_artifact_id` alongside `screenshot_artifact_id`. PNG chunks/CRC, byte limits, equal dimensions and a 16-megapixel limit are checked before inference. Both screenshots are untrusted evidence. Comparison hashes/byte equality are distinct from model findings. Cloud fallback is rejected. INSTALL/UPDATE prompts are synchronized.

Validation: `python -m pytest tests/unit/test_frontend_visual_diff.py tests/test_frontend_review.py tests/test_vision_service.py tests/test_vision_service_orchestration.py tests/test_vision_service_phases.py tests/test_mcp_agent_routing.py -q --tb=short` — **169 passed**, request `req_a1d2fe1f3a2e`, execution `78ef29ae753e41deb843b34ddf798041`. Provider responses are stubbed in this suite: live Qwen-VL comparison quality and deployed MCP acceptance remain required. Current installed feature configuration disables vision in the generated MCP action enum; direct adapter tests enable features only within their fixture and are not deployed-wire proof. The bounded status response reported Ollama online but returned no installed-model inventory, so model availability remains unknown. Indexed review refused the 11-segment diff under its 8-segment limit (`req_c840e2876097`); primary specification/quality review was performed directly.

**Files:**
- Modify: `src/local_ai_hub/frontend_review.py:280-340`
- Test: `tests/unit/test_frontend_visual_diff.py`

- [x] **Step 1: Write test comparing baseline vs candidate screenshots**
- [x] **Step 2: Implement visual diff**
Implement `compare_screens(baseline_png, current_png, *, review)` in `frontend_review.py`, injecting the existing local vision service rather than constructing another runtime. Uses the configured vision model to detect visual shifts.
- [x] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(vision): implement local visual regression diffing via Qwen-VL"`

---

### Task 81: Ephemeral Port Bind for `mock_server` (#43, #45)

**2026-10-15 source integration — `5d339a2c`.** Broker, service, HTTP, SDK client and MCP start defaults now preserve zero and request an ephemeral loopback port. The actual bound port is returned and used as the registry/status/stop key; explicit fixed ports remain supported. Cassette recording applies the existing safe response-header allowlist before writing, excluding Authorization/Cookie/Set-Cookie. INSTALL/UPDATE prompts document the new default and retaining the returned port.

Validation: `python -m pytest tests/unit/test_mock_server_ephemeral_port.py tests/test_mcp_command_operation_acceptance.py::test_mcp_command_mock_server_start_uses_dedicated_endpoint_and_port -q --tb=short -r f` — **10 passed**, request `req_bfb22493bdbf`, execution `1f9c18fa5ae6409c8656bc6f862b268f`. Includes two actual loopback listeners (omitted and zero port), HTTP requests, status/stop and joined worker threads. The network-safety regression selection also exited 0 (`req_faba54bdb42c`); its compact output omitted the final count and reports platform capability skips, so no complete platform claim follows. A broader command-operation file also exposed unrelated `auto_fix` payload expectation drift (`req_dde793adb03e`); the exact fixture was subsequently reconciled with the existing `runs=5` and empty `env` transport defaults (no production behavior change). The full command-operation file then passed all 13 cases, request `req_7011527eea53`; this specific drift is resolved.

**Files:**
- Modify: `src/local_ai_hub/commands.py:10100-10150`
- Test: `tests/unit/test_mock_server_ephemeral_port.py`

- [x] **Step 1: Write test binding mock server on port=0 and verifying assigned port is returned**
- [x] **Step 2: Implement fix**
When `port` is 0 or omitted, bind socket to port 0 (`sock.bind(('127.0.0.1', 0))`) and return assigned ephemeral port. Sanitize `Authorization` and `Cookie` headers during `record_mock`.
- [x] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(mock): support ephemeral port binding and header sanitization in mock server"`

---

### Task 82: Non-Blocking GPU Telemetry in `VRAMBalancer` (#53, #97)

**2026-10-15 reassessment and source integration — `5cf40494`.** The prior implementation launched a background probe but still waited up to three seconds in ordinary `status()`. It did not meet the nonblocking criterion. Ordinary status now returns fresh cache immediately or a conservative explicitly stale snapshot while one background sampler runs. Refresh is request-driven; no permanent polling thread is introduced. Explicit `status(force=True)` and `sample_vram()` preserve bounded fresh sampling for benchmarks. Thread-start failure clears the single-flight flag and reports its actual cause without falsely claiming a wait timeout. Existing pressure tests now explicitly request fresh sampling; they retain their pressure assertions. INSTALL/UPDATE prompts are synchronized.

Validation: `python -m pytest tests/unit/test_vram_balancer_non_blocking.py tests/test_vram_balancer.py tests/test_model_policy_repetition.py tests/test_sqlite_resilience.py -q --tb=short` — **33 passed**, request `req_9fa4200641a2`, execution `9752c5ccbc5f46879961b682edf79efd`. A blocked probe stays blocked while ordinary status returns; eleven calls share one probe. Forced sampling, pressure thresholds, pin updates, timeout fallback, fresh-cache reuse and sampler-start failure are covered. This proves the non-waiting contract; the plan's sub-0.1-ms live latency target remains unmeasured. Indexed review degraded because its generated response exceeded the requested budget; no successful local-review claim follows. Primary specification and code-quality review was performed directly.

**Files:**
- Modify: `src/local_ai_hub/vram_balancer.py:50-95`
- Test: `tests/unit/test_vram_balancer_non_blocking.py`

- [x] **Step 1: Write test verifying `vram_balancer.status()` returns immediately without waiting for `nvidia-smi`**
- [x] **Step 2: Implement fix**
Use one request-driven background sampler with cached ordinary status; preserve an explicit bounded fresh-sampling API. Measure the separate <0.1 ms latency target at the runtime acceptance gate.
- [x] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(vram): make GPU telemetry non-blocking via background sampling worker"`

---

### Task 83: Idle Unload Timer for Local Models in VRAM (#54)

**2026-10-15 implementation checkpoint — execution deferred.** The timer uses the existing affinity dispatcher, with validated `scheduler.idle_timeout_seconds=300` and explicit disable value 0. It tracks model preparation and completion of both foreground/background scheduler jobs, claims release only with no pending/inflight/switching/background-GPU reservation, and targets only the active model actually prepared or used by this scheduler. A merely observed pre-existing model is not claimed for idle release. The dispatcher reserves residency under its condition, calls `unload_model` outside that lock with a five-second absolute deadline and shutdown callback, then wakes queued arrivals. Tiered runtimes forward the same deadline/cancellation to the selected provider. The existing Ollama unload implementation sends `keep_alive=0`; backend selection remains unchanged.

Any attempted release clears scheduler affinity so the next request must prepare the model afresh, including when release is unconfirmed. Failure does not create a repeated unload loop. Metadata distinguishes `request_accepted` from `unconfirmed`; acceptance is not physical-VRAM proof. Existing operator files, provider keep_alive values and durable state are untouched; the new scheduler timer intentionally limits residency of scheduler-owned idle models independently of provider keep_alive, and operators can disable it with the new setting. Deferred cases cover threshold, busy/disabled/foreign guards, release outside the condition lock, unconfirmed-release affinity and tiered forwarding. No model unload, test, inference or service restart occurred. Runtime timing, direct-call concurrency boundaries and physical VRAM reclamation remain final gate work.

**Files:**
- Modify: `src/local_ai_hub/ollama.py:180-220`
- Test: `tests/unit/test_model_idle_unload.py`

- [x] **Step 1: Write idle ownership/threshold/release regression source (execution deferred)**
- [x] **Step 2: Implement owned idle release in existing dispatcher (validation pending)**
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

**2026-10-15 implementation checkpoint — execution deferred.** Added `guide` to the existing status action/detail contract. The result contains one compact card per enabled tool, with selector, required fields for its example action, example arguments, enabled action count and a token-use tip. Examples/requirements use the existing operation registry and feature gates; disabled tools/actions are not advertised. Guide generation is local to the MCP process and invokes neither health HTTP nor models nor any example. The cards explicitly defer other actions/optional fields to the full schema. MCP retains guide fields through projection. Both agent prompts describe the new detail.

Deferred regression source covers all eight contract-derived cards, feature exclusions, example schema validity and both MCP selector forms with HTTP calls forbidden. Nothing was executed. The planned 70% schema-token reduction remains an unverified acceptance target; `schema_token_reduction_verified=false` prevents the implementation from claiming it before a current full-wire baseline comparison. The implementation commit therefore describes compact cards without asserting the unmeasured percentage.

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:1675-1710`
- Test: `tests/unit/test_guide_cards_status.py`

- [x] **Step 1: Write contract/feature/MCP guide regression source (execution deferred)**
- [x] **Step 2: Implement local compact guide cards (validation and token target pending)**
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

**2026-10-15 implementation checkpoint — execution deferred.** Existing template matching treated literal route characters as regex syntax and ignored query rules. Added compiled matchers for escaped literal/template paths, explicit `path_regex` and `query_matchers` wildcard rules. Explicit regexes are limited to 256 characters, character classes/escapes/anchors and at most one repetition; groups, alternatives, backreferences and counted repeats fail before listener bind. Template parameters occupy whole segments. Query rules support `*`/`?`, at most 16 rules, 128-character keys/patterns, 512-character values and 64 parsed fields. Targets/path lengths are bounded; request socket I/O has a five-second timeout. PATCH and HEAD now use the same matcher, with HEAD omitting the body.

The existing `spec_path` accepts a bounded JSON mock cassette/spec `{ "routes": [{ "method": "GET", "path_regex": "^/users/[0-9]+$", "query_matchers": {"name": "Ada*"} }] }`, or OpenAPI operations with `x-local-ai-path-regex` / `x-local-ai-query-matchers`. Spec input stays under root, caps at 4 MB/256 routes and rejects malformed/empty supported-route sets before bind. This explicit matcher spec is distinct from recorded HTTP-response cassettes; it does not execute regex supplied outside the restricted grammar. Existing loopback/ephemeral listeners and synthetic unmatched responses remain. Deferred regressions cover dynamic matching, literal escaping, duplicate query values, limits and rejection before bind; no listener or test was started during implementation.

**Files:**
- Modify: `src/local_ai_hub/commands.py:10150-10190`
- Test: `tests/unit/test_mock_server_regex_matcher.py`

- [x] **Step 1: Write dynamic matcher and pre-bind rejection regression source (execution deferred)**
- [x] **Step 2: Implement bounded regex/query matching (validation pending)**
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

**2026-10-15 implementation checkpoint — execution deferred.** Added persistent `progress_percent`/`current_stage` metadata in a new `async_job_progress` table beside the exact existing durable job schema; existing job columns/records are neither altered nor rebuilt. The three-argument executor contract remains intact. `report_job_progress` uses an execution-scoped ContextVar callback bound to job ID, tenant and claimed attempt. Writes require the current running, noncancelled, unexpired job lease and matching attempt. Percent is finite, monotonic within the attempt and capped at 99 while running; only a done state with available result artifact reports 100. Stage strings are bounded to 160 characters and writes are throttled to at most four per second per callback; dropped/throttled reports return false. Callback context is reset on every executor exit. Startup/finalizing phases and actual completed batch-item fractions use this reporter. Reporting outside an executing job is a no-op.

Execution claim now uses a queued-state/attempt compare-and-set to avoid two claimants both executing the same queued attempt. Public status/wait carries progress fields through MCP projection, keeps tenant filtering, derives terminal stages from actual state, and marks unavailable optional progress storage explicitly. Existing tombstone cleanup also removes orphan progress rows. Progress does not wake terminal waits or prove a successful result. Deferred temporary-database cases cover persistence/reopen, monotonicity/throttling, foreign tenant/attempt rejection, cancellation, context reset and terminal 100%. No tests, job executors, builds or runtime migrations were run during implementation; all current-runtime adoption remains pending the whole-bundle gate.

**Files:**
- Modify: `src/local_ai_hub/async_jobs.py:100-140`
- Test: `tests/unit/test_async_jobs_progress.py`

- [x] **Step 1: Write durable scoped-progress regression source (execution deferred)**
- [x] **Step 2: Implement attempt-bound callbacks and public progress state (validation pending)**
Add `progress_percent: float` and `current_stage: str` to job state record.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(jobs): add progress percentage and stage callback to async jobs"`

---

### Task 90: Local LLM OOM Fallback & VRAM Context Scaling (#55)

**2026-10-15 Ollama-path implementation checkpoint — execution deferred.** The selected Ollama streaming attempt loop now recognizes memory-allocation errors and halves `options.num_ctx` at most once, within the original attempt count and absolute deadline. Caller payload, operator configuration and device selection are preserved. A conservative serialized-input byte budget plus generation reserve refuses recovery if the smaller context cannot retain the input; it never drops task/evidence text silently. Recovery metadata reports original/effective context and explicitly says input/device were unchanged. Generic model-load failures without memory evidence do not trigger a guessed GPU/CPU change. This implementation applies to the selected Ollama path; llama.cpp/SYCL route recovery and live OOM behavior still need separate assessment before closing the overall criterion.

Source review also found an explicit stream error could leave an earlier successful fragment in `final`, causing a false-success return. Explicit stream errors now prevent that return. Output, chat or thinking fragments prevent retries; thinking callbacks count as emitted output. Deferred in-memory provider cases cover context halving, caller-input preservation, partial-fragment failure and thinking non-replay, plus the retained-input budget refusal. No provider/model, test, build or benchmark was executed. Real VRAM recovery, actual context fit and runtime acceptance remain pending the full bundle.

**Files:**
- Modify: `src/local_ai_hub/ollama.py:220-260`
- Test: `tests/unit/test_llm_oom_fallback.py`

- [x] **Step 1: Write Ollama OOM/partial-stream regression source (execution deferred)**
- [ ] **Step 2: Ollama-path implementation present; assess selected llama.cpp route before closure**
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

**2026-10-15 source reassessment — execution deferred.** Master already contains `67a9047f`: `_rerank_uncached` sends at most two pairs to each `_predict`, which releases both the cooperative priority slot and `_predict_lock` before the next batch. Existing backend/device identity checks restart a whole logical ranking after accelerator changes rather than mixing scores. No duplicate production rewrite is needed. The existing interleaving regression substitutes a fair lock and open gate, so it cannot prove production priority behavior. Added a deferred case using the actual `CooperativePriorityGate` and `threading.Lock`, with event-controlled fake model inference: a waiting foreground request must run between background batches. Only the condition's wait method is observed to synchronize arrival; production admission logic remains intact. Neither regression was executed in this phase. Same-priority FIFO fairness, real inference latency and native backend behavior are not established by this source assessment and remain final validation concerns.

**Files:**
- Modify: `src/local_ai_hub/reranker.py:240-280`
- Test: `tests/unit/test_reranker_micro_batching.py`

- [x] **Step 1: Write interleaving regression including the real priority gate (execution deferred)**
- [x] **Step 2: Existing two-pair batching and lock release confirmed in source; no duplicate rewrite**
Chunk reranking pairs into micro-batches of 2 pairs. Release and re-acquire `_predict_lock` between micro-batches to allow concurrent threads to proceed.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(reranker): use micro-batching with lock yield to prevent thread starvation during inference"`
