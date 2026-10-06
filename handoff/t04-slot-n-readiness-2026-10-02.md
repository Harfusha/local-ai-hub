# T04 slot-N validation readiness (2026-10-02)

## Candidate identity and state

- Root: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
- Branch: `codex/t04-integration-2b33602`
- HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
- No active pytest process in this T04 worktree at handoff time.
- T20 said slot N is provisional and requires this package before explicit GO. No tests have run for current bytes.
- T20 corrected prior slot-I attribution: slot I belonged to T07. Its `Transport closed` / `outcome UNKNOWN` is not T04 evidence. T04's older slot-A in-process pass is historical and does not validate current hashes.

## T04 acceptance batch files

These files form current client/in-process/path-hints/retry acceptance batch. Hashes are SHA-256 of current file bytes.

| Path | SHA-256 |
|---|---|
| `src/local_ai_hub/client.py` | `CA624A5356A8632AD0CF603DBB8A9B37221DB68F6FD2B97FF8DE5EE0D47153B2` |
| `src/local_ai_hub/inprocess_transport.py` | `25528A07417E5FDA4D86A954A0A44B73C30145A1FABC5B5E6244D0C3CEE51B47` |
| `src/local_ai_hub/operational_mode.py` | `3A083FA9DFF1B42E634B434ECAB8519916EBDC825579920CCF448B84AEC8F145` |
| `tests/test_inprocess_transport.py` | `6993215113A42C8DE0077C5160FBCF537663C0E6E7DA347C94B643272FE74FEE` |
| `tests/test_client_transport.py` | `777CC424B651130DC96FE4D2EAC21FE6E4C152E1C19C46F18EAE380587F588F3` |
| `tests/test_t04_client_request_id_http.py` | `F0C80022420D81C7F78AB4438CDA5B2E8C0C29396426D6E98A5737D4F79D8CC0` |
| `tests/test_client_path_hints.py` | `6FC0EF7185D6EEC8313C7919AB9346BBD28A1F72820F1A36173D71F094309A6D` |
| `tests/test_t04_root_path_hint_chain.py` | `95C85C244B968546581F5158BC29FD60DDC81BA5108C670440426CAEFEA3DF20` |
| `tests/test_t04_client_retry_acceptance.py` | `FA3958885FD096A0748CD438D9CDFB45671092CA5777BF1A824F2D95CBC8269E` |
| `tests/test_client_startup_resilience.py` | `ECAAF238CB64046D22AB825DB7BB0A85EB98F75EDBD330C640FEA44E880627E4` |

`mcp_server.py` SHA-256 is `1D7C6E0C0FE37FB61C23BC203E179B05E472175326DD8DDCCB388916EA1827A`; it includes the T04 path-hints wrapper hunk plus preserved T07 request-ID and earlier investigation-option hunks. `http_server.py` SHA-256 is `840933FF8801832D4DDC4746853011AB1486338EA42BBA186E137393574156D7`; it is a dirty shared dependency, not a T04-owned edit. Preserve both files' other-agent changes.

Other dirty and untracked T04/inherited candidate paths remain outside this exact slot-N batch. The repository-wide status was captured before this receipt; no inherited paths were changed in this continuation.

## Checks and diff pin

- `git diff --check`: exit 0. Git printed LF-to-CRLF advisories for the T04 plan and `tests/test_client_transport.py` only.
- Full tracked working-tree diff SHA-256: `bd1982343e4e54590560e526e19d67104b50ab4f5c08e85e933b95d5612db92c` (98,334 bytes). This includes inherited/shared tracked hunks; it is not a T04-only patch hash. Untracked acceptance files are pinned above by file hashes.
- Latest source-only change: empty `path_hints` now behaves as omitted; `tests/test_client_path_hints.py::test_post_omits_empty_path_hints` covers the contract. Static `ast.parse` and scoped `git diff --check` passed; no tests ran.

## Proposed single validation batch

Run only after T20 gives explicit slot-N GO. The batch includes the existing in-process and client-transport acceptance, HTTP request-ID retry, both path-hints boundaries, and replay-safe retry/startup regressions:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_inprocess_transport.py tests/test_client_transport.py tests/test_t04_client_request_id_http.py tests/test_client_path_hints.py tests/test_t04_root_path_hint_chain.py::test_registered_repo_search_forwards_hints_over_real_root_http tests/test_t04_client_retry_acceptance.py tests/test_client_startup_resilience.py::test_first_post_starts_daemon_and_retries_same_id_and_path_hints tests/test_client_startup_resilience.py::test_unclassified_mutation_pre_send_failure_does_not_autostart_or_retry
```

The separate daemon-off MCP acceptance still depends on T03's `operational_action` / `requires_heavy_work` wiring. Do not treat this client/core batch as integrated MCP acceptance.

## Static transport interface review

AST-only review passed for the T04 injection contract: `HubClient.__init__` keeps `inprocess_transport` keyword-only; `get` and `request` expose `operational_action` and `requires_heavy_work`; `_open` forwards both to the injected transport; `InProcessTransport.open` accepts both; `close` exists. Parsed `client.py`, `inprocess_transport.py`, `tests/test_inprocess_transport.py`, and `tests/test_client_transport.py`. Result: `STATIC_TRANSPORT_CONTRACT_PASS`. This is signature/structure evidence only, not runtime acceptance. T03 MCP transport selection/wiring remains a separate integration dependency.

## T03 wiring boundary verified

Current `src/local_ai_hub/mcp_server.py:80` constructs `CLIENT = HubClient(tenant=TENANT)` without `InProcessTransport`. Bounded search found no `InProcessTransport`, `inprocess_transport`, `operational_action`, or `requires_heavy_work` use in the MCP server. `src/local_ai_hub/operation_contracts.py` is absent from this candidate checkout. T03 owns this wiring per the existing interface contract; T04 will not edit it. The requested slot-N batch proves client/core in-process behavior only. Actual daemon-off MCP integration remains blocked on T03 wiring and a later authorized acceptance run.

## PR #2 orphaned managed-supervisor recovery (2026-10-02)

The PR #2 behavior was absent: `ensure_server()` returned immediately whenever `service.managed` existed. T04 now treats the marker as recoverable only when operational mode is active, the respected `service.disabled` marker is absent, both `supervisor.pid` and `supervisor.lock` have no live PID, and no process listens on the configured port. It rechecks disabled/live-supervisor/port conditions under the startup lock. For an orphaned managed service it starts `python -m local_ai_hub.supervisor`, passes the active resolved custom config through `LOCAL_AI_CONFIG`, keeps existing `PYTHONPATH`/hidden-detached setup, and does not kill the supervisor when the Hub is still warming at timeout. Unmanaged installations keep the existing direct Hub startup path.

Added startup regressions: `test_blocked_operational_modes_prevent_managed_supervisor_recovery`, `test_orphaned_managed_service_recovers_supervisor_with_active_config`, `test_orphaned_managed_recovery_preserves_live_supervisor_and_port_singletons`, and `test_disabled_marker_blocks_orphaned_managed_supervisor_recovery`. Also corrected the diagnosed stale transport-test setup: `test_client_replays_duplicate_request_until_owner_finishes` now uses public `client.post()` so `/api/search` replay safety is classified by the normal route allowlist; assertions remain unchanged.

Current SHA-256: `src/local_ai_hub/client.py` `2E71D1157A9FAE04EFF4079C72372728B2E70D5F2331192E2D6F9A1673C706A7`; `tests/test_client_startup_resilience.py` `EC9871C9298B97E3F258EAC2150CC1C76ED291FA5CDB362148B182C5C4DFFEE9`; `tests/test_client_transport.py` `FE3F90240CCA4DAE7F3B2B0DD3CAFEA8A0AA29916AC7CC1A35A9EB364C1BF242`. `git diff --check` passed (exit 0, CRLF advisory for `test_client_transport.py`); AST parsing passed for all three files. No tests ran after PR #2 edits. Prior N batch failed and was released; request a fresh T20 slot before running this updated batch.

Proposed next single batch command after explicit T20 GO:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_inprocess_transport.py tests/test_client_transport.py tests/test_t04_client_request_id_http.py tests/test_client_path_hints.py tests/test_t04_root_path_hint_chain.py::test_registered_repo_search_forwards_hints_over_real_root_http tests/test_t04_client_retry_acceptance.py tests/test_client_startup_resilience.py::test_blocked_operational_modes_prevent_managed_supervisor_recovery tests/test_client_startup_resilience.py::test_orphaned_managed_service_recovers_supervisor_with_active_config tests/test_client_startup_resilience.py::test_orphaned_managed_recovery_preserves_live_supervisor_and_port_singletons tests/test_client_startup_resilience.py::test_disabled_marker_blocks_orphaned_managed_supervisor_recovery tests/test_client_startup_resilience.py::test_first_post_starts_daemon_and_retries_same_id_and_path_hints tests/test_client_startup_resilience.py::test_unclassified_mutation_pre_send_failure_does_not_autostart_or_retry`

## Q/P follow-up: fresh selectors only

T20 confirmed N already ran the previous 55-test batch. For Q after P/T06, run only the four PR #2 selectors added after N; these were not part of N:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_startup_resilience.py::test_blocked_operational_modes_prevent_managed_supervisor_recovery tests/test_client_startup_resilience.py::test_orphaned_managed_service_recovers_supervisor_with_active_config tests/test_client_startup_resilience.py::test_orphaned_managed_recovery_preserves_live_supervisor_and_port_singletons tests/test_client_startup_resilience.py::test_disabled_marker_blocks_orphaned_managed_supervisor_recovery
```

This expands to seven parameterized cases. Do not include `tests/test_client_transport.py::test_client_replays_duplicate_request_until_owner_finishes` in Q: N already ran it and it failed because the old direct `request()` test setup bypassed the safe POST classifier. T04 corrected that setup to public `client.post()` after root-cause analysis. Request separate T20 approval for that same-selector rerun. Current HEAD remains `3658d5056354849ddf17883ed04f807f16cc44c1`; Q file hashes, diff-check, and no-runner status were refreshed in the T20 handoff. No tests run since N.
