# Wave 5 Implementation Plan: Agent Coordination & Memory

> **Governing workflow:** Follow [Simplified Worktree and Integration Process](../specs/2026-10-07-simplified-worktree-integration.md). The primary agent implements, reviews, and integrates on current `master`. Subagents and isolated worktrees are optional for independent implementation with disjoint scope; audits and routine work remain with the primary agent. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide rock-solid multi-agent execution, prevent race conditions in blackboard/memory, support Swarm DAG workflows, and protect git worktree integrity.

**Architecture:** Modifies `agent_blackboard.py`, `agent_memory.py`, `leases.py`, `swarm.py`, `worktrees.py`, `process_utils.py`, `projection.py`, and `mcp_server.py`. Adds optimistic concurrency (ETag/version CAS), automated zombie lease reaping, and pre-switch git status validation.

**Tech Stack:** Python 3.11, SQLite 3, Git Worktrees, Pytest.

---

### Task 69: Compare-And-Swap (CAS) on Blackboard & Memory (#32, #48)

**Files:**
- Modify: `src/local_ai_hub/agent_blackboard.py:120-160`
- Modify: `src/local_ai_hub/agent_memory.py:200-240`
- Test: `tests/unit/test_cas_blackboard_and_memory.py`

- [ ] **Step 1: Write test verifying update fails with conflict if version doesn't match**

```python
# tests/unit/test_cas_blackboard_and_memory.py
from local_ai_hub.agent_blackboard import BlackboardStore

def test_blackboard_cas_conflict(tmp_path):
    board = BlackboardStore({"state_dir": str(tmp_path)})
    board.update("b1", "sec1", {"val": 1})
    current = board.get("b1", "sec1")
    etag = current.get("etag")
    board.update("b1", "sec1", {"val": 2})
    res = board.update("b1", "sec1", {"val": 3}, expected_etag=etag)
    assert res.get("success") is False
    assert res.get("conflict") is True
```

- [ ] **Step 2: Implement CAS logic**
In `agent_blackboard.py` and `agent_memory.py`, add `expected_etag` or `expected_version` parameter to updates:
`UPDATE ... WHERE id=? AND version=?`. Return `conflict: True` when 0 rows updated.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(coord): implement atomic Compare-And-Swap (CAS) on blackboard and agent memory"`

---

### Task 70: Zombie Lease Reaper (#28)

**Files:**
- Modify: `src/local_ai_hub/leases.py:150-190`
- Test: `tests/unit/test_zombie_lease_reaper.py`

- [ ] **Step 1: Write test verifying expired leases are automatically freed**
- [ ] **Step 2: Implement fix**
Add automated background prune or lazy reaping during `acquire_lease()`:
`DELETE FROM leases WHERE expires_at < ?`. Return cleared lease metrics in status.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(leases): automatically reap expired zombie file locks"`

---

### Task 71: Uncommitted Changes Guard Before Worktree Switching (#79)

**Files:**
- Modify: `src/local_ai_hub/worktrees.py:80-120`
- Modify: `src/local_ai_hub/process_utils.py:1750-1790`
- Test: `tests/unit/test_worktree_uncommitted_guard.py`

- [ ] **Step 1: Write test verifying switching or removing a dirty worktree errors out before data loss**
- [ ] **Step 2: Implement fix**
1. Run `git status --porcelain` before worktree removal or branch switch.
2. If modified files exist, return `error: "uncommitted_changes_in_worktree"` and abort unless `force=True`.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(worktrees): guard against deleting or switching worktrees with uncommitted changes"`

---

### Task 72: Swarm DAG Execution & Auto-Rollback on Failure (#46, #47)

**Files:**
- Modify: `src/local_ai_hub/swarm.py:200-260`
- Test: `tests/unit/test_swarm_dag_and_rollback.py`

- [ ] **Step 1: Write test verifying dependent swarm steps execute in parallel and rollback working tree if a step fails**
- [ ] **Step 2: Implement DAG runner & rollback**
Allow steps to declare `depends_on: ["step_id"]`. Execute independent steps in parallel. On failure of any required step, trigger `git checkout -f` rollback of the worktree to the pre-swarm snapshot.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(swarm): add DAG dependency execution and automated rollback on failure"`

---

### Task 73: Export Verification Receipts to Markdown / Commit Footers (#50)

**Files:**
- Modify: `src/local_ai_hub/agent_verification.py:180-220`
- Modify: `src/local_ai_hub/mcp_server.py:3740-3760`
- Test: `tests/unit/test_verification_export.py`

- [ ] **Step 1: Write test exporting task receipts to human-readable markdown format**
- [ ] **Step 2: Implement export action**
Add `action="verify_export"` to `local_ai_coord`. Formats all verified criteria for a task as a Markdown audit table or Git commit trailers (`Verified-by: ...`).

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(verification): add human-readable markdown audit export for verification receipts"`

---

### Task 74: Agent-to-Human Question Channel & Session Memory (#20)

**Files:**
- Modify: `src/local_ai_hub/agent_tasks.py:350-390`
- Modify: `src/local_ai_hub/mcp_server.py:3820-3840`
- Test: `tests/unit/test_agent_question_channel.py`

- [ ] **Step 1: Write test creating user question and retrieving recorded response**
- [ ] **Step 2: Implement channel**
Add `action="ask"` and `action="answer"` to `local_ai_coord`. Stores questions in SQLite `agent_questions` table, allowing autonomous agents to request human input without losing context.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(coord): add agent-to-human question channel and persistent session questions"`

---

### Task 75: Cross-Repo & Multi-Workspace Memory Sharing (#49)

**Files:**
- Modify: `src/local_ai_hub/agent_memory.py:310-350`
- Test: `tests/unit/test_cross_workspace_memory.py`

- [ ] **Step 1: Write test verifying memory tagged `scope="global"` is retrievable across different project roots**
- [ ] **Step 2: Implement fix**
Allow memories to specify `scope: "project" | "global"`. When querying memories, include global memories regardless of `root`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(memory): allow cross-workspace and global scope memories"`

---

### Task 76: Preservation of `missing_criteria` in `verify_completion` (#93)

**Files:**
- Modify: `src/local_ai_hub/projection.py:220-250`
- Modify: `src/local_ai_hub/mcp_server.py:3760-3770`
- Test: `tests/unit/test_verify_completion_projection.py`

- [ ] **Step 1: Write test verifying `missing_criteria` is preserved in MCP response**
- [ ] **Step 2: Implement fix**
In `projection.py`, register `"verify"` as a protected task kind and preserve `missing_criteria`, `unverified_criteria`, and `receipts`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(projection): preserve missing_criteria in verify_completion response"`

---

### Task 77: Preservation of `mergeable` and `conflicts` in `simulate_merge` (#95)

**Files:**
- Modify: `src/local_ai_hub/projection.py:230-260`
- Modify: `src/local_ai_hub/mcp_server.py:3865-3870`
- Test: `tests/unit/test_simulate_merge_projection.py`

- [ ] **Step 1: Write test verifying `simulate_merge` output preserves `mergeable: True` and conflict list**
- [ ] **Step 2: Implement fix**
Map `simulate_merge` to task kind `"general"` with `extra_fields=["mergeable", "conflicts", "exit_code"]`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(projection): retain mergeable and conflicts in simulate_merge response"`

---

### Task 78: Detection of `.git` File Pointers for Worktrees & Submodules (#98)

**Files:**
- Modify: `src/local_ai_hub/repo_tools.py:140-170`
- Modify: `src/local_ai_hub/process_utils.py:1780-1810`
- Test: `tests/unit/test_worktree_dotgit_file.py`

- [ ] **Step 1: Write test verifying repository root is recognized when `.git` is a file containing `gitdir: ...`**
- [ ] **Step 2: Implement fix**
Use `(root / ".git").exists()` instead of `(root / ".git").is_dir()` and resolve target git directory via `git rev-parse --git-dir`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(git): support .git file pointers in git worktrees and submodules"`
