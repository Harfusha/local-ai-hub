# T04 current-root acceptance handoff — 2026-10-01 v4

Supersedes handoff receipts v1-v3 for final current-root pins and the full bounded T04 acceptance set. Use LF patch v3 only.

## Handoff artifact

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`, HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`.
- New test SHA-256: `9E6A8FE9FD52B8DDBC721663FC2E85CB19BA20009B44B7BD977B7D4FA135B510`.
- Patch: `handoff/t04-public-http-conversation-auth-cancel-deadline-2026-10-01-v3.patch`.
- Patch SHA-256: `6E22966E5F34DB964531B43A8309E5B62FBB1E6226F8B20B7609FCA520C63D59`.
- Patch adds one test file only. Current-root `git apply --check --whitespace=error` passes; destination remains absent. No root writes by T04.

## Root snapshot and source origin

- Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Import origin verified: `C:\Users\Adam\.local-ai-hub\src\local_ai_hub\__init__.py`.
- Root source hashes held stable across relevant E2Es:
  - `http_server.py`: `4B635B978EF556A69863507D9B7672604068997BE32C55CEFA1E1C1CCCC9C8BE`
  - `client.py`: `5518706E0E81623E3FF0184274BD17F18C9BF7F43D9BC4DD37FD754586B0D056`
  - `mcp_server.py`: `8EC5C493964419233A349A78ECCA6487A78078B6125A7A328980877B3AA132FB`

## T04 acceptance receipts

- Public conversation/auth/SSE cancel/deadline fixture, current root: `1 passed in 6.24s`. Covers unauthenticated conversation 401 before generation, authenticated conversation start/continue, unauthenticated SSE 401, real event replay, cancellation of blocked read, deadline `retry_timeout` and `outcome_unknown`.
- Same selector in candidate with `ResourceWarning` promoted to error: `1 passed in 9.76s`.
- Root path-hint public MCP/HTTP chain + public conversation/auth/cancel/deadline test: `2 passed in 13.58s`.
- Daemon-off MCP status + MCP-owned autostart and exact HTTP payload fixture, current root: `2 passed in 11.60s`.
- Request-ID preflight + safe GET stable-ID retry + unsafe POST no replay, current root: `3 passed in 2.69s`.
- Malformed JSON GET/POST classification/no ambiguous replay, current root: `3 passed in 1.75s`.
- Readiness timeout stops only owned child, missing executable preserves pre-send failure, actual local child cold-start returns real `/api/search` result and cleanup owns child/PID lock, current root: `3 passed in 12.36s`.

Fixtures use temporary state and loopback servers; generation is stubbed; external model backends disabled. No live Hub, GPU, or T02 benchmark.

## Status

T04 behavioral acceptance is covered on current root by focused tests, but integration remains pending: T20 has not applied the one-file test patch or produced integrated receipt. T21 adapter/runtime proof remains separate. Coverage drift remains T01/T20-owned and did not block these T04 checks. Do not mark full T04 or consolidated goal done yet.
