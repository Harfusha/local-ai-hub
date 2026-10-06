# T04 public HTTP handoff receipt — 2026-10-01 v1

## Patch

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`, HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`.
- Test: `tests/test_t04_public_http_stream_acceptance.py`, SHA-256 `89CABF4A047CBFF388612B550BED7D1689B1A9937EE0A8C910C59680C7A282CD`.
- Handoff patch: `handoff/t04-public-http-conversation-auth-cancel-deadline-2026-10-01-v2.patch`, SHA-256 `9BB4416E074EED6A5424E3F21B3E2C851FFFEF354E1749FC52A06276B92203D5`.
- v2 supersedes v1. Apply v2 only; both add same test path.
- `git apply --check` against current root passed. Destination test path is absent in root. Patch adds test only; no root files changed.

## Coverage

One bounded fixture uses actual `LocalAIHTTPServer`/`Handler`, actual `HubClient`, temporary state/config, and actual AgentStateStore. Generation is stubbed; Ollama/llama/GPU and live Hub are not used.

The test covers:
- unauthenticated public conversation POST returns 401 without generation;
- authenticated conversation start and continuation traverse actual public HTTP routes;
- unauthenticated SSE GET returns 401;
- authenticated SSE GET replays a persisted event;
- cancel interrupts a blocked client read while server has no event to deliver;
- transport deadline returns `retry_timeout=true` and `outcome_unknown=true`.

## Validation

Candidate, strict resource-warning mode:
`python -X tracemalloc=6 -B -m pytest -q -p no:cacheprovider -W error::ResourceWarning --tb=short tests/test_t04_public_http_stream_acceptance.py::test_public_http_conversation_auth_stream_cancel_and_deadline`

Result: `1 passed in 11.08s`, exit 0.

Current root source, import origin verified as `C:\Users\Adam\.local-ai-hub\src\local_ai_hub\__init__.py`; source hashes held constant before/after test:
- `http_server.py`: `4B635B978EF556A69863507D9B7672604068997BE32C55CEFA1E1C1CCCC9C8BE`
- `client.py`: `5518706E0E81623E3FF0184274BD17F18C9BF7F43D9BC4DD37FD754586B0D056`
- `mcp_server.py`: `8EC5C493964419233A349A78ECCA6487A78078B6125A7A328980877B3AA132FB`

Against those root hashes:
- Path-hint public MCP/HTTP chain plus this public conversation/auth/cancel/deadline selector: `2 passed in 13.58s`.
- Daemon-off MCP status plus MCP-owned autostart/payload fixture: `2 passed in 11.60s`.
- Candidate actual-child cold start, HTTP search result, PID lock and owned-child cleanup: `1 passed in 10.21s`.

No T02 benchmark ran. Root checkout stayed unchanged by this task.

## Remaining

T20 must integrate this add-file test patch and attach it to its current root receipt. T04 still awaits T21 adapter/runtime evidence and final integration review; this receipt does not claim full acceptance.
