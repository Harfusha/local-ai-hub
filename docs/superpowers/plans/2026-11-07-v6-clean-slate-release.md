# v6.0.0 Clean Slate Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Overview

Transition Local AI Hub to version 6.0.0 with a clean-slate runtime state architecture:
1. Bump version to `6.0.0` across metadata (`__init__.py`, `pyproject.toml`, `RELEASE.json`, `CHANGELOG.md`).
2. Implement automatic startup state wiping in `src/local_ai_hub/state_lifecycle.py` and `src/local_ai_hub/app.py` when `state_version != 6`.
3. Provide safe clean-state mechanisms without requiring manual deletion of complex SQLite directories.
4. User constraint: Do NOT delete `state/` or restart the running hub service in this stage until explicitly instructed by the operator.

## Architecture

- **State Versioning**: `state_version.json` tracked in `state_dir` with schema `{"version": 6, "clean_slate_wiped": bool, ...}`.
- **Auto-Wipe**: When `state_dir` contains pre-v6 state (or no `state_version.json`), the startup hook purges disposable caches, indexes, traces, and stale lockfiles, writing version 6 marker.
- **Service Continuity**: Active service process remains unmolested until operator triggers manual restart/rebuild.

## Tasks

- [x] Create `src/local_ai_hub/state_lifecycle.py` with `ensure_state_version`, `read_state_version`, and `wipe_disposable_state`.
- [x] Create unit tests in `tests/test_state_lifecycle.py` verifying fresh init, v6 preservation, and upgrade auto-wipe.
- [x] Hook `ensure_state_version(state_dir)` into `LocalAIApp.__init__` in `src/local_ai_hub/app.py`.
- [x] Bump version to `6.0.0` in `src/local_ai_hub/__init__.py`, `pyproject.toml`, `RELEASE.json`, and `CHANGELOG.md`.
- [ ] Verify test suite and release check consistency.
- [ ] Checkpoint Agent OS task `task_f18fe113e02c`.
- [ ] Report ready status to operator without restarting service or deleting current live data.
