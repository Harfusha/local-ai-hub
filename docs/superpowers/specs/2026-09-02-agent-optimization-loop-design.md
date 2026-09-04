# Agent optimization loop design

## Scope

Improve cloud-agent cache reuse, tail latency, validation, telemetry, and evidence-led rollout.
Do not alter any Qwen 3.5 or Qwen 2.5 model, offload, context, or routing setting.

## Design

- Telemetry exposes an explicit process/deployment cohort so historical failures cannot
  be mistaken for current behavior.
- Repository-heavy endpoints use the existing durable job store when `delivery=auto`
  observes a breached foreground budget. Their synchronous behavior remains default.
- Cache prewarming uses only canonical deterministic/index/context capsules and root
  revision keys. It never persists prompts or generated model output.
- Command capabilities are discovered once per process and unavailable executables are
  terminal local results with a documented fallback, not retries.
- Partial context responses become bounded artifact references with continuation data.
- Request-attached evaluations and per-agent SLO cohorts remain evidence-only; promotion
  never changes routing automatically.

## Safety

All new controls are opt-in or report-only, have bounded waiting, and retain fresh-state
checks. Telemetry stores only opaque identifiers and numeric metadata.
