# Adaptive Retrieval Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Make context retrieval combine all available repository intelligence and return the highest-quality bounded context before native discovery.

**Architecture:** Keep `/api/context/pack` stable while upgrading its service-layer retrieval to an adaptive ensemble. Deterministic/indexed and exact evidence remain authoritative; optional Serena, CodeGraphContext, RAG, and local-model ranking contribute bounded evidence and diagnostics. Harden lexical fallback separately.

**Tech Stack:** Python 3.11+, pytest, existing CodeIndex, ExternalCodeIntelligence, RAG, evidence store, process utilities, MCP prompt/schema generation.

---

### Task 1: Add failing tests for high-quality retrieval contract

**Files:**
- Modify: `tests/test_context_delivery.py`
- Modify: `tests/test_repo_tools.py`
- Modify: `tests/test_agent_consistency.py`
- Create: `tests/test_adaptive_retrieval.py`

- [ ] **Step 1: Add tests for backend fan-out and additive provenance.**

  Assert adaptive context collects deterministic, code-index, lexical, semantic, Serena, and CodeGraph candidates when enabled; one backend failure becomes a warning and does not erase successful evidence.

- [ ] **Step 2: Add tests for fusion and diversity.**

  Assert exact/symbol/graph agreement outranks a single lexical hit, duplicate path/line evidence is merged, and final selection keeps multiple relevant files under the character budget.

- [ ] **Step 3: Add tests for lexical query planning and process bounds.**

  Assert stopwords and covered compound components are not passed as standalone patterns, configured source pathspecs/excludes are present, global match cap stops collection, and timeout invokes process-tree cleanup.

- [ ] **Step 4: Run focused tests and confirm RED.**

  Run `python -m pytest -q tests/test_adaptive_retrieval.py tests/test_repo_tools.py tests/test_context_delivery.py`.
  Expected: new assertions fail because adaptive orchestration and bounded lexical planner are not implemented.

### Task 2: Introduce bounded lexical query planning and process-safe fallback

**Files:**
- Modify: `src/local_ai_hub/repo_tools.py`
- Modify: `src/local_ai_hub/process_utils.py` only if an existing helper cannot safely drain/terminate the child
- Modify: `src/local_ai_hub/defaults.toml`
- Test: `tests/test_repo_tools.py`

- [ ] **Step 1: Add high-signal lexical term planning.**

  Preserve quoted/hyphenated identifiers and exact phrases, remove generic request words, remove compound components when the compound is present, and cap terms before building argv.

- [ ] **Step 2: Add source pathspec/exclusion planning.**

  Derive bounded pathspecs from configured extensions/special filenames and exclude configured generated/vendor directories without changing public result fields.

- [ ] **Step 3: Replace whole-output `subprocess.run` grep capture.**

  Stream bounded stdout, stop at global candidate cap, drain stderr, and call `terminate_tree` on cap/timeout/error. Preserve cooldown and retryable error behavior.

- [ ] **Step 4: Run focused lexical tests and confirm GREEN.**

  Run `python -m pytest -q tests/test_repo_tools.py tests/test_adaptive_retrieval.py`.

### Task 3: Build adaptive candidate fusion in services

**Files:**
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/agent_consistency.py` if additive context quality metadata needs a typed field
- Test: `tests/test_adaptive_retrieval.py`

- [ ] **Step 1: Add a bounded retrieval candidate model/helper.**

  Normalize backend outputs into evidence records containing source, path, line range, symbol/relationship metadata, rank, score, revision, and exactness.

- [ ] **Step 2: Run independent backend retrieval with per-backend limits.**

  Always use deterministic and CodeIndex anchors; query Serena and CodeGraphContext whenever available rather than checking task wording; include preprocessor cards and RAG when configured. Catch timeout/malformed responses per backend.

- [ ] **Step 3: Fuse and deduplicate candidates.**

  Use reciprocal-rank fusion plus exact phrase/symbol match, graph proximity, changed-path match, backend agreement, and per-file diversity. Keep authoritative evidence IDs and bounded snippets.

- [ ] **Step 4: Add one bounded local-model quality pass.**

  Send only candidate metadata/snippets and evidence IDs to the local model. Accept only selected existing evidence IDs and missing-concept labels; reject invented paths/lines.

- [ ] **Step 5: Make adaptive retrieval the default context path.**

  Preserve explicit fast mode, but default `local_ai_repo(action="context")` to adaptive orchestration and expose `retrieval_sources`, `retrieval_quality`, `retrieval_warnings`, and `retrieval_iterations` additively.

- [ ] **Step 6: Run focused adaptive tests and confirm GREEN.**

  Run `python -m pytest -q tests/test_adaptive_retrieval.py tests/test_context_delivery.py tests/test_agent_consistency.py`.

### Task 4: Promote adaptive context as first repository step

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/generator.py`
- Modify: `skills/tool-orchestration/SKILL.md`
- Modify: `AGENTS.md`
- Modify: `docs/INSTALL_PROMPT.md`
- Modify: `docs/UPDATE_PROMPT.md`
- Test: `tests/test_surface_and_packaging.py`

- [ ] **Step 1: Update MCP descriptions and default mode.**

  State that context is the first repository action and orchestrates deterministic/indexed, Serena, CodeGraphContext, lexical, RAG, and bounded local-model ranking before native reads.

- [ ] **Step 2: Update generated agent guidance and skills.**

  Replace cheapest-first-only wording for context retrieval with adaptive quality-first orchestration while retaining bounded fallback and no-invention rules.

- [ ] **Step 3: Sync install/update prompts and surface tests.**

  Keep both bootstrap prompts aligned with the new first-step contract.

- [ ] **Step 4: Run prompt/schema tests and confirm GREEN.**

  Run `python -m pytest -q tests/test_surface_and_packaging.py tests/test_adaptive_retrieval.py`.

### Task 5: Full validation and review

**Files:**
- Review: all changed files above

- [ ] **Step 1: Run indexed impact/review.**

  Use `local_ai_repo(action="impact")` and `local_ai_repo(action="review_diff")` for changed paths.

- [ ] **Step 2: Run repository validation through the command broker.**

  Run `python tools/release_check.py`, `python -m compileall -q src mcp tools tests`, `python -m pytest -q`, and `python tools/selftest.py` through `local_ai_command`.

- [ ] **Step 3: Inspect diff and unrelated changes.**

  Confirm `src/local_ai_hub/scheduler.py` remains untouched and no generated state is included.

- [ ] **Step 4: Attach verification receipt and complete the task contract.**

  Record validation evidence, then call `verify_completion` and mark the coordination task complete only after all acceptance criteria pass.
