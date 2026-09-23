# llama.cpp Provider Selection and Managed Setup Implementation Plan

> **For agentic workers:** Follow this plan task by task. Keep all runtime artifacts under the configured state directory. Do not create commits, tags, pushes, or pull requests.

**Goal:** Make provider selection consistent across setup, runtime, supervision, doctor, and status, with managed llama.cpp available only when explicitly selected.

**Architecture:** Preserve the current Ollama and llama.cpp routing interfaces. Derive one provider decision from the existing Ollama enablement and `llama_cpp.mode` settings, then use it in setup, lifecycle management, and health reporting. Provision pinned llama.cpp artifacts and the default model under `server.state_dir`; use CPU only as llama.cpp's internal fallback after GPU initialization fails.

**Tech Stack:** Python 3.11+, TOML configuration, existing subprocess/process utilities, pytest, PowerShell and shell installer entry points.

**Spec:** `docs/superpowers/specs/2026-09-23-llama-cpp-provider-repair-design.md`

## Global Constraints

- Runtime binaries, model files, logs, and mutable state stay under `server.state_dir`.
- Downloads have pinned versions, bounded transfer time, and verified checksums before extraction or use.
- The managed server binds to loopback and keeps the existing OpenAI-compatible routing contract.
- Ollama-enabled configurations never install or start llama.cpp.
- `llama_cpp.mode = "auto"` only discovers an external configured endpoint; `"on"` selects managed llama.cpp; `"off"` disables it.
- Unsupported platforms and invalid downloads fail with a clear actionable message; they never trigger an implicit provider switch.
- Preserve no-commit/no-push project policy.

## Files to Change

- `src/local_ai_hub/config.py`: validate the existing `llama_cpp.mode` selector; keep provider resolution in the runtime module below.
- `src/local_ai_hub/llama_cpp_runtime.py`: pinned downloader, safe extraction, managed server startup/stop, and CPU fallback.
- `src/local_ai_hub/ollama.py`: route requests and report provider-aware health; keep CPU retry inside llama.cpp startup.
- `src/local_ai_hub/supervisor.py`: ensure the managed llama.cpp process follows Hub start, stop, and restart lifecycle, using existing helpers in `src/local_ai_hub/process_utils.py`.
- `src/local_ai_hub/services.py`: report the selected backend's health in `run_doctor`.
- `tools/setup.py`: provision managed llama.cpp only for explicit selection; use state-scoped, pinned, checksum-verified artifacts.
- `tools/doctor.py` and `tools/hubctl.py`: align CLI output with the same provider decision and health state.
- `config/defaults.toml` and `config.toml.example`: document defaults and the `on` / `auto` / `off` contract.
- `tests/test_setup.py`, `tests/test_llama_cpp_routing.py`, and focused service/CLI tests: lock selection, setup, startup fallback, and diagnostics behavior.
- `docs/INSTALLATION.md`, `docs/OPERATIONS.md`, `docs/LLAMA_CPP_SYCL.md`, `docs/INSTALL_PROMPT.md`, and `docs/UPDATE_PROMPT.md`: keep user and agent setup guidance consistent.

## Task 1: Unify provider selection and request health

**Files:** `src/local_ai_hub/config.py`, `src/local_ai_hub/ollama.py`, `tests/test_llama_cpp_routing.py`

**Interface:** Add a single typed provider resolver over the loaded config. It returns `ollama`, `llama_cpp_managed`, `llama_cpp_external`, or `disabled`. Ollama enabled wins. With Ollama disabled, `mode="on"` selects managed llama.cpp, `mode="auto"` selects only a reachable configured external endpoint, and `mode="off"` selects disabled.

- [ ] Add parameterized regression cases for all four resolutions, including Ollama enabled plus llama.cpp `on`.
- [ ] Route request and `is_online()` behavior through the resolver so provider health is not inferred from Ollama alone.
- [ ] Keep fallback-to-Ollama behavior explicit in its existing configuration; do not silently change providers.
- [ ] Run the focused routing tests and correct failures before moving to lifecycle work.

## Task 2: Provision and supervise managed llama.cpp

**Files:** `tools/setup.py`, `src/local_ai_hub/supervisor.py`, `src/local_ai_hub/ollama.py`, `tests/test_setup.py`, new focused supervisor tests.

**Interface:** Add a state-scoped managed-runtime installer and launcher used only when the resolver returns `llama_cpp_managed`. The installer selects a pinned artifact for a supported OS/architecture, verifies its SHA-256 before extraction, and provisions the configured default model similarly. The supervisor starts the loopback server idempotently, records its PID/status under `state`, and stops/restarts only its own child process.

- [ ] Add setup tests proving Ollama-enabled, external `auto`, and disabled configurations perform no llama.cpp download.
- [ ] Add setup tests proving explicit managed mode installs once, reuses verified artifacts, enforces a bounded download timeout, and rejects checksum mismatch or unsupported platform without changing provider.
- [ ] Start with the configured GPU backend; if GPU initialization fails, retry once with llama.cpp CPU backend and report the active mode.
- [ ] Add supervisor tests for already-running, start failure, restart, and child-only stop behavior.
- [ ] Run focused setup, routing, and supervisor tests; inspect state-path and process cleanup behavior.

## Task 3: Make diagnosis and status provider-aware

**Files:** `src/local_ai_hub/services.py`, `tools/doctor.py`, `tools/hubctl.py`, focused service/CLI tests.

- [ ] Change `run_doctor` to check only the selected provider; show disabled providers as skipped/disabled, not failed.
- [ ] Ensure status output names the selected provider, reports managed CPU fallback, and distinguishes unavailable external `auto` endpoints from failed Ollama.
- [ ] Add tests for Ollama selected/healthy, llama.cpp managed/healthy, llama.cpp external/missing, and both providers intentionally disabled.
- [ ] Run focused doctor and CLI tests.

## Task 4: Align defaults, docs, and install prompts

**Files:** `config/defaults.toml`, `config.toml.example`, `docs/INSTALLATION.md`, `docs/OPERATIONS.md`, `docs/LLAMA_CPP_SYCL.md`, `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`.

- [ ] Document that Ollama enabled selects Ollama and prevents llama.cpp provisioning.
- [ ] Document `mode="on"` as managed installation, `"auto"` as external endpoint detection only, and `"off"` as disabled.
- [ ] Document state storage, checksum verification, supported platform behavior, CPU fallback, and doctor/status meanings.
- [ ] Cross-check both canonical prompts and all docs against the same decision table.

## Task 5: Whole-project verification and installed configuration

**Files:** implementation paths above; installed user config only if needed to preserve the already requested llama.cpp choice.

- [ ] Set the installed config to managed llama.cpp explicitly (`ollama.enabled=false`, `llama_cpp.mode="on"`) without changing unrelated preferences.
- [ ] Run the repository validation commands from `AGENTS.md`: `python tools/release_check.py`, `python -m compileall -q src mcp tools tests`, `python -m pytest -q`, and `python tools/selftest.py`.
- [ ] Run installed-instance checks: `python tools/doctor.py` and `python tools/hubctl.py status`.
- [ ] Review changed paths and confirm no generated model/runtime files entered the repository, no doc contradicts the decision table, and no commit was created.

## Review Focus

1. Ollama is enabled while llama.cpp says `on`; tests in Task 1 prove Ollama remains selected and setup tests in Task 2 prove no llama.cpp download occurs.
2. `llama_cpp.mode="auto"` has no endpoint; Task 1 tests prove it is not converted into a managed install and Task 3 proves diagnostics name the unavailable external endpoint.
3. A corrupted or partial artifact is present; Task 2 proves checksum mismatch blocks extraction/startup and a later run can recover safely.
4. GPU initialization fails after process launch; Task 2 proves one CPU retry succeeds and health reports CPU mode.
5. llama.cpp is explicitly selected on an unsupported platform; Task 2 proves setup returns an actionable error without falling back to Ollama.

## Completion Review

- Run indexed diff/impact review before final validation.
- Run all focused tests after each task and the full validation list after integration.
- Do not claim completion unless the doctor and status reflect the active selected backend and all checks above pass.
