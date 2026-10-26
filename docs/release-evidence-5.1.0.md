# Local AI Hub 5.1.0 — Release Verification Dossier

**Release Date:** 2026-10-26  
**Target Version:** `5.1.0`  
**Distribution File:** `dist/local_ai_hub-5.1.0-py3-none-any.whl`  
**Wheel SHA256:** `7a51e031560f2ab8eabd4531c71114898013bf1fe4efbdae4ee26547a6bb95f4`  
**Active Service:** PID `37268` listening on `http://127.0.0.1:11435`

---

## 1. Automated Verification & Test Results

| Gate / Test Cohort | Execution Command | Result / Status | Details / Evidence |
|---|---|---|---|
| **Syntax & Static Analysis** | `python -m compileall -q src tools tests` | **PASS (exit 0)** | 0 compilation errors across all modules. |
| **Linter Hygiene** | `pyflakes src tools` | **PASS (exit 0)** | 0 warnings, 0 unused imports or variables. |
| **Core Selftest** | `python tools/selftest.py` | **PASS (100% green)** | 6/6 checks passed: undefined-globals, config, repo-filtering, http-health, http-capabilities, agent-state-store. |
| **System Diagnostics** | `python tools/doctor.py` | **PASS (all [OK])** | Core Python 3.13, hardware detection, SQLite WAL mode, tools catalog healthy. |
| **Comprehensive Release Gate** | `python tools/release_check.py --allow-installed --live-smoke --json` | **PASS (16/16)** | Full live smoke verified: `qwen2.5-coder:7b` (code & reasoning), `qwen3.5:9b` (vision), Whisper audio. |
| **Surface Inventory & Contracts** | `python -m pytest -q tests/test_surface_audit_policy.py tests/test_surface_inventory.py` | **PASS (744 passed in 83.92s)** | 426 registered operations verified with exact field policies and 0 unreviewed drift. |
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

- **Built Wheel:** `dist/local_ai_hub-5.1.0-py3-none-any.whl` (size: 1,698,590 bytes)
- **Validation Environment:** Clean disposable virtual environment (`tempfile.TemporaryDirectory`)
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
    "wheel_sha256": "7a51e031560f2ab8eabd4531c71114898013bf1fe4efbdae4ee26547a6bb95f4"
  }
  ```
- **Result:** `smoke: passed`, `success: true`.

---

## 4. Live Runtime & Chrome Browser Acceptance

- **Running Server:** PID `37268` on `http://127.0.0.1:11435`
- **Endpoint Health:** `/health`, `/ready`, `/api/live/status?light=1` all return HTTP 200 with `hub_online: true`.
- **Browser Acceptance:**
  - URL: `http://127.0.0.1:11435/dashboard#overview`
  - Browser: Google Chrome (DevTools Protocol)
  - Console Diagnostics: `browser_console_logs: []` (**0 errors, 0 unhandled rejections**)
  - Visual Verification: Full dashboard rendered with resident metrics, model routing cards, and zero degraded UI indicators.
