# T18 assigned-checkout manual merge handoff — 2026-10-06

Scope: C:/Users/Adam/.codex/worktrees/t18-status-dashboard/.local-ai-hub only.
Branch: codex/sync-t18-status-dashboard-20261006.
Pinned master: f57947215fd48c37f14a7325b4651be836de553f.
This is a committed integration candidate with outstanding behavior/test issues, not release acceptance.

## Preservation and merge ownership

- Starting checkout HEAD was 816354853ae03ad70d5c38bb43e2eeda539b2692, already on the requested sync branch.
- Original pre-checkpoint HEAD: a1b04bb3bf88dc26a4d17409baf4ae6e2845018f, retained at refs/checkpoints/sync-t18-status-dashboard-original-20261006.
- Existing tracked-dirty checkpoint: 816354853ae03ad70d5c38bb43e2eeda539b2692, retained at refs/checkpoints/sync-t18-status-dashboard-tracked-20261006.
- Remaining source/tests/docs and authored handoff patches were checkpointed before merge: 938a96ae7c4db791be3f3e266f64f6d468f07f9a (163 files), retained at refs/checkpoints/sync-t18-status-dashboard-preserved-20261006.
- Pinned target retained at refs/checkpoints/sync-t18-status-dashboard-master-20261006. No moving-master lookup, root-checkout edit, master-ref update, fetch, push, stash, reset, clean, new worktree, or new chat.
- Four original .t18-* overlay/snapshot directories and handoff/.tmp_dashboard_patch remain preserved as untracked artifacts. They are duplicate historical inspection material, not new authoritative source. Runtime/cache data was not checkpointed; /.t18-sync-tmp/ is ignored.
- Hub terminal failure/native-fallback authorization came from the user. No Hub operation was retried or polled. The optional token-economizer setup script was absent in both configured skill locations; no tools were installed and User PATH was not changed.
- Manual merge used exactly f5794721 and reviewed conflict hunks. Checkpoint contents remain recoverable even where newer master behavior superseded older local code/tests. Resolved 25 conflicted paths; merge commit includes this handoff and all relevant remaining changes.

## Behavioral reconciliation and candidate overlap

- Kept local bounded trace detail, trajectory event pages, extracted status poller, redacted mode GET, telemetry cursor/budget handling, unknown/offline distinction, and telemetry MCP sanitization.
- Kept master cancellation, journal uncertainty, tenant/lease scope, HTTP error normalization, auth/action-token rules, locked operational-mode transitions, and parallel status scheduling.
- Reconciled duplicate HTTP helpers and duplicate AgentStateStore.event_page introduced by automatic merge. _publish, event_page, and Handler._stream_agent_events have AST-identical behavior to pinned master.
- Retained 32 bounded status workers from the local checkpoint with master parallel scheduling; fixed a merge-only undefined subscribers reference. Applied master dashboard client header and repository/worktree identity rendering.
- Updated the dashboard golden to the reviewed merged document and aligned mode setter/trace reset/client envelope fixtures with the chosen behavior.
- Gemini preprocessing, defaults.toml, and operational_mode.py are byte-identical to pinned master. No CodeGraph runtime route/UI was reintroduced; historical scan-ignore and test/doc names still contain that word.
- T14 /api/context/pack handler subtree is AST-identical to pinned master. Its ownership and design were preserved.
- Candidate 70059e18e64691d118ed48bd19ba57a5d5fa3919 was inspected read-only, not merged/cherry-picked or used as an overlay. It is not an ancestor of pinned f5794721. Both candidates overlap dashboard/status/HTTP/telemetry behavior; this checkout preserves its own historical source/tests/docs.
- 70059e18 contains additional polling, cursor, telemetry enqueue, and deadline work. Independent source review identified candidate refresh-callback, degraded backoff, SSE resume, and headless-diagnostic concerns. Those findings are advisory about that separate candidate, not runtime claims about this checkout.

## Actual targeted checks

All pytest runs used python -B -m pytest -q -p no:cacheprovider --tb=short. Later runs explicitly set PYTHONPATH=assigned/src and TEMP/TMP plus unique --basetemp under the assigned ignored scratch directory. Tests are side-effecting validation owned by this task, not a read-only audit. The first pytest run used pytest's default temporary directory; no external repository source/ref was edited. A standalone initial dashboard import resolved the installed module; its hash was discarded, then recomputed with assigned/src provenance.

- Final dashboard/status/telemetry/auth/diagnostic run: 74 passed in 22.30s. Files: test_dashboard_polling_quality.py, test_dashboard_operational_surfaces.py, test_status_snapshot_quality.py, test_telemetry_error_diagnostics_t18.py, test_telemetry_error_metadata_privacy_t18.py, test_telemetry_report_bounds_t18.py, test_http_admin_action_auth_t18.py, test_http_status_diagnostics_t18.py.
- Three initial merge failures were fixed and individually rechecked: 3 passed. The final 74-test run supersedes the initial 71-pass/3-fail result.
- Expanded focused run across status, traces, SSE, GET, registry, DB query, timeline, hubctl, CodeGraph and preprocessing: 90 passed / 22 failed. Subsequent merge corrections supersede its trace, undefined-subscriber, client-envelope, and hubctl failures.
- Trace/SSE/hubctl/drop run after those fixes: 51 passed / 11 failed. Later duplicate-event_page removal supersedes empty-stream failures.
- Latest SSE/drop run: 14 passed / 5 failed in 39.13s; outstanding cases listed below.
- Safety/MCP/auth/optional-preprocessing run: 37 passed / 6 failed in 32.15s; the six failures are MCP cases listed below. Selected journal-uncertainty, HTTP accounting, auth and optional-phase checks passed.
- AST parsed all 26 Python files then differing from pinned master: no syntax errors, no duplicate top-level functions or class methods.
- git diff --check f5794721 for source/tests/tools passed after removing three dashboard whitespace lines. Pyflakes retains two duplicate agent_swarms schema keys already present in pinned master and one dynamic operational_mode_gate_error import warning; no undefined-name finding remains.
- Source receipts: pinned preprocessing/defaults/mode equality; T14 context-pack subtree equality; SSE publish/page/stream subtree equality.
- No full release suite, dependency install, model pull, deployment, live Hub health acceptance, or hardware/model-quality validation.

## Outstanding behavior and acceptance issues

1. SSE tests: test_sse_stream_replays_all_pages_and_advances_cursor expects 1000-event pages while the preserved handler uses 100; test_sse_stream_surfaces_retention_gap_before_kind_filtered_replay expects stream.gap but no such retention event is emitted in that scenario. Handler behavior equals pinned master.
2. Drop metrics: three test_agent_event_drop_metrics.py cases expect agent_state.gap and capped old-format ranges; master publishes stream.gap. The exact-count case observes 5 versus expected 3, so cumulative gap/drop accounting remains an explicit issue.
3. Route registry: test_do_post_selects_every_golden_branch_without_moving_existing_gates and test_named_telemetry_dispatch_stays_after_recovery_and_inside_error_boundary fail. Preserved full historical registry and mixed legacy/extracted dispatch need a later owner decision; no dispatch redesign was attempted.
4. MCP: two telemetry tests assume outputSchema.anyOf (KeyError); direct invocation hits lazy-client recursion; owned-daemon delegate fixture cannot import operational_mode_gate_error; context forwarding expects two calls but sees one; low-budget warnings shorten scope_drift. Keep these failures visible; T14 endpoint itself was not changed.
5. T19 CodeGraph removal test rejects the retained .codegraphcontext scan-ignore string in repo_tools.py. repo_tools.py and that test equal pinned master; runtime backend removal remains preserved.
6. Three T21 search fallback tests fail on missing python_fallback_limit and unexpected max_files in fixture iter_files. Source/test paths equal pinned master. Gemini preprocessing and the selected optional-phase checks were preserved, not redesigned.
7. Historical handoff receipts and root-overlay fixtures are archived evidence only. Unselected historical overlay tests, live browser/Hub behavior, model latency/quality, and release acceptance remain unverified.

Complete changed-file inventory versus pinned master: T18_SYNC_CHECKOUT_FILES_20261006.txt.
Final merge HEAD and ancestry/unresolved/index verification are reported in the final chat handoff; this note lives inside that merge commit.
