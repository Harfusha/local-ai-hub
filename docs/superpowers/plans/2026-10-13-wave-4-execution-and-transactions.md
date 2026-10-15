# Wave 4 Implementation Plan: Execution, Commands & Testing

> **Governing workflow:** Follow [Simplified Worktree and Integration Process](../specs/2026-10-07-simplified-worktree-integration.md). The primary agent implements, reviews, and integrates on current `master`. Subagents and isolated worktrees are optional for independent implementation with disjoint scope; audits and routine work remain with the primary agent. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure 100% reliable command execution, seamless patch application, zero orphan background processes, and structured test failure feedback.

**Architecture:** Modifies `commands.py`, `command_transactions.py`, `process_utils.py`, `mcp_server.py`, `mcp/local-ai/local_ai_command.json`, `deterministic.py`, and `repo_tools.py`. Exposes environment overrides, interactive stdin, Windows Job Objects for tree termination, and automated test result summarization.

**Tech Stack:** Python 3.11, Windows Job Objects, Subprocess, Pytest, Git, JUnit XML parsers.

---

### Task 53: Expose Custom Environment Variables (`env`) in `local_ai_command` (#29, #71)

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:3580-3620`
- Modify: `mcp/local-ai/local_ai_command.json`
- Modify: `src/local_ai_hub/commands.py:7240-7260`
- Test: `tests/unit/test_command_env_overrides.py`

- [ ] **Step 1: Write test verifying custom environment variables are passed to subprocess**

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

- [ ] **Step 2: Implement fix in `mcp_server.py` and schema**
1. Add `env` property to `local_ai_command.json`.
2. In `mcp_server.py`, accept `env: dict[str, str] | None = None` in `local_ai_command`.
3. Wire `env` to `_environment_overrides` in `commands.py`.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(commands): expose env variable overrides in local_ai_command MCP tool"`

---

### Task 54: Process Tree Termination via Windows Job Objects (#30)

**Files:**
- Modify: `src/local_ai_hub/process_utils.py:150-200`
- Modify: `src/local_ai_hub/commands.py:7400-7450`
- Test: `tests/unit/test_windows_job_process_tree_kill.py`

- [ ] **Step 1: Write test verifying terminating parent process kills all spawned children**
- [ ] **Step 2: Implement fix**
Assign spawned command processes to a Windows Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(process): ensure full subprocess tree termination using Windows Job Objects on cancellation"`

---

### Task 55: Structured Test Failure Summarizer (`failed_tests` array) (#78)

**Files:**
- Modify: `src/local_ai_hub/commands.py:7550-7600`
- Test: `tests/unit/test_structured_test_summarizer.py`

- [ ] **Step 1: Write test verifying pytest failure output parses into structured JSON list**
- [ ] **Step 2: Implement parser in `commands.py`**
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

- [ ] **Step 1: Write test verifying command receives piped stdin string**
- [ ] **Step 2: Implement fix**
Add `input` / `stdin` parameter to `local_ai_command` and pass to `proc.communicate(input=...)`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(commands): add stdin input support for interactive CLI prompts"`

---

### Task 57: Whitespace & CRLF Tolerant Patch Application (#13)

**Files:**
- Modify: `src/local_ai_hub/commands.py:8110-8140`
- Test: `tests/unit/test_fuzzy_patch_application.py`

- [ ] **Step 1: Write test applying patch with mismatched line endings (CRLF vs LF)**
- [ ] **Step 2: Implement fix**
In `patch_and_verify`, add `--ignore-whitespace --ignore-space-change` flags when initial `git apply --check` fails.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(commands): allow whitespace-tolerant fallback in patch_and_verify"`

---

### Task 58: Windows Long Path Support (`\\?\`) (#39)

**Files:**
- Modify: `src/local_ai_hub/process_utils.py:100-130`
- Test: `tests/unit/test_windows_long_paths.py`

- [ ] **Step 1: Write test reading and writing file in directory path > 260 chars on Windows**
- [ ] **Step 2: Implement fix**
Add `ensure_extended_path(p: Path) -> Path` that prepends `\\?\` prefix when length exceeds 240 chars.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(io): add Windows extended-length path (\\\\?\\) support to bypass 260-char limit"`

---

### Task 59: Direct File Slicing in `local_ai_artifact` (`path` + lines) (#26)

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:3920-3940`
- Test: `tests/unit/test_artifact_direct_file_slice.py`

- [ ] **Step 1: Write test verifying slicing file by path and lines directly**
- [ ] **Step 2: Implement fix**
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
- Modify: `src/local_ai_hub/process_utils.py:210-240`
- Test: `tests/unit/test_windows_path_normalization.py`

- [ ] **Step 1: Write test verifying `c:/foo/bar` and `C:\foo\bar` resolve to identical cache keys**
- [ ] **Step 2: Implement fix**
Add `canonical_path(p: str | Path) -> str`: normalizes slashes to `/` and uppercase drive letter (`C:/...`).
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(paths): normalize drive letter casing and slashes on Windows"`

---

### Task 62: Diffing Arbitrary Commits in `git_diff` (#31)

**Files:**
- Modify: `src/local_ai_hub/repo_tools.py:890-930`
- Test: `tests/unit/test_git_diff_arbitrary_revisions.py`

- [ ] **Step 1: Write test diffing `HEAD~3..HEAD` or `commitA..commitB`**
- [ ] **Step 2: Implement fix**
Support `rev1` and `rev2` parameters in `git_diff`, running `git diff rev1...rev2`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(git): support diffing arbitrary commits and revisions in git_diff"`

---

### Task 63: Filtered `git_history_search` (#33)

**Files:**
- Modify: `src/local_ai_hub/repo_tools.py:940-980`
- Test: `tests/unit/test_filtered_git_history_search.py`

- [ ] **Step 1: Write test filtering git commit search by author and file path**
- [ ] **Step 2: Implement fix**
Pass `--author`, `--since`, `--until`, and `-- <path>` to `git log` search query.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(git): add author, date, and path filters to git_history_search"`

---

### Task 64: In-Memory Dry-Run Patch Simulation (#35)

**Files:**
- Modify: `src/local_ai_hub/commands.py:8080-8110`
- Test: `tests/unit/test_patch_dry_run.py`

- [ ] **Step 1: Write test validating patch applicability without modifying disk files**
- [ ] **Step 2: Implement fix**
Run `git apply --check` or in-memory string replacement without touching file system when `dry_run=True`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(commands): add dry_run simulation to patch_and_verify without filesystem edits"`

---

### Task 65: Recency Decay Weighting for Git Hotspots (#36)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:5790-5830`
- Test: `tests/unit/test_hotspots_recency_decay.py`

- [ ] **Step 1: Write test verifying recent commits receive higher hotspot score than 3-year-old changes**
- [ ] **Step 2: Implement fix**
Apply exponential half-life decay: `score = count * (0.5 ** (days_old / 90.0))`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(git): apply exponential recency decay to git hotspots scoring"`

---

### Task 66: Deduplication of Stack Traces in Command Outputs (#37)

**Files:**
- Modify: `src/local_ai_hub/commands.py:7600-7640`
- Test: `tests/unit/test_stack_trace_clustering.py`

- [ ] **Step 1: Write test verifying 50 identical test error traces are clustered into 1 with count badge**
- [ ] **Step 2: Implement fix**
Group repeated error messages and traces, printing the first instance and `... [and 49 identical failures]`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(commands): cluster and deduplicate identical error stack traces in command output"`

---

### Task 67: Test Matrix Consistency Validation (#58)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:6190-6230`
- Test: `tests/unit/test_test_matrix_validation.py`

- [ ] **Step 1: Write test verifying `test_matrix` returns only combinations backed by existing test files**
- [ ] **Step 2: Implement fix**
Validate each combination in `test_matrix` against files matching `test_*.py` on disk.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(deterministic): validate test matrix against actual test files on disk"`

---

### Task 68: Automated Stash Restore Hook on Transaction Abort (#77)

**Files:**
- Modify: `src/local_ai_hub/command_transactions.py:140-180`
- Test: `tests/unit/test_transaction_stash_restore_hook.py`

- [ ] **Step 1: Write test simulating unexpected process exit during transaction restoring stashed changes**
- [ ] **Step 2: Implement fix**
Register an `atexit` and `except Exception` handler in `command_transactions.py` that runs `git stash pop` if a transaction fails.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(transactions): ensure stashed changes are restored upon transaction abort"`
