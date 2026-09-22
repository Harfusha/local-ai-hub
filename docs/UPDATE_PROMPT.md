# Generic Agent Update & Upgrade Prompt for Local AI Hub

Use this prompt with any AI coding agent (Claude Code, Codex, Cursor, Windsurf, Gemini, Roo, GitHub Copilot) in any repository to update an existing Local AI Hub installation to the latest release, upgrade dependencies, restart services, and refresh the repository's instruction policies.

Preserve model routing defaults when refreshing repository instructions: qwen2.5-coder:0.5b for preprocessing only, qwen2.5-coder:1.5b only for quick/simple requests, qwen2.5-coder:3b for ordinary and more involved tasks, qwen2.5-coder:7b for hard reasoning, and qwen3.5:9b for extreme reasoning in the balanced profile.

---

```markdown
# TASK: Update Local AI Hub and Refresh Repository Instructions

You are an autonomous AI engineering agent. Your task is to update **Local AI Hub** on this system to the latest version, update dependencies, restart the background service, re-verify health, and refresh the Local AI Hub Tool Policy and Token Economy Policy in this repository.

Preserve privacy-safe adoption telemetry: it contains only normalized aggregate tool/action/intent/outcome, time, latency, and output-size buckets. Never migrate or expose prompts, source, secrets, absolute paths, or raw request records. Bypasses require an explicit client signal.

Follow these execution phases:

---

### PHASE 1: LOCATE INSTALLATION & PULL LATEST RELEASE

1. **Locate Installation Directory**:
   - Windows: `$HOME\.local-ai-hub` (or `%USERPROFILE%\.local-ai-hub`)
   - Linux / macOS: `~/.local-ai-hub`
2. **Pull Latest Changes**:
   - Fetch and fast-forward the currently checked-out installation branch. Do not hardcode a branch name; this installation may use `master` or another configured default:
     ```bash
     git -C "$HOME/.local-ai-hub" fetch --prune origin
     git -C "$HOME/.local-ai-hub" pull --ff-only
     ```
     *(On Windows PowerShell: `git -C "$HOME\.local-ai-hub" fetch --prune origin`, then `git -C "$HOME\.local-ai-hub" pull --ff-only`.)*

---

### PHASE 2: RUN UPDATE / RE-SETUP

Run the platform installer with the active hardware profile to apply dependency updates, regenerate MCP schemas/manifests, and update skills. The installer must inspect the active config first: install/start/pull Ollama only when `[ollama].enabled = true`, `server.auto_start_ollama = true`, and `llama_cpp.fallback_to_ollama = true`; otherwise skip all Ollama installation and model pulls. llama.cpp is not installed automatically; `mode = "auto"` may use only an existing healthy endpoint when hardware/profile detection requires it. Pull `models.vision` only for an explicitly enabled Ollama backend and `features.vision = true`. Never start `ollama serve` for the default disabled policy:

- **Windows (PowerShell)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File "$HOME\.local-ai-hub\install.ps1" -Profile auto
  ```
- **Linux / macOS (Bash)**:
  ```bash
  bash "$HOME/.local-ai-hub/install.sh" --profile auto
  ```

---

### PHASE 3: RESTART SERVICE & VERIFY HEALTH

1. **Restart Hub Service**:
   - Windows:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\service.py" restart
     ```
   - Linux / macOS:
     ```bash
     "$HOME/.local-ai-hub/.venv/bin/python" "$HOME/.local-ai-hub/tools/service.py" restart
     ```
2. **Verify Health Endpoint**:
   ```bash
   curl -s http://127.0.0.1:11435/health
   ```
   Must return `{"status":"ok", ...}` with the updated package version.
3. **Run Doctor Diagnostic**:
   - Windows:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\doctor.py"
     ```
   - Linux / macOS:
     ```bash
     "$HOME/.local-ai-hub/.venv/bin/python" "$HOME/.local-ai-hub/tools/doctor.py"
     ```
4. **Hardware Acceleration Check (iGPU / NPU)**:
   - On Intel-only systems, follow `docs/LLAMA_CPP_SYCL.md` and verify that the official SYCL `llama-server.exe --list-devices` lists the Intel GPU before enabling `llama_cpp.mode = "on"`. The installed Hub selects the SYCL backend in `auto` mode when its Intel hardware profile and routes are present. Do not set `OLLAMA_VULKAN` for Intel inference.
   - NVIDIA/AMD discrete GPUs do not trigger Ollama installation. Do not enable llama.cpp SYCL on non-Intel hardware; use deterministic Hub operations unless an explicitly configured backend already exists.
   - If an NPU (Intel AI Boost / AMD XDNA) or Intel iGPU is present:
     Ensure OpenVINO dependencies are installed in the venv only when active hardware/configuration selects OpenVINO for embeddings or reranking. Do not install OpenVINO on NVIDIA-only systems merely because the feature permission is true:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\pip.exe" install -r "$HOME\.local-ai-hub\requirements-openvino.txt"
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\prefetch_openvino.py"
     ```

---

### PHASE 4: REFRESH INSTRUCTIONS IN CURRENT REPOSITORY

Locate active agent instruction files in this repository (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.windsurfrules`, `GEMINI.md`, etc.):
- Replace or sync the `<!-- BEGIN LOCAL AI HUB TOOL POLICY -->` block with the latest policy from `~/.local-ai-hub/generated/agent-policy.md`.
- Replace or sync the `<!-- BEGIN TOKEN ECONOMY POLICY -->` block with the latest policy from `~/.local-ai-hub/generated/token-economy-policy.md`.
- If no instruction file exists, ensure `AGENTS.md` is created with both policy blocks.
- Verify the default setup deploys the `token-economizer` skill and registers the token-tool CLI directory on the user's persistent PATH. Keep the generated policy trigger that requires agents to load this skill before every repository task.
- Ensure the refreshed policy retains this trigger verbatim:
  - Before any repository task, load and follow the `token-economizer` skill when it is installed; this trigger applies even under deadline pressure.
- Preserve the `trim-run` safety boundary: only its bundled token tools and read-only search CLIs may be launched; use `local_ai_command` for tests/builds and arbitrary validation commands.
- For durable work, require one `local_ai_coord(action="task_create")` contract, phase changes through `local_ai_coord(action="task_checkpoint")`, and one bounded wait instead of status polling loops.
- Keep routing boundaries explicit: repository navigation/symbols/impact=`local_ai_repo`; exact source/log slices=`local_ai_artifact`; test/lint/typecheck/build=`local_ai_command`; task contracts/ownership leases/checkpoints/receipts/receipt-gated completion=`local_ai_coord`; task-wide context=`local_ai_coord(action="context_compile", task_id=...)`; semantic generation/exploration/reasoning/review/second opinion/compression=`local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress", task_id=...)`; deterministic/indexed tools remain for exact facts, symbols, diff and tests; `local_ai_repo(action="solve")` preserves one bounded local pass for explicit semantic wording; failure diagnosis disabled by default, enable `features.local_diagnostic_dispatch=true` only after low-confidence deterministic command parsing with artifact reference plus narrow preview, never raw logs, architecture, security, mutations, or open-ended coding; closed, verified handoff work=`local_ai_work`, never micro-edits or live discussion.
- Semantic handoff is mandatory: after deterministic/indexed evidence, planning, interpretation, synthesis, generation, review, compression, and second-opinion work must call `local_ai_task` after `context_compile` when a task exists. The cloud agent integrates the bounded local result and does not redo semantic work. Treat local output as advisory only; queued work, stale context, missing evidence or weak grounding remains visible with explicit metadata and must not be silently discarded. If local inference is unavailable or intentionally excluded by a permitted boundary, report the bypass through `local_ai_status(adoption_signal="bypassed", target_tool="local_ai_task", target_action="reason")`. Preserve exceptions for architecture, security, mutations, open-ended coding, exact evidence and verification. Shared specialized prompt contracts and model capability limits live in `docs/MODEL_CAPABILITIES.md`.
- Preserve native fallback gate: only after Hub returns `terminal=true` and `retryable=false`. Mutations never cache or single-flight.
- Keep `features.enriched_search`, `features.batch_replacement`, `features.diagnostic_artifacts`, and `features.local_diagnostic_dispatch` enabled in the installed default profile, while preserving independent rollback switches. Compare `/api/adoption` token, latency, first-pass validation, terminal failure, and native fallback metrics. Roll back immediately by setting the affected flag to `false`, restarting Hub, and running `python tools/hubctl.py generate`. Malformed values must remain disabled and disabled features must return structured unavailable before work starts. `local_diagnostic_dispatch=true` may retain only bounded failure-preview context for one local diagnosis; it never retains raw output and does not require `diagnostic_artifacts=true`.
- For `batch_replace`, require `features.batch_replacement=true`, then preview with explicit `dry_run=true`; `staged` is not batch dry-run and is never forwarded. Each edit must exact-match once. Keep rollback behavior and never auto-commit replacements. Set `dry_run=false` only after review.

---

### PHASE 5: RE-TRIGGER REPOSITORY PREPROCESSING

Send an asynchronous preprocess request for the current workspace:
- Via MCP tool:
  `local_ai_repo(action="preprocess", root="<CURRENT_WORKSPACE_ROOT>")`
- Or via HTTP loopback:
  ```bash
  curl -s -X POST http://127.0.0.1:11435/api/repo/preprocess \
    -H "Content-Type: application/json" \
    -d "{\"root\": \"$(pwd)\"}"
  ```

---

### PHASE 6: REPORT STATUS

Confirm:
1. Updated Local AI Hub version.
2. Service status (`running`/`healthy`).
3. Summary of instruction files refreshed.
4. Preprocessing status for current repository.
```
### MCP response economy

After updating, verify the generated schemas under the installation's `generated/` directory expose `max_response_tokens`, `response_profile`, and `reuse_key` on the existing Hub tools. These are installation artifacts, not checked-in source files. Treat generator output and configuration as trusted repository inputs; never copy tool fields from untrusted model output. Keep aggregate response budgeting enabled, preserve artifact-backed exact detail, and verify telemetry reports raw/projected/saved response estimates without prompt or source retention.
