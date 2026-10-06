# T04 review of PR #3 safe-request retry — 2026-10-02

PR: [Harfusha/local-ai-hub#3](https://github.com/Harfusha/local-ai-hub/pull/3), one commit `2f5e6d0`, title `fixes`; review restricted to `client.py` safe-request retry behavior. No prompt/docs changes or unrelated PR hunks adopted.

## Comparison and finding

T04 client already creates one `request_id` and serialized body per call; every `once()` attempt reuses them. `post()` marks only allowlisted read-only operations replay-safe. Initial HTTP `in_progress` responses already use a single `duplicate_deadline` and `sleep(min(retry_after, remaining))`. Auto-start already passes the remaining time to `ensure_server(timeout=remaining)`. A mutating POST with an ambiguous after-write failure is not retried; the strengthened selector asserts this even with `auto_start=True`.

Missing behavior: after an explicitly replay-safe request has a transport failure and the Hub restarts, T04 called `once(remaining)` once. If that retry received HTTP 503 `in_progress`, it returned the intermediate response instead of continuing the existing bounded duplicate-request loop.

T04-only correction in this worktree extracts `request_until_terminal()` and calls it for initial and post-start attempts. It reuses the same request ID/body, keeps `ensure_server(timeout=remaining)`, and keeps retry backoff capped by the original deadline. It does not broaden replay-safe routes or retry an ambiguous mutation.

PR #3 uses the same retry-loop idea after server restart, but its visible hunk calls `ensure_server()` without the remaining request timeout. T04 keeps that startup wait bounded. No prompt/runtime-policy text changed.

## Focused tests added/strengthened

- Added `test_safe_post_restart_retry_waits_for_terminal_response_within_deadline`: first attempt fails at transport, startup consumes part of budget, retry receives 503 `in_progress`, backoff occurs, third attempt succeeds; request ID and body remain stable; startup and network timeout values stay within original one-second budget.
- Strengthened `test_unsafe_post_is_not_replayed_after_transport_failure`: auto-start enabled, ambiguous after-write mutation failure; exactly one request, no startup/retry.
- Existing safe GET and client retry selectors remain in the focused test module.

## Scope and hashes

Worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`; HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`.

- `src/local_ai_hub/client.py`: pre-edit SHA-256 `338A2C40C982E2A079B99F2A9C7044630F70788082B6219AA6174F1EAAB82098`; post-edit SHA-256 `B6CB4E36241F3865BACF37CFA57A9A00CDD5ABA7EDD128A5B20DC2351F8770B5`.
- `tests/test_t04_client_retry_acceptance.py`: post-edit SHA-256 `0939AB490DAC09EA39488EBACF2852B6B683BE3F7B28FBC9533EFE2F27D2CC7D`. Pre-edit hash was not captured; original selectors/content retained, then focused assertions added.
- Only these two T04-owned paths changed for PR #3. `http_server.py`, `test_command_replay_policy.py`, prompts, `/api/context/pack`, and root checkout untouched. T07's stated planned path `tests/test_command_replay_policy.py` does not overlap.

## Validation status

No tests run after these new edits. T20 says slot A is closed and slot D belongs to T15; new targeted tests need next exclusive slot. The suggested next command is:

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_client_retry_acceptance.py tests/test_client_transport.py::test_client_replays_duplicate_request_until_owner_finishes tests/test_client_startup_resilience.py::test_first_post_starts_daemon_and_retries_same_id_and_path_hints`

`local_ai_repo(action="solve")` for this comparison hung and was stopped once; no repeat. Follow-up `review_diff` returned terminal `400 unexpected argument for local_ai_repo: paths`; manual review is recorded above. No production conclusion beyond the source-level finding until the new targeted tests run.

## T20-directed retry-scope amendment (2026-10-02)

This amendment supersedes the earlier note that the pre-send retry exception remained unchanged.

- Retry branch now runs only when `replay_safe is True`; `False` explicitly skips both startup and retry, including a proven pre-send refusal.
- Added `/api/search` to the existing read-only POST allowlist. This preserves cold-start search/path-hint behavior while keeping mutation routes non-replayable.
- Updated `test_unclassified_mutation_pre_send_failure_does_not_autostart_or_retry` to assert no child spawn, and added `test_explicit_replay_safe_false_never_retries_pre_send_mutation_failure`. Existing ambiguous-after-write mutation test still asserts one attempt. Safe-restart test continues to assert same request ID/body, bounded startup wait, bounded backoff, and terminal response after intermediate 503.
- Post-amendment SHA-256: `src/local_ai_hub/client.py` `89633C62382606CC6E5B134158D2992C061B3DA7B9ED46CE30B16803C8613E8D`; `tests/test_t04_client_retry_acceptance.py` `47A1F4B9DC1D2568D2D1C63E9825B8B7B182478E60468D0702AE017F2A9EBBDD`; `tests/test_client_startup_resilience.py` `ECAAF238CB64046D22AB825DB7BB0A85EB98F75EDBD330C640FEA44E880627E4`.
- Previous-to-current preimages for this amendment: client `B6CB4E36241F3865BACF37CFA57A9A00CDD5ABA7EDD128A5B20DC2351F8770B5`; retry test `0939AB490DAC09EA39488EBACF2852B6B683BE3F7B28FBC9533EFE2F27D2CC7D`; startup test `67264628ED9221610C346594B6385851BAC7B3D1351B0A138A426B1A03D86D9D`.
- No tests run after amendment. T20 reported slot D assigned to T15. Next T04 command after a fresh slot:

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_client_retry_acceptance.py tests/test_client_transport.py::test_client_replays_duplicate_request_until_owner_finishes tests/test_client_startup_resilience.py::test_first_post_starts_daemon_and_retries_same_id_and_path_hints tests/test_client_startup_resilience.py::test_unclassified_mutation_pre_send_failure_does_not_autostart_or_retry`

No prompt changes, root edits, or `/api/context/pack` edits.

## Explicit replay-safe / in-progress clarification (2026-10-02)

This amendment supersedes the prior scope note and source hashes.

- `request_until_terminal()` now polls only when `replay_safe is True` and response has both `in_progress=true` and `retryable=true`. Explicit false returns that response once. A terminal 503 without `in_progress` returns once even for a replay-safe call.
- `/api/search` remains explicitly allowlisted as read-only so its startup fallback stays replay-safe.
- Added `test_explicit_replay_safe_false_does_not_poll_in_progress_mutation` and `test_replay_safe_post_does_not_retry_terminal_503`; retained safe-after-restart terminal polling and bounded-deadline coverage. Startup mutation test proves pre-send refusal with false does not start daemon or retry.
- Latest hashes: `client.py` `ECDFAE20344CD8BE228CD2E2A034F787314627856E5EA588EEA4CCB99CB68879`; `test_t04_client_retry_acceptance.py` `FA3958885FD096A0748CD438D9CDFB45671092CA5777BF1A824F2D95CBC8269E`; `test_client_startup_resilience.py` `ECAAF238CB64046D22AB825DB7BB0A85EB98F75EDBD330C640FEA44E880627E4`.
- Preimages for this amendment: client `89633C62382606CC6E5B134158D2992C061B3DA7B9ED46CE30B16803C8613E8D`; retry test `47A1F4B9DC1D2568D2D1C63E9825B8B7B182478E60468D0702AE017F2A9EBBDD`; startup test unchanged from prior amendment.
- These newest source/test bytes remain unvalidated. T20 slot D is assigned to T15. Run focused command from this receipt only after a fresh T04 slot.

## Path-hints fixture alignment (2026-10-02)

The loopback HTTP test `test_post_transmits_path_hints_over_http_and_returns_search_result` now uses the exact T03/T21 contract tuple `path=templates/element`, `purpose=repository_search`, `scope=repository_search`; expected result path is `templates/element/button.py`. The test file SHA-256 is `032BF90E3B4C39CEAFAAE77D1750EDB9EC7A97BDFC74D1382EA4FE5E9DEACE24` (prior baseline `D94A3AD064AC9D02E47EB85AE8348B1DB15CBD5DBF1A55AB3334A6C686B3AF5D`). `client.py` already supports optional bounded `path_hints` on `/api/search`; its SHA-256 remains `ECDFAE20344CD8BE228CD2E2A034F787314627856E5EA588EEA4CCB99CB68879`. No test ran after the fixture edit; run the focused path-hints and retry selectors only after T20 grants a fresh exclusive T04 slot. Current candidate MCP wrapper still lacks `path_hints`; T03 owns that wrapper, so this receipt proves client transport only, not the full MCP-to-service chain.

## MCP path-hints forwarding amendment (2026-10-02)

Per the latest T04 scope instruction, `local_ai_repo` and `_local_ai_repo_impl` now accept optional `path_hints`; the `search` action passes them to `HubClient.post` for `/api/search`. The client remains responsible for filtering fields, enforcing the 64-item cap, and serializing only on the approved search route. The new optional parameter is appended to both signatures and the wrapper call to preserve existing positional arguments. Existing `tests/test_t04_root_path_hint_chain.py::test_registered_repo_search_forwards_hints_over_real_root_http` covers the registered MCP tool, real HTTP payload, service receipt, empty hints, invalid paths, and result isolation; it has not been run after this edit. No tests ran because T20 slot G is UNKNOWN. Static checks passed: `git diff --check`; `ast.parse` on six source/test files (`AST_PARSE_PASS 6`). Current file hashes: `mcp_server.py` `1D7C6E0C0FE37FB61C23BC203E179B05E472175326DD8DDCCB388916EA1827A`; `client.py` `ECDFAE20344CD8BE228CD2E2A034F787314627856E5EA588EEA4CCB99CB68879`; `test_t04_root_path_hint_chain.py` `95C85C244B968546581F5158BC29FD60DDC81BA5108C670440426CAEFEA3DF20`. The existing T07 request-ID and unrelated investigation-option hunks in `mcp_server.py` were preserved.

After T20 grants an exclusive slot, run:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_root_path_hint_chain.py::test_registered_repo_search_forwards_hints_over_real_root_http tests/test_client_path_hints.py tests/test_t04_client_retry_acceptance.py tests/test_client_transport.py::test_client_replays_duplicate_request_until_owner_finishes tests/test_client_startup_resilience.py::test_first_post_starts_daemon_and_retries_same_id_and_path_hints tests/test_client_startup_resilience.py::test_unclassified_mutation_pre_send_failure_does_not_autostart_or_retry`

## T07 f374 replay-safe guard handoff (2026-10-02)

T07 ported the minimal `replay_safe && in_progress && retryable` polling guard into f374 `src/local_ai_hub/client.py` and added the explicit-false regression to f374 `tests/test_client_transport.py`, reusing its existing fixture and imports. Keep T04 branch unchanged as a separate acceptance packet. During later integration, deduplicate the matching source guard and retain both T04 and T07 acceptance coverage scopes. The approved T20 slot-I selector returned `Transport closed` with `outcome UNKNOWN`; no retry or native fallback occurred. T20 was notified and released slot I. This is not a passing test receipt and does not validate either worktree's current bytes.

## Empty path-hints acceptance fix (2026-10-02)

Source review found the existing registered-tool acceptance selector expects `path_hints=[]` to behave like omitted hints. `HubClient.post()` previously serialized an empty list, so the HTTP body included `path_hints: []` and the service received an explicit empty value. Changed the `/api/search` branch to add the field only when the sequence is non-empty; added `tests/test_client_path_hints.py::test_post_omits_empty_path_hints`. Current SHA-256: `src/local_ai_hub/client.py` `CA624A5356A8632AD0CF603DBB8A9B37221DB68F6FD2B97FF8DE5EE0D47153B2`; `tests/test_client_path_hints.py` `6FC0EF7185D6EEC8313C7919AB9346BBD28A1F72820F1A36173D71F094309A6D`. Static checks passed: `git diff --check` and `ast.parse` for both files. No tests ran. Request an exclusive T04 slot from T20 before running:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_path_hints.py tests/test_t04_root_path_hint_chain.py::test_registered_repo_search_forwards_hints_over_real_root_http tests/test_t04_client_retry_acceptance.py tests/test_client_transport.py::test_client_replays_duplicate_request_until_owner_finishes tests/test_client_startup_resilience.py::test_first_post_starts_daemon_and_retries_same_id_and_path_hints tests/test_client_startup_resilience.py::test_unclassified_mutation_pre_send_failure_does_not_autostart_or_retry`

## Slot-I attribution correction (2026-10-02)

T20 clarified that slot I belonged to T07, not T04. The prior T07 handoff paragraph records T07's `Transport closed` / `outcome UNKNOWN`; it must not be treated as a T04 validation attempt or result. T04 has no slot-I test receipt. The T04 path-hints and retry changes remain unverified; the older slot-A in-process receipt is historical and predates current bytes.
