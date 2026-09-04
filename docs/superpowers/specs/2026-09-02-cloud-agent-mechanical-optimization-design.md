# Cloud Agent Mechanical Optimization Design

## Scope

Reduce cloud-agent latency, duplicate work, terminal HTTP failures and unmeasured cache misses without changing Qwen 2.5/3.5 models, routing, offload, or generation settings.

## Design

The MCP client performs deterministic request preflight for known terminal cases: non-Git diff/impact requests, empty symbol arguments and unavailable command capabilities. It returns a compact terminal result rather than opening a network request. The hub exports a small cache-outcome contract (`cache_hit`, `coalesced`, `cache_layer`) consistently for repository endpoints so callers can reuse a result and telemetry can measure actual endpoint reuse.

Context packing returns a bounded fast deterministic/index result under a foreground deadline. If wider synthesis would exceed the budget, it writes a continuation artifact and returns the artifact cursor. The continuation runs in a mechanical worker path only; it does not submit a generation task or alter a model lane. Identical root/revision/query context requests coalesce through the existing revision cache.

The command broker reports executable capability and terminal rejection before process spawn. Known safe validation commands receive an explicit deadline and cancellation outcome. Optional code-intelligence backends are advertised only when their process health is sound; an unhealthy backend remains quarantined and built-in indexes continue serving requests.

Telemetry records endpoint cache outcomes and per-agent SLO budget decisions. A/B evaluation remains opaque-id, paired, report-only evidence. No optimization can promote or alter routing automatically.

## Error and privacy contract

Terminal client misuse is `success:false`, `terminal:true`, `retryable:false`; it is not retried. Artifacts contain existing bounded response content only. Telemetry continues to exclude prompts, source and model output.

## Verification

Tests prove client preflight avoids transport, context deadline returns continuation, cache outcome reaches endpoint telemetry, command rejection avoids spawn, unhealthy optional backends vanish from capabilities, and SLO decisions remain report-only. Full compile, pytest, selftest, live process telemetry follow.
