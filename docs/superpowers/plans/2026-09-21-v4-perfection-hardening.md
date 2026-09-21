# Local AI Hub 4.0 Perfection Hardening Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every remaining measurable 4.0 quality gap with a regression test, a bounded runtime probe, or an explicit terminal environment non-claim.

**Architecture:** Keep deterministic/indexed evidence authoritative. Extend public routing only where an existing feature currently drops caller input. Keep model output advisory, add no prompt/source/model payloads to telemetry, and use bounded synthetic probes for optional backends and load behavior.

**Tech Stack:** Python 3.11+, MCP routing, SQLite Agent OS, pytest, Local AI Hub command broker, bounded Ollama probes.

---

## Evidence baseline

- Final committed revision: `3b96cb88b9e0805c6a14ff2685c3f24b19d42e37`.
- Full suite: `1684 passed, 5 skipped, 6 subtests passed`; the five skips are platform/grammar-dependent.
- Focused v4 matrix: `139 passed`.
- Live status: Hub `4.0.0`, Ollama online, `qwen2.5-coder:7b`, `vram_pressure=high`, `context_budget_factor=0.5`.
- Local 7B second opinion was rejected by the semantic quality gate as `malformed_task`; it is not evidence.
- A real routing gap is visible in `src/local_ai_hub/mcp_server.py`: `local_ai_task(action="eval_suite")` forwards only `suite_name`, while `services.eval_suite()` supports caller-supplied `cases` and `model`.
- A real benchmark adapter gap is visible in `src/local_ai_hub/benchmark.py`: the non-streaming path passed unsupported `max_tokens` to `OllamaRuntime.generate()`.
- A real RAG stability gap is visible in `src/local_ai_hub/rag.py`: the publish transaction used unbounded `BEGIN IMMEDIATE` despite shared SQLite retry policy.
- A real context-routing gap is visible in `/api/agent-state/context`: focused requests defaulted to an empty fast repository query, so the response could be `complete=true` while carrying no authoritative repository evidence.

## Task 1: Preserve evaluation inputs through MCP

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:1144-1420`
- Test: `tests/test_mcp_agent_routing.py`
- Test: `tests/test_feature_surface_parity.py`

- [x] **Step 1: Add a failing forwarding test.** Reproduced the missing `cases` parameter with a red MCP routing test.
- [x] **Step 2: Add the smallest public parameter.** Added bounded `cases` forwarding and bounded `model`; no raw history.
- [x] **Step 3: Run the forwarding and action-schema tests through `local_ai_command`.** Receipt: `rcpt_e79b1e0de9eb`.
- [x] **Step 4: Run a live synthetic eval with two cases.** `qwen2.5-coder:7b`, 2/2 passed, pass rate 1.0; generated text remained advisory.

## Task 2: Bounded live model and optional-backend matrix

**Files:**
- Modify: `docs/FEATURE_AUDIT_V4.md`
- Test: `tests/test_local_model_availability.py`, `tests/test_tiered_ollama_runtime.py`, `tests/test_rag_hybrid.py`

- [x] **Step 1: Run the existing model, tier, RAG, hardware, and fallback tests through the command broker.** Focused v4 matrix: 139 passed.
- [x] **Step 2: Run bounded live benchmark/eval.** Hardware benchmark passed after adapter fix; synthetic eval passed 2/2; Hub status showed Ollama online, qwen 7B, high VRAM pressure and context factor 0.5.
- [x] **Step 3: Probe optional backends once.** Serena and CodeGraph returned healthy live backend receipts; RAG index/search succeeded after the lock fix; unavailable optional llama.cpp/OpenVINO paths remain explicit non-claims.
- [x] **Step 4: Update the feature audit so every optional capability has a measured status and an explicit non-claim when the host lacks it.** Live receipts and host-specific non-claims are recorded in `docs/FEATURE_AUDIT_V4.md`.

## Task 3: Stability and contention proof

**Files:**
- Modify only if a reproducible defect is found: `src/local_ai_hub/agent_events.py`, `src/local_ai_hub/sqlite_support.py`, `src/local_ai_hub/scheduler.py`, `src/local_ai_hub/async_jobs.py`
- Test: `tests/test_agent_state_e2e.py`, `tests/test_resource_backpressure.py`, `tests/test_async_review_sla.py`

- [x] **Step 1: Run the busy-database regression eight times and preserve the receipt.** 8/8 isolated runs passed; receipt `rcpt_5b6d30ab9c22`; no blind retry rewrite.
- [x] **Step 2: Run bounded contention/backpressure matrix.** Focused v4 matrix: 139 passed; queue/cancellation/high-pressure and async review gates passed.
- [x] **Step 3: Fix reproducible defects.** Added RAG publish retry regression (`rcpt_1c3373329ffa`) and benchmark adapter regression (`rcpt_fb1b3c4dfa7a`). The busy-db full-suite timing incident was not reproducible in isolation and remains an explicit environment timing note.

## Task 4: Unified task-context delivery and provenance

**Files:**
- Modify: `src/local_ai_hub/http_server.py`, `src/local_ai_hub/agent_context.py`, `src/local_ai_hub/mcp_server.py`
- Test: `tests/test_unified_task_context_transport.py`, `tests/test_task_context_task_integration.py`

- [x] **Step 1: Route focused task context to a task-specific repository query.** Focus and changed paths now select the full deterministic-first pack; explicit `mode=fast` remains available.
- [x] **Step 2: Preserve task checkpoint affected paths in compiled context.** Checkpoint context now includes bounded affected paths.
- [x] **Step 3: Expose bounded context provenance.** Semantic MCP responses carry `task_context_id`, etag and evidence IDs; the model-facing context includes a short receipt manifest.
- [x] **Step 4: Verify transport and model handoff.** Context transport/integration tests pass; live context compile returns current revision and evidence IDs.

## Task 5: Final audit and release proof

**Files:**
- Modify: `docs/FEATURE_AUDIT_V4.md`
- Modify: `docs/MIGRATION_3_TO_4.md` only if the public routing contract changes
- Modify: this plan

- [x] **Step 1: Run indexed impact/review/security checks after edits; queued or advisory output is not completion evidence.** Deterministic impact and focused gates are retained; queued review is not counted.
- [x] **Step 2: Run focused gates, compileall, release check, selftest, diff check, and the full pytest suite through the command broker on one final revision.** Full receipt `rcpt_4f57295eb5b3`: 1687 passed, 5 skipped, 6 subtests.
- [x] **Step 3: Verify live `/health` and `/api/agent-state/context` with a task-scoped current revision and record receipts.** Hub 4.0.0/Ollama online; context returned current repository fingerprint plus evidence IDs.
- [ ] **Step 4: Require `verify_completion` for every acceptance criterion, then mark the Agent OS task complete only after the worktree is clean.** Final receipt-gated completion is the remaining administrative step.
