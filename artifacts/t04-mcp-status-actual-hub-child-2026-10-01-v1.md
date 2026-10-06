# T04 actual Hub child acceptance receipt v1

Date: 2026-10-01
Candidate: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
Root integration target: `C:\Users\Adam\.local-ai-hub` (read-only in this check)

## Result

Added one test-only acceptance test proving first registered FastMCP `local_ai_status` call starts and uses the real `local_ai_hub.__main__` HTTP server entrypoint, waits for a successful status response, then shuts down and reaps only the owned child. Test uses temporary TOML config, state directory, probe files, and ephemeral loopback port. Ollama, smart Ollama, llama.cpp, code intelligence, Serena, preprocessing, background GPU, and agent state are disabled. CPU-only hardware probe prevents GPU discovery. No user Hub service, production config, credentials, or model were used.

Test asserts the child's exact `Popen.argv`, `LOCAL_AI_CONFIG`, source-first `PYTHONPATH`, child `local_ai_hub.__file__` and `local_ai_hub.__main__` origin, status success, readiness PID/lock state, Windows hidden launch flags, and child process exit/reap. Outer watchdog kills the tracked PID tree on timeout.

## Validation

- Candidate source: `python -B -m pytest -q -s --tb=short tests/test_t04_mcp_status_actual_hub_child.py` — 1 passed in 5.71s. Observed status call elapsed 4.305s; `ensure_server` called once; child PID 118112 exited and was reaped.
- Current root source: same selector with `T04_SOURCE_ROOT=C:\Users\Adam\.local-ai-hub\src` — 1 passed in 5.72s. Status call elapsed 4.267s; `ensure_server` called once; child PID 447376 exited and was reaped.
- Both observed exact argv: `C:\Python313\pythonw.exe -m local_ai_hub --config <temporary isolated-hub.toml>`.
- Candidate child origin: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub\src\local_ai_hub\__main__.py`.
- Root child origin: `C:\Users\Adam\.local-ai-hub\src\local_ai_hub\__main__.py`.
- Windows launch assertions passed: `creationflags=134218240` (`CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`), `STARTF_USESHOWWINDOW=1`, `wShowWindow=0`.
- Root source hashes stayed unchanged: `http_server.py` `4B635B978EF556A69863507D9B7672604068997BE32C55CEFA1E1C1CCCC9C8BE`; `client.py` `5518706E0E81623E3FF0184274BD17F18C9BF7F43D9BC4DD37FD754586B0D056`; `mcp_server.py` `8EC5C493964419233A349A78ECCA6487A78078B6125A7A328980877B3AA132FB`.
- Strict root `git apply --check --whitespace=error` passed for add-file patch. Root test path was absent; no root writes occurred.

## Transfer

- Patch: `handoff/t04-mcp-status-actual-hub-child-2026-10-01-v1.patch`
- Patch SHA-256: `3CB911884C2C13A0E3E85AD9DC3329244AFAC68BE186769B872C90BF5D5F0637`
- Test source SHA-256: `48FBB57D0610AFC5E92305A804C15EF991CD61937428740601FDE37A1C3F4B63`
- Patch is LF-only, 12,889 bytes.

This closes only the real-entrypoint/MCP-status cold-start evidence gap. It does not claim completion of separate T21 adapter/runtime evidence or any live user Hub acceptance.
