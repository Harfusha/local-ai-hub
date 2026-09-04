# Cloud-agent delivery and phase-observability design

## Goal

Keep cloud agents responsive without changing existing synchronous calls: a caller may opt into `delivery=auto` with a latency budget; the hub returns a durable async job only when observed endpoint p95 exceeds that budget. Expose queue and service phase timings on generation results and attribute them to HTTP tail metrics.

## Evidence and constraints

- Repository-operation cache, evaluation cohorts, durable async jobs and external-backend circuit breakers already exist.
- Current high tails are inference/queue dominated, so persistent transport pooling or a second admission lane would add complexity without evidence of benefit.
- Default delivery must remain synchronous for compatibility. `async` is explicit; `auto` acts only with a positive budget and sufficient fresh sample history.
- Qwen 9B routing/model configuration is out of scope.

## Design

1. A pure delivery-policy helper validates `sync|async|auto` and selects async only when a positive latency budget is exceeded by observed p95. Sparse history stays synchronous and reports why.
2. Telemetry exposes a bounded, metadata-only HTTP p95 estimator per endpoint. No prompt, source or full path is stored.
3. `/v1/delegate`, `/v1/reason`, `/v1/review`, `/v1/second-opinion`, `/v1/compress`, `/v1/route` and `/v1/delegate/batch` honor the policy before executing. Async output is the existing durable job contract, preserving coalescing and low-priority scheduling.
4. `local_ai_task` forwards `delivery` and `latency_budget_ms`; `submit` remains the direct explicit job API.
5. Local generation results carry only rounded `latency.queue_wait_ms` and `latency.service_ms`; HTTP telemetry reads them into existing phase percentile aggregation.

## Non-goals

- No new MCP tool, polling loop, retry loop, cache key that risks tenant isolation, or Qwen model change.
- No fast-lane admission split: current admission telemetry has no rejections, and async delivery removes long work from foreground handlers.
