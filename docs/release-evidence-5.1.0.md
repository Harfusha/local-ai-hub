# Local AI Hub 5.1.0 — Release Verification Dossier

**Release Date:** 2026-10-26  
**Target Version:** `5.1.0`  
**Distribution File:** `dist/local_ai_hub-5.1.0-py3-none-any.whl`  
**Wheel SHA256:** `04bd322436b8e1b61c800ff922a92ab2d41c7d98b0c8e7b083c72773fa8ecb39`  
**Active Service:** PID `46708` listening on `http://127.0.0.1:11435`  
**CI/CD Pipeline Run:** Run #169 — [GitHub Actions](https://github.com/Harfusha/local-ai-hub/actions/runs/40401323844)

---

## 1. Automated Verification & Test Results

| Gate / Test Cohort | Execution Command | Result / Status | Details / Evidence |
|---|---|---|---|
| **Syntax & Static Analysis** | `python -m compileall -q src tools tests` | **PASS (exit 0)** | 0 compilation errors across all modules. |
| **Linter Hygiene** | `pyflakes src tools` | **PASS (exit 0)** | 0 warnings, 0 unused imports or variables. |
| **Core Selftest** | `python tools/selftest.py` | **PASS (100% green)** | 6/6 checks passed: undefined-globals, config, repo-filtering, http-health, http-capabilities, agent-state-store. |
| **System Diagnostics** | `python tools/doctor.py` | **PASS (all [OK])** | Core Python 3.13, hardware detection, SQLite WAL mode, tools catalog healthy. |
| **Comprehensive Release Gate** | `python tools/release_check.py --allow-installed --live-smoke --json` | **PASS (16/16)** | Full live smoke verified: `qwen2.5-coder:7b` (code & reasoning), `qwen3.5:9b` (vision), Whisper audio. |
| **Surface Inventory & Contracts** | `python -m pytest -q tests/test_surface_audit_policy.py tests/test_surface_inventory.py` | **PASS (748 passed in 113.66s)** | 426 registered operations verified with exact field policies and 0 unreviewed drift. |
| **Prompt Synchronization** | `python tools/sync_prompt_policies.py --check` | **PASS** | `INSTALL_PROMPT.md` and `UPDATE_PROMPT.md` policy blocks strictly match generated definitions. |

---

## 2. Statistical Performance Benchmark (T0–T12 Gate)

- **Benchmark Command:** `python tools/benchmark_native_candidates.py --case json-budget --root . --repetitions 1000 --output docs/perf_candidate_json_budget.json`
- **Output Artifact:** `docs/perf_candidate_json_budget.json`
- **Metric Observations (1,000 paired executions):**
  - Sample size: **1,000 independent pairs** (`tail_sample_gate_met: true`)
  - Baseline execution p50: 1.25 ms | p95: 1.84 ms | p99: 2.38 ms
  - Candidate execution p50: 0.91 ms | p95: 1.28 ms | p99: 1.59 ms
  - **Speedup Median (p50):** **1.38x**
  - **Speedup 95th Percentile (p95):** **1.44x** (exceeds 1.25x gate requirement)
  - **Speedup 99th Percentile (p99):** **1.50x** (exceeds 1.25x gate requirement)
  - **Statistical Gate Verdict:** `tail_gate_met: true`

---

## 3. Isolated Wheel Packaging & MCP Smoke Test

- **Built Wheel:** `dist/local_ai_hub-5.1.0-py3-none-any.whl` (size: 1,698,984 bytes)
- **Validation Environment:** Clean disposable virtual environment (`test_smoke_venv`)
- **Package Integrity:** `pip check` -> `No broken requirements found.`
- **Functional MCP Smoke Execution (`tools/wheel_smoke.py`):**
  ```json
  {
    "mcp": {
      "ollama_online": false,
      "server_name": "Local AI Hub (compact)",
      "tool_count": 5
    },
    "module_path": "...\\Lib\\site-packages\\local_ai_hub\\__init__.py",
    "smoke": "passed",
    "success": true,
    "version": "5.1.0",
    "wheel_sha256": "04bd322436b8e1b61c800ff922a92ab2d41c7d98b0c8e7b083c72773fa8ecb39"
  }
  ```
- **Result:** `smoke: passed`, `success: true`.

---

## 4. Multi-Platform Hosted CI Verification (GitHub Actions Run #169)

- **Workflow Run:** [Run #169 on master](https://github.com/Harfusha/local-ai-hub/actions/runs/40401323844)
- **Platforms Verified:**
  - Ubuntu Linux (`ubuntu-latest`: Python 3.11, 3.12, 3.13, 3.14)
  - macOS ARM64 (`macos-latest`: Python 3.11, 3.12, 3.13, 3.14)
  - Windows x64 (`windows-latest`: Python 3.11, 3.12, 3.13, 3.14)
- **Status:** All matrix configurations verified with 0 FAIL / 0 ERROR.
