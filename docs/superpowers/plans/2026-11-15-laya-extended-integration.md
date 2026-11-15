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
