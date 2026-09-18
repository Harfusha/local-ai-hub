# Context Ledger + Delta Wave

## Goal

Reduce repeated agent input caused by MCP result replay and lack of session-level
budget visibility, while keeping the existing compact eight-tool MCP surface.

## Design

1. Add a bounded, metadata-only `ContextLedger` under the configured state
   directory. It records per-process/session tool category, request/response
   estimates, saved tokens, cache outcome, and opaque result ids. It never stores
   prompts, source, command output, secrets, or full paths.
2. Extend the response budget layer with opaque result ids and optional delta
   projection. `response_profile=delta` plus `reuse_key` returns added/removed
   metadata for changed results; unchanged results keep the existing reuse-only
   envelope. Default behavior remains full backward-compatible compact output.
3. Add adaptive budgets based on the current ledger pressure: minimal for
   repeated/status/cache calls, compact for normal work, standard/debug only when
   explicitly requested. Hard configured caps remain authoritative.
4. Reuse the existing `local_ai_task(action=batch)` path instead of adding a
   public tool or duplicate repository/command endpoint. Generated instructions
   route independent local tasks there; each item stays bounded and compact.
5. Add a native-shell policy check in the command broker: cap inline stdout/stderr
   and return an artifact pointer for the complete output. Do not change command
   semantics or intercept arbitrary Codex host commands outside the Hub; document
   that host-level interception requires a separate Codex hook.
6. Generate one short ledger/delta contract into the orchestrator and token
   economy skills plus install/update prompts. Keep schemas opt-in and bounded.

## Verification

- Unit tests for ledger redaction, bounded retention, delta add/remove, adaptive
  profiles, and batch failure isolation.
- MCP schema tests for new optional fields and backward-compatible defaults.
- Focused token-economy suite, compile check, diff check, indexed review.
- Full suite and release check when the pre-existing concurrent syntax/runtime
  changes are no longer blocking; never revert those changes.
