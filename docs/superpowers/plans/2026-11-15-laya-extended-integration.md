# Laya Extended Integration: Ad-hoc Capture & Additional Decision Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Overview
Expand Laya shadow capture and decision surface across Local AI Hub:
1. Support ad-hoc session capture when no formal Agent OS `task_id` is passed, avoiding `task_scope_unavailable` skips.
2. Register deterministic runtime baselines for `redundant_step` (`command_broker_dedup`) and `next_step` (`pipeline_step_progress`).
3. Connect automatic shadow observation hooks for `watchdog`, `redundant_step`, `next_step`, and ensure `delegation` fires on ad-hoc pipeline execution.
4. Verify complete test suite with zero regressions.

## Proposed Changes

### `src/local_ai_hub/laya_candidates.py`
- Add `_AdhocTask` support in `_find_task` for task IDs prefixed with `adhoc_`.
- Add `DecisionCategory.REDUNDANT_STEP: "command_broker_dedup"` and `DecisionCategory.NEXT_STEP: "pipeline_step_progress"` to `_RUNTIME_BASELINE_METHODS`.

### `src/local_ai_hub/services.py`
- In `_queue_laya_shadow_observation`, fallback to `adhoc_<session_id>` if `task_id` is empty and extract evidence IDs from `result["evidence"]` when omitted.
- Register `command_broker_dedup` and `pipeline_step_progress` in expected baseline methods.
- Add helper `_queue_laya_redundant_step_observation` and `_queue_laya_next_step_observation`.

### `src/local_ai_hub/app.py`
- Register `command_broker_dedup` and `pipeline_step_progress` in `_derive_laya_decision_baseline` and `queue_laya_decision_observation`.
- In `_watchdog_loop`, add periodic evaluation of active tasks against `derive_watchdog_lifecycle_baseline`.

### `src/local_ai_hub/pipeline.py`
- Wire `_queue_laya_next_step_shadow` and `_queue_laya_redundant_step_shadow`.

## Tasks

- [ ] Task 1: Ad-hoc session fallback in `laya_candidates.py` & `services.py`
- [ ] Task 2: Register baselines for `redundant_step` and `next_step`
- [ ] Task 3: Automatic hook for `watchdog` in `app.py`
- [ ] Task 4: Automatic hooks for `redundant_step` and `next_step` in `pipeline.py` / `services.py`
- [ ] Task 5: End-to-end test verification and live capture test

## Stop handoff — verified state (2026-11-17)

Implementation stopped at the operator's request. The goal is paused, not complete.

### Requirements to preserve

- Use the pinned **local Laya model**, never a remote Laya API or cloud fallback.
- Cloud agents may send bounded input/options and receive a typed Laya proposal plus deterministic baseline.
- Keep Laya shadow-only. Hub authorization, receipts, task lifecycle and execution remain deterministic.
- Capture authentic, redacted examples with verified repository/task/session/evidence provenance and outcomes across useful decision hooks, including Agent OS tasks.
- Restore local-model enrichment of preprocessing cards.
- No synthetic inference/labels, model pulls, training, export, or promotion.

See the active requirements in `../specs/2026-11-10-laya-active-decision-service-training-capture.md` and annotation policy in `../agent-evaluation/laya-annotation-protocol.md`.

### Completed and verified in the stopped run

- `src/local_ai_hub/preprocess.py`: CPU selector gained `rebalance`; only worker 0 rebalances. Other CPU workers avoid redundant writer-actor waits.
- `tests/test_preprocess_fair_scheduler.py`: regression covers blocked rebalance, non-blocking CPU selection, and the existing GPU serialization.
- `python -m pytest tests/test_preprocess_fair_scheduler.py -q`: **39 passed**.
- Hub restart returned `restarted`; subsequent status showed Hub and Ollama online.
- Do not assume the running installation loaded this exact source revision.

### Runtime evidence and blocker

Last status after one minute idle: target project `C:\Users\Adam\.local-ai-hub` was waiting in `rag` for a preprocessing slot (limit 9); `file_cards=1634`, `pending_file_card_enrichment=1537`, `failed_file_card_enrichment=0`, overall progress 56.8%, embeddings 1513/2261, progress age 1475.1s. No movement was observed in the idle interval. `scheduler_background_allowed=false`.

The mode remained `active`, revision 94. Switching to `preprocessing` repeatedly returned retryable HTTP 423 `inference_active` (request IDs `req_5ea641ac81db`, `req_f9076796334a`, `req_98361076c233`). Scheduler status later showed queue=0, inflight=0, foreground_inflight=0, but the mode guard still rejected the change. Source in `src/local_ai_hub/http_server.py` checks active inference admissions, resource release, transcriptions, and conversations. Available diagnostics did not identify which counter remained active. GPU reservation status was `free`.

Before restart, candidate listing showed 5 pending examples while dashboard `candidates_count=0`. This mismatch was not resolved; candidate count was not refreshed after restart. Live Laya local-model inference and post-restart card enrichment were not verified.

### Approved releases attempted

No lease mutation succeeded. Hub rejected exact release attempts because the lease was missing/changed, owner absence was not confirmed, or scheduler lease conditions did not match:

- PID 22472 — `13fbffb10c6c4473afe229e4c1cdb349`, generation `e8ea6fd8befb450cac791f563e493af0`.
- PID 53208 — `26a6fd7fec1844929bd89189eea35171`, generation `6213bab636b140989e9ae09841108b24`.
- PID 54644 — `e26d91d7f2174bf4a9f9e8738036a7dc`, generation `48e60391a4854ca3b1e8f48a53167f33`.
- Scheduler job 8 — `69e0e907710e4e23821abc0448cd350c`, generation `7eb04f597bb646ce9c4c49fbf1dfc345`.

The separately authorized operator release-marker action also made no mutation (`no valid current GPU reservation could be released`). No lease files were manually edited or removed. A local semantic review ended with an unknown outcome after transport failure; later scheduler status showed no pending job and three cancelled pending requests, but that review is not evidence.

### Remaining work, in order

1. Use a supported read-only diagnostic to identify the exact active inference/resource-release/transcription/conversation admission preventing preprocessing mode. Do not clear internal registries, terminate unknown processes, or release new/changed leases without exact supported identity.
2. After the guard reports drained, set preprocessing mode and verify its readiness/revision. Then verify target project progress in separated status snapshots without unnecessary foreground traffic; confirm RAG advances and enriched-card count rises while pending count falls.
3. Call read-only Laya `runtime_status`; verify pinned local checkpoint configuration and runtime availability without loading or downloading. Only run real, shadow inference through the local model if the configured quality and resource gates allow it.
4. Verify the decision surface returns proposal + deterministic baseline, preserves evidence/task/session provenance and redaction, abstains safely, and cannot authorize actions. Reconcile candidate listing with dashboard counts.
5. Verify authentic capture and outcome labels separately for decision endpoint, Agent OS task start/checkpoint/completion, watchdog, delegation/review, context/model routing, redundant work/next step, and card enrichment. Do not claim the integration is universal until each path is checked.
6. Reconcile the five tasks above with current code before implementation. This plan still lists all five unchecked; existing dirty changes may already cover some of them.
7. Run relevant capture/provenance and card-enrichment tests after resuming. The full suite was not run; do not run it without explicit request.

### Ownership and workspace

- Agent OS task: `task_20b8dc923812`; session: `01a1e4f9-274a-7b12-bf39-d1597f584f85`; Agent OS plan: `plan_5edb272644b5`.
- Last task checkpoint: `cpu_selector_fix_runtime_blocked`. User paused the goal; do not resume automatically.
- Before this handoff edit, Hub Git status showed 14 modified paths and untracked `.ownership/`. After the edit, status showed 15 modified paths (including this plan) and untracked `.ownership/` plus `docs/PREPROCESSING_REPAIR_HANDOFF_2026-11-17.md`; that latter file appeared during work and was not inspected or edited. Dirty paths include `preprocess.py`, `preprocess_write_actor.py`, `app.py`, `generator.py`, Laya/preprocess tests, plan files, and agent instructions. Preserve all existing work: no reset, stash, clean, or broad checkout.
- This handoff records verified results and gaps; it does not mark the feature complete or imply runtime acceptance.

