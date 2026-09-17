# Minified JSON Serialization Design

## Goal

Use minified JSON for all production runtime, transport, cache, state, async-job, and telemetry serialization while preserving intentionally human-readable JSON exports, debug artifacts, documentation, and test fixtures.

## Design

- Add one shared production serializer with `ensure_ascii=False`, compact separators, and existing `default` behavior where required.
- Replace production `json.dumps` calls that feed HTTP/MCP responses, caches, persisted state, async jobs, telemetry, hashes, and internal wire payloads.
- Keep explicit `indent=2` serialization for human-facing exports and artifact/debug presentation.
- Do not monkey-patch `json.dumps`; do not alter free-form text, source code, logs, or model output merely to remove whitespace.
- Preserve JSON round-trip semantics, Unicode, key ordering behavior unless a caller already requests sorting, and existing size/truncation limits.

## Testing

- Add focused tests for the shared serializer and representative MCP/runtime paths.
- Assert compact separators and JSON round-trip equality.
- Assert explicit human-readable exports remain formatted.
- Run focused tests, then release check, compileall, full pytest, and selftest.

## Scope

Existing unrelated worktree changes remain untouched. No schema change is intended; only JSON representation changes.
