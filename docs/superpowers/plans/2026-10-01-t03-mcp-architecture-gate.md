# T03 MCP Architecture Gate Plan

**Goal:** Close T03 MCP acceptance with a daemon-off HTTP auto-start path, action-specific typed input/output contracts, explicit live FastMCP schemas, and registry parity.

**Architecture:** Keep the eight-tool MCP surface and HTTP as the only Hub transport. Reuse the existing bounded `HubClient(auto_start=True)` lifecycle. Derive tool-list schemas from the same action contracts used by pre-dispatch validation and output validation; keep unknown Hub fields compatible.

**Scope:** T03-owned contract registry, MCP registration/dispatch seams, and focused tests only. Preserve all inherited dirty work. Do not edit T14 response-budget hunks, T21 path-hint adapters, `/api/context/pack`, root, or T04/T07-owned paths.

## Tasks

1. **Restore and pin checkpoint.** Record assigned worktree HEAD, dirty paths, existing T03 acceptance receipt, and ownership boundaries. Do not clean or reset.
2. **Close status output-shape gap with TDD.** Add tests requiring stable typed success/failure shapes for `local_ai_status.full` and `local_ai_status.agent_state`; reject malformed declared fields while preserving extras.
3. **Keep wire schemas derived.** Ensure FastMCP's registered `inputSchema` and `outputSchema` equal feature-aware contract builders for all eight tools; preserve pre-dispatch argument rejection and missing-SDK import/error behavior.
4. **Verify acceptance.** Run only focused contract, dispatch, daemon-off, missing-SDK, and live-registry tests. Capture exact commands, results, and postimage hashes. Use bounded native pytest only because Hub command tools are unavailable.
5. **Handoff.** Produce a T03-owned patch and receipt for T20; inspect patch paths to exclude inherited owner hunks. Stop if any required implementation would cross an owner boundary.
