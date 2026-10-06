# T04 client transport and HTTP E2E receipt

Date: 2026-10-01 (Europe/Prague)

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
No root writes. `git diff --check` passed; only LF/CRLF advisory for existing dirty files.

## Fresh native test receipts

All commands ran from the candidate worktree with `PYTHONPATH=C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub\src`, `python -B -m pytest -q -p no:cacheprovider --tb=short`.

1. Connection and replay safety (9 selectors):
   - Result: `9 passed in 2.19s`, exit 0.
   - Selectors: pool reuse; identical request coalescing; idle disconnect reconnect; duplicate replay; ambiguous default POST; no coalescing for mutating POST; refusal classification; non-refusal connect failure classification; write-failure outcome unknown.
2. Request-ID and route retry safety (7 selectors):
   - Result: `7 passed in 3.37s`, exit 0.
   - Selectors: safe POST stable request ID; no replay for unclassified mutation or file-writing generate; allowlisted read-only replay; explicit ID on safe retry; malformed ID rejection; distinct IDs not coalesced.
3. HTTP conversation continuation (4 selectors):
   - Result: `4 passed in 10.85s`, exit 0.
   - Includes real HTTP HubClient continuation and production route coverage for next turn, expired ID, and competing continuation.
4. Client path hints (7 selectors):
   - Result: `7 passed in 2.97s`, exit 0.
   - Includes serialization over a real loopback HTTP socket; client-level evidence only.
5. Real child startup and `/api/search`:
   - Selector: `tests/test_client_startup_resilience.py::test_autostart_launches_real_hub_child_and_returns_http_search_result`.
   - Result: `1 passed in 8.55s`, exit 0.
   - Starts the actual child, calls HTTP `/api/search`, checks process ownership/marker, then reaps that child.

Total across these non-overlapping command batches: **28 passed**. The real-child selector ran in the immediately preceding T04 continuation with unchanged candidate source/test hashes.

## Hashes

- `src/local_ai_hub/client.py`: `B582F3DD53B656A7CD56E3D0A4E35F3E099D22452CD7D9060C8FAEFBE3294144`
- `tests/test_client_transport.py`: `777CC424B651130DC96FE4D2EAC21FE6E4C152E1C19C46F18EAE380587F588F3`
- `tests/test_client_path_hints.py`: `D94A3AD064AC9D02E47EB85AE8348B1DB15CBD5DBF1A55AB3334A6C686B3AF5D`
- `tests/test_client_startup_resilience.py`: `7C209E127DA857FF1DE2E379FBB56855CCA9E95E61333BD5578EB924ED35DD31`
- `tests/test_conversation_continue_route_contract.py`: `32065B53B2D187648D8B181D106DCA59043BC609883A723F6760DB039BD2F3D5`
- Root-only test patch `handoff/t04-real-child-startup-root-test.patch`: `DF2A2C5967885E0784EFEEA5BFF13B74DB57B81B3126BE8FBB8B4FDE2FFDFD76`

## Integration boundary

The focused root selector for the real-child test remains T20-owned; this run validates only the T04 candidate. Production MCP-to-service path-hint E2E also remains open: T04's MCP wrapper does not forward `path_hints`, and service-consumer ownership is outside this T04 handoff. Existing root API/query acceptance receipt records a separate 30-pass root batch, but it does not prove the real-child selector or complete MCP-to-service hint path.

## Current-source superseding evidence

The current root overlay hash and fresh owned transport/auth/SSE selectors are recorded in `artifacts/t04-owned-client-current-acceptance-2026-10-01.md`. The current-root path-hint chain now passes through real FastMCP, `HubClient`, HTTP `/api/search`, and `repo_search`; the older open-path-hint statement above describes the T04 candidate branch and predates this root-overlay proof. Root tests remain T20-owned.
