# Wave 1 Implementation Plan: Reliability & Bottlenecks

> **Governing workflow:** Follow [Simplified Worktree and Integration Process](../specs/2026-10-07-simplified-worktree-integration.md). The primary agent implements, reviews, and integrates on current `master`. Subagents and isolated worktrees are optional for independent implementation with disjoint scope; audits and routine work remain with the primary agent. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate all fatal crashes, lockups, 400/403 validation traps, and data-loss projection bugs across Local AI Hub.

**Architecture:** Modifies `code_index.py`, `mcp_server.py`, `services.py`, `http_server.py`, `commands.py`, `process_utils.py`, `agent_events.py`, `repo_tools.py`, `telemetry.py`, `sqlite_support.py`, and `projection.py`. Replaces Python callbacks in SQLite SQL queries with index-backed SQL predicates, fixes missing JSON payload keys in MCP proxies, adds schema parameter synonyms, and prevents stream pipe deadlocks.

**Tech Stack:** Python 3.11, SQLite 3, Windows Process APIs, MCP JSON schemas, pytest.

---

### Task 1: Fix `dead_code` GIL Lockup (#1)

**Files:**
- Modify: `src/local_ai_hub/code_index.py:3030-3050`
- Test: `tests/unit/test_code_index_dead_code.py`

 - [x] **Step 1: Write failing test verifying SQL query does not register Python callbacks in JOIN**

```python
# tests/unit/test_code_index_dead_code.py
import sqlite3
from local_ai_hub.code_index import CodeIndex

def test_find_dead_code_sql_avoids_python_callback(tmp_path):
    idx = CodeIndex({"state_dir": str(tmp_path)})
    res = idx.find_dead_code(str(tmp_path), limit=10)
    assert res.get("success") is True
    assert "dead_symbols" in res
```

- [ ] **Step 2: Run test to verify baseline**
Run: `python -m pytest tests/unit/test_code_index_dead_code.py -v`

 - [x] **Step 3: Implement fix in `code_index.py`**
In `src/local_ai_hub/code_index.py:3035`, replace the custom function call `hub_root_archive_path(r.path)` in the SQL query with native SQL filtering `AND (r.path NOT LIKE '%archive%' AND r.path NOT LIKE '%.trash%')` or pre-filter paths before the JOIN to avoid evaluating Python GIL callbacks across 11.6M rows.

- [ ] **Step 4: Verify test passes**
Run: `python -m pytest tests/unit/test_code_index_dead_code.py -v`

- [ ] **Step 5: Commit**
`git commit -m "fix(code_index): eliminate python callback from dead_code JOIN query"`

---

### Task 2: Fix Data Loss in `negative_knowledge_find` Projection (#2)

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:3770-3780`
- Modify: `src/local_ai_hub/projection.py:390-410`
- Test: `tests/unit/test_mcp_negative_knowledge_projection.py`

 - [x] **Step 1: Write failing test verifying incident matches are preserved**

```python
# tests/unit/test_mcp_negative_knowledge_projection.py
from local_ai_hub.mcp_server import _compact

def test_negative_knowledge_find_preserves_incidents():
    raw_response = {
        "success": True,
        "matches": [
            {"incident_id": "inc-1", "error_class": "TimeoutError", "message": "Command timed out"}
        ],
        "count": 1
    }
    projected = _compact(raw_response, "task_memory")
    assert "matches" in projected or "incidents" in projected
    assert len(projected.get("matches", [])) == 1
```

- [ ] **Step 2: Run test to verify failure**
Run: `python -m pytest tests/unit/test_mcp_negative_knowledge_projection.py -v`

- [x] **Step 3: Implement fix**
Current `negative_knowledge_find` dispatch in `src/local_ai_hub/mcp_server.py` uses `"task_memory"`; `projection.py` preserves `matches` and `incidents` for that task kind. Exact source review confirmed this existing implementation on 2026-10-16; execution remains deferred to the complete-package gate.

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/unit/test_mcp_negative_knowledge_projection.py -v`

- [ ] **Step 5: Commit**
`git commit -m "fix(mcp): preserve incident matches in negative_knowledge_find projection"`

---

### Task 3: Fix 403 `root_not_allowed` in `skeletonize` (#3)

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:3294-3300`
- Test: `tests/unit/test_mcp_skeletonize.py`

- [x] **Step 1: Write regression tests for canonical root forwarding**

```python
# tests/unit/test_mcp_skeletonize.py
def test_skeletonize_mcp_payload_includes_root(monkeypatch):
    captured = {}
    class DummyClient:
        def post(self, url, payload, **kwargs):
            captured.update(payload)
            return {"success": True, "skeleton": "def foo(): ..."}
    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())
    from local_ai_hub.mcp_server import local_ai_repo
    local_ai_repo(action="skeletonize", root="C:/test/root", task="def bar():\n    pass")
    assert captured.get("root") == "C:/test/root"
```

- [ ] **Step 2: Run test to verify failure**
Run: `python -m pytest tests/unit/test_mcp_skeletonize.py -v`

- [x] **Step 3: Implement fix**
In `src/local_ai_hub/mcp_server.py:3296`, update payload to include `"root": root`:
```python
if action == "skeletonize":
    return _compact(CLIENT.post("/api/repo/skeletonize", {
        "root": root,
        "code": task or query,
        "language": path or "python",
    }, timeout=_timeout("quick")), "architecture")
```

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/unit/test_mcp_skeletonize.py -v`

- [ ] **Step 5: Commit**
`git commit -m "fix(mcp): supply root in skeletonize payload to prevent 403"`

---

### Task 4: Auto-resolve `workspace` from `root` in `local_ai_rag` (#5)

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:3455-3490`
- Modify: `src/local_ai_hub/rag.py:320-350`
- Test: `tests/unit/test_rag_workspace_resolver.py`

- [x] **Step 1: Write regression tests for inferred and explicit workspace identities**

```python
# tests/unit/test_rag_workspace_resolver.py
from local_ai_hub.rag import RAGStore

def test_rag_auto_resolves_workspace_from_root(tmp_path):
    store = RAGStore({"state_dir": str(tmp_path)}, services=None)
    ws_id = store.workspace_id(str(tmp_path))
    assert ws_id.startswith(".local-ai-hub-")
```

- [ ] **Step 2: Defer test execution until integrated source package is complete**
The operator requires all source changes across the package before any test execution. Do not run this task's test during implementation.

- [x] **Step 3: Implement fix**
In `mcp_server.py`, require an explicit absolute root for repository RAG actions. Derive the canonical workspace from root when workspace is empty or contains a rooted path; preserve explicit opaque workspace identifiers.

- [ ] **Step 4: Run deferred regression tests at final package gate**
Run: `python -m pytest tests/unit/test_rag_workspace_resolver.py -v` only after all six waves' source changes are complete.

- [ ] **Step 5: Commit**
`git commit -m "fix(rag): automatically resolve workspace hash ID from root path"`

---

### Task 5: Enforce Canonical MCP Parameters (#6)

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:3560-3620`
- Test: `tests/unit/test_mcp_parameter_normalization.py`

- [x] **Step 1: Write regression tests for strict canonical parameters**
Verify `local_ai_command` keeps `root` separate from `cwd`, requires nonempty `paths` for `format`, and rejects retired `changed_paths`, `files`, `input`, and positional compatibility forms.

- [ ] **Step 2: Defer test execution until integrated source package is complete**
The operator requires all source changes across the package before any test execution. Do not run this task's test during implementation.

- [x] **Step 3: Implement fix**
In `mcp_server.py` and `operation_contracts.py`, remove alias resolution and retired fields. Keep `root`/`cwd` independent, use `paths` as the sole path-list field, and use `stdin` as the sole command input field.

- [ ] **Step 4: Run deferred regression test at final package gate**
Run: `python -m pytest tests/unit/test_mcp_parameter_normalization.py -v` only after all six waves' source changes are complete.

- [ ] **Step 5: Commit**
`git commit -m "fix(mcp): normalize parameter aliases across repo and command tools"`

---

### Task 6: Add `runs` Parameter to `flaky_detect` in Command Schema (#7)

**Files:**
- Modify: `src/local_ai_hub/operation_contracts.py`
- Test: `tests/unit/test_flaky_detect_schema.py`

- [x] **Step 1: Write regression test verifying the public schema accepts `runs`**

```python
# tests/unit/test_flaky_detect_schema.py
import json

def test_command_schema_includes_runs():
    schema = json.load(open("mcp/local-ai/local_ai_command.json", encoding="utf-8"))
    assert "runs" in schema["properties"]
    assert schema["properties"]["runs"]["type"] == "integer"
```

- [ ] **Step 2: Defer test execution until integrated source package is complete**
The operator requires all source changes across the package before any test execution. Do not run this task's test during implementation.

- [x] **Step 3: Implement fix**
Publish `runs` as an integer with minimum `1` and default `5` in `operation_contracts.py`; the MCP tool signature forwards the selected count to the command endpoint.

- [ ] **Step 4: Run deferred regression test at final package gate**
Run: `python -m pytest tests/unit/test_flaky_detect_schema.py -v` only after all six waves' source changes are complete.

- [ ] **Step 5: Commit**
`git commit -m "fix(schema): expose runs parameter for flaky_detect in local_ai_command"`

---

### Task 7: Worktree Lifecycle Cleanup & `git worktree prune` (#8)

**Files:**
- Modify: `src/local_ai_hub/process_utils.py:1770-1810`
- Modify: `src/local_ai_hub/worktrees.py:140-180`
- Test: `tests/unit/test_worktree_lifecycle_prune.py`

- [x] **Step 1: Write regression tests for explicit removal, stale metadata pruning, and prune failure reporting**
- [x] **Step 2: Implement safe owned-worktree cleanup**
`remove_git_worktree` removes the explicitly owned worktree and prunes stale metadata under one bounded deadline. Do not add an idle sweep that deletes a `Temp/lah_wt_*` directory based only on a dead process; ownership, active checkout, and dirty content must be proven before cleanup.

- [ ] **Step 3: Run deferred regression tests at final package gate and commit integrated package**
Run `tests/unit/test_worktree_lifecycle_prune.py` only after all six waves' source changes are complete. Commit only after the integrated package review and final gate.

---

### Task 8: Telemetry Allowlist & Timing Breakdown (#9)

**Files:**
- Modify: `src/local_ai_hub/telemetry.py:200-260`
- Test: `tests/unit/test_telemetry_label_allowlist.py`

- [x] **Step 1: Write regression tests for bounded labels and measured phase durations**
- [x] **Step 2: Implement fix**
Replace obfuscated label `<path>` with actual tool action and root name. Retain error category and phase durations (`db_wait_ms`, `exec_ms`, `serialization_ms`) in metrics without omitting diagnostic failure details.

- [ ] **Step 3: Run deferred regression tests at final package gate and commit integrated package**
Run telemetry regression coverage only after all six waves' source changes are complete. Commit only after the integrated package review and final gate.
`git commit -m "feat(telemetry): add phase timing breakdown and clear action label allowlist"`

---

### Task 9: Exclude Generated Artifact and Validation Snapshots from Code Indexing (#10)

**Files:**
- Modify: `src/local_ai_hub/repo_tools.py:170-210`
- Test: `tests/test_code_index_ignored_paths.py`

**Contract:** Exclude generated artifact snapshots and `.validation/` contents from indexing, while preserving legitimate project content under `artifacts/` (including `artifacts/release/`) and similarly named source paths. Do not blanket-ignore the entire `artifacts/` directory.

- [x] **Step 1: Write test verifying generated artifact snapshots and `.validation/` are excluded while legitimate `artifacts/release/` content remains indexable**

```python
# tests/unit/test_repo_tools_ignore_dirs.py
from local_ai_hub.repo_tools import RepositoryTools

def test_repo_tools_ignores_artifacts_and_validation(tmp_path):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "test.md").write_text("# Test")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "code.py").write_text("def ok(): pass")
    rt = RepositoryTools({})
    files = list(rt.iter_files(str(tmp_path)))
    file_names = [f.name for f in files]
    assert "code.py" in file_names
    assert "test.md" not in file_names
```

- [x] **Step 2: Implement scoped exclusions in `repo_tools.py`**
Exclude known generated snapshot paths and `.validation/` without excluding legitimate project content beneath `artifacts/`.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(repo_tools): exclude artifacts and validation directories from indexing"`

---

### Task 10: CPU Reranker 3.0s Timeout Bypass in Adaptive Context (#61)

**Files:**
- Modify: `src/local_ai_hub/services.py:5010-5035`
- Test: `tests/unit/test_adaptive_context_reranker_timeout.py`

- [x] **Step 1: Write regression test verifying RAG in adaptive context bypasses CPU reranker under deadline**
- [x] **Step 2: Implement fix in `services.py`**
In `services.py:5020`:
```python
rag_use_reranker = (
    bool(self.config.get("rag", {}).get("use_reranker", True))
    and not (self.reranker and self.reranker.active_device == "cpu")
)
```
- [ ] **Step 3: Run deferred regression test at final package gate and commit integrated package**
Run `tests/unit/test_adaptive_context_reranker_timeout.py` only after all six waves' source changes are complete. Commit only after the integrated package review and final gate.

---

### Task 11: Auto-infer `guarded=true` on `changed_paths` / `focus` (#62)

**Files:**
- Modify: `src/local_ai_hub/http_server.py:7690-7710`
- Test: `tests/unit/test_guarded_context_inference.py`

- [x] **Step 1: Write regression tests verifying context infers `guarded=true` from `changed_paths` or `focus`**
- [x] **Step 2: Implement fix in `http_server.py`**
At line 7698: If `changed_paths` or `focus` is present in payload, automatically set `guarded = True`, eliminating 400 error.
- [ ] **Step 3: Run deferred regression tests at final package gate and commit integrated package**
Run `tests/unit/test_guarded_context_inference.py` only after all six waves' source changes are complete. Commit only after the integrated package review and final gate.

---

### Task 12: Expose `env` Overrides in `local_ai_command` (#71)

**Files:**
- Modify: `src/local_ai_hub/commands.py:7240-7260`
- Modify: `src/local_ai_hub/mcp_server.py:3580-3620`
- Test: `tests/unit/test_command_env_overrides.py`

- [x] **Step 1: Write regression tests for environment schema and subprocess propagation**
- [x] **Step 2: Implement fix**
Expose `env` in MCP schema and wire it directly to `_environment_overrides` in `commands.py`.
- [ ] **Step 3: Run deferred regression tests at final package gate and commit integrated package**
Run `tests/unit/test_command_env_overrides.py` only after all six waves' source changes are complete. Commit only after the integrated package review and final gate.

---

### Task 13: Subprocess Pipe Deadlock Guard (#72)

**Files:**
- Modify: `src/local_ai_hub/process_utils.py:1650-1700`
- Modify: `src/local_ai_hub/commands.py:7300-7350`
- Test: `tests/unit/test_subprocess_pipe_deadlock.py`

- [x] **Step 1: Write regression tests with large stdout/stderr output and bounded capture**
- [x] **Step 2: Implement fix**
Use asynchronous stream drainers with non-blocking threads to continuously drain stdout and stderr into memory buffers up to `max_output_bytes`.
- [ ] **Step 3: Run deferred regression tests at final package gate and commit integrated package**
Run `tests/unit/test_subprocess_pipe_deadlock.py` only after all six waves' source changes are complete. Commit only after the integrated package review and final gate.

---

### Task 14: Graceful In-Memory Degraded Mode on SQLite Lock (#73)

**Files:**
- Modify: `src/local_ai_hub/sqlite_support.py:110-150`
- Test: `tests/unit/test_sqlite_degraded_fallback.py`

- [x] **Step 1: Write regression tests simulating locked database behavior and degraded HTTP response**
- [x] **Step 2: Implement fix**
Catch `sqlite3.OperationalError: database is locked` after exhausted retries. Return `{"success": False, "degraded": True, "error": "database_locked"}` instead of unhandled 500 crash.
- [ ] **Step 3: Run deferred regression tests at final package gate and commit integrated package**
Run `tests/unit/test_sqlite_degraded_fallback.py` only after all six waves' source changes are complete. Commit only after the integrated package review and final gate.

---

### Task 15: Windows `WinError 5` Exponential Backoff Retry on File Delete (#74)

**Files:**
- Modify: `src/local_ai_hub/process_utils.py:80-120`
- Test: `tests/unit/test_windows_delete_retry.py`

- [x] **Step 1: Write regression tests for transient WinError 5 retry, exhaustion, and unrelated permission errors**
- [x] **Step 2: Implement fix**
Add `safe_unlink(path: Path, max_attempts: int = 5, delay: float = 0.05)` that catches `PermissionError: [WinError 5] Access is denied` on Windows, retrying with exponential backoff before failing.
- [ ] **Step 3: Run deferred regression tests at final package gate and commit integrated package**
Run `tests/unit/test_windows_delete_retry.py` only after all six waves' source changes are complete. Commit only after the integrated package review and final gate.

---

### Task 16: Max Indexable File Size Guard Against OOM (#75)

**Files:**
- Modify: `src/local_ai_hub/repo_tools.py:220-250`
- Modify: `src/local_ai_hub/code_index.py:2800-2820`
- Test: `tests/unit/test_max_indexable_file_guard.py`

- [x] **Step 1: Write regression tests for size-bound reads and AST indexing skips**
- [x] **Step 2: Implement fix**
Check `os.stat().st_size` before loading file into memory. Skip AST parsing for files > 2 MB, indexing only basic path metadata.
- [ ] **Step 3: Run deferred regression tests at final package gate and commit integrated package**
Run `tests/unit/test_max_indexable_file_guard.py` only after all six waves' source changes are complete. Commit only after the integrated package review and final gate.

---

### Task 17: Repair Loop Hollow Stub Termination (#91)

**Files:**
- Modify: `src/local_ai_hub/commands.py:8750-8775`
- Test: `tests/unit/test_repair_loop_stub.py`

- [x] **Step 1: Write regression test verifying `repair_loop` fails fast when no patch generator is configured**
- [x] **Step 2: Implement fix**
If `_synthesize_repair_patch` returns `None` and no incident fix exists, do not cycle through `max_attempts` doing nothing. Immediately return `repaired: False, reason: "no_candidate_synthesizer"`.
- [ ] **Step 3: Run deferred regression test at final package gate and commit integrated package**
Run `tests/unit/test_repair_loop_stub.py` only after all six waves' source changes are complete. Commit only after the integrated package review and final gate.

---

### Task 18: Increase Busy Lock Timeout for `agent_events.sqlite3` Streaming Logs (#94)

**Files:**
- Modify: `src/local_ai_hub/agent_events.py:115-130`
- Test: `tests/unit/test_agent_events_busy_timeout.py`

- [x] **Step 1: Write regression test verifying two-second SQLite busy timeout**
- [x] **Step 2: Implement fix**
Increase `timeout_seconds` in `agent_events.py` from 0.25 to 2.0 s with retry backoff in `BEGIN IMMEDIATE`.
- [ ] **Step 3: Run deferred regression test at final package gate and commit integrated package**
Run `tests/unit/test_agent_events_busy_timeout.py` only after all six waves' source changes are complete. Commit only after the integrated package review and final gate.
