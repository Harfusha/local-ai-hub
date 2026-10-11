# Local-only Hub Control Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove remote Hub access and client targeting while retaining local dashboard and MCP operation.

**Architecture:** Bind and route every Hub client to IPv4 loopback. Reject remote-enable and host/origin override keys at config and server boundaries.

**Tech Stack:** Python 3.11+, pytest, TOML, Markdown.

**Spec:** `docs/superpowers/specs/2026-10-10-local-only-control-boundary.md`

## Global Constraints

- Keep HTTP bind exactly `127.0.0.1`.
- Enforce that bind in `LocalAIHTTPServer.server_bind`, including direct construction paths.
- Keep dashboard and stdio MCP transport functional.
- Preserve same-machine Browser Bridge; it cannot target a remote Hub.
- Preserve unrelated dirty audit edits; do not stage or commit.

## Review Focus

- No client host override or remote-enable switch remains in runtime config.
- Non-local host/origin overrides fail closed.
- Canonical architecture, install, update, and troubleshooting docs agree.

## Tasks

- [x] Remove remote config keys and host overrides; force client, supervisor, and in-process transport to loopback.
- [x] Update focused regression tests for removed keys and preserved local transport.
- [x] Update architecture and canonical prompts; add the local-only spec.
- [x] Run one focused validation batch and inspect the scoped diff.
- [x] Close the direct-constructor bind bypass and verify rejection before socket bind.
