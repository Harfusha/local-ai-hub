# Agent-facing response signal cleanup

## Goal

Make routine Local AI Hub responses contain only information an agent needs to act, continue work, or report a result. Accounting, protocol, cache, and diagnostic metadata must stay out of routine responses unless detailed diagnostics are explicitly enabled.

## Requirements

- Apply the same projection to every MCP tool result, including early validation, authorization, mode-gate, budget-rejection, and output-contract failures.
- Hide `response_budget`, `token_efficiency`, `request_id`, and cache-only `reused` metadata from ordinary responses. Keep response-size enforcement and telemetry accounting internal.
- Keep actionable result content, errors, status, terminal/retryable and mutation state, task/job/operation identifiers, evidence/artifact/context identity, workspace identity, useful pagination, and genuine truncation/partial state.
- Keep detailed diagnostics opt-in: `response_profile="debug"` requires the dashboard diagnostics toggle, or an explicit `[agent_output].detailed_diagnostics` / `[telemetry].agent_diagnostics` setting. Full telemetry capture alone must not add diagnostics to ordinary responses. Caller-provided `extra_fields` must not enable diagnostics.
- Apply the same rule to agent-facing HTTP responses after budget reconciliation. Preserve diagnostic/aggregate endpoints and dashboard behavior.
- Do not flatten caller-authored payloads, canonical task memory, evidence, or result documents.

## Acceptance

- Routine successful, failed, and truncated MCP responses omit accounting and transport metadata after all post-processing.
- Explicit dashboard diagnostics still expose the diagnostic fields.
- Existing response-budget enforcement, telemetry capture, retry safety, task lifecycle, evidence, and pagination semantics remain intact.
