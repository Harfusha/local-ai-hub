# Agent Fast-Path, Cache, and Telemetry Design

## Goal

Make Local AI Hub demonstrably useful to cloud agents through fast deterministic
and cached paths, correct failure accounting, and trustworthy quality/cost
measurement. Qwen 9B model-performance tuning is explicitly out of scope.

## Observed baseline

- The 30-day aggregate combines `inference` and `http` duration samples when
  calculating p50/p95/p99. It cannot represent an agent-facing latency SLO.
- `cache_hit_rate` measures cache reuse across inference events. Exact cache
  keys already omit tenant and agent, so cross-agent exact reuse is canonical.
- Semantic reuse is deliberately restricted by model, system, options,
  execution profile, context fingerprint, and source family. Relaxing it could
  return a correct answer for the wrong repository context.
- Inference telemetry shows zero retries, degraded results, and fallbacks in
  the live sample. HTTP failures include policy rejections and must not be
  reported as runtime retries or model failures.

## Scope

1. Split telemetry into agent request, local inference, policy rejection, and
   internal/monitoring cohorts. Each cohort exposes count, success rate,
   p50/p95/p99, queue/service time where applicable, and retry/fallback counts.
2. Make dashboard and MCP status label estimates accurately: avoided cloud
   tokens remain estimates; policy rejections, client cancellations, and
   operational failures remain separate.
3. Preserve strict exact/semantic cache correctness. Add cache-decision
   telemetry that identifies cache layer and safe miss category without storing
   prompts or source text.
4. Improve cloud-agent fast paths only through deterministic/index/cache reuse,
   request coalescing, bounded work, and result-state guidance. Do not block a
   request on speculative local-model work.
5. Add repeatable A/B evaluation support for representative agent tasks. It
   records latency, cloud/local token estimates, cache layer, test outcome
   supplied by the caller, and an explicit quality verdict. No quality gain is
   claimed until this data exists.

## Non-goals

- No Qwen 9B model, scheduler, VRAM, context-window, or decoding change.
- No looser semantic cache threshold or reuse across a different context/model
  scope.
- No retries for policy rejection, validation failure, cancellation, or a
  request already marked `in_progress`.
- No collection of prompts, code, model output, secrets, or full project paths
  in telemetry.

## Design

### Cohort telemetry

`TelemetryStore` will classify every event into a stable cohort from its
existing metadata. `agent_http` contains authenticated agent API calls but
excludes dashboard, status, health, and control polling. `inference` contains
local generation. `policy_rejection` records a denied request as an expected
client outcome, not a service error. `internal` holds watchdog and background
events.

Summary queries will calculate percentiles independently for each cohort.
Existing aggregate values remain only as an explicitly labelled diagnostic
aggregate for compatibility. Agent SLO decisions use `agent_http`; local-model
work uses `inference` and is never represented as a fast-path result.

### Cache correctness and observability

Cache keys stay strict. The exact key remains shared across tenants and agents;
semantic keys keep their current context/model/system/options boundary.
Telemetry adds metadata-only `cache_miss_reason` values such as `new_exact_key`,
`context_scope_changed`, `model_scope_changed`, and `semantic_below_threshold`.
The hub can then distinguish low repetition from an implementation defect.

Coalesced calls remain successful reuse. A caller receiving `in_progress` does
not retry the same work; it receives a bounded, machine-readable wait/result
state instead.

### Reliability and retry discipline

Classify failures before retry accounting. Count a retry only when a retryable
runtime attempt occurs. Do not count validation, authorization, policy, client
cancellation, duplicate work, or overload admission responses as retries.
Record the terminal category without message payload. Existing circuit breakers
and bounded runtime retry behavior remain authoritative.

### Quality and savings evaluation

Add a compact evaluation record API behind the existing task/report surface.
Callers submit a task identifier, hub on/off cohort, test outcome when known,
and a human or deterministic quality verdict. Reports compare matched cohorts:
success rate, quality rate, p50/p95/p99, cloud tokens avoided estimate, local
tokens, and cache reuse. Results missing a matched control are labelled
`insufficient_evidence`, never presented as quality or saving gains.

## Acceptance criteria

- Status and dashboard expose separate `agent_http` and `inference` latency
  distributions; neither mixes the other.
- Policy rejections never inflate retry, degradation, or operational failure
  counters.
- Cache reuse remains exact or within the existing semantic scope; regression
  tests prove cross-agent exact reuse and rejected cross-context semantic reuse.
- Repeated identical agent work coalesces or returns cached output without a
  duplicate runtime call.
- Evaluation report labels unmatched or incomplete evidence correctly and
  calculates no quality/saving claim from an estimate alone.
- Existing public MCP tools remain unchanged; new information fits the current
  status/task/report responses.

## Verification

Targeted pytest coverage precedes each production change. Full validation:

```powershell
python -m compileall -q src mcp tools tests
python -m pytest -q
python tools/selftest.py
```
