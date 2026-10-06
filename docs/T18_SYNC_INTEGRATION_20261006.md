# T18 candidate committed synchronization

Scope: only `C:/Users/Adam/.codex/worktrees/t18-candidate-2b33602`.
Branch: `codex/sync-t18-candidate-2b33602-20261006`.
Manual merge target pinned once: `182e1c463597b485d6b5145c52c21f8727e9b8c2`.
The supplied older master `fbc965f5` was not chased after this pin.

Preservation references:

- `codex/checkpoint-t18-candidate-2b33602-original-20261006`: `357099bad9ce5ec2e345c6d121d992dd5b086ec0`, the clean handoff HEAD containing all eight originally untracked files (six historical patches/notes and two T18 tests).
- `codex/checkpoint-t18-candidate-2b33602-dirty-20261006`: `fcb49e482c3c5135f9426122b0be6fee1628a805`, all original tracked dirty source/tests/docs.
- `codex/checkpoint-t18-candidate-2b33602-pre-dirty-head-20261006`: `ec0a79cf9ec92cb4af8bff7ed802f0d64f9307bc`, original pre-checkpoint candidate HEAD.
- `codex/checkpoint-t18-candidate-2b33602-pinned-master-20261006`: the pinned target above.

## Integration decisions

- Kept master ordered T08 `AgentStateStore`, durable sequence cursors, bounded high-water replay, transaction-owned append, gap reporting, and queue-loss markers. Removed the older T18 duplicate `append_in_transaction` that would otherwise override that implementation. `agent_events.py` matches pinned master exactly.
- Kept master allowlisted error diagnostics and classification-only fingerprints. Retained T18 telemetry queue acceptance, ordering, self-accounting rejection, and metadata-only recording.
- Kept master generated MCP/schema contracts, extracted HTTP admin authorization/result audit, operational-mode protections and project identity handling. Generator and MCP server match pinned master exactly.
- Preserved T18 cache warming/stale responses, nonblocking cache contention and controlled dashboard polling; reconciled with master bounded executor probes. Added the T18 `degraded` response field consistently. Cache hits intentionally reuse the cached Agent OS summary.
- Preserved bounded incident resolution and atomically appended its event using the current ordered T08 transaction implementation.
- Preserved T18 trace UI/history/reveal code and privacy notice without claiming its unfinished backend is implemented. Preserved master trace-list behavior plus T18 oversized-offset protection.
- Reviewed dashboard hunks after normalizing line endings for three-way comparison; restored the predominant master CRLF style afterward. No whole-file ours/theirs selection.
- Master Gemini preprocessing and CodeGraph removal were retained; their source paths have no candidate delta. `/api/context/pack` remains T14-owned and was not redesigned.
- Preserved all 49 candidate operational tests in `tests/test_operational_api_contracts_t18_candidate.py`; master had deleted/split the monolith. Historical patches are evidence only, not applied wholesale.

## Actual targeted checks

No Hub calls repeated: the user supplied terminal Hub failure and explicitly authorized native fallback. Native validation owner: this chat, this checkout. Tests may create SQLite/temporary runtime data beneath unique `.t18-sync-*-check-state` directories; these directories remain preserved and are excluded from commits. Bytecode and pytest cache writes were disabled. No dependency installation, model calls, full release suite, push, root checkout edits or master-ref writes.

- Event/telemetry privacy/error metadata/status schema: **15 passed**.
- Live status HTTP, telemetry accounting/rejection, error classification/diagnostics: **21 passed**.
- Ordered T08 event page/snapshot, event page contracts, drop metrics, incidents and SSE: **32 passed, 3 failed**.
- First combined dashboard/status/debug run: **210 passed, 17 failed**. It exposed UI expectation mismatches, response-shape/cache fixture mismatches, and unfinished debug paging.
- Intermediate status/polling run after shape reconciliation: **38 passed, 2 failed**; fixtures then reconciled to cached-summary behavior and the explicit degraded field.
- Final custom-modal/status run: **164 passed**. UI tests retain primary-before-technical-details checks and now accept the explicit privacy/history notice.
- Admin authorization/error metadata: **8 passed, 1 failed**.
- Python AST parse: nine affected source files passed; duplicate class/module definitions: none.
- Dashboard JavaScript `node --check`: passed before and after restoring retained T18 code.
- `git diff --check`: passed after conflict resolution.
- Final source/archive AST parse and dashboard JavaScript syntax passed; `/api/context/pack` route AST is identical to pinned master. Candidate source/tests/docs staged whitespace check against pinned master passed with CRLF recognized as line endings. A broader staged check against the old candidate HEAD reported inherited master/archive whitespace; those unrelated files were preserved.
- One mistyped test filename produced `no tests ran`; the corrected bounded HTTP group is the 21-pass run above. No result was counted from that invocation.

## Outstanding behavior and tests

This is a committed integration handoff, not release acceptance.

1. `DebugTraceStore.detail` still only accepts `since_seq`. Candidate `limit`, `before_seq`, `full_payload` and `content_field`/`content_offset` paging/reveal are incomplete. Nine retained `test_debug_traces.py` cases fail on unsupported arguments or missing route forwarding. Dashboard history/full-content retrieval cannot be accepted until that backend exists; no new backend feature was added during synchronization.
2. Candidate composite/global SSE resume cursors are not integrated into ordered master replay. The dashboard retained cursor persistence code, but unfiltered reconnect cannot claim complete global replay. Use explicit stream/sequence replay. The unused candidate cursor helpers remain preserved.
3. Three older ordered/SSE expectations fail: `test_publish_counts_each_oldest_event_eviction` expects 2 drops rather than the current 3; `test_sse_stream_replays_all_pages_and_advances_cursor` expects 1000-event pages rather than current bounded 100-event pages; `test_sse_stream_surfaces_retention_gap_before_kind_filtered_replay` expects the older `stream.gap` replay form. Ordered-state source matches master; these tests are retained, not weakened to manufacture acceptance.
4. `test_mode_control_action_token_runs_remote_mode_post` expects remote mode writes, whereas retained master mode protections prevent them (`mode_writes=[]`). Remote mode policy was not weakened.
5. Candidate `audit_accepted:false` response signaling and older inline admin/DB-query bounded contracts are not fully reconciled with master's extracted routes. Master authentication and audit paths prevail. Telemetry queue acceptance does not prove persistence.
6. The archived 49-test candidate monolith was preserved but not executed: older event-object mocks and inline-admin expectations need migration to the current dict-event/extracted-route contracts.
7. No installed-service, browser, Gemini model runtime, physical GPU, or full-release acceptance was established. Previous receipts were not used as current proof.

## Candidate files versus pinned master

The final committed delta consists of the six retained `T18-review-artifacts-20260928/*` files; `docs/DASHBOARD.md`, `docs/HTTP_API.md`, this note; source `agent_incidents.py`, `app.py`, `dashboard.py`, `debug_traces.py`, `http_server.py`, `telemetry.py`; and tests `test_dashboard_custom_modals.py`, `test_dashboard_operational_surfaces.py`, `test_dashboard_polling_quality.py`, `test_debug_traces.py`, `test_event_page_contract_t18.py`, `test_http_tool_accounting_rejections.py`, `test_operational_api_contracts_t18_candidate.py`, `test_status_snapshot_quality.py`, `test_telemetry_privacy_t18.py`, `test_telemetry_self_accounting.py`.

Git's final merge-parent/ancestor, unresolved-index and tracked-cleanliness checks must accompany the commit hash in the chat handoff. Runtime/cache files are not part of this delta.
