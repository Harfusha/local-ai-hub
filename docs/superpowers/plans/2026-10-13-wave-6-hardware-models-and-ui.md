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

**2026-10-15 implementation checkpoint — execution/calibration deferred.** The referenced `tokens.py` does not exist: aggregate protocol estimation is in `budget.py`, while `context_budget` used a separate character ratio and `token_economy` could silently fetch tokenizer files. Added `code_tokens` with lazy offline cl100k/o200k BPE construction from existing cache data only, validating the official SHA-256 rank-data hashes before loading. It never calls `get_encoding`, downloads, rewrites corrupt caches or changes global loader functions. Source: https://github.com/openai/tiktoken/blob/main/tiktoken_ext/openai_public.py ; cache layout: https://github.com/openai/tiktoken/blob/main/tiktoken/load.py . Missing data/package falls back to CamelCase/snake/numeric-aware source estimation, explicitly uncalibrated rather than claiming a 5% bound.

`tokcount` retains its tuple/count CLI compatibility, exposes per-encoding provenance in JSON, distinguishes estimated/mixed output and treats special-token-looking code as ordinary text. `context_budget` now uses the same named-encoding counter, checks root/path policy, bounds input to 64 files/2 MB per file/8 MB total, and marks omitted source and heuristic slice recommendations. MCP preserves provenance. The aggregate serialized-response estimator remains unchanged because its `estimated_tokens` units are an existing wire-budget contract; this source change does not silently reinterpret protocol accounting as model-exact counts.

Deferred cases forbid loading/downloading on missing or corrupt caches, preserve corrupt data, exercise path containment, and compare real installed cached tiktoken references across Python/TS/C#/Unicode/special-looking source. Missing real tokenizer data skips that reference case with an explicit NOT VERIFIED reason; a skip cannot satisfy final acceptance. No tokenizer import, tokenizer download, count benchmark or test ran now. The 5% target, estimator-only calibration, actual model-tokenizer compatibility, latency/RAM and any broader budget-consumer migration remain unverified final acceptance work.

**Files:**
- Modify: `src/local_ai_hub/tokens.py:40-80`
- Test: `tests/unit/test_calibrated_tokenizer.py`

- [x] **Step 1: Write offline safety and real-reference accuracy regression source (execution deferred)**
- [x] **Step 2: Implement offline named-BPE counts and explicit code fallback provenance (calibration pending)**
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

**2026-10-15 implementation checkpoint — execution deferred.** Successful task creation with criteria or changed paths schedules an optional prediction through the existing adaptive-context pipeline, using its normal task/tenant/session/root/config/memory/repository cache identities and freshness checks. Goal text is the predicted query, with the standard 4,000-token budget and empty phase/profile. It does not introduce a second task-memory result cache, fabricate receipts or create another task. MCP task creation forwards existing `paths` as changed paths; authenticated HTTP root/tenant are used, not a guessed checkout. `context_warmup_scheduled` only means queue admission, not a completed pack or guaranteed hit.

The lazy daemon queue has one worker/four waiting entries, deduplicates pending/active predictions, retains at most 64 recent identities, suppresses immediate repeats and drops queued work older than 30 seconds. Active operational mode is required at submit and execution. A changed/terminal task invalidates its prediction; `preprocessing.task_context_warmup=false` disables the feature. App close drops pending work and joins the worker for at most one second; an already-running adaptive computation still relies on existing bounded backend waits and application shutdown cancellation. Exact downstream request identity and unchanged source/memory state are required for cache reuse; generic first-call/L1-hit and latency claims remain pending final measurement. Deferred fake-operation cases cover queue capacity, active deduplication, close, request identity, task drift and gaming exclusion. No warmup worker, inference, test or service restart was started during source implementation.

**Files:**
- Modify: `src/local_ai_hub/services.py:4180-4220`
- Test: `tests/unit/test_predictive_cache_warmup.py`

- [x] **Step 1: Write bounded queue and scoped warmup regression source (execution deferred)**
- [x] **Step 2: Implement optional task-create prediction using existing context pipeline (validation pending)**
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

**2026-10-15 source reassessment — execution deferred.** Existing `connect_sqlite` applies a caller-bounded connection/busy timeout, closes the connection on setup failures, and intentionally avoids selecting WAL on hot-path connection creation. Existing `retry_busy` already retries only lock/busy errors, caps attempts, doubles the delay up to `max_delay_seconds` and samples jitter in `[0.5*backoff, backoff]`. `714115e3` adds the explicit optional degraded result after exhaustion; other failures still propagate immediately. A second `connect_with_retry` API would duplicate these mechanisms and would not replace operation-level write retry. The plan's `sqlite3.BusyError` spelling is not the public exception used here: Python reports lock contention through `sqlite3.OperationalError` and SQLite error codes handled by `is_busy_error`.

Added deferred cases for exact capped jitter ranges/attempt count, no retry on non-busy errors, and real two-connection writer contention in a `tmp_path` database, releasing the first writer between attempts. No SQLite test or contention workload was executed during this assessment. Whole-Hub lock behavior, latency and concurrent runtime acceptance remain final validation work.

**Files:**
- Modify: `src/local_ai_hub/sqlite_support.py:70-110`
- Test: `tests/unit/test_sqlite_dynamic_retry.py`

- [x] **Step 1: Write bounded jitter and real writer-contention regression source (execution deferred)**
- [x] **Step 2: Existing bounded connection and operation-level exponential jitter confirmed; no duplicate API**
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

**2026-10-15 integrated recovery implementation — source only; whole-bundle tests remain deferred.** Foreground and interruptible Ollama calls now share one streaming parser with complete-marker validation and partial-output tracking. Interruptible calls retain one generic attempt; a pre-output memory allocation failure may use exactly one dedicated half-context retry within the original absolute deadline, including when `request_attempts=1`. Generic retries/configuration remain unchanged. Full retained input budgeting includes tool/format/template fields; unknown multimodal token cost refuses recovery instead of guessing or dropping image/task data.

Managed llama.cpp provisioning prepares non-startup private presets using the same verified model file and half `ctx-size`. Recovery is bound to the held process generation and matching managed endpoint; external/unowned providers are unchanged. Managed generation/admission/unload operations serialize, and an OOM or provider-confirmed load failure can switch once after explicit original-model unloaded status. Unconfirmed quiescence returns `outcome_unknown`; no new model is loaded. Recovery routing persists for the warm logical model, shares consistent physical aliases, and clears on unload. Inventory retains configured ownership identity plus the actual served alias so peer handoff cannot misclassify or unload a foreign model. Shared aliases with conflicting configured contexts fail before overwriting a preset; excluded vision routes cannot redirect the text-server port. Existing startup SYCL-to-CPU fallback remains.

Service error handling now preserves partial/unknown/cleanup state and stops alternate-model/stale substitution after those failures, cancellation or an expired deadline. Reduced-context provenance survives successful responses and excludes exact, semantic and stale caching under the unreduced execution profile. Completion-contract version 2 separates all three cache scopes from legacy entries that could contain unterminated successful fragments; old cache records are retained. Deferred source cases cover actual OpenAI alias serialization using memory streams, process-generation binding, quiescence, shared aliases, cancellation/serialization, one-attempt OOM reserve, both streaming entry points, retained-input refusal, legacy cache separation and service cache/replay boundaries. No tests, compile/import checks, explicit provider starts, service restarts or benchmarks were run in this implementation phase; repository advisory calls are not runtime acceptance. Native behavior is grounded against pinned b10964 documentation: https://github.com/ggml-org/llama.cpp/blob/b10964/tools/server/README.md#model-presets . Real OOM/VRAM recovery, live concurrency, install provenance and release acceptance remain open.

**2026-10-15 native-context/stream follow-up — source only, execution deferred.** Managed llama.cpp presets now carry validated per-route `context_length` as `ctx-size`; previously request admission checked a configured window that the generated preset never applied. No live preset, configuration or process was changed. Native SSE rejects malformed/non-object events and EOF before `[DONE]` or finish reason, forwards reasoning deltas, and marks partial text/tool/thinking failures without replay. HTTP error capture is capped at 1000 bytes with remaining-deadline socket wait and owned response close. Deferred in-memory cases cover these contracts and temporary preset provenance. Upstream preset keys correspond to server arguments, while `/models/load` documents only a model name: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#model-presets . Native OOM context halving still requires a scheduler-owned reload/preset strategy; adding `num_ctx` to completion JSON would not implement it. This criterion remains open, alongside real memory/device acceptance.

**2026-10-15 Ollama-path implementation checkpoint — execution deferred.** The selected Ollama streaming attempt loop now recognizes memory-allocation errors and halves `options.num_ctx` at most once, within the original attempt count and absolute deadline. Caller payload, operator configuration and device selection are preserved. A conservative serialized-input byte budget plus generation reserve refuses recovery if the smaller context cannot retain the input; it never drops task/evidence text silently. Recovery metadata reports original/effective context and explicitly says input/device were unchanged. Generic model-load failures without memory evidence do not trigger a guessed GPU/CPU change. This implementation applies to the selected Ollama path; llama.cpp/SYCL route recovery and live OOM behavior still need separate assessment before closing the overall criterion.

Source review also found an explicit stream error could leave an earlier successful fragment in `final`, causing a false-success return. Explicit stream errors now prevent that return. Output, chat or thinking fragments prevent retries; thinking callbacks count as emitted output. Deferred in-memory provider cases cover context halving, caller-input preservation, partial-fragment failure and thinking non-replay, plus the retained-input budget refusal. No provider/model, test, build or benchmark was executed. Real VRAM recovery, actual context fit and runtime acceptance remain pending the full bundle.

**Files:**
- Modify: `src/local_ai_hub/ollama.py:220-260`
- Test: `tests/unit/test_llm_oom_fallback.py`

- [x] **Step 1: Write Ollama/native OOM, partial-stream and service-boundary regression source (execution deferred)**
- [x] **Step 2: Integrated Ollama/native recovery source; live acceptance deferred**
Catch `CUDA out of memory` / `model load failed`. Automatically reduce `num_ctx` by 50% or fall back to CPU offload.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(ollama): automatically scale context window down on VRAM OOM error"`

---

### Task 91: In-Process `speculative_lint` with Daemon Mode (#56)

**2026-10-15 service integration checkpoint — source only, tests deferred until the whole bundle.** Added lazy Ruff session pool keyed by tenant/canonical root (default four sessions), idle retirement on admission with cleanup-confirmation capacity retention, existing broker read-only classification before daemon dispatch, explicit one-shot transport for custom/other-language commands, app-close ownership and async attempt/tenant/lease-bound cancellation. Unknown daemon cleanup propagates to durable `outcome_unknown`, preceding ordinary cancellation or result acceptance. Debounce ownership now includes tenant; its metadata is bounded to 512 entries. Deferred regression source covers session reuse/isolation, capacity retained during unconfirmed retirement, unknown cleanup, admission cancellation ownership and cross-tenant debounce. No tests, imports, Ruff processes, service restarts or benchmarks were executed. Remaining acceptance: real Ruff same-process/crash/cancellation behavior, Biome/other-language daemon disposition, all integrated gates. Concurrent dashboard/docs/telemetry edits remain outside this change.

**2026-10-15 transport implementation checkpoint — integrated source; runtime acceptance open.** Speculative lint routes through a tenant/root session pool and persistent Ruff LSP transport: owned hidden process helpers, binary Content-Length frames capped at 4 MB, bounded generation-owned response/write queues, continuously drained stderr, bounded lock/write/read waits with cancellation, initialize/pull diagnostics and versioned didOpen/didChange documents capped at 64. Workspace edit requests are refused; no code-action/format/fix request is sent. On failure the generation is detached and its held process handle is reaped; a new process is blocked while cleanup is pending or unconfirmed. Close prevents respawn. Source snapshots cap at 2 MB per file/8 MB per request and diagnostics at 512. Protocol background I/O is a transport helper, not an extra Hub service.

Deferred framing cases cover multiple Unicode messages, short reads and invalid/oversized headers/frames, with no child process. Ruff server/pull-diagnostics capability is documented by https://docs.astral.sh/ruff/editors/features/ and its native server implementation. The transport has not been imported or started. Remaining required work: tenant/root session pool, broker policy and feature routing, cancellation hookup, bounded pool lifecycle, same-process reuse and crash/timeout receipts, real installed Ruff capability acceptance, and Biome/other-language disposition. T91 remains open; a protocol helper alone does not satisfy daemon-mode execution. Concurrent dirty edits to `telemetry.py` and `tests/test_telemetry_contract.py` were observed during this slice and preserved outside its commit.

**Files:**
- Modify: `src/local_ai_hub/speculative_lint.py:40-90`
- Test: `tests/unit/test_speculative_lint_daemon.py`

- [x] **Step 1: Write tests for framing, session reuse/isolation, cleanup, cancellation ownership, and Biome routing**
- [x] **Step 2: Implement daemon integration**
Ruff uses persistent LSP sessions. Biome uses the owned foreground provider contract when daemon mode is enabled; disabled mode uses explicit read-only one-shot `ci`. Custom commands and other-language tools remain one-shot after broker policy checks. Source and fake-provider regressions are present; real installed-tool acceptance remains open.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(lint): run speculative linting via persistent background daemon"`

---

### Task 92: Traces Search MCP Action for Self-Debugging (#57)

**2026-10-15 source assessment and SDK parity — execution deferred.** Existing `DebugTraceStore.list` already applies parameterized exact action and minimum-duration filters; existing `local_ai_status(action="traces")` reaches the trace endpoint behind the HTTP `trace.read` authorization gate. Completed `HubClient.status(detail="traces", min_duration_ms=..., trace_action=...)` parity and reused it from MCP without a health request. Client/MCP filters reject booleans, non-integers, negative/over-day duration and over-64-character action; HTTP malformed/out-of-range trace filters now return explicit 400 instead of silently widening the query. Deferred SDK source cases cover encoded filters and pre-transport rejection, alongside existing temporary SQLite and MCP cases. No test/import/server request executed. Source behavior is implemented; integrated authorization/filter/transport acceptance remains pending with the whole-bundle gate.

**Files:**
- Modify: `src/local_ai_hub/debug_traces.py:110-150`
- Modify: `src/local_ai_hub/mcp_server.py:1680-1700`
- Test: `tests/unit/test_debug_traces_search.py`

- [x] **Step 1: Write tests for duration/action filtering through store, SDK, and MCP**
- [x] **Step 2: Implement action**
Add `action="traces"` to `local_ai_status`. Queries `debug_traces.sqlite3` with filters for `min_duration_ms` and `action`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(telemetry): expose trace search in local_ai_status for agent self-debugging"`

---

### Task 93: Database Schema Migration Drift Detection (#59)

**2026-10-15 source reassessment/fixes — bundle execution deferred.** Existing detector already opens only an in-root live SQLite DB with `mode=ro`, scans bounded migration files and replays supported CREATE/ALTER/DROP table DDL into `:memory:` with a deadline/page cap. Fixed generated-column omission using `table_xinfo` on both sides, ASCII-only SQLite identifier normalization (retaining distinct Unicode names), sorted missing/extra column outputs, and bounded migration value/statement length plus replay metadata table/column/time limits. Added deferred temporary-DB cases for generated columns, ASCII/Unicode identifier behavior, ALTER rename/drop/add sequence, deterministic ordering and unchanged live DB bytes. No database was opened and no test/import executed during implementation. Required source comparison is present; final integrated temporary-DB/route/Windows acceptance remains open. Type/default/constraint equality is outside the original table/column drift criterion and is not implied by `type_mismatches={}`.

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:6380-6430`
- Test: `tests/unit/test_migration_drift_detection.py`

- [x] **Step 1: Write temporary-DB drift tests including generated columns and migration ordering**
- [x] **Step 2: Implement bounded drift detector**
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
