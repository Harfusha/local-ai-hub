# v6.0.0 Clean Slate Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Overview

Transition Local AI Hub to version 6.0.0 with a clean-slate runtime state architecture:
1. Bump version to `6.0.0` across metadata (`__init__.py`, `pyproject.toml`, `RELEASE.json`, `CHANGELOG.md`).
2. Implement fail-closed state version enforcement in `src/local_ai_hub/state_lifecycle.py` and `src/local_ai_hub/app.py` when `state_version != 6`.
3. Preserve all runtime files; require a separately backed-up offline conversion for incompatible state.
4. User constraint: Do NOT delete current live state. Restart only after explicit operator instruction.

## Architecture

- **State Versioning**: `state_version.json` tracked in `state_dir` with schema `{"version": 6, "clean_slate_wiped": false, ...}`.
- **Mismatch Handling**: Existing state with missing, older, or newer version marker stops startup with an offline-conversion error. Runtime never deletes or rewrites existing state.
- **Service Continuity**: Active service process remains unmolested until operator triggers manual restart/rebuild.

## Tasks

- [x] Create `src/local_ai_hub/state_lifecycle.py` with `ensure_state_version`, `read_state_version`, and `wipe_disposable_state`.
- [x] Create unit tests in `tests/test_state_lifecycle.py` verifying fresh init, v6 preservation, and mismatch fail-closed with byte-for-byte preservation.
- [x] Hook `ensure_state_version(state_dir)` into `LocalAIApp.__init__` in `src/local_ai_hub/app.py`.
- [x] Bump version to `6.0.0` in `src/local_ai_hub/__init__.py`, `pyproject.toml`, `RELEASE.json`, and `CHANGELOG.md`.
- [ ] Verify test suite and release check consistency.
- [ ] Checkpoint Agent OS task `task_f18fe113e02c`.
- [ ] Report ready status to operator without restarting service or deleting current live data.

## Audit correction — 2026-11-07

The initial v6 hook used wildcard SQLite deletion and removed durable Agent OS,
workspace-memory, artifact, evidence, work-order, and fencing stores on startup.
That contradicted the source policy requiring preserved durable data and explicit
offline conversion. The runtime hook now refuses mismatches without mutation; the
old auto-wipe behavior is removed. The live state marker records that a wipe had
already occurred before this correction; no pre-wipe backup was found in the state
directory during the audit.
