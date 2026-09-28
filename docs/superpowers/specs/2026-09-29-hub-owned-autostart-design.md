# Hub-owned on-demand autostart

**Status:** Draft for user review  
**Date:** 2026-09-29

## Purpose

Start the local AI Hub daemon on demand when an eligible client request finds no Hub listener. Bound startup time, prevent duplicate daemons during concurrent requests, and clean up a failed startup without killing a Hub another caller is using.

The existing eight MCP tools and HTTP dispatch contract remain unchanged.

## Current constraints

- `HubClient` already checks the disabled marker, managed-service marker, supervisor PID, and listener before a direct spawn.
- `hub.start.lock` serializes startup owners across processes. Other clients wait for health within their own request budget.
- Startup has configured wait and poll limits. The caller's remaining request budget caps its wait.
- The lock is removed in `finally`, including readiness timeout and spawn failure.
- A successful detached child can outlive the caller. The current lock does not track waiting clients, so a caller must not terminate a child while another caller may still need it.
- Windows startup must use `process_utils.py` helpers to hide the child window and terminate its process tree.

## Behavior

1. The client first attempts the normal HTTP request. Autostart applies only after a loopback connection refusal, and only when autostart is enabled.
2. The client checks existing Hub, disabled-service, and managed-supervisor conditions. It does not bypass a managed service or replace an existing listener.
3. One startup owner acquires the state-directory lock and starts one Hub child. Concurrent clients join the same startup generation and poll health; they do not spawn competing children.
4. Each client uses a monotonic deadline bounded by `min(startup_wait_seconds, remaining_request_timeout)`. No startup or health wait is unbounded.
5. When health succeeds, all waiting clients may continue their existing request flow. The daemon remains running as the Hub service; closing an MCP client does not stop a healthy Hub.
6. When spawn fails, startup returns the existing unavailable result and removes the startup lock.
7. When readiness times out, a shared startup coordinator records waiter ownership before cleanup. The child process tree is terminated and reaped only after the startup generation is marked failed and no live waiter can still use it. If another waiter remains, cleanup is deferred to that generation's final waiter. A caller timeout never kills a healthy or managed Hub.
8. Lock and waiter records contain only process/generation metadata under `server.state_dir`. They do not contain prompts, source text, secrets, or model output.

## Coordination and failure semantics

The startup generation needs an atomic state transition shared by all local callers: `starting`, `ready`, `failed`, or `stopping`. A waiter registers before relying on the generation and removes its registration on every exit. Readiness success and failure cleanup use the same synchronization boundary, so cleanup cannot race a waiter that just observed health.

Stale owner or waiter records are reclaimable only after process-liveness checks. A stale lock never justifies killing a child unless its recorded generation and process identity still match. All process waits and termination operations have fixed bounds. If cleanup cannot confirm process exit within the bound, return an unavailable result and retain enough state for the next startup attempt to detect the remaining process safely.

Public failures keep the current normalized client error shape. No MCP tool, HTTP endpoint, schema, or dispatch behavior changes.

## Test and acceptance criteria

- Connection refusal with autostart disabled does not spawn a child.
- Eligible refusal starts one child and retries the original request within the original deadline.
- Concurrent callers produce at most one child for one state directory and startup generation.
- Existing listener, disabled marker, managed marker, or live supervisor prevents direct spawning.
- Spawn `OSError` returns unavailable and removes `hub.start.lock`.
- Readiness timeout with no remaining waiter terminates and reaps the spawned process tree within the cleanup bound.
- One caller timing out does not terminate a child another live waiter still needs; the last failed waiter performs cleanup once.
- Readiness success preserves the daemon after the initiating client exits.
- Windows child launch is hidden; timeout cleanup terminates the child process tree without leaving descendants.
- Startup and cleanup never exceed configured bounds. Existing eight MCP tools and HTTP dispatch tests remain unchanged and pass.

## Scope exclusions

- No new MCP tools or HTTP endpoints.
- No change to managed-service restart policy, HTTP retry eligibility, request IDs, tool schemas, or `/api/context/pack`.
- No termination of a healthy Hub on request timeout or MCP client shutdown.
- No telemetry containing project paths, prompts, source, secrets, or model output.

## Review note

The waiter-generation synchronization is required to satisfy both timeout cleanup and concurrent-start safety. Implementation must use a repository-supported cross-process primitive; it must not rely on an unsynchronized directory count. If no suitable primitive exists, stop before implementation and revise this design rather than adding an unsafe kill path.
