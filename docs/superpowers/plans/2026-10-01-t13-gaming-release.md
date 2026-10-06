# T13 Gaming Resource Release Plan

> **For agentic workers:** Implement in the existing T13 candidate worktree. Do not edit root. Keep `/api/search` and `/api/context/pack` untouched.

## Ownership and boundaries

- T13-owned: operational-mode orchestration, async release/admission ownership, admin mode handler, preprocess pause behavior, and T13 tests.
- T11-owned: `embeddings.py` and `reranker.py`. Candidate API is bounded `release_accelerator(timeout_seconds)` returning a dict; owner confirms root `release(timeout_seconds)->bool` is also supported. T13 consumes these contracts with before/after `status()` checks; do not modify owner files. `not_applicable` is a successful no-op, not an unload receipt; `status().cache` is not a CUDA cleanup receipt.
- T12-owned: `ollama.py` and `llama_cpp.py`. T13 delegates to `unload_configured_models(timeout_seconds, should_stop, deadline)`; do not duplicate inventory/unload requests or edit owner files. Require a post-unload loaded-row receipt before reporting success.
- T17-owned: service transcription and vision files. T17 supplied and T13 applied its candidate patch for `transcribe(..., cancel_event=...)`; HTTP gaming signals active events and waits up to 4.5 seconds. Preserve owner files except through owner-scoped patches.
- Root remains read-only. Produce root-current scoped patches and receipts for T20.

## Steps

1. Inventory current candidate/root interfaces and T11/T12/T17 ownership; note incompatible signatures without editing shared files.
2. Implement T13 adapters in `operational_mode.py`: bounded owner-delegated Ollama unload, per-component status before/after, bounded owner-supported release calls, component-reported cache cleanup receipts (or `not_reported`), and honest statuses. Never treat an unload acknowledgement as verified absence or measured VRAM release.
3. Keep async release ownership active until every worker exits; block new inference and queue dispatch while release owns resources. Defer release when inference or preprocessing remains active.
4. Treat Whisper as process-scoped: block new transcription in gaming, signal the T17-owned cancellation event, wait for synchronous process cleanup, and retain resource ownership on timeout. Do not claim model memory release.
5. Add deterministic fake tests for unload success/failure/deadline, CPU/Ollama/CUDA components, cache cleanup, in-flight deferral, and no stale queued work after gaming.
6. Do not run tests until T02 releases its exclusive slot. Run `git diff --check`, then create root-current scoped patches and verify each with `git apply --check`. Send only scoped patches and exact receipts to T20.
