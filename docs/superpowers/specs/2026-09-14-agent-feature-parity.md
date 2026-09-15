# Agent feature parity

## Goal

Make every enabled Local AI Hub capability discoverable through MCP descriptions, generated skills, and managed instructions. Explicitly trigger Agent OS for meaningful multi-step work so agents use durable task state, checkpoints, context, and receipt-gated completion.

## Constraints

- Keep the existing compact MCP tool surface and derive exposed capabilities from `FeatureSet`.
- Do not enable a feature whose configuration gate is off; `local_ai_work` stays omitted when `work_orchestrator` is disabled.
- Keep trivial one-step tasks lightweight; use Agent OS for non-trivial, multi-step, long-running, or delegated work.
- Preserve unrelated working-tree changes.

## Acceptance

- MCP descriptions accurately summarize all enabled Agent OS action families and their lifecycle.
- Generated and checked-in skills, references, global policy, and install/update prompts carry the same trigger and lifecycle guidance.
- Tests cover enabled and disabled feature configurations, including conditional work-tool exposure.
- Focused tests and repository checks pass.
