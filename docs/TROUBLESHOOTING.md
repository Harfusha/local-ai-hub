# Troubleshooting

## Hub will not start
Run `local-ai-hub --version`, `python tools/hubctl.py service-status`, then `python tools/doctor.py`. Invalid TOML now fails fast; fix the reported file/key instead of deleting state blindly. Check that the configured loopback port is free. There should be only one per-user Hub daemon; do not launch one manually for each agent.

## Agent MCP proxy cannot reach the shared daemon
Check `python tools/hubctl.py status` and `/health` first. Start or restart the single user service with `python tools/hubctl.py start` or `restart`, then reconnect the agent. All chats and worktrees under this OS account reuse that service; do not launch another Hub for an MCP client. After reboot, the service starts when the user session is available; a skipped service registration needs manual startup each session. For a wrong-repository or root-scope denial, check that every global repository, task, or memory request sets `root` to the caller's project root and preserves task context; `cwd=install_dir` is the Hub installation, not the repository. Root must be absolute, existing, symlink-free, and inside `security.allowed_roots` (maximum 32; empty default denies). Both MCP API and `HubClient` pass caller root explicitly. The server derives effective tenant; supplied tenant headers/body/query only confirm it, with mismatch rejected as terminal 403. See [Security model](SECURITY_MODEL.md) for principal precedence and derivation.

If the daemon is offline, MCP requests must return a structured error. `request_not_sent` means delivery did not begin; `outcome_unknown` means delivery may have occurred, so do not replay automatically. The T04 client classification is pending integration in this candidate, and T13 auth/lifecycle behavior remains candidate-only and untested. The per-user supervisor owns managed restart and recovery; MCP proxies must not start a competing daemon. `HubClient` may use only bounded, lock-guarded autostart when no managed supervisor or listener owns the installation. If setup reports `detached-fallback`, reboot persistence is unverified; do not launch another Hub. Use the platform service identity and acceptance checks in [Operations](OPERATIONS.md#shared-daemon-install-update-and-acceptance-matrix).

## Serena unavailable
Check the code-intelligence status in the dashboard, rediscover executables, then reset sessions. Setup can reinstall isolated tool environments. Deterministic/code-index/search operations should continue while these backends are degraded.

## Context references a deleted temp repository
Use a stable project root. The API returns a structured stale/degraded result rather than crashing; callers should discard the obsolete root.

## Commands are blocked
Use `local_ai_command(action="classify")`. Unknown, mutating, install/deploy/publish/clean and unsafe formatter commands are denied by default. Run intentional mutation directly under user control rather than weakening the hub policy.

## Dashboard authentication
Run `python tools/hubctl.py dashboard` to print the dashboard URL (default `http://127.0.0.1:11435/dashboard`). Set the API token in the dashboard toolbar for the current browser session. The token is not placed in the URL. No remote Hub access/control mode exists. HTTP and HubClient use only `127.0.0.1`; remote host, client-host, and origin overrides are rejected. Non-loopback binds and anonymous API access are unsupported. `/health` is public liveness; `/ready` and protected API routes require a token with the `monitor` permission for readiness.
# Frontend vision review

## Offline fixture test fails

Run `python -m pytest -q tests/test_frontend_review_e2e.py`. It is deliberately independent of Ollama, a GPU, a browser, login state, and network access. If it fails after changing the fixture, preserve the stable `data-testid` hooks and the `element_id` mapping used by the test; do not replace it with a live-browser smoke test.

## Local model unavailable

The offline contract still runs without a local generation backend. For live review, use an already configured llama.cpp vision route only when the Intel hardware/profile requires it; the Hub never installs or starts llama.cpp automatically, and never starts Ollama under the default policy. Verify the vision route with `python tools/doctor.py`. A missing model should be reported as a bounded capability/dependency failure, not silently replaced with a cloud call.

## Current-tab capture errors

Capture is explicit and current-tab bound. Keep the target tab open and on the expected origin, grant only the requested local extension permission, and retry from that tab. The bridge must not navigate, submit forms, perform login, collect cookies, or capture network request bodies. A timeout, navigation race, closed tab, or origin mismatch is expected to fail closed.

## Findings do not map to source

Check that the bundle contains `redaction: "none"`, unique stable DOM `element_id` values, accessibility/computed-style evidence, and bounded runtime references. The coder packet intentionally contains the relevant DOM elements plus their ancestors and only the repository files selected by the repository context step; oversized or malformed context must be fixed at the producer.
