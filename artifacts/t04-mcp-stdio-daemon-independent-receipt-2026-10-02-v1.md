# T04 MCP daemon-independent stdio receipt

Date: 2026-10-02 (Europe/Prague)
Worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
Branch: `codex/t04-integration-2b33602`

## Change

Added `tests/test_t04_mcp_stdio_daemon_independent.py` only. It runs two real MCP stdio clients against a daemon-off, isolated Hub config, performs initialize/list-tools/call-tool handshake concurrently, and asserts both calls succeed while one Hub child starts. Its timeout case delays the exact spawned child, then verifies timeout reaps that process and releases the startup lock. Test instrumentation also cleans up the successful isolated Hub child through its original `Popen` handle when the MCP server exits.

Test file SHA-256: `B6754BEF4CAE9F24FF6E42E53CC0E624D7B88E0B08895362E16F4131CD2509B2`.

## Verification

Command:

```text
python -B -m pytest -q --tb=short tests/test_t04_mcp_stdio_daemon_independent.py
```

Result: **2 passed in 15.31s**, exit 0.

Command:

```text
python -B -m pytest -q --tb=short tests/test_client_startup_resilience.py -k "readiness_timeout_terminates_only_owned_child_and_cleans_lock or concurrent_offline_requests_share_one_startup or timeout_keeps_lock_while_unreaped_child_is_alive"
```

Result: **3 passed, 9 deselected in 3.12s**, exit 0.

Python AST parse passed; new file has no trailing whitespace. Scoped `git diff --check` for the pre-existing `client.py` and `mcp_server.py` changes passed.

## Ownership and limits

No production file changed in this turn. Existing dirty `client.py` and `mcp_server.py` hunks remain untouched; `/api/context/pack` and root remain untouched. This receipt validates unmanaged cold-start behavior and startup-timeout cleanup; it does not claim managed-supervisor behavior or a full transport suite.
