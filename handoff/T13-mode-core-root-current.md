# T13 operational-mode root comparison

Compared candidate `6050c41ce5510a6de3eaeb674a180560ea404f24` with root `98a9a1a7611af574caf20a88620c4aa3eb2e918a` on 2026-10-01.

## Equivalent code already in root

- `src/local_ai_hub/operational_mode.py` persists mode with cross-process writer locking, revisions, atomic replacement, degraded fail-closed reads, and `operational_mode_gate_error`.
- `src/local_ai_hub/http_server.py` exposes `/api/mode` and uses `operational_mode_change_guard` for updates.
- `src/local_ai_hub/mcp_server.py` applies the mode gate to tool calls.
- Root `/api/mode` also calls `runtime.unload_configured_models(timeout_seconds=3.0)`; bounded Ollama unload already exists in `ollama.py`.
- Root API differs from candidate API. Root uses `set_operational_mode(state_dir, mode)` and a snapshot with `updated_at`; candidate uses `set_operational_mode(mode, state_dir)` and omits that field. Do not replace root module with candidate module.

## Missing T13 behavior

Root search found no `begin_resource_release`, `end_resource_release`, `inference_admission`, or in-process accelerator release helpers. Candidate token ownership and accelerator cleanup are not equivalent to root's bounded Ollama unload. They require cross-file changes in `async_jobs.py`, `http_server.py`, preprocessing, and backend owners. No isolated mode-core code patch emitted: current root already has mode state, gate, HTTP/MCP surface, and Ollama unload; missing release ownership stays a shared-hunk integration item.

## Validation

- Read-only source comparison only; no tests run.
- Root was not modified.
