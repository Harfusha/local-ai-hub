# Local AI Hub Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining low-risk performance gaps while preserving existing incremental indexing, cache, SQLite, and concurrency behavior.

**Architecture:** Keep Python orchestration and existing storage contracts. Add optional JSON acceleration with a stdlib fallback, replace RAG's recursive directory walk with a bounded `os.scandir` walk, add embedding cache reuse at the service boundary, and provide a reproducible profiler/benchmark entry point for preprocess, index, RAG, and MCP/HTTP workloads. Do not add process pools or force native dependencies.

**Tech Stack:** Python 3.11+, SQLite WAL, `os.scandir`, `orjson`/`msgspec` optional extras, `py-spy`/`scalene` optional profilers, pytest.

---

### Task 1: Add failing tests for filesystem and JSON behavior

**Files:**
- Modify: `tests/test_rag_dedup.py`
- Modify: `tests/test_json_utils.py`
- Create: `tests/test_performance_tools.py`

- [x] Add tests proving ignored directories are not traversed, symlink directories are not followed, and eligible files are yielded once.
- [x] Add tests proving JSON codec round-trips compact output and uses stdlib fallback when optional backends are unavailable.
- [x] Add tests proving benchmark command construction stays bounded and rejects unknown stages.
- [x] Run the focused tests and confirm the new tests fail for the missing behavior.

### Task 2: Add optional JSON acceleration

**Files:**
- Modify: `src/local_ai_hub/json_utils.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_json_utils.py`

- [x] Add optional `orjson` and `msgspec` performance extras without adding either to core installation.
- [x] Use `orjson` only for compatible compact serialization; retain stdlib behavior for `indent`, custom keyword combinations, and unsupported objects.
- [x] Keep `dumps` return type `str`, preserve Unicode, sorting, `default`, and explicit pretty-print behavior.
- [x] Add a small backend introspection/benchmark helper without exposing optional imports as hard dependencies.
- [x] Run JSON tests and the serialization contract tests.

### Task 3: Replace RAG recursive walk with `os.scandir`

**Files:**
- Modify: `src/local_ai_hub/rag.py`
- Modify: `tests/test_rag_dedup.py`

- [x] Implement iterative `os.scandir` traversal with `follow_symlinks=False`.
- [x] Filter ignored directory names before pushing them onto the stack.
- [x] Use directory-entry stat data where available and preserve extension/max-size semantics.
- [x] Preserve deterministic path ordering and existing error handling.
- [x] Run RAG tests and filesystem regression tests.

### Task 4: Add embedding cache at the service boundary

**Files:**
- Modify: `src/local_ai_hub/services.py`
- Modify: `defaults.toml`
- Modify: `tests/test_rag_fragment_cache.py`
- Create: `tests/test_embedding_cache.py`

- [x] Create a bounded L1/L2 cache namespace for embeddings, keyed by backend, model, query flag, and exact text content.
- [x] Cache only successful vectors; preserve batch ordering and partial cache misses.
- [x] Keep cache disabled/configurable through the existing `[cache]` settings.
- [x] Ensure cache payloads stay bounded and do not cross tenant/workspace privacy boundaries unnecessarily.
- [x] Add tests for hit reuse, model/backend/query key separation, and mixed hit/miss batches.

### Task 5: Add reproducible performance probes

**Files:**
- Create: `tools/performance_probe.py`
- Create: `tests/test_performance_probe.py`
- Modify: `docs/TESTING.md`

- [x] Add stages `preprocess`, `index`, `rag`, and `mcp`/`http` with bounded duration, iteration, and payload arguments.
- [x] Report bounded wall-time statistics (min/mean/P50/P95/P99/max); `py-spy`/`scalene` provide CPU/memory detail without persisting source text or prompts.
- [x] Detect `py-spy`/`scalene` availability and print exact wrapper commands rather than installing packages automatically.
- [x] Ensure probe failures are explicit and never silently claim a performance improvement.
- [x] Document representative commands and acceptance threshold: at least 15–20% end-to-end improvement before enabling an optimization by default.

### Task 6: Verify, review, and stop

**Files:**
- No production files beyond prior tasks.

- [x] Run focused tests, then the full test suite through the command broker.
- [x] Run compile and self-test checks required by the repository guide.
- [ ] Release check remains blocked by pre-existing runtime/generated directories (`state/`, `tool-envs/`, `generated/`) outside this change.
- [x] Review the diff, confirm existing `rag.py` and `tests/test_rag_dedup.py` user changes remain intact, and run the security audit.
- [x] Report measured results separately from unmeasured assumptions.

### Task 7: Keep native-code experiments isolated

**Files:**
- Create: `experiments/cython_simhash_votes.pyx`
- Create: `tools/cython_experiment.py`
- Create: `tests/test_cython_experiment.py`

- [x] Add a temporary Cython benchmark for the narrow SimHash voting kernel.
- [x] Validate native output against the Python result before measuring speed.
- [x] Keep the experiment disabled in production; require a working C compiler and an end-to-end gain before integration.
