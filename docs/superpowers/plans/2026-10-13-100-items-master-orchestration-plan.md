# Local AI Hub: Master Implementation Plan for 100 Ergonomics, Quality & Performance Enhancements

> **For agentic workers:** Follow the governing simplified integration process below. Execute and review bounded tasks directly; optional independent implementation agents follow the same criteria. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Local AI Hub into a rock-solid, ultra-fast, and deeply capable local engine for cloud and local coding agents by executing all 100 identified enhancements across 6 modular waves.

**Architecture:** The primary agent owns the 6 waves, implementation, review, and integration on current `master`, under the governing [simplified integration process](../specs/2026-10-07-simplified-worktree-integration.md). Optional parallel implementations require disjoint write scopes and isolation where needed. All unit state uses temporary databases. Apply TDD to behavior changes: failing regression, minimal implementation, passing targeted tests, review, then commit.

**Tech Stack:** Python 3.11+, SQLite 3 (WAL mode, custom pragmas, recursive CTEs), NumPy, tree-sitter / regex AST fallbacks, pytest, MCP (Model Context Protocol), Windows Process Job Objects.

---

## Development and Optional Subagent Protocol

> 📖 **Operational Playbook:** Detailed dispatch scripts, subagent prompts (Implementer, Spec Reviewer, Quality Reviewer), and worktree teardown routines are documented in [Subagent Dispatch Playbook](file:///c:/Users/Adam/.local-ai-hub/docs/superpowers/plans/2026-10-13-subagent-dispatch-playbook.md).

The October 7 governing process takes precedence over historical per-task worktree and mandatory reviewer-agent wording in this plan and all linked wave plans. Use the following isolation rules only when a separate implementation worker is warranted:

1. **Subagent Worktree Isolation:**
   - An independent writing subagent operates in an assigned isolated worktree (`git worktree add -b codex/<wave>-<task_id> ../wt-<task_id>`). Routine work stays on `master`.
   - Run verification commands against the worktree root.
2. **Database Isolation During Tests:**
   - Tests MUST use in-memory SQLite (`:memory:`) or isolated temporary state directories via `tmp_path` fixtures (`test_cfg["state_dir"] = str(tmp_path)`).
   - NEVER point unit tests to live databases in `c:\Users\Adam\.local-ai-hub\state\`.
3. **Two-Stage Review Process:**
   - The primary agent performs a specification review; a separate reviewer agent is optional:
     - Observable behavior and public contracts satisfy the task criteria; historical line numbers are navigation hints.
     - No extraneous edits or architectural drift.
   - The primary agent then performs a code-quality review:
     - Error handling, bounded timeouts, Windows process flags, type annotations, zero full-file rewrites.
4. **Integration Gate:**
   - Integrate each reviewed bounded change promptly after its relevant tests pass on integrated `master`. Run the full required suite at each wave/release gate. Preserve and classify every leftover before recoverable archival; no blanket stash/reset/rebase/merge.

---

## Wave Breakdown & Dependency DAG

### Integration checkpoint — 2026-10-15, master `6ce835de`

- Full local inventory: 244 branches and 106 registered worktrees; 105 worktrees clean, only the current master checkout dirty. No stashes. No worktree status errors.
- 56 branch refs are not ancestral to master. `git cherry` finds no patch-unique changes on `gemini/wave-6-task-77`, `gemini/wave-8-task-84`, `gemini/wave-9-task-87`, `gemini/wave-9-task-88`, or `gemini/wave-9-task-94`.
- The remaining 51 refs include unique patches and overlapping ancestry. In particular, tasks 100–127 form one stack ending at `gemini/wave-11-task-127`; refs are not independent implementation units.
- Preserve all refs and worktrees pending task-criterion and patch review. Ancestry or patch novelty alone does not authorize integration or deletion. No blanket merge, reset, stash, rebase, or cleanup was performed.
- T79 is committed as `6ce835de`; T74–T78 remain a dirty reviewed implementation candidate. Focused integrated regression command: `python -m pytest tests/test_agent_events.py tests/test_agent_events_fresh_init.py tests/test_agent_tasks.py tests/test_repo_tools.py tests/unit/test_agent_question_channel.py tests/unit/test_agent_question_scope.py tests/unit/test_cross_workspace_memory.py tests/unit/test_verify_completion_projection.py tests/unit/test_simulate_merge_projection.py tests/unit/test_worktree_dotgit_file.py -q --tb=short` — 86 passed, request `req_b5c8cca96a18`. This is candidate evidence, not full release acceptance.

```mermaid
graph TD
    W1["Wave 1: Reliability & Crash Killers (#1-#10, #61-#62, #71-#75, #91-#95)"]
    W2["Wave 2: Database Indices & Storage Scaling (#4, #14, #21-#25, #66-#70, #81, #84-#87, #89-#90)"]
    W3["Wave 3: Code Intelligence & AST (#11, #16, #19, #34, #38, #60, #63-#65, #80, #82-#83, #92, #96)"]
    W4["Wave 4: Execution, Commands & Testing (#13, #15, #26-#27, #29-#31, #33, #35-#37, #39, #58, #76-#78, #91)"]
    W5["Wave 5: Coordination, Memory & Worktrees (#2, #8, #20, #28, #32, #46-#50, #79, #93-#95, #98, #100)"]
    W6["Wave 6: Hardware, Models & Multimodal UI (#12, #18, #40-#45, #51-#57, #59, #88, #97)"]

    W1 --> W2
    W1 --> W4
    W2 --> W3
    W4 --> W5
    W3 --> W5
    W5 --> W6
```

---

## Wave Manifest & Document Links

Each wave is detailed in its dedicated, fully specified plan document containing exact code diffs, failing tests, and verification steps:

1. **[Wave 1: Reliability & Bottlenecks Plan](file:///C:/Users/Adam/.local-ai-hub/docs/superpowers/plans/2026-10-13-wave-1-reliability-and-bottlenecks.md)**
   - Tasks: #1, #2, #3, #5, #6, #7, #8, #9, #10, #61, #62, #71, #72, #73, #74, #75, #91, #92, #93, #94, #95.
   - Focus: Removing GIL lockups in `dead_code`, 403 errors in `skeletonize`, 66s CPU reranker timeout bypass, parameter normalizers, projection data loss fixes.
2. **[Wave 2: Performance & Storage Plan](file:///C:/Users/Adam/.local-ai-hub/docs/superpowers/plans/2026-10-13-wave-2-performance-and-storage.md)**
   - Tasks: #4, #14, #17, #21, #22, #23, #24, #25, #66, #67, #68, #69, #70, #81, #84, #85, #86, #87, #89, #90.
   - Focus: SQLite B-Tree point index on `edges` (3000x speedup), GC & auto-vacuum of 75 dead worktrees (22.8 GB -> 8 GB), `orjson` serialization, multi-slice artifact reading, batch embedding lookups.
3. **[Wave 3: Code Intelligence & AST Plan](file:///C:/Users/Adam/.local-ai-hub/docs/superpowers/plans/2026-10-13-wave-3-code-intelligence-and-ast.md)**
   - Tasks: #11, #16, #19, #34, #38, #60, #63, #64, #65, #80, #82, #83, #96, #99, #100.
   - Focus: Exposing `callees`, `implementations`, `declaration` in MCP, AST-aware regex chunker for TS/C#/Rust on Windows, symbol signatures in index, overlapping line deduplication.
4. **[Wave 4: Execution & Testing Plan](file:///C:/Users/Adam/.local-ai-hub/docs/superpowers/plans/2026-10-13-wave-4-execution-and-transactions.md)**
   - Tasks: #13, #15, #26, #27, #29, #30, #31, #33, #35, #36, #37, #39, #58, #76, #77, #78.
   - Focus: Exposing `env` in `local_ai_command`, pipe buffer deadlock protection in subprocesses, interactive `stdin` support, structured test failure summarizer, in-memory patch dry-run, git diff between arbitrary revisions.
5. **[Wave 5: Coordination & Memory Plan](file:///C:/Users/Adam/.local-ai-hub/docs/superpowers/plans/2026-10-13-wave-5-agent-coordination-and-memory.md)**
   - Tasks: #20, #28, #32, #46, #47, #48, #49, #50, #79, #98.
   - Focus: Agent-to-human question channel, lease zombie auto-reaper, CAS updates on blackboard and memory, swarm DAG support, git worktree uncommitted change detection, verification receipt markdown exporter.
6. **[Wave 6: Hardware, Models & UI Plan](file:///C:/Users/Adam/.local-ai-hub/docs/superpowers/plans/2026-10-13-wave-6-hardware-models-and-ui.md)**
   - Tasks: #12, #18, #40, #41, #42, #43, #44, #45, #51, #52, #53, #54, #55, #56, #57, #59, #88, #97.
   - Focus: Exposing `browser_bridge` headless DOM & screenshots in MCP, local visual diffing via Qwen-VL, ephemeral port binding for mock server, non-blocking GPU telemetry, calibrated code tokenizer.

---

## Global Verification & Quality Matrix

Before declaring completion of all 100 items:

```bash
# 1. Compilation
python -m compileall -q src tests tools

# 2. Strict release check
python tools/release_check.py --allow-installed

# 3. Unit & Integration test suite
python -m pytest -q

# 4. Hub selftest
python tools/selftest.py

# 5. Doctor diagnostics
python tools/doctor.py
```
