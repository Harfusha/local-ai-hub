# Tiered Ollama Runtime Design

## Goal

Run fast local code models and the 9B smart model through separate Ollama endpoints while allowing only one GPU-resident model at a time on the 8GB GPU.

## Runtime topology

- The existing, user-managed Ollama server remains at `127.0.0.1:11434`.
- It serves the fast and background model tiers. Its intended request parallelism remains two.
- Local AI Hub owns a smart Ollama sidecar at `127.0.0.1:11437`. Port `11435` remains Hub's HTTP API and port `11436` remains reserved for the existing background runtime.
- The sidecar serves only `qwen3.5:9b` with one request slot, a 32k context window, Flash Attention, and a `q8_0` KV cache.
- The sidecar must use the existing Ollama model store and never change global user environment variables.

## Routing and VRAM lifecycle

The model tier selects the endpoint. Fast and background tiers route to the external endpoint; smart and reasoning tiers route to the sidecar.

Before Hub dispatches work to either endpoint, it acquires one shared GPU-residency lease. While holding it, Hub requests that the other endpoint unload its active model, waits for a bounded `/api/ps` confirmation, then runs the requested model. Hub releases the lease after request completion. This serializes cross-endpoint model residency without imposing a process-wide lock on unrelated CPU-only work.

The external endpoint remains user-managed. Hub performs best-effort model eviction there only for models it routed. If the external process is unavailable, Hub preserves current existing fallback behavior rather than attempting to start, stop, or reconfigure it.

## Failure handling

- Smart sidecar startup, unload, readiness, and request waits have bounded deadlines.
- A failed sidecar start opens a cooldown and returns the existing fast-path fallback; it never loops or repeatedly respawns.
- A failed eviction is recorded in status and telemetry. Hub does not issue a smart request while the other endpoint still reports a model resident.
- Hub shuts down only its sidecar. It never terminates the user-managed process on `11434`.

## Configuration

Add a `smart_ollama` configuration block for endpoint, enabled state, model, context, parallelism, cache type, Flash Attention, keep-alive, startup timeout, stop timeout, and retry cooldown. Defaults preserve current single-endpoint behavior until the feature is explicitly enabled.

## Observability

Status exposes both endpoint profiles, ownership, active model, residency lease holder, sidecar process state, handoff counters, unload/start failures, and last error. Telemetry records endpoint and handoff outcome as metadata only.

## Tests

Test endpoint selection, sidecar launch configuration, cross-endpoint unload ordering, bounded readiness failure, cooldown behavior, fallback routing, ownership-safe shutdown, and status projection. Tests use a local fake Ollama HTTP server and real runtime orchestration code.
