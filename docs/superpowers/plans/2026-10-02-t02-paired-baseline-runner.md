# T02 Paired Matrix Preparation Implementation Plan

> **For agentic workers:** Execute inline in the existing T02 worktree. Do not start benchmark measurements before T20 supplies immutable source pins and a CPU slot.

**Goal:** Prepare reproducible paired baseline/candidate receipts for all six existing T02 size cases, including the four missing cases.

**Architecture:** Keep `run_benchmark_matrix` as the only measurement engine. Add a case/pin manifest and a small coordinator that validates immutable source and synthetic input identities, runs the same six-case matrix with isolated state/scratch for each side, then validates paired receipts and quality gates.

**Tech Stack:** Python, JSON, existing `tools/benchmark_surfaces.py`, pytest.

**Spec:** Approved bounded design in this task on 2026-10-02; existing acceptance source is `docs/superpowers/plans/2026-09-22-hub-quality-performance-master-plan.md`.

## Global Constraints

- Work only in `C:\Users\Adam\.codex\worktrees\hub-audit-repairs\.local-ai-hub`.
- Preserve inherited dirty files and their ownership.
- Do not edit root or `/api/context/pack`.
- Define cases `(100,10000)`, `(100,100000)`, `(10000,10000)`, `(10000,100000)`, `(100000,10000)`, `(100000,100000)`.
- Do not measure until T20 supplies immutable baseline/candidate source pins and explicit CPU-slot assignment.
- Use 1000 light samples, 30 paired comparison samples, concurrency `1/4/16/32`.
- Keep cold and warm epochs disjoint and independently proven.
- Keep `plan_grade=false` until six valid paired case receipts and all required quality gates exist.
- Apply 10% maximum paired p95/p99 regression cap; missing semantic or model quality remains `NOT_ESTABLISHED`.

## Review Focus

- Runner refuses missing, mutable, or mismatched source/input pins.
- Baseline and candidate use identical generator version, seed, case parameters, and fixture fingerprints.
- State and scratch paths cannot overlap between source sides or regimes.
- Quality failures and incomplete cases cannot be promoted to passing or plan-grade.
- Preparation and tests do not launch benchmark subprocesses.

## Tasks

1. Add failing tests for the six-case manifest, four deferred cases, required parameters, and pending source pins.
2. Add a versioned JSON case manifest with exact dimensions, deterministic input identity fields, acceptance limits, and pin placeholders.
3. Add failing tests for runner pin validation, paired receipt matching, cold/warm separation, quality limits, and no benchmark launch in prepare mode.
4. Implement a small coordinator over the existing six-case matrix engine. Keep measurement disabled while pins or slot assignment are absent.
5. Add focused tests for source/input digest stability, per-side state/scratch isolation, and refusal of incomplete `plan_grade` claims.
6. Run only bounded manifest/runner contract selectors. Save exact outputs and hashes in a new T02 handoff receipt; then request T20 pins and CPU slot.
