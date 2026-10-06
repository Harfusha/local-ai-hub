# T04 public HTTP handoff receipt — 2026-10-01 v3

Supersedes handoff receipts v1/v2. Use patch v3 only. v2's CRLF patch and v2 receipt's mistyped filename are superseded; no old artifact was overwritten.

## Patch and candidate

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`.
- Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`.
- Test file: `tests/test_t04_public_http_stream_acceptance.py`.
- Test SHA-256: `9E6A8FE9FD52B8DDBC721663FC2E85CB19BA20009B44B7BD977B7D4FA135B510`.
- LF-only patch: `handoff/t04-public-http-conversation-auth-cancel-deadline-2026-10-01-v3.patch`.
- Patch SHA-256: `6E22966E5F34DB964531B43A8309E5B62FBB1E6226F8B20B7609FCA520C63D59`.
- Patch contains only one new test file; no production client or server source.
- Current-root `git apply --check --whitespace=error` passed. Root destination is absent.

## Fixture safety and cleanup

The test uses actual `LocalAIHTTPServer`/`Handler`, `HubClient`, temporary config/state, and real AgentStateStore. Generation is stubbed. No live Hub/GPU/model service is used.

Every resource acquisition is inside `ExitStack`: HTTP server, app, server thread, clients, and streams. Teardown closes streams/clients, shuts server, joins accept thread within 2 seconds and asserts it stopped, closes app/server. Published cancellation/deadline events wake server-side stream handlers after client closure. Assertions unchanged.

## Exact current-root source pins

Root HEAD remained `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Source origin was verified as `C:\Users\Adam\.local-ai-hub\src\local_ai_hub\__init__.py`. Hashes matched before/after public HTTP tests:

- `src/local_ai_hub/http_server.py`: `4B635B978EF556A69863507D9B7672604068997BE32C55CEFA1E1C1CCCC9C8BE`
- `src/local_ai_hub/client.py`: `5518706E0E81623E3FF0184274BD17F18C9BF7F43D9BC4DD37FD754586B0D056`
- `src/local_ai_hub/mcp_server.py`: `8EC5C493964419233A349A78ECCA6487A78078B6125A7A328980877B3AA132FB`

## Receipts

- Candidate public conversation/auth/SSE cancel/deadline selector with `ResourceWarning` as error: `1 passed in 9.76s`.
- Same selector against exact root source pins above: `1 passed in 6.24s`.
- Current-root path-hint public MCP/HTTP E2E against same pins: `1 passed`; in its combined fresh run with the public selector, `2 passed in 13.58s`.
- Current-root daemon-off MCP status plus MCP autostart/payload fixture: `2 passed in 11.60s`.
- Candidate real-child autostart/search/PID-lock/owned-child cleanup: `1 passed in 10.21s`.
- Current-root request-ID preflight plus safe-GET stable retry and unsafe-POST no-replay: `3 passed in 2.69s`.

Root stayed read-only. No T02 benchmark ran.

## Status

Concrete T20 artifact ready. T04 remains partial pending T20 patch integration/current integrated receipt and T21 adapter/runtime proof. This receipt does not mark the full goal complete.
