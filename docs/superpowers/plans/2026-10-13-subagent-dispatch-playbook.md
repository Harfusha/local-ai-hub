# Subagent Dispatch Playbook: 100 Items Implementation

> **Status:** Optional dispatch reference, subordinate to [Simplified Worktree and Integration Process](../specs/2026-10-07-simplified-worktree-integration.md). The primary agent implements, reviews, and integrates on current `master`. Use a subagent only for independently bounded implementation with disjoint write scope or an explicit user request. Review and audit do not require separate agents.

---

## 1. Subagent Lifecycle & Worktree Setup

Use an isolated worktree only when parallel implementation or a concrete conflict boundary requires it. Routine tasks stay on current `master`. Unit databases always use `tmp_path` or `:memory:`, independently of checkout choice.

### Launch Script (PowerShell)

```powershell
param(
    [string]$Wave = "wave-1",
    [string]$TaskId = "task-01"
)

$Branch = "codex/$Wave-$TaskId"
$WorktreePath = "../lah-wt-$TaskId"

Write-Host "Creating worktree at $WorktreePath on branch $Branch..."
git worktree add -b $Branch $WorktreePath master

Write-Host "Worktree ready. Dispatch subagent with working directory: $WorktreePath"
```

### Teardown Script (PowerShell)

```powershell
param(
    [string]$TaskId = "task-01"
)

$WorktreePath = "../lah-wt-$TaskId"
Write-Host "Cleaning up worktree $WorktreePath..."
git worktree remove $WorktreePath
git worktree prune
```

---

Before teardown, inspect dirty/untracked work, unique commits, and ownership; record the disposition in the existing plan and retain a recoverable ref. Do not remove a worktree merely because its task ended. The script above applies only after those checks pass.

## 2. Optional Subagent Prompts

### A. Implementer Subagent Prompt

```markdown
You are an autonomous engineering subagent executing Task [TASK_NUMBER] from Wave [WAVE_NUMBER].
Your task specification is in: docs/superpowers/plans/2026-10-13-[WAVE_NAME].md under Task [TASK_NUMBER].

STRICT RULES:
1. Follow Test-Driven Development (TDD):
   - Step 1: Write the failing test in tests/unit/
   - Step 2: Run pytest to confirm it fails as expected
   - Step 3: Implement minimal code in the specified file
   - Step 4: Run pytest to confirm it passes
   - Step 5: Commit with the exact message from the plan
2. DO NOT modify any files outside the files explicitly listed in the task.
3. Use temporary directories (tmp_path) for all SQLite databases in unit tests. Never touch state/*.sqlite3.
4. On Windows, use helpers from process_utils.py (e.g. hidden_run_kwargs).
5. When complete, reply with a summary of the commit hash and test verification output.
```

### B. Spec Reviewer Subagent Prompt

```markdown
You are a Spec Compliance Reviewer subagent for Task [TASK_NUMBER].
Compare the implementation commit against the task specification in:
docs/superpowers/plans/2026-10-13-[WAVE_NAME].md

CHECKLIST:
- Does behavior satisfy the specified acceptance criteria in the current architecture? File/line hints may be stale; explain necessary integration changes.
- Did they add tests verifying the required edge cases?
- Did they preserve all existing unrelated comments and docstrings?
- Are any unexpected files modified or added?
Reply with PASS if fully compliant, or FAIL with a list of specific gaps to fix.
```

### C. Code Quality Reviewer Subagent Prompt

```markdown
You are a Code Quality Reviewer subagent for Task [TASK_NUMBER].
Inspect the git diff of the commit for:
- Deadlock risks (SQLite busy timeouts, subprocess pipe draining)
- Windows compatibility (long paths, backslashes vs forward slashes, process kill on exit)
- Type annotations and docstrings
- Error handling (never bare `except Exception: pass` without logging or telemetry)
Reply with APPROVE or REQUEST_CHANGES.
```

---

## 3. Bounded Implementation and Integration Sequence

```mermaid
sequenceDiagram
    autonumber
    actor Orchestrator as Main Agent / Orchestrator
    participant Implementer as Main Agent or Optional Independent Implementer
    participant Git as Git Master Branch

    Orchestrator->>Implementer: Assign bounded Task N; isolate only when needed
    Implementer->>Implementer: TDD (Failing test -> Code -> Pass -> Commit)
    Implementer-->>Orchestrator: Commit ready
    Orchestrator->>Orchestrator: Review specification, code quality, Windows safety
    Orchestrator->>Git: Integrate reviewed change promptly; run targeted tests
    Orchestrator->>Orchestrator: Update existing plan; classify leftovers before archival
```

---

## 4. End-of-Wave Global Integration Gate

At the end of each wave before proceeding to the next wave, run the full validation suite:

```bash
# 1. Compilation
python -m compileall -q src tests tools

# 2. Strict release check
python tools/release_check.py --allow-installed

# 3. Unit test suite
python -m pytest tests/unit/ -q

# 4. Hub selftest
python tools/selftest.py

# 5. Doctor diagnostics
python tools/doctor.py
```
