# Wave 4 Implementation Plan: Execution, Commands & Testing

> **Governing workflow:** Follow [Simplified Worktree and Integration Process](../specs/2026-10-07-simplified-worktree-integration.md). The primary agent implements, reviews, and integrates on current `master`. Subagents and isolated worktrees are optional for independent implementation with disjoint scope; audits and routine work remain with the primary agent. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure 100% reliable command execution, seamless patch application, zero orphan background processes, and structured test failure feedback.

**Architecture:** Modifies `commands.py`, `command_transactions.py`, `process_utils.py`, `mcp_server.py`, `mcp/local-ai/local_ai_command.json`, `deterministic.py`, and `repo_tools.py`. Exposes environment overrides, interactive stdin, Windows Job Objects for tree termination, and automated test result summarization.

**Tech Stack:** Python 3.11, Windows Job Objects, Subprocess, Pytest, Git, JUnit XML parsers.

---

### Task 53: Expose Custom Environment Variables (`env`) in `local_ai_command` (#29, #71)

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py` (canonical inline command schema and dispatch)
- Modify: `src/local_ai_hub/commands.py` (validated process environment)
- Test: `tests/unit/test_command_env_overrides.py`

- [x] **Step 1: Write tests for process environment and public MCP schema**

```python
# tests/unit/test_command_env_overrides.py
from local_ai_hub.commands import CommandBroker

def test_command_receives_custom_env(tmp_path):
    broker = CommandBroker({"state_dir": str(tmp_path)})
    res = broker.run(
        "python -c \"import os; print('MY_VAR=' + os.environ.get('MY_VAR', ''))\"",
        cwd=str(tmp_path),
        tenant="test",
        _environment_overrides={"MY_VAR": "HELLO_AGENT"}
    )
    assert "MY_VAR=HELLO_AGENT" in res.get("stdout", "")
```

- [x] **Step 2: Implement fix in `mcp_server.py` and command dispatch**
The command schema is generated from the current MCP registration; no standalone `mcp/local-ai/local_ai_command.json` exists in this checkout. `env` is validated and passed to the broker's environment override contract.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(commands): expose env variable overrides in local_ai_command MCP tool"`

---

### Task 54: Process Tree Termination via Windows Job Objects (#30)

**Files:**
- Modify: `src/local_ai_hub/process_utils.py:150-200`
- Modify: `src/local_ai_hub/commands.py:7400-7450`
- Test: `tests/unit/test_windows_job_process_tree_kill.py`

- [x] **Step 1: Write tests for Windows job ownership and process-tree cleanup**
- [x] **Step 2: Implement fix**
Assign spawned command processes to a Windows Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(process): ensure full subprocess tree termination using Windows Job Objects on cancellation"`

---

### Task 55: Structured Test Failure Summarizer (`failed_tests` array) (#78)

**Files:**
- Modify: `src/local_ai_hub/commands.py:7550-7600`
- Test: `tests/unit/test_structured_test_summarizer.py`

- [x] **Step 1: Write tests for pytest, Jest, and Cargo failure output**
- [x] **Step 2: Implement parser in `commands.py`**
Parse regex patterns for pytest, jest, and cargo test outputs. Include `failed_tests: [{name, file, line, error_message}]` in command result payload.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(commands): provide structured failed_tests list on test command failure"`

---

### Task 56: Support Interactive `stdin` in `local_ai_command` (#76)

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:3580-3600`
- Modify: `mcp/local-ai/local_ai_command.json`
- Modify: `src/local_ai_hub/commands.py:7300-7340`
- Test: `tests/unit/test_command_stdin_input.py`

- [x] **Step 1: Write tests for piped and default-empty stdin across broker/MCP**
- [x] **Step 2: Implement fix**
Add `input` / `stdin` parameter to `local_ai_command` and pass to `proc.communicate(input=...)`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(commands): add stdin input support for interactive CLI prompts"`

---

### Task 57: Whitespace & CRLF Tolerant Patch Application (#13)

**Files:**
- Modify: `src/local_ai_hub/commands.py:8110-8140`
- Test: `tests/unit/test_fuzzy_patch_application.py`

- [x] **Step 1: Write tests for whitespace/line-ending patch application**
- [x] **Step 2: Implement fix**
In `patch_and_verify`, add `--ignore-whitespace --ignore-space-change` flags when initial `git apply --check` fails.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(commands): allow whitespace-tolerant fallback in patch_and_verify"`

---

### Task 58: Windows Long Path Support (`\\?\`) (#39)

**Files:**
- Modify: `src/local_ai_hub/process_utils.py:100-130`
- Test: `tests/unit/test_windows_long_paths.py`

- [x] **Step 1: Write tests for short and extended Windows paths**
- [x] **Step 2: Implement fix**
Add `ensure_extended_path(p: Path) -> Path` that prepends `\\?\` prefix when length exceeds 240 chars.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(io): add Windows extended-length path (\\\\?\\) support to bypass 260-char limit"`

---

### Task 59: Direct File Slicing in `local_ai_artifact` (`path` + lines) (#26)

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:3920-3940`
- Test: `tests/unit/test_artifact_direct_file_slice.py`

- [x] **Step 1: Write tests for bounded direct source slices**
- [x] **Step 2: Implement fix**
If `artifact_id` is empty but `path` is provided, slice repository file directly from disk.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(artifact): allow slicing repository files directly by path and line range"`

---

### Task 60: Test Selection Fix in `run_affected` (#15)

**2026-10-15 implementation checkpoint — execution deferred until the whole remaining bundle.** Actual selection lives in `services.affected_tests` and `DeterministicEngine.affected_tests`; automatic patch validation also independently chose pytest whenever any Python path was present. A shared deterministic compatibility table now filters Python, JS/TS module variants, .NET, Rust and Go paths before command construction. Both selection layers and the automatic patch path use it; excluded paths are reported instead of being counted as tests run. Command paths are quoted using the existing host convention; leading-dash relative filenames receive `./` so they cannot become runner flags. Unknown runners no longer default unrelated files to pytest. `run_affected` propagates selection failures and explicitly fails when only incompatible candidates exist, instead of reporting that no tests were found. Full-suite fallback behavior for uncertain selection remains in place.

Deferred regression source: `tests/unit/test_run_affected_language_filter.py` covers the real deterministic mixed-language selection path, spaces, runner families, unknown files and leading-dash paths. It uses temporary state and a fake dependency index; it has not been executed. Integration, command-policy acceptance, platform quoting and full-suite fallback still require final bundle validation.

**Files:**
- Modify: `src/local_ai_hub/services.py:6575-6610`
- Test: `tests/unit/test_run_affected_language_filter.py`

- [x] **Step 1: Write mixed-runner regression source (execution deferred)**
- [x] **Step 2: Implement shared runner filtering (validation pending)**
Filter `auto_detected_tests` by runner compatibility: only pass `.py` files to pytest, `.ts`/`.js` to jest/vitest.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(commands): filter affected test files by test runner language compatibility"`

---

### Task 61: Windows Path Case and Slash Normalization (#27)

**Files:**
- Modify: `src/local_ai_hub/process_utils.py` (canonical Windows path identity)
- Test: `tests/unit/test_windows_path_normalization.py`

- [x] **Step 1: Write tests verifying canonical Windows path identity**
- [x] **Step 2: Implement fix**
Add `canonical_path(p: str | Path) -> str`: normalizes slashes to `/` and uppercase drive letter (`C:/...`).
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(paths): normalize drive letter casing and slashes on Windows"`

---

### Task 62: Diffing Arbitrary Commits in `git_diff` (#31)

**2026-10-15 implementation checkpoint — execution deferred.** Added nullable keyword-only `rev1`/`rev2` through the existing MCP operation contract, client, GET/POST route, service and bounded RepositoryTools backend. Both refs must be provided together, cannot combine with staged mode, and are resolved independently to commit IDs with bounded Git calls before constructing `rev1...rev2`. Literal pathspecs prevent optional path filters from becoming Git magic. Revision queries bypass the workspace-only result cache so moving refs are resolved afresh. The structured deterministic API now reuses bounded stream capture instead of retaining unbounded subprocess output; incomplete preview statistics are explicitly marked. Working-tree and index modes retain their default comparison behavior. Both agent prompts describe merge-base semantics and resolved IDs. Deferred regression source uses temporary Git repositories for diverged branches, dirty-file exclusion, path filtering and MCP forwarding; it has not run. No runtime/release acceptance is claimed.

**Files:**
- Modify: `src/local_ai_hub/repo_tools.py:890-930`
- Test: `tests/unit/test_git_diff_arbitrary_revisions.py`

- [x] **Step 1: Write arbitrary-revision and forwarding regression source (execution deferred)**
- [x] **Step 2: Implement bounded revision diff across existing public surface (validation pending)**
Support `rev1` and `rev2` parameters in `git_diff`, running `git diff rev1...rev2`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(git): support diffing arbitrary commits and revisions in git_diff"`

---

### Task 63: Filtered `git_history_search` (#33)

**Files:**
- Modify: `src/local_ai_hub/repo_tools.py` (bounded filtered Git history search)
- Test: `tests/unit/test_bounded_git_insights.py`

- [x] **Step 1: Write tests filtering Git history by author, date, and path**
- [x] **Step 2: Implement fix**
Pass `--author`, `--since`, `--until`, and `-- <path>` to `git log` search query.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(git): add author, date, and path filters to git_history_search"`

---

### Task 64: In-Memory Dry-Run Patch Simulation (#35)

**Files:**
- Modify: `src/local_ai_hub/commands.py` (patch dry-run boundary)
- Test: `tests/unit/test_patch_dry_run.py`

- [x] **Step 1: Write tests validating patch applicability without modifying disk files**
- [x] **Step 2: Implement fix**
Run `git apply --check` or in-memory string replacement without touching file system when `dry_run=True`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(commands): add dry_run simulation to patch_and_verify without filesystem edits"`

---

### Task 65: Recency Decay Weighting for Git Hotspots (#36)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py` (90-day hotspot half-life)
- Test: `tests/unit/test_bounded_git_insights.py`

- [x] **Step 1: Write tests for recency ordering and Windows file identity**
- [x] **Step 2: Implement fix**
Apply exponential half-life decay: `score = count * (0.5 ** (days_old / 90.0))`.
No three-year hotspot window is implied.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(git): apply exponential recency decay to git hotspots scoring"`

---

### Task 66: Deduplication of Stack Traces in Command Outputs (#37)

**Files:**
- Modify: `src/local_ai_hub/commands.py` (bounded stack-trace clustering)
- Test: `tests/unit/test_stack_trace_clustering.py`

- [x] **Step 1: Write tests for repeated stack-trace clustering and bounded summaries**
- [x] **Step 2: Implement fix**
Group repeated error messages and traces, printing the first instance and `... [and 49 identical failures]`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(commands): cluster and deduplicate identical error stack traces in command output"`

---

### Task 67: Test Matrix Consistency Validation (#58)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py` (bounded test-matrix evidence)
- Test: `tests/unit/test_test_matrix_validation.py`

- [x] **Step 1: Write tests for current, contained, regular test files and incomplete scans**
- [x] **Step 2: Implement fix**
Validate each combination in `test_matrix` against files matching `test_*.py` on disk.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(deterministic): validate test matrix against actual test files on disk"`

---

### Task 68: Automated Stash Restore Hook on Transaction Abort (#77)

**Files:**
- Modify: `src/local_ai_hub/command_transactions.py` (transaction-scoped stash ownership)
- Test: `tests/unit/test_transaction_stash_restore_hook.py`

- [x] **Step 1: Write tests for restoration on abort and cleanup on success**
- [x] **Step 2: Implement scoped transaction guard**
Stash restoration is explicit and transaction-owned. No process-global `atexit` hook or unqualified `git stash pop` can consume unrelated user stashes.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(transactions): ensure stashed changes are restored upon transaction abort"`
