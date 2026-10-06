# T13 focused acceptance receipt — 2026-10-01

## Pin and scope

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub`
- HEAD: `6050c41ce5510a6de3eaeb674a180560ea404f24`
- Selected dirty worktree patch SHA-256: `521f489f8a3884076fcfddc38fda041b8c7d9d28d2237a450746b7ee7f4f5c62`
- This receipt covers T13 mode/release and cancellation seams only. No broad suite ran. No product source changed in this validation turn.
- `async_jobs.py` remains pre-existing modified worktree content. T13 did not edit it.

## Exact focused command result

Command: `python -B -m pytest -q -p no:cacheprovider --tb=short` followed by these explicit nodes:

- `tests/test_operational_mode.py`: transient PermissionError retry; Windows sharing violation retry and bounded retry; Windows open-file replace guard; T13 Ollama release delegation, deferral, receipt mapping, missing-owner fail-closed; MCP deterministic-read gate; in-process release deferral and stalled-component bound.
- `tests/test_operational_mode_http.py`: admin control in maintenance; gaming cleanup outside guard with reservation retained; maintenance safe-read rejection; bounded sync inference retry; raw Ollama proxy gate; gaming persist/unload receipt; active resume deferral while release owns accelerator; Whisper cancellation/new-request block; timeout ownership; unavailable-admission fail-closed; unverified cleanup ownership retention.
- `tests/test_t13_cancellation_seams.py`: drain timeout fails closed and blocks new request; pause gate skips legacy uncancellable callback.
- `tests/test_t13_inference_start_gate.py`: queued preprocess and GPU worker recheck mode before runtime start.
- `tests/test_t13_mode_resume_matrix.py`: persisted pause blocks jobs; active resume dispatches again.

Result: **48 passed in 1.21s**.

## Evidence limits

- Tests used fakes. No live Ollama, CUDA, Whisper process, or physical VRAM release was tested.
- No direct `async_jobs.py` reliability suite ran. The resume matrix is a T13 integration check; ownership implementation stayed unchanged.
- Hub command broker was unavailable in this environment. Pytest ran natively in the isolated T13 worktree; root checkout was not used.
