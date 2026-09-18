# Local-model routing enforcement

## Goal

Make semantic work use the configured local model by default. Keep deterministic repository, command, and exact-evidence work deterministic. Keep the cloud agent responsible for coordination, authorized edits, final decisions, and verification.

## Current gap

`local_ai_repo` and `local_ai_command` can finish their deterministic work without creating a local-model handoff. The policy says delegation is the default, but the Hub does not control the native cloud-agent loop. A cloud agent can therefore perform planning, interpretation, and synthesis itself after receiving deterministic evidence.

## Design

### 1. Routing contract

Add a shared routing decision for tool requests:

- deterministic actions remain directly executable;
- semantic actions produce an explicit local-model handoff or are executed through `local_ai_task`;
- cloud-only continuation is allowed only for coordination, mutations, security-sensitive decisions, and final verification;
- unavailable or overloaded local inference returns a bounded fallback reason, never a silent bypass.

The contract must be represented in structured results so agents can act on it without parsing prose.

### 2. Adoption telemetry

Record bounded counters and per-request flags:

- `local_recommended`
- `local_used`
- `bypass_reason`
- `fallback_used`

Expose aggregate adoption rate and bypass counts in status/dashboard output. Do not persist prompts, source text, model output, secrets, or full paths.

### 3. Agent-facing guidance

Update the canonical agent prompts and repository policy with a compact routing sequence: deterministic evidence first, local semantic handoff second, cloud integration last. The guidance must name permitted bypass reasons and require reporting them.

### 4. Failure behavior

If Ollama is unavailable, local inference times out, or VRAM pressure prevents a bounded request, return a structured fallback state. Do not retry indefinitely. Preserve current deterministic functionality.

## Alternatives rejected

- Prompt-only change: low implementation cost, but no enforcement or reliable measurement.
- Full server-side takeover of the cloud-agent loop: stronger control, but incompatible with the Hub boundary and larger risk.

## Testing

Add tests proving:

1. semantic routing marks local delegation as required/recommended;
2. deterministic actions do not invoke semantic routing;
3. explicit fallback carries a reason and remains bounded;
4. telemetry distinguishes recommended, used, bypassed, and fallback requests;
5. existing status and deterministic tool behavior stay compatible.

## Scope boundary

This change does not force local models to edit files, run security decisions, or replace cloud-agent coordination. It fixes the missing handoff and makes bypasses visible.
