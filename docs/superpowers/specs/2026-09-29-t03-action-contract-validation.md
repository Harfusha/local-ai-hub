# T03 Action Contract Validation

## Goal

Make the MCP boundary publish, enforce, and validate contracts per registered action while preserving the existing eight-tool surface and Hub HTTP dispatch.

## Decisions

- Each action has an explicit allowlist. The single-action schema contains only the selector, shared response controls, and fields accepted by that action. The live MCP schema uses an action conditional with the same property set and rejects other properties.
- Runtime argument validation uses the same action allowlist and typed property schemas before MCP calls the handler. Feature-disabled actions retain the HTTP-compatible 403 response; malformed calls return 400.
- Numeric JSON values must be finite. The check applies to top-level and nested input/output values.
- MCP outputs for status, artifact, repo, task, RAG, command, coordination, and work are checked against their action schema. The schemas type only declared stable fields and preserve extra Hub fields; a mismatch becomes a bounded terminal 500 response.
- Unexpected MCP dispatch exceptions become a bounded terminal 500 error. HTTP validation and disabled-feature status semantics are mirrored at the MCP boundary.
- `fallback_used` is protected reliability metadata during response budgeting and compaction.
- Hub-owned daemon auto-start remains outside this T03 contract change. T04 owns its client lifecycle implementation and proof.
- Keep `/api/context/pack`, its route, payload semantics, and Agent 2 ownership unchanged. No T01, T04, or T07 hunks enter the T03 patch.

## Acceptance

1. All registered actions have allowlists; representative action schemas omit unrelated tool-wide arguments, and runtime rejects them before dispatch.
2. The live MCP schema encodes per-action properties, including enabled and disabled batch-replacement fields.
3. Each public tool rejects wrong types in a declared action payload field; unknown response fields remain intact.
4. `NaN`, positive infinity, and negative infinity fail numeric input validation; output numeric fields receive the same finite check.
5. MCP validation, feature-disabled, and unexpected-dispatch errors have tested 400, 403, and 500 envelopes.
6. `fallback_used` survives reliability-protected compaction.
7. Focused contract/dispatch suites pass; the T04 `test_client_transport.py` failure is tracked separately and is not an acceptance claim for T03.

## Boundaries

This work changes the contract registry, MCP boundary validation, and focused tests only. It does not edit the Hub context-pack route, T01 inventory, T04 client lifecycle, T07 replay/journal handlers, or the T09/T21 completion integration.
